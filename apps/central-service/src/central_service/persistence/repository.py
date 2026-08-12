"""Central pilot persistence repository (C1b/C2a).

Typed row access for the tenant/device/credential domain and the C2a
ingestion domain. Every tenant-owned query takes an explicit
``organization_id`` and is scoped server-side in SQL; authentication looks up
credentials by token and fails closed on unknown, disabled, or mismatched
rows. Session tokens are split into a public lookup half and a hashed secret
half so resolution is one indexed query.
"""

from __future__ import annotations

import hashlib
import json
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, cast

from assemblyvision_domain.models import (
    BusinessResult,
    ComponentCorrection,
    InspectionRecord,
    InternalDecision,
    ReviewDisposition,
    allowed_review_dispositions,
)
from sqlalchemy import Engine, Select, Text, and_, case, func, or_, select, text
from sqlalchemy.engine import RowMapping
from sqlalchemy.exc import IntegrityError

from central_service.auth.passwords import CredentialHash, hash_credential, verify_credential
from central_service.persistence.schema import (
    admin_sessions,
    administrators,
    audit_logs,
    devices,
    inspection_components,
    inspection_media,
    inspections,
    organizations,
    production_lines,
    review_records,
    sites,
    upload_receipts,
)

_SESSION_LOOKUP_BYTES = 16
_SESSION_SECRET_BYTES = 32
_ACTIVE = "ACTIVE"


def _utc(value: datetime) -> datetime:
    """Return ``value`` normalized to an aware UTC datetime.

    SQLite returns naive datetimes for ``DateTime(timezone=True)`` columns;
    PostgreSQL returns aware ones. Naive values are interpreted as UTC so
    callers always compare aware clocks.
    """
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _row_to_datetime(value: datetime | None) -> datetime | None:
    return _utc(value) if value is not None else None


def _uuid_or_none(value: object | None) -> str | None:
    """Serialize an optional UUID identity to its string form, or None."""
    return str(value) if value is not None else None


# The ingestion uniqueness constraints that protect effectively-once
# persistence (task C1 section 5.4). A concurrent insert losing the race on
# one of these is a payload conflict, never an internal error.
_CONFLICT_CONSTRAINTS = frozenset(
    {
        "uq_upload_receipts_device_key",
        "uq_inspections_device_inspection",
        "uq_inspections_device_sequence",
        "uq_inspection_media_device_media",
        "uq_inspection_media_object_key",
    }
)

# Review append uniqueness constraints (C4): a concurrent append losing the
# race on one of these is an explicit REVIEW_CONFLICT, never a 500.
_REVIEW_CONFLICT_CONSTRAINTS = frozenset(
    {
        "uq_review_records_inspection_revision",
        "uq_review_records_inspection_key",
    }
)


def _integrity_constraint(exc: IntegrityError) -> str | None:
    """Return the violated constraint name (PostgreSQL), or None.

    psycopg attaches ``diag.constraint_name`` to integrity errors; SQLite
    exposes only a message, so the name stays None there and non-conflict
    integrity errors propagate as internal errors.
    """
    diag = getattr(exc.orig, "diag", None)
    name = getattr(diag, "constraint_name", None) if diag is not None else None
    return str(name) if name else None


@dataclass(frozen=True)
class SiteRow:
    id: int
    organization_id: int
    name: str
    created_at: datetime


@dataclass(frozen=True)
class LineRow:
    id: int
    site_id: int
    organization_id: int
    name: str
    created_at: datetime


@dataclass(frozen=True)
class DeviceRow:
    id: int
    organization_id: int
    site_id: int
    production_line_id: int
    device_id: str
    name: str
    status: str
    created_at: datetime


@dataclass(frozen=True)
class AdministratorRow:
    id: int
    organization_id: int
    username: str
    created_at: datetime


@dataclass(frozen=True)
class PilotBootstrapResult:
    """Outcome of an idempotent pilot bootstrap run."""

    organization_id: int
    site_id: int
    production_line_id: int
    device_id: str
    device_row_id: int
    administrator_id: int
    created: tuple[str, ...]

    @property
    def bootstrapped(self) -> bool:
        return bool(self.created)


@dataclass(frozen=True)
class UploadReceiptRow:
    """A persisted, replayable central upload receipt (design 14)."""

    idempotency_key: str
    request_hash: str
    kind: str
    object_id: str
    inspection_id: str | None
    central_object_id: str | None
    size_bytes: int
    status: str
    response_code: int
    created_at: datetime


@dataclass(frozen=True)
class MediaManifestEntry:
    """One media item from the parent inspection manifest (C2b cross-check)."""

    media_kind: str
    mime_type: str
    size_bytes: int
    checksum_sha256: str


@dataclass(frozen=True)
class MediaBindingRow:
    """One persisted inspection_media binding for reconciliation (C2b)."""

    id: int
    organization_id: int
    device_row_id: int
    inspection_row_id: int
    source_media_id: str
    media_kind: str
    mime_type: str
    object_key: str
    central_object_id: str
    lifecycle: str
    size_bytes: int
    checksum_sha256: str


@dataclass(frozen=True)
class InspectionSummaryRow:
    """One inspection row for the history list (C3)."""

    id: int
    inspection_id: str
    device_id: str
    device_row_id: int
    site_id: int
    production_line_id: int
    device_sequence: int
    lifecycle_status: str
    started_at: datetime
    completed_at: datetime
    received_at: datetime
    barcode_status: str
    barcode_value: str | None
    product_resolution_status: str
    product_code: str | None
    internal_decision: str
    business_result: str
    rule_version_id: str
    request_hash: str

    @property
    def upload_delay_ms(self) -> int:
        """Edge completion to central receive, in milliseconds."""
        return int((self.received_at - self.completed_at).total_seconds() * 1000)


@dataclass(frozen=True)
class ComponentEvidenceRow:
    """One persisted component evidence row (C3 detail)."""

    component_code: str
    state: str
    best_confidence: float | None
    usable_frame_count: int
    detection_count: int
    policy_reason_codes: list[str]


@dataclass(frozen=True)
class InspectionDetailRow:
    """Full inspection detail including evidence, media, and versions (C3)."""

    summary: InspectionSummaryRow
    reason_codes: list[str]
    missing_components: list[str]
    low_confidence_components: list[str]
    application_version: str
    product_model_version_id: str
    product_model_checksum_sha256: str
    component_model_version_id: str
    component_model_checksum_sha256: str
    aggregation_policy_version: str
    processing_ms: int
    inference_metadata: dict[str, object] | None
    components: list[ComponentEvidenceRow]
    media: list[MediaBindingRow]
    # Verified central receipt for the INSPECTION upload (task C1 5.3).
    receipt_status: str | None
    receipt_created_at: datetime | None


@dataclass(frozen=True)
class DeviceStatusRow:
    """One device's central last-seen and inspection volume (C3 overview)."""

    device_id: str
    name: str
    last_seen_at: datetime | None
    inspection_count: int


@dataclass(frozen=True)
class InspectionFilter:
    """Bounded history/dashboard filters; every field is optional."""

    site_id: int | None = None
    line_id: int | None = None
    device_row_id: int | None = None
    from_at: datetime | None = None
    to_at: datetime | None = None
    barcode: str | None = None
    product_code: str | None = None
    business_result: str | None = None
    internal_decision: str | None = None
    reason_code: str | None = None
    model_version_id: str | None = None
    rule_version_id: str | None = None

    def fingerprint(self) -> str:
        """Stable hash of the normalized filter for cursor binding (C3)."""
        canonical = json.dumps(
            {
                "site_id": self.site_id,
                "line_id": self.line_id,
                "device_row_id": self.device_row_id,
                "from_at": self.from_at.isoformat() if self.from_at else None,
                "to_at": self.to_at.isoformat() if self.to_at else None,
                "barcode": self.barcode,
                "product_code": self.product_code,
                "business_result": self.business_result,
                "internal_decision": self.internal_decision,
                "reason_code": self.reason_code,
                "model_version_id": self.model_version_id,
                "rule_version_id": self.rule_version_id,
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class DashboardSummaryRow:
    """Overview counts for a scope/period (C3, design 17)."""

    inspection_count: int
    ok_count: int
    ng_count: int
    uncertain_count: int
    avg_upload_delay_ms: float | None


@dataclass(frozen=True)
class TimeseriesPointRow:
    """One daily bucket of outcome counts (C3 dashboard)."""

    bucket: str
    ok_count: int
    ng_count: int
    uncertain_count: int


@dataclass(frozen=True)
class ReviewRow:
    """One appended central review record (C4, design 24)."""

    id: int
    inspection_id: str
    revision: int
    disposition: str
    reason: str | None
    note: str | None
    reviewer: str
    component_corrections: list[dict[str, object]]
    original_business_result: str
    original_internal_decision: str
    original_reason_codes: list[str]
    created_at: datetime


@dataclass(frozen=True)
class ReviewSubmitResult:
    """Outcome of one review submission (append or idempotent replay)."""

    review: ReviewRow
    replayed: bool


@dataclass(frozen=True)
class ReviewQueueRow:
    """One NG/uncertain inspection awaiting review (C4 queue)."""

    summary: InspectionSummaryRow
    reason_codes: list[str]


class ReviewNotFoundError(Exception):
    """The inspection to review does not exist in this organization."""


class ReviewConflictError(Exception):
    """The submitted If-Match revision is stale (concurrent change, C4)."""


class ReviewDispositionError(Exception):
    """The disposition is not permitted for the machine outcome (C4)."""


class PayloadConflictError(Exception):
    """A reused upload identity arrived with different content (409).

    The original accepted resource is never altered; the conflict attempt is
    recorded as an immutable audit event before the exception propagates.
    """

    def __init__(self, *, reason: str, idempotency_key: str) -> None:
        super().__init__(reason)
        self.reason = reason
        self.idempotency_key = idempotency_key


class _ConflictDetected(Exception):
    """Internal sentinel: a conflict was found inside the ingest transaction."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


class CentralRepository:
    """Typed read/write access to the central pilot schema."""

    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    # -- tenant queries (organization-scoped) ---------------------------------

    def list_sites(self, organization_id: int) -> list[SiteRow]:
        with self._engine.connect() as connection:
            rows = connection.execute(
                select(sites)
                .where(sites.c.organization_id == organization_id)
                .order_by(sites.c.name)
            ).mappings()
            return [self._site_from_row(row) for row in rows]

    def list_lines(self, organization_id: int, site_id: int | None = None) -> list[LineRow]:
        statement: Select[Any] = select(production_lines).where(
            production_lines.c.organization_id == organization_id
        )
        if site_id is not None:
            statement = statement.where(production_lines.c.site_id == site_id)
        statement = statement.order_by(production_lines.c.name)
        with self._engine.connect() as connection:
            rows = connection.execute(statement).mappings()
            return [self._line_from_row(row) for row in rows]

    def list_devices(self, organization_id: int) -> list[DeviceRow]:
        with self._engine.connect() as connection:
            rows = connection.execute(
                select(devices)
                .where(devices.c.organization_id == organization_id)
                .order_by(devices.c.device_id)
            ).mappings()
            return [self._device_from_row(row) for row in rows]

    def get_device(self, organization_id: int, device_row_id: int) -> DeviceRow | None:
        statement = select(devices).where(
            and_(devices.c.id == device_row_id, devices.c.organization_id == organization_id)
        )
        with self._engine.connect() as connection:
            row = connection.execute(statement).mappings().first()
        return self._device_from_row(row) if row is not None else None

    # -- credential authentication --------------------------------------------

    def authenticate_device(self, token: str) -> DeviceRow | None:
        """Resolve ``token`` to the single active registered device, or None.

        The token is verified against every stored hash because salts are
        random per row; the pilot fleet is small and scrypt dominates the
        cost. Disabled devices never authenticate.
        """
        with self._engine.connect() as connection:
            rows = connection.execute(select(devices)).mappings().all()
        for row in rows:
            device = self._device_from_row(row)
            if device.status != _ACTIVE:
                continue
            stored = CredentialHash(salt=row["upload_token_salt"], digest=row["upload_token_hash"])
            if verify_credential(token, stored):
                return device
        return None

    def authenticate_administrator(self, token: str) -> AdministratorRow | None:
        with self._engine.connect() as connection:
            rows = connection.execute(select(administrators)).mappings().all()
        for row in rows:
            stored = CredentialHash(salt=row["token_salt"], digest=row["token_hash"])
            if verify_credential(token, stored):
                return self._administrator_from_row(row)
        return None

    # -- administrator browser sessions ---------------------------------------

    def create_admin_session(
        self, administrator_id: int, organization_id: int, ttl: timedelta
    ) -> str:
        """Create a session and return its single-use bearer token.

        The token is split into a public lookup half and a secret half stored
        only as a salted hash, so a leaked sessions table cannot forge one.
        The session row carries the administrator's organization scope so
        every tenant-owned row stays scoped (C1 invariant 6).
        """
        token = secrets.token_urlsafe(_SESSION_LOOKUP_BYTES + _SESSION_SECRET_BYTES)
        lookup = token[:_SESSION_LOOKUP_BYTES]
        secret = token[_SESSION_LOOKUP_BYTES:]
        stored = hash_credential(secret)
        expires_at = datetime.now(UTC) + ttl
        with self._engine.begin() as connection:
            connection.execute(
                admin_sessions.insert().values(
                    administrator_id=administrator_id,
                    organization_id=organization_id,
                    session_lookup=lookup,
                    session_token_hash=stored.digest,
                    session_token_salt=stored.salt,
                    expires_at=expires_at,
                )
            )
        return token

    def resolve_admin_session(self, session_token: str) -> AdministratorRow | None:
        """Return the administrator owning a live session token, or None."""
        if len(session_token) < _SESSION_LOOKUP_BYTES + _SESSION_SECRET_BYTES:
            return None
        lookup = session_token[:_SESSION_LOOKUP_BYTES]
        secret = session_token[_SESSION_LOOKUP_BYTES:]
        with self._engine.connect() as connection:
            row = (
                connection.execute(
                    select(admin_sessions).where(admin_sessions.c.session_lookup == lookup)
                )
                .mappings()
                .first()
            )
        if row is None:
            return None
        expires_at = _utc(row["expires_at"])
        if expires_at <= datetime.now(UTC):
            return None
        stored = CredentialHash(salt=row["session_token_salt"], digest=row["session_token_hash"])
        if not verify_credential(secret, stored):
            return None
        with self._engine.connect() as connection:
            admin_row = (
                connection.execute(
                    select(administrators).where(administrators.c.id == row["administrator_id"])
                )
                .mappings()
                .first()
            )
        if admin_row is None:
            return None
        administrator = self._administrator_from_row(admin_row)
        # Defensive consistency check: a session row must belong to the same
        # organization as its administrator.
        if administrator.organization_id != int(row["organization_id"]):
            return None
        return administrator

    def purge_expired_sessions(self) -> int:
        """Delete expired sessions and return the number removed."""
        with self._engine.begin() as connection:
            result = connection.execute(
                admin_sessions.delete().where(admin_sessions.c.expires_at <= datetime.now(UTC))
            )
        return int(result.rowcount)

    # -- pilot bootstrap -------------------------------------------------------

    def bootstrap_pilot(
        self,
        *,
        organization_name: str,
        site_name: str,
        line_name: str,
        device_id: str,
        device_name: str,
        device_upload_token: str,
        admin_username: str,
        admin_token: str,
    ) -> PilotBootstrapResult:
        """Create the pilot organization/site/line/device/administrator.

        Idempotent by name/identity: existing rows are reused, and an existing
        device or administrator is never re-created or re-keyed. The pilot
        enrollment and its mandatory bootstrap audit event commit in one
        transaction, so a failed audit rolls the whole enrollment back and no
        active credential can exist without its audit record.
        """
        created: list[str] = []
        with self._engine.begin() as connection:
            organization_row = (
                connection.execute(
                    select(organizations).where(organizations.c.name == organization_name)
                )
                .mappings()
                .first()
            )
            if organization_row is None:
                organization_row = (
                    connection.execute(
                        organizations.insert()
                        .values(name=organization_name)
                        .returning(*organizations.c)
                    )
                    .mappings()
                    .one()
                )
                created.append("organization")
            organization_id = int(organization_row["id"])

            site_row = (
                connection.execute(
                    select(sites).where(
                        and_(sites.c.organization_id == organization_id, sites.c.name == site_name)
                    )
                )
                .mappings()
                .first()
            )
            if site_row is None:
                site_row = (
                    connection.execute(
                        sites.insert()
                        .values(organization_id=organization_id, name=site_name)
                        .returning(*sites.c)
                    )
                    .mappings()
                    .one()
                )
                created.append("site")
            site_id = int(site_row["id"])

            line_row = (
                connection.execute(
                    select(production_lines).where(
                        and_(
                            production_lines.c.site_id == site_id,
                            production_lines.c.name == line_name,
                        )
                    )
                )
                .mappings()
                .first()
            )
            if line_row is None:
                line_row = (
                    connection.execute(
                        production_lines.insert()
                        .values(organization_id=organization_id, site_id=site_id, name=line_name)
                        .returning(*production_lines.c)
                    )
                    .mappings()
                    .one()
                )
                created.append("production_line")
            line_id = int(line_row["id"])

            device_row = (
                connection.execute(
                    select(devices).where(
                        and_(
                            devices.c.organization_id == organization_id,
                            devices.c.device_id == device_id,
                        )
                    )
                )
                .mappings()
                .first()
            )
            if device_row is None:
                device_hash = hash_credential(device_upload_token)
                device_row = (
                    connection.execute(
                        devices.insert()
                        .values(
                            organization_id=organization_id,
                            site_id=site_id,
                            production_line_id=line_id,
                            device_id=device_id,
                            name=device_name,
                            status=_ACTIVE,
                            upload_token_hash=device_hash.digest,
                            upload_token_salt=device_hash.salt,
                        )
                        .returning(*devices.c)
                    )
                    .mappings()
                    .one()
                )
                created.append("device")
            device_row_id = int(device_row["id"])

            admin_row = (
                connection.execute(
                    select(administrators).where(
                        and_(
                            administrators.c.organization_id == organization_id,
                            administrators.c.username == admin_username,
                        )
                    )
                )
                .mappings()
                .first()
            )
            if admin_row is None:
                admin_hash = hash_credential(admin_token)
                admin_row = (
                    connection.execute(
                        administrators.insert()
                        .values(
                            organization_id=organization_id,
                            username=admin_username,
                            token_hash=admin_hash.digest,
                            token_salt=admin_hash.salt,
                        )
                        .returning(*administrators.c)
                    )
                    .mappings()
                    .one()
                )
                created.append("administrator")
            administrator_id = int(admin_row["id"])

            connection.execute(
                audit_logs.insert().values(
                    organization_id=organization_id,
                    actor_type="SYSTEM",
                    actor_id=None,
                    action="PILOT_BOOTSTRAP",
                    target_type="pilot",
                    target_id=str(organization_id),
                    detail=f"created={','.join(created) or 'none'}",
                )
            )

        return PilotBootstrapResult(
            organization_id=organization_id,
            site_id=site_id,
            production_line_id=line_id,
            device_id=device_id,
            device_row_id=device_row_id,
            administrator_id=administrator_id,
            created=tuple(created),
        )

    # -- ingestion (C2a) ------------------------------------------------------

    def ingest_inspection(
        self,
        *,
        device: DeviceRow,
        idempotency_key: str,
        request_hash: str,
        object_id: str,
        inspection_id: str,
        record: InspectionRecord,
        payload_json: str,
        received_at: datetime,
    ) -> tuple[UploadReceiptRow, bool]:
        """Persist one accepted inspection with its receipt and audit event.

        Returns ``(receipt, replayed)``. An identical replay (same device,
        idempotency key, and canonical request hash) returns the original
        persisted receipt without a second inspection, component, or audit
        acceptance row. Reusing the idempotency key, inspection id, or device
        sequence with a different hash raises :class:`PayloadConflictError`
        after recording the attempt as an audit event; the original accepted
        resource is preserved. The inspection, receipt, components, and audit
        acceptance event commit in one transaction (C2a exit criteria).
        """
        try:
            with self._engine.begin() as connection:
                existing_receipt = self._receipt_by_key(connection, device.id, idempotency_key)
                if existing_receipt is not None:
                    if existing_receipt["request_hash"] == request_hash:
                        return self._receipt_from_row(existing_receipt), True
                    raise _ConflictDetected(
                        f"idempotency key {idempotency_key} was accepted with different content"
                    )
                if (
                    self._inspection_by_identity(connection, device.id, inspection_id=inspection_id)
                    is not None
                ):
                    raise _ConflictDetected(
                        f"inspection id {inspection_id} was already accepted for this device"
                    )
                if (
                    self._inspection_by_identity(
                        connection, device.id, device_sequence=record.device_sequence
                    )
                    is not None
                ):
                    raise _ConflictDetected(
                        f"device sequence {record.device_sequence} was already accepted "
                        "for this device"
                    )

                inspection_row = (
                    connection.execute(
                        inspections.insert()
                        .values(
                            organization_id=device.organization_id,
                            device_row_id=device.id,
                            inspection_id=inspection_id,
                            device_sequence=record.device_sequence,
                            lifecycle_status=str(record.lifecycle_status.value),
                            started_at=record.started_at,
                            completed_at=record.completed_at,
                            received_at=received_at,
                            barcode_status=str(record.barcode_result.status),
                            barcode_value=record.barcode_result.value,
                            product_resolution_status=str(record.product_resolution.status),
                            product_code=record.product_resolution.product_code,
                            product_version_id=_uuid_or_none(
                                record.product_resolution.product_version_id
                            ),
                            internal_decision=str(record.decision.internal_decision.value),
                            business_result=str(record.decision.business_result.value),
                            missing_components=list(record.decision.missing_components),
                            low_confidence_components=list(
                                record.decision.low_confidence_components
                            ),
                            decision_reason_codes=list(record.decision.reason_codes),
                            decided_at=record.decision.decided_at,
                            application_version=record.application_version,
                            product_model_version_id=str(record.product_model_version_id),
                            product_model_checksum_sha256=record.product_model_checksum_sha256,
                            component_model_version_id=str(record.component_model_version_id),
                            component_model_checksum_sha256=record.component_model_checksum_sha256,
                            rule_version_id=str(record.rule_version_id),
                            aggregation_policy_version=record.aggregation_policy_version,
                            processing_ms=record.processing_ms,
                            inference_metadata=(
                                record.inference_metadata.model_dump(mode="json")
                                if record.inference_metadata is not None
                                else None
                            ),
                            payload_json=payload_json,
                            request_hash=request_hash,
                        )
                        .returning(*inspections.c)
                    )
                    .mappings()
                    .one()
                )
                inspection_pk = int(inspection_row["id"])
                for evidence in record.evidence:
                    connection.execute(
                        inspection_components.insert().values(
                            inspection_id=inspection_pk,
                            component_code=evidence.component_code,
                            state=str(evidence.state),
                            best_confidence=evidence.best_confidence,
                            usable_frame_count=evidence.usable_frame_count,
                            detection_count=evidence.detection_count,
                            policy_reason_codes=list(evidence.policy_reason_codes),
                        )
                    )
                receipt_row = (
                    connection.execute(
                        upload_receipts.insert()
                        .values(
                            organization_id=device.organization_id,
                            device_row_id=device.id,
                            idempotency_key=idempotency_key,
                            request_hash=request_hash,
                            kind="INSPECTION",
                            object_id=object_id,
                            inspection_id=inspection_id,
                            central_object_id=None,
                            size_bytes=len(payload_json.encode("utf-8")),
                            status="ACCEPTED",
                            response_code=201,
                        )
                        .returning(*upload_receipts.c)
                    )
                    .mappings()
                    .one()
                )
                connection.execute(
                    audit_logs.insert().values(
                        organization_id=device.organization_id,
                        actor_type="DEVICE",
                        actor_id=device.id,
                        action="INSPECTION_ACCEPTED",
                        target_type="inspection",
                        target_id=inspection_id,
                        detail=f"idempotency_key={idempotency_key}",
                    )
                )
            return self._receipt_from_row(receipt_row), False
        except _ConflictDetected as exc:
            # target_id is the bounded 36-char inspection identity; the
            # idempotency key (which embeds two UUIDs) would exceed the
            # audit target_id column on PostgreSQL, so it goes in detail.
            self.record_payload_conflict(
                device=device,
                target_type="inspection-upload",
                target_id=inspection_id,
                detail=f"idempotency_key={idempotency_key} reason={exc.reason}",
            )
            raise PayloadConflictError(reason=exc.reason, idempotency_key=idempotency_key) from exc
        except IntegrityError as exc:
            # A concurrent request lost the insert race on an ingestion
            # uniqueness constraint; the database is authoritative, so this is
            # the same payload-conflict contract (409), never a 500.
            if _integrity_constraint(exc) not in _CONFLICT_CONSTRAINTS:
                raise
            self.record_payload_conflict(
                device=device,
                target_type="inspection-upload",
                target_id=inspection_id,
                detail="concurrent duplicate identity rejected by the database",
            )
            raise PayloadConflictError(
                reason="a concurrent duplicate upload was rejected by the database",
                idempotency_key=idempotency_key,
            ) from exc

    def record_payload_conflict(
        self,
        *,
        device: DeviceRow,
        target_type: str,
        target_id: str,
        detail: str,
    ) -> None:
        """Append one payload-conflict audit event (C2a/C2b, contract 08)."""
        self.write_audit(
            organization_id=device.organization_id,
            actor_type="DEVICE",
            actor_id=device.id,
            action="UPLOAD_PAYLOAD_CONFLICT",
            target_type=target_type,
            target_id=target_id,
            detail=detail,
        )

    def get_receipt(self, device: DeviceRow, idempotency_key: str) -> UploadReceiptRow | None:
        """Return the persisted receipt for one device/key, or None."""
        with self._engine.connect() as connection:
            row = self._receipt_by_key(connection, device.id, idempotency_key)
        return self._receipt_from_row(row) if row is not None else None

    # -- media binding (C2b) --------------------------------------------------

    def get_inspection_media_manifest(
        self, device_row_id: int, inspection_id: str
    ) -> tuple[int, datetime, dict[str, MediaManifestEntry]] | None:
        """Return ``(inspection_row_id, capture_at, manifest)`` for a parent.

        The manifest is parsed from the accepted immutable payload so the
        incoming MEDIA bytes can be cross-checked against the media metadata
        the edge recorded in the inspection; ``capture_at`` is the edge
        capture clock of the parent inspection (design 14 media row). Returns
        None when the inspection is not accepted for this device or its
        payload cannot be decoded.
        """
        with self._engine.connect() as connection:
            row = (
                connection.execute(
                    select(
                        inspections.c.id, inspections.c.started_at, inspections.c.payload_json
                    ).where(
                        and_(
                            inspections.c.device_row_id == device_row_id,
                            inspections.c.inspection_id == inspection_id,
                        )
                    )
                )
                .mappings()
                .first()
            )
        if row is None:
            return None
        try:
            payload = json.loads(str(row["payload_json"]))
        except (ValueError, TypeError):
            return None
        media_items = payload.get("media", []) if isinstance(payload, dict) else []
        manifest: dict[str, MediaManifestEntry] = {}
        for item in media_items:
            if not isinstance(item, dict):
                continue
            source_id = str(item.get("media_id") or "")
            if not source_id:
                continue
            manifest[source_id] = MediaManifestEntry(
                media_kind=str(item.get("kind") or ""),
                mime_type=str(item.get("mime_type") or ""),
                size_bytes=int(item.get("size_bytes") or 0),
                checksum_sha256=str(item.get("checksum_sha256") or ""),
            )
        return int(row["id"]), _utc(row["started_at"]), manifest

    def persist_media(
        self,
        *,
        device: DeviceRow,
        inspection_row_id: int,
        idempotency_key: str,
        request_hash: str,
        object_id: str,
        inspection_id: str,
        central_object_id: str,
        object_key: str,
        media_kind: str,
        mime_type: str,
        size_bytes: int,
        checksum_sha256: str,
        capture_at: datetime,
        received_at: datetime,
    ) -> tuple[UploadReceiptRow, bool]:
        """Persist one accepted media binding with its receipt and audit event.

        Returns ``(receipt, replayed)``. Identical replay returns the original
        receipt without a second binding or audit row; reusing the media
        identity with different content raises :class:`PayloadConflictError`
        after recording the attempt as an audit event. The object is written to
        the store by the caller *before* this transaction; a failure here
        leaves a staged object for the reconciliation command.
        """
        try:
            with self._engine.begin() as connection:
                existing_receipt = self._receipt_by_key(connection, device.id, idempotency_key)
                if existing_receipt is not None:
                    if existing_receipt["request_hash"] == request_hash:
                        return self._receipt_from_row(existing_receipt), True
                    raise _ConflictDetected(
                        f"idempotency key {idempotency_key} was accepted with different content"
                    )
                existing_binding = connection.execute(
                    select(inspection_media.c.id).where(
                        and_(
                            inspection_media.c.device_row_id == device.id,
                            inspection_media.c.source_media_id == object_id,
                        )
                    )
                ).first()
                if existing_binding is not None:
                    raise _ConflictDetected(
                        f"source media id {object_id} was already bound for this device"
                    )
                connection.execute(
                    inspection_media.insert().values(
                        organization_id=device.organization_id,
                        device_row_id=device.id,
                        inspection_row_id=inspection_row_id,
                        source_media_id=object_id,
                        media_kind=media_kind,
                        mime_type=mime_type,
                        size_bytes=size_bytes,
                        checksum_sha256=checksum_sha256,
                        object_key=object_key,
                        central_object_id=central_object_id,
                        lifecycle="AVAILABLE",
                        capture_at=capture_at,
                        received_at=received_at,
                    )
                )
                receipt_row = (
                    connection.execute(
                        upload_receipts.insert()
                        .values(
                            organization_id=device.organization_id,
                            device_row_id=device.id,
                            idempotency_key=idempotency_key,
                            request_hash=request_hash,
                            kind="MEDIA",
                            object_id=object_id,
                            inspection_id=inspection_id,
                            central_object_id=central_object_id,
                            size_bytes=size_bytes,
                            status="ACCEPTED",
                            response_code=201,
                        )
                        .returning(*upload_receipts.c)
                    )
                    .mappings()
                    .one()
                )
                connection.execute(
                    audit_logs.insert().values(
                        organization_id=device.organization_id,
                        actor_type="DEVICE",
                        actor_id=device.id,
                        action="MEDIA_ACCEPTED",
                        target_type="inspection-media",
                        target_id=object_id,
                        detail=f"inspection_id={inspection_id}",
                    )
                )
            return self._receipt_from_row(receipt_row), False
        except _ConflictDetected as exc:
            # target_id is the bounded 36-char source media identity.
            self.record_payload_conflict(
                device=device,
                target_type="media-upload",
                target_id=object_id,
                detail=f"idempotency_key={idempotency_key} reason={exc.reason}",
            )
            raise PayloadConflictError(reason=exc.reason, idempotency_key=idempotency_key) from exc
        except IntegrityError as exc:
            if _integrity_constraint(exc) not in _CONFLICT_CONSTRAINTS:
                raise
            self.record_payload_conflict(
                device=device,
                target_type="media-upload",
                target_id=object_id,
                detail="concurrent duplicate media identity rejected by the database",
            )
            raise PayloadConflictError(
                reason="a concurrent duplicate media upload was rejected by the database",
                idempotency_key=idempotency_key,
            ) from exc

    def get_media_by_central_object_id(
        self, organization_id: int, central_object_id: str
    ) -> MediaBindingRow | None:
        """Resolve one media binding by its stable central object id (C3).

        Organization-scoped so the authorized streaming endpoint can never
        leak another tenant's object.
        """
        with self._engine.connect() as connection:
            row = (
                connection.execute(
                    select(inspection_media).where(
                        and_(
                            inspection_media.c.organization_id == organization_id,
                            inspection_media.c.central_object_id == central_object_id,
                        )
                    )
                )
                .mappings()
                .first()
            )
        return self._media_binding_from_row(row) if row is not None else None

    def list_media_bindings(self) -> list[MediaBindingRow]:
        """Return every persisted media binding (reconciliation command)."""
        with self._engine.connect() as connection:
            rows = connection.execute(select(inspection_media).order_by(inspection_media.c.id))
            return [self._media_binding_from_row(row) for row in rows.mappings()]

    def get_media_binding(self, device_row_id: int, source_media_id: str) -> MediaBindingRow | None:
        """Return the binding for one device/source media id, or None.

        Lets the ingest service detect a media-identity conflict before
        writing an object, avoiding a staged orphan for the common retry
        path (the persisted check inside ``persist_media`` remains the
        concurrent backstop).
        """
        with self._engine.connect() as connection:
            row = (
                connection.execute(
                    select(inspection_media).where(
                        and_(
                            inspection_media.c.device_row_id == device_row_id,
                            inspection_media.c.source_media_id == source_media_id,
                        )
                    )
                )
                .mappings()
                .first()
            )
        return self._media_binding_from_row(row) if row is not None else None

    @staticmethod
    def _media_binding_from_row(row: RowMapping) -> MediaBindingRow:
        return MediaBindingRow(
            id=int(row["id"]),
            organization_id=int(row["organization_id"]),
            device_row_id=int(row["device_row_id"]),
            inspection_row_id=int(row["inspection_row_id"]),
            source_media_id=str(row["source_media_id"]),
            media_kind=str(row["media_kind"]),
            mime_type=str(row["mime_type"]),
            object_key=str(row["object_key"]),
            central_object_id=str(row["central_object_id"]),
            lifecycle=str(row["lifecycle"]),
            size_bytes=int(row["size_bytes"]),
            checksum_sha256=str(row["checksum_sha256"]),
        )

    # -- history and dashboard queries (C3) -----------------------------------

    def list_inspections(
        self,
        organization_id: int,
        filter_: InspectionFilter,
        *,
        after_completed_at: datetime | None,
        after_id: int | None,
        limit: int,
    ) -> tuple[list[InspectionSummaryRow], bool]:
        """Keyset-paginated inspection history for one organization (C3).

        Returns ``(items, has_more)``; rows are ordered ``completed_at DESC,
        id DESC`` (design 14 section 8.2). The cursor values are the last
        row's completion time and id; filters are scoped server-side to the
        organization.
        """
        conditions = [inspections.c.organization_id == organization_id]
        conditions.extend(self._inspection_filter_conditions(filter_, alias="i"))
        if after_completed_at is not None and after_id is not None:
            conditions.append(
                or_(
                    inspections.c.completed_at < after_completed_at,
                    and_(
                        inspections.c.completed_at == after_completed_at,
                        inspections.c.id < after_id,
                    ),
                )
            )
        statement = (
            select(
                inspections,
                devices.c.device_id,
                devices.c.site_id,
                devices.c.production_line_id,
            )
            .join(devices, devices.c.id == inspections.c.device_row_id)
            .where(*conditions)
            .order_by(inspections.c.completed_at.desc(), inspections.c.id.desc())
            .limit(limit + 1)
        )
        with self._engine.connect() as connection:
            rows = connection.execute(statement).mappings().all()
        has_more = len(rows) > limit
        items = [self._inspection_summary_from_row(row) for row in rows[:limit]]
        return items, has_more

    def get_inspection_detail(
        self, organization_id: int, inspection_id: str
    ) -> InspectionDetailRow | None:
        """Full inspection detail with evidence and media (C3)."""
        with self._engine.connect() as connection:
            row = (
                connection.execute(
                    select(
                        inspections,
                        devices.c.device_id,
                        devices.c.site_id,
                        devices.c.production_line_id,
                    )
                    .join(devices, devices.c.id == inspections.c.device_row_id)
                    .where(
                        and_(
                            inspections.c.organization_id == organization_id,
                            inspections.c.inspection_id == inspection_id,
                        )
                    )
                )
                .mappings()
                .first()
            )
            if row is None:
                return None
            inspection_pk = int(row["id"])
            component_rows = (
                connection.execute(
                    select(inspection_components)
                    .where(inspection_components.c.inspection_id == inspection_pk)
                    .order_by(inspection_components.c.component_code)
                )
                .mappings()
                .all()
            )
            media_rows = (
                connection.execute(
                    select(inspection_media)
                    .where(inspection_media.c.inspection_row_id == inspection_pk)
                    .order_by(inspection_media.c.source_media_id)
                )
                .mappings()
                .all()
            )
            receipt_row = (
                connection.execute(
                    select(upload_receipts.c.status, upload_receipts.c.created_at)
                    .where(
                        and_(
                            upload_receipts.c.device_row_id == row["device_row_id"],
                            upload_receipts.c.inspection_id == inspection_id,
                            upload_receipts.c.kind == "INSPECTION",
                        )
                    )
                    .order_by(upload_receipts.c.id.desc())
                )
                .mappings()
                .first()
            )
        components = [
            ComponentEvidenceRow(
                component_code=str(cr["component_code"]),
                state=str(cr["state"]),
                best_confidence=(
                    float(cr["best_confidence"]) if cr["best_confidence"] is not None else None
                ),
                usable_frame_count=int(cr["usable_frame_count"]),
                detection_count=int(cr["detection_count"]),
                policy_reason_codes=list(cr["policy_reason_codes"] or []),
            )
            for cr in component_rows
        ]
        media = [self._media_binding_from_row(mr) for mr in media_rows]
        return InspectionDetailRow(
            summary=self._inspection_summary_from_row(row),
            reason_codes=list(row["decision_reason_codes"] or []),
            missing_components=list(row["missing_components"] or []),
            low_confidence_components=list(row["low_confidence_components"] or []),
            application_version=str(row["application_version"]),
            product_model_version_id=str(row["product_model_version_id"]),
            product_model_checksum_sha256=str(row["product_model_checksum_sha256"]),
            component_model_version_id=str(row["component_model_version_id"]),
            component_model_checksum_sha256=str(row["component_model_checksum_sha256"]),
            aggregation_policy_version=str(row["aggregation_policy_version"]),
            processing_ms=int(row["processing_ms"]),
            inference_metadata=(
                dict(row["inference_metadata"]) if row["inference_metadata"] is not None else None
            ),
            components=components,
            media=media,
            receipt_status=(str(receipt_row["status"]) if receipt_row is not None else None),
            receipt_created_at=(
                CentralRepository._parse_dt(receipt_row["created_at"])
                if receipt_row is not None
                else None
            ),
        )

    def device_last_seen(self, organization_id: int) -> list[DeviceStatusRow]:
        """Per-device central last-seen and inspection volume (C3 overview)."""
        statement = (
            select(
                devices.c.device_id,
                devices.c.name,
                func.max(inspections.c.received_at).label("last_seen"),
                func.count(inspections.c.id).label("inspection_count"),
            )
            .select_from(
                devices.outerjoin(inspections, inspections.c.device_row_id == devices.c.id)
            )
            .where(devices.c.organization_id == organization_id)
            .group_by(devices.c.id)
            .order_by(devices.c.device_id)
        )
        with self._engine.connect() as connection:
            rows = connection.execute(statement).mappings().all()
        return [
            DeviceStatusRow(
                device_id=str(row["device_id"]),
                name=str(row["name"]),
                last_seen_at=(
                    CentralRepository._parse_dt(row["last_seen"])
                    if row["last_seen"] is not None
                    else None
                ),
                inspection_count=int(row["inspection_count"] or 0),
            )
            for row in rows
        ]

    def dashboard_summary(
        self, organization_id: int, filter_: InspectionFilter
    ) -> DashboardSummaryRow:
        """Outcome counts and mean upload delay for a scope/period (C3)."""
        conditions = [inspections.c.organization_id == organization_id]
        conditions.extend(self._inspection_filter_conditions(filter_, alias="i"))
        # Seconds between edge completion and central receive: epoch diff on
        # PostgreSQL, julianday diff on SQLite (test databases).
        if self._engine.dialect.name == "sqlite":
            delay_expr = (
                func.julianday(inspections.c.received_at)
                - func.julianday(inspections.c.completed_at)
            ) * 86400.0
        else:
            delay_expr = func.extract(
                "epoch", inspections.c.received_at - inspections.c.completed_at
            )
        statement = select(
            func.count(inspections.c.id),
            func.sum(case((inspections.c.business_result == "OK", 1), else_=0)),
            func.sum(case((inspections.c.business_result == "NG", 1), else_=0)),
            func.sum(
                case(
                    (inspections.c.internal_decision == "UNCERTAIN", 1),
                    else_=0,
                )
            ),
            func.avg(delay_expr),
        ).where(*conditions)
        with self._engine.connect() as connection:
            row = connection.execute(statement).one()
        total = int(row[0] or 0)
        ok_count = int(row[1] or 0)
        ng_count = int(row[2] or 0)
        uncertain_count = int(row[3] or 0)
        avg_delay = float(row[4]) * 1000 if row[4] is not None else None
        return DashboardSummaryRow(
            inspection_count=total,
            ok_count=ok_count,
            ng_count=ng_count,
            uncertain_count=uncertain_count,
            avg_upload_delay_ms=avg_delay,
        )

    def dashboard_timeseries(
        self, organization_id: int, filter_: InspectionFilter
    ) -> list[TimeseriesPointRow]:
        """Daily outcome counts for a scope/period (C3, design 17)."""
        conditions = [inspections.c.organization_id == organization_id]
        conditions.extend(self._inspection_filter_conditions(filter_, alias="i"))
        bucket = func.date(inspections.c.completed_at)
        statement = (
            select(
                bucket.label("bucket"),
                func.count(inspections.c.id),
                func.sum(case((inspections.c.business_result == "OK", 1), else_=0)),
                func.sum(case((inspections.c.business_result == "NG", 1), else_=0)),
                func.sum(
                    case(
                        (inspections.c.internal_decision == "UNCERTAIN", 1),
                        else_=0,
                    )
                ),
            )
            .where(*conditions)
            .group_by(bucket)
            .order_by(bucket)
        )
        with self._engine.connect() as connection:
            rows = connection.execute(statement).all()
        return [
            TimeseriesPointRow(
                bucket=str(r[0]),
                ok_count=int(r[2] or 0),
                ng_count=int(r[3] or 0),
                uncertain_count=int(r[4] or 0),
            )
            for r in rows
        ]

    def _inspection_filter_conditions(self, filter_: InspectionFilter, *, alias: str) -> list[Any]:
        """SQL conditions for the bounded C3 filters (organization-scoped)."""
        conditions: list[Any] = []
        if filter_.device_row_id is not None:
            conditions.append(inspections.c.device_row_id == filter_.device_row_id)
        if filter_.site_id is not None:
            conditions.append(devices.c.site_id == filter_.site_id)
        if filter_.line_id is not None:
            conditions.append(devices.c.production_line_id == filter_.line_id)
        if filter_.from_at is not None:
            conditions.append(inspections.c.completed_at >= filter_.from_at)
        if filter_.to_at is not None:
            conditions.append(inspections.c.completed_at < filter_.to_at)
        if filter_.barcode is not None:
            conditions.append(inspections.c.barcode_value == filter_.barcode)
        if filter_.product_code is not None:
            conditions.append(inspections.c.product_code == filter_.product_code)
        if filter_.business_result is not None:
            conditions.append(inspections.c.business_result == filter_.business_result)
        if filter_.internal_decision is not None:
            conditions.append(inspections.c.internal_decision == filter_.internal_decision)
        if filter_.reason_code is not None:
            # The decision reason codes are a JSON string array; matching the
            # quoted literal is portable across SQLite and PostgreSQL without
            # JSON-array operators. The value is bounded by the API validator.
            quoted = '"' + filter_.reason_code.replace('"', "") + '"'
            conditions.append(inspections.c.decision_reason_codes.cast(Text).like(f"%{quoted}%"))
        if filter_.model_version_id is not None:
            conditions.append(
                or_(
                    inspections.c.product_model_version_id == filter_.model_version_id,
                    inspections.c.component_model_version_id == filter_.model_version_id,
                )
            )
        if filter_.rule_version_id is not None:
            conditions.append(inspections.c.rule_version_id == filter_.rule_version_id)
        return conditions

    @staticmethod
    def _inspection_summary_from_row(row: RowMapping) -> InspectionSummaryRow:
        return InspectionSummaryRow(
            id=int(row["id"]),
            inspection_id=str(row["inspection_id"]),
            device_id=str(row["device_id"]),
            device_row_id=int(row["device_row_id"]),
            site_id=int(row["site_id"]),
            production_line_id=int(row["production_line_id"]),
            device_sequence=int(row["device_sequence"]),
            lifecycle_status=str(row["lifecycle_status"]),
            started_at=CentralRepository._parse_dt(row["started_at"]),
            completed_at=CentralRepository._parse_dt(row["completed_at"]),
            received_at=CentralRepository._parse_dt(row["received_at"]),
            barcode_status=str(row["barcode_status"]),
            barcode_value=(str(row["barcode_value"]) if row["barcode_value"] is not None else None),
            product_resolution_status=str(row["product_resolution_status"]),
            product_code=(str(row["product_code"]) if row["product_code"] is not None else None),
            internal_decision=str(row["internal_decision"]),
            business_result=str(row["business_result"]),
            rule_version_id=str(row["rule_version_id"]),
            request_hash=str(row["request_hash"]),
        )

    @staticmethod
    def _receipt_by_key(
        connection: Any, device_row_id: int, idempotency_key: str
    ) -> RowMapping | None:
        row = (
            connection.execute(
                select(upload_receipts).where(
                    and_(
                        upload_receipts.c.device_row_id == device_row_id,
                        upload_receipts.c.idempotency_key == idempotency_key,
                    )
                )
            )
            .mappings()
            .first()
        )
        return cast("RowMapping | None", row)

    @staticmethod
    def _inspection_by_identity(
        connection: Any,
        device_row_id: int,
        *,
        inspection_id: str | None = None,
        device_sequence: int | None = None,
    ) -> RowMapping | None:
        if inspection_id is not None:
            row = (
                connection.execute(
                    select(inspections).where(
                        and_(
                            inspections.c.device_row_id == device_row_id,
                            inspections.c.inspection_id == inspection_id,
                        )
                    )
                )
                .mappings()
                .first()
            )
            return cast("RowMapping | None", row)
        if device_sequence is not None:
            row = (
                connection.execute(
                    select(inspections).where(
                        and_(
                            inspections.c.device_row_id == device_row_id,
                            inspections.c.device_sequence == device_sequence,
                        )
                    )
                )
                .mappings()
                .first()
            )
            return cast("RowMapping | None", row)
        return None

    @staticmethod
    def _receipt_from_row(row: RowMapping) -> UploadReceiptRow:
        return UploadReceiptRow(
            idempotency_key=str(row["idempotency_key"]),
            request_hash=str(row["request_hash"]),
            kind=str(row["kind"]),
            object_id=str(row["object_id"]),
            inspection_id=(str(row["inspection_id"]) if row["inspection_id"] is not None else None),
            central_object_id=(
                str(row["central_object_id"]) if row["central_object_id"] is not None else None
            ),
            size_bytes=int(row["size_bytes"]),
            status=str(row["status"]),
            response_code=int(row["response_code"]),
            created_at=CentralRepository._parse_dt(row["created_at"]),
        )

    # -- central review (C4) ---------------------------------------------------

    def submit_review(
        self,
        *,
        organization_id: int,
        inspection_id: str,
        disposition: ReviewDisposition,
        reason: str | None,
        note: str | None,
        component_corrections: list[ComponentCorrection],
        reviewer: str,
        idempotency_key: str,
        if_match_revision: int | None,
        created_at: datetime,
    ) -> ReviewSubmitResult:
        """Append one review revision with optimistic concurrency (C4).

        The revision is per-inspection and monotonic; the client must submit
        the current latest revision via ``If-Match`` (None means no review yet)
        or the append fails with :class:`ReviewConflictError` and nothing is
        overwritten. An identical retry under the same idempotency key returns
        the original record. SQLite serializes submissions with BEGIN
        IMMEDIATE so concurrent reads cannot fork the chain; PostgreSQL relies
        on the unique revision constraint for the same guarantee. The
        disposition must be permitted for the machine outcome (design 24.3).
        A concurrent append losing the unique revision/idempotency race is an
        explicit conflict (PostgreSQL), never an internal error.
        """
        try:
            if self._engine.dialect.name == "sqlite":

                def _run(connection: Any) -> ReviewSubmitResult:
                    connection.execute(text("BEGIN IMMEDIATE"))
                    try:
                        result = self._submit_review_inner(
                            connection,
                            organization_id=organization_id,
                            inspection_id=inspection_id,
                            disposition=disposition,
                            reason=reason,
                            note=note,
                            component_corrections=component_corrections,
                            reviewer=reviewer,
                            idempotency_key=idempotency_key,
                            if_match_revision=if_match_revision,
                            created_at=created_at,
                        )
                        connection.commit()
                        return result
                    except Exception:
                        connection.rollback()
                        raise

                with self._engine.connect() as connection:
                    return _run(connection)

            with self._engine.begin() as connection:
                return self._submit_review_inner(
                    connection,
                    organization_id=organization_id,
                    inspection_id=inspection_id,
                    disposition=disposition,
                    reason=reason,
                    note=note,
                    component_corrections=component_corrections,
                    reviewer=reviewer,
                    idempotency_key=idempotency_key,
                    if_match_revision=if_match_revision,
                    created_at=created_at,
                )
        except IntegrityError as exc:
            if _integrity_constraint(exc) not in _REVIEW_CONFLICT_CONSTRAINTS:
                raise
            raise ReviewConflictError(
                "a concurrent review append was rejected by the database"
            ) from exc

    def _submit_review_inner(
        self,
        connection: Any,
        *,
        organization_id: int,
        inspection_id: str,
        disposition: ReviewDisposition,
        reason: str | None,
        note: str | None,
        component_corrections: list[ComponentCorrection],
        reviewer: str,
        idempotency_key: str,
        if_match_revision: int | None,
        created_at: datetime,
    ) -> ReviewSubmitResult:
        inspection = (
            connection.execute(
                select(
                    inspections.c.id,
                    inspections.c.business_result,
                    inspections.c.internal_decision,
                    inspections.c.payload_json,
                ).where(
                    and_(
                        inspections.c.organization_id == organization_id,
                        inspections.c.inspection_id == inspection_id,
                    )
                )
            )
            .mappings()
            .first()
        )
        if inspection is None:
            raise ReviewNotFoundError(f"no inspection {inspection_id} to review")
        inspection_pk = int(inspection["id"])

        # Idempotent retry: same inspection + key returns the original record.
        existing = (
            connection.execute(
                select(review_records).where(
                    and_(
                        review_records.c.inspection_row_id == inspection_pk,
                        review_records.c.idempotency_key == idempotency_key,
                    )
                )
            )
            .mappings()
            .first()
        )
        if existing is not None:
            return ReviewSubmitResult(review=self._review_from_row(existing), replayed=True)

        latest = connection.execute(
            select(func.max(review_records.c.revision)).where(
                review_records.c.inspection_row_id == inspection_pk
            )
        ).scalar()
        latest_revision = int(latest) if latest is not None else 0
        if (if_match_revision or 0) != latest_revision:
            raise ReviewConflictError(
                f"expected revision {if_match_revision or 0}, current revision {latest_revision}"
            )

        allowed = allowed_review_dispositions(
            BusinessResult(str(inspection["business_result"])),
            InternalDecision(str(inspection["internal_decision"])),
        )
        if disposition not in allowed:
            raise ReviewDispositionError(
                f"disposition {disposition.value} is not permitted for machine "
                f"outcome {inspection['business_result']}/{inspection['internal_decision']}"
            )

        # Original reason codes come from the immutable accepted payload.
        payload = json.loads(str(inspection["payload_json"]))
        reason_codes = (
            list(payload.get("decision", {}).get("reason_codes", []))
            if isinstance(payload, dict)
            else []
        )
        row = (
            connection.execute(
                review_records.insert()
                .values(
                    organization_id=organization_id,
                    inspection_row_id=inspection_pk,
                    revision=latest_revision + 1,
                    disposition=disposition.value,
                    reason=reason,
                    note=note,
                    reviewer=reviewer,
                    component_corrections=(
                        [correction.model_dump() for correction in component_corrections]
                        if component_corrections
                        else None
                    ),
                    original_business_result=str(inspection["business_result"]),
                    original_internal_decision=str(inspection["internal_decision"]),
                    original_reason_codes=reason_codes,
                    idempotency_key=idempotency_key,
                    created_at=created_at,
                )
                .returning(*review_records.c)
            )
            .mappings()
            .one()
        )
        connection.execute(
            audit_logs.insert().values(
                organization_id=organization_id,
                actor_type="ADMIN",
                actor_id=None,
                action="REVIEW_APPENDED",
                target_type="inspection",
                target_id=inspection_id,
                detail=f"revision={row['revision']} disposition={disposition.value}",
            )
        )
        return ReviewSubmitResult(review=self._review_from_row(row, inspection_id), replayed=False)

    def list_review_history(self, organization_id: int, inspection_id: str) -> list[ReviewRow]:
        """Append-only review history for one inspection, oldest first (C4)."""
        with self._engine.connect() as connection:
            inspection_pk = connection.execute(
                select(inspections.c.id).where(
                    and_(
                        inspections.c.organization_id == organization_id,
                        inspections.c.inspection_id == inspection_id,
                    )
                )
            ).scalar_one_or_none()
            if inspection_pk is None:
                return []
            rows = (
                connection.execute(
                    select(review_records)
                    .where(review_records.c.inspection_row_id == int(inspection_pk))
                    .order_by(review_records.c.revision)
                )
                .mappings()
                .all()
            )
        return [self._review_from_row(row, inspection_id) for row in rows]

    def get_latest_review(self, organization_id: int, inspection_id: str) -> ReviewRow | None:
        """Latest review for one inspection (detail view), or None (C4)."""
        with self._engine.connect() as connection:
            inspection_pk = connection.execute(
                select(inspections.c.id).where(
                    and_(
                        inspections.c.organization_id == organization_id,
                        inspections.c.inspection_id == inspection_id,
                    )
                )
            ).scalar_one_or_none()
            if inspection_pk is None:
                return None
            row = (
                connection.execute(
                    select(review_records)
                    .where(review_records.c.inspection_row_id == int(inspection_pk))
                    .order_by(review_records.c.revision.desc())
                )
                .mappings()
                .first()
            )
        return self._review_from_row(row, inspection_id) if row is not None else None

    def list_review_queue(
        self,
        organization_id: int,
        *,
        after_completed_at: datetime | None,
        after_id: int | None,
        limit: int,
    ) -> tuple[list[ReviewQueueRow], bool]:
        """NG/uncertain inspections without any review, newest first (C4).

        The M1 routing policy prioritizes NG and uncertain inspections; it is
        versioned and auditable and does not imply every NG always requires
        review after the pilot policy is revised.
        """
        reviewed_subquery = select(review_records.c.inspection_row_id).distinct()
        conditions = [
            inspections.c.organization_id == organization_id,
            inspections.c.business_result == "NG",
            ~inspections.c.id.in_(reviewed_subquery),
        ]
        if after_completed_at is not None and after_id is not None:
            conditions.append(
                or_(
                    inspections.c.completed_at < after_completed_at,
                    and_(
                        inspections.c.completed_at == after_completed_at,
                        inspections.c.id < after_id,
                    ),
                )
            )
        statement = (
            select(
                inspections,
                devices.c.device_id,
                devices.c.site_id,
                devices.c.production_line_id,
            )
            .join(devices, devices.c.id == inspections.c.device_row_id)
            .where(*conditions)
            .order_by(inspections.c.completed_at.desc(), inspections.c.id.desc())
            .limit(limit + 1)
        )
        with self._engine.connect() as connection:
            rows = connection.execute(statement).mappings().all()
        has_more = len(rows) > limit
        items = [
            ReviewQueueRow(
                summary=self._inspection_summary_from_row(row),
                reason_codes=list(row["decision_reason_codes"] or []),
            )
            for row in rows[:limit]
        ]
        return items, has_more

    @staticmethod
    def _review_from_row(row: RowMapping, inspection_id: str = "") -> ReviewRow:
        return ReviewRow(
            id=int(row["id"]),
            inspection_id=inspection_id,
            revision=int(row["revision"]),
            disposition=str(row["disposition"]),
            reason=str(row["reason"]) if row["reason"] is not None else None,
            note=str(row["note"]) if row["note"] is not None else None,
            reviewer=str(row["reviewer"]),
            component_corrections=[dict(item) for item in (row["component_corrections"] or [])],
            original_business_result=str(row["original_business_result"]),
            original_internal_decision=str(row["original_internal_decision"]),
            original_reason_codes=list(row["original_reason_codes"] or []),
            created_at=CentralRepository._parse_dt(row["created_at"]),
        )

    # -- audit ----------------------------------------------------------------

    def write_audit(
        self,
        *,
        organization_id: int | None,
        actor_type: str,
        actor_id: int | None,
        action: str,
        target_type: str | None = None,
        target_id: str | None = None,
        detail: str | None = None,
    ) -> None:
        """Append one immutable audit event (contract 08)."""
        with self._engine.begin() as connection:
            connection.execute(
                audit_logs.insert().values(
                    organization_id=organization_id,
                    actor_type=actor_type,
                    actor_id=actor_id,
                    action=action,
                    target_type=target_type,
                    target_id=target_id,
                    detail=detail,
                )
            )

    # -- row mappers ----------------------------------------------------------

    def _site_from_row(self, row: RowMapping) -> SiteRow:
        return SiteRow(
            id=int(row["id"]),
            organization_id=int(row["organization_id"]),
            name=str(row["name"]),
            created_at=self._parse_dt(row["created_at"]),
        )

    def _line_from_row(self, row: RowMapping) -> LineRow:
        return LineRow(
            id=int(row["id"]),
            site_id=int(row["site_id"]),
            organization_id=int(row["organization_id"]),
            name=str(row["name"]),
            created_at=self._parse_dt(row["created_at"]),
        )

    def _device_from_row(self, row: RowMapping) -> DeviceRow:
        return DeviceRow(
            id=int(row["id"]),
            organization_id=int(row["organization_id"]),
            site_id=int(row["site_id"]),
            production_line_id=int(row["production_line_id"]),
            device_id=str(row["device_id"]),
            name=str(row["name"]),
            status=str(row["status"]),
            created_at=self._parse_dt(row["created_at"]),
        )

    def _administrator_from_row(self, row: RowMapping) -> AdministratorRow:
        return AdministratorRow(
            id=int(row["id"]),
            organization_id=int(row["organization_id"]),
            username=str(row["username"]),
            created_at=self._parse_dt(row["created_at"]),
        )

    @staticmethod
    def _parse_dt(value: object) -> datetime:
        """Normalize a column value (str from SQLite, datetime from PostgreSQL)."""
        if isinstance(value, datetime):
            return _utc(value)
        return _utc(datetime.fromisoformat(str(value)))
