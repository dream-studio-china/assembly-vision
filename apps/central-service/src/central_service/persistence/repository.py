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
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, TypeVar, cast
from uuid import uuid4

from assemblyvision_domain.models import (
    BusinessResult,
    ComponentCorrection,
    InspectionRecord,
    InternalDecision,
    ReviewDisposition,
    allowed_review_dispositions,
)
from sqlalchemy import Engine, Select, Table, Text, and_, case, func, or_, select, text
from sqlalchemy.engine import RowMapping
from sqlalchemy.exc import IntegrityError

from central_service.auth.passwords import CredentialHash, hash_credential, verify_credential
from central_service.persistence.schema import (
    admin_sessions,
    administrators,
    audit_logs,
    components,
    desired_configurations,
    devices,
    inspection_components,
    inspection_media,
    inspections,
    model_packages,
    model_versions,
    organizations,
    product_version_barcodes,
    product_version_components,
    product_versions,
    production_lines,
    products,
    review_records,
    rule_component_policies,
    rule_model_compatibilities,
    rule_versions,
    rules,
    sites,
    upload_receipts,
)

_SESSION_LOOKUP_BYTES = 16
_SESSION_SECRET_BYTES = 32
_ACTIVE = "ACTIVE"
_DESIRED_PRODUCT_MODEL_VERSIONS = model_versions.alias("desired_product_model_versions")
_DESIRED_COMPONENT_MODEL_VERSIONS = model_versions.alias("desired_component_model_versions")


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


def _normalize_sha256(value: object) -> str | None:
    """Normalize a checksum to a bare 64-hex value, or None when invalid.

    Accepts the canonical bare form and the ``sha256:<hex>`` prefix form
    (contract 10 example); the stored form is always bare lowercase hex.
    """
    if not isinstance(value, str):
        return None
    text = value.strip()
    if text.lower().startswith("sha256:"):
        text = text[len("sha256:") :]
    text = text.lower()
    if len(text) != 64 or any(ch not in "0123456789abcdef" for ch in text):
        return None
    return text


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


# ---------------------------------------------------------------------------
# C5 metadata governance rows, errors, and conflict mapping. Published central
# versions are immutable and registered metadata only: they never imply a
# device downloaded, validated, or activated the content. The mapped
# constraints translate concurrent uniqueness races into explicit conflicts.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ComponentRow:
    id: int
    organization_id: int
    component_code: str
    display_name: str
    created_at: datetime


@dataclass(frozen=True)
class ProductRow:
    id: int
    organization_id: int
    product_code: str
    name: str
    created_at: datetime


@dataclass(frozen=True)
class ProductSummaryRow:
    """A stable product with its latest governed version (C5)."""

    id: int
    organization_id: int
    product_code: str
    name: str
    created_at: datetime
    version_count: int
    latest_version_id: str | None
    latest_version_number: int | None
    latest_version_status: str | None


@dataclass(frozen=True)
class ProductComponentRow:
    component_code: str
    expected_count: int


@dataclass(frozen=True)
class ProductComponentInput:
    """A required component and its frozen expected count for a draft version."""

    component_code: str
    expected_count: int


@dataclass(frozen=True)
class ProductVersionRow:
    id: int
    organization_id: int
    product_id: int
    product_code: str
    version_id: str
    version: int
    status: str
    barcodes: list[str]
    components: list[ProductComponentRow]
    published_at: datetime | None
    published_by: str | None
    publish_reason: str | None
    created_at: datetime


@dataclass(frozen=True)
class ProductDetailRow:
    product: ProductRow
    versions: list[ProductVersionRow]


@dataclass(frozen=True)
class RuleRow:
    id: int
    organization_id: int
    rule_code: str
    name: str
    created_at: datetime


@dataclass(frozen=True)
class RuleSummaryRow:
    """A stable rule with its latest governed version (C5)."""

    id: int
    organization_id: int
    rule_code: str
    name: str
    created_at: datetime
    version_count: int
    latest_version_id: str | None
    latest_version_number: int | None
    latest_version_status: str | None


@dataclass(frozen=True)
class RulePolicyRow:
    component_code: str
    high_confidence: float
    medium_confidence: float
    minimum_medium_detections: int
    require_adjacent_frames: bool
    expected_count: int


@dataclass(frozen=True)
class RulePolicyInput:
    """Per-component confidence/temporal policy for a rule draft (design 14)."""

    component_code: str
    high_confidence: float
    medium_confidence: float
    minimum_medium_detections: int
    require_adjacent_frames: bool
    expected_count: int


@dataclass(frozen=True)
class RuleVersionRow:
    id: int
    organization_id: int
    rule_id: int
    rule_code: str
    product_version_id: str
    version_id: str
    version: int
    status: str
    barcode_required: bool
    minimum_usable_frames: int
    uncertain_maps_to_ng: bool
    mandatory_gates: dict[str, bool]
    component_policies: list[RulePolicyRow]
    compatible_model_version_ids: list[str]
    content_sha256: str
    published_at: datetime | None
    published_by: str | None
    publish_reason: str | None
    created_at: datetime


@dataclass(frozen=True)
class RuleDetailRow:
    rule: RuleRow
    versions: list[RuleVersionRow]


@dataclass(frozen=True)
class ModelPackageRow:
    id: int
    organization_id: int
    model_code: str
    name: str
    task: str
    created_at: datetime


@dataclass(frozen=True)
class ModelSummaryRow:
    """A stable model package with its latest governed version (C5)."""

    id: int
    organization_id: int
    model_code: str
    name: str
    task: str
    created_at: datetime
    version_count: int
    latest_version_id: str | None
    latest_version_number: int | None
    latest_version_status: str | None


@dataclass(frozen=True)
class ModelVersionRow:
    id: int
    organization_id: int
    model_package_id: int
    model_code: str
    task: str
    version_id: str
    version: int
    status: str
    semantic_version: str
    edge_version_label: str
    runtime: str
    input_width: int
    input_height: int
    class_names: list[str]
    artifacts: list[dict[str, object]]
    datasets: list[dict[str, object]]
    split_strategy: str
    source_revision: str
    training_config_revision: str
    metrics: list[dict[str, object]]
    limitations: list[str]
    manifest_sha256: str
    published_at: datetime | None
    published_by: str | None
    publish_reason: str | None
    created_at: datetime


@dataclass(frozen=True)
class ModelDetailRow:
    package: ModelPackageRow
    versions: list[ModelVersionRow]


@dataclass(frozen=True)
class DesiredConfigurationRow:
    """The current desired bundle for one device (M1, C5).

    A desired assignment records intent only: M1 has no remote download,
    validation, or activation, and the record never changes edge behavior.
    """

    id: int
    organization_id: int
    device_row_id: int
    device_id: str
    device_name: str
    revision: int
    product_version_id: str
    product_model_version_id: str
    component_model_version_id: str
    rule_version_id: str
    reason: str
    assigned_by: str
    assigned_at: datetime
    created_at: datetime


@dataclass(frozen=True)
class ComponentCreateResult:
    component: ComponentRow
    replayed: bool


@dataclass(frozen=True)
class ProductCreateResult:
    product: ProductRow
    replayed: bool


@dataclass(frozen=True)
class ProductVersionCreateResult:
    version: ProductVersionRow
    replayed: bool


@dataclass(frozen=True)
class RuleCreateResult:
    rule: RuleRow
    replayed: bool


@dataclass(frozen=True)
class RuleVersionCreateResult:
    version: RuleVersionRow
    replayed: bool


@dataclass(frozen=True)
class ModelCreateResult:
    package: ModelPackageRow
    replayed: bool


@dataclass(frozen=True)
class ModelVersionCreateResult:
    version: ModelVersionRow
    replayed: bool


@dataclass(frozen=True)
class PublishResult:
    """Outcome of an idempotent version publish (C5).

    A repeat publish returns the already-published version without writing a
    second audit event.
    """

    version_id: str
    status: str
    replayed: bool


class MetadataCodeExistsError(Exception):
    """A stable resource code already exists in the organization (409)."""


class MetadataVersionNotFoundError(Exception):
    """A governed version_id does not exist in this organization (404)."""


class MetadataVersionConflictError(Exception):
    """A version number or public version_id collided (409)."""


class IdempotencyConflictError(Exception):
    """An idempotency key was reused with a different payload (409)."""


class InvalidComponentError(Exception):
    """A product version's component set is invalid (422)."""


class InvalidPolicyError(Exception):
    """A rule version's component policy is invalid (422)."""


class InvalidManifestError(Exception):
    """A model manifest draft is invalid (422)."""


class IncompatibleVersionError(Exception):
    """A publish or assignment references an incompatible version (409)."""


class AmbiguousBarcodeError(Exception):
    """A published barcode would map to a second product version (409)."""


class ProductNotFoundError(Exception):
    """The stable product does not exist in this organization (404)."""


class RuleNotFoundError(Exception):
    """The stable rule does not exist in this organization (404)."""


class ModelNotFoundError(Exception):
    """The stable model package does not exist in this organization (404)."""


class DeviceNotFoundError(Exception):
    """The device does not exist in this organization (404)."""


class DesiredConfigurationNotFoundError(Exception):
    """The device has no desired configuration record (404)."""


class RevisionMismatchError(Exception):
    """The If-Match revision is stale (412)."""


_METADATA_CONFLICTS: dict[str, type[Exception]] = {
    "uq_components_org_code": MetadataCodeExistsError,
    "uq_products_org_code": MetadataCodeExistsError,
    "uq_rules_org_code": MetadataCodeExistsError,
    "uq_model_packages_org_code": MetadataCodeExistsError,
    "uq_product_versions_product_version": MetadataVersionConflictError,
    "uq_rule_versions_rule_version": MetadataVersionConflictError,
    "uq_model_versions_package_version": MetadataVersionConflictError,
    "uq_product_versions_org_version_id": MetadataVersionConflictError,
    "uq_rule_versions_org_version_id": MetadataVersionConflictError,
    "uq_model_versions_org_version_id": MetadataVersionConflictError,
    "uq_components_org_key": IdempotencyConflictError,
    "uq_products_org_key": IdempotencyConflictError,
    "uq_rules_org_key": IdempotencyConflictError,
    "uq_model_packages_org_key": IdempotencyConflictError,
    "uq_product_versions_product_key": IdempotencyConflictError,
    "uq_rule_versions_rule_key": IdempotencyConflictError,
    "uq_model_versions_package_key": IdempotencyConflictError,
    "uq_product_version_barcodes_published": AmbiguousBarcodeError,
    "uq_desired_configurations_device": RevisionMismatchError,
}


_T = TypeVar("_T")


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

    def revoke_admin_session(self, session_token: str) -> bool:
        """Delete the session row for a token; returns True when one existed."""
        if len(session_token) < _SESSION_LOOKUP_BYTES + _SESSION_SECRET_BYTES:
            return False
        lookup = session_token[:_SESSION_LOOKUP_BYTES]
        with self._engine.begin() as connection:
            result = connection.execute(
                admin_sessions.delete().where(admin_sessions.c.session_lookup == lookup)
            )
        return int(result.rowcount) > 0

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

    # -- metadata governance (C5) -------------------------------------------

    def _metadata_write(self, fn: Callable[[Any], _T]) -> _T:
        """Run ``fn(connection)`` inside one write transaction (C5).

        SQLite serializes with BEGIN IMMEDIATE (the review pattern) so
        concurrent metadata writes cannot interleave; PostgreSQL uses the
        engine transaction with unique constraints as the concurrency backstop.
        """
        if self._engine.dialect.name == "sqlite":

            def _run() -> _T:
                with self._engine.connect() as connection:
                    connection.execute(text("BEGIN IMMEDIATE"))
                    try:
                        result = fn(connection)
                        connection.commit()
                        return result
                    except Exception:
                        connection.rollback()
                        raise

            return _run()
        with self._engine.begin() as connection:
            return fn(connection)

    def _metadata_write_mapped(self, fn: Callable[[Any], _T]) -> _T:
        """Run a metadata write and map uniqueness races to typed conflicts."""
        try:
            return self._metadata_write(fn)
        except IntegrityError as exc:
            error_type = _METADATA_CONFLICTS.get(_integrity_constraint(exc) or "")
            if error_type is None:
                raise
            raise error_type("a concurrent metadata write was rejected by the database") from exc

    @staticmethod
    def _metadata_replay(
        connection: Any,
        *,
        table: Table,
        organization_id: int,
        scope_column: str,
        scope_value: Any,
        idempotency_key: str | None,
        request_hash: str,
        label: str,
    ) -> RowMapping | None:
        """Return the prior row for an idempotent retry, or None.

        A reused key with the same request hash replays the original result; a
        reused key with a different hash is an explicit conflict and never
        mutates the original row.
        """
        if idempotency_key is None:
            return None
        existing = (
            connection.execute(
                select(table).where(
                    and_(
                        table.c.organization_id == organization_id,
                        table.c[scope_column] == scope_value,
                        table.c.idempotency_key == idempotency_key,
                    )
                )
            )
            .mappings()
            .first()
        )
        if existing is None:
            return None
        if str(existing["request_hash"]) != request_hash:
            raise IdempotencyConflictError(f"idempotency key was reused with a different {label}")
        return cast(RowMapping, existing)

    @staticmethod
    def _next_version(connection: Any, *, table: Table, scope_column: str, scope_value: Any) -> int:
        latest = connection.execute(
            select(func.max(table.c.version)).where(table.c[scope_column] == scope_value)
        ).scalar()
        return (int(latest) if latest is not None else 0) + 1

    @staticmethod
    def _canonical_hash(payload: dict[str, object]) -> str:
        """Stable SHA-256 of a normalized payload (idempotency/content pinning)."""
        return hashlib.sha256(
            json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()

    @staticmethod
    def _audit_metadata(
        connection: Any,
        *,
        organization_id: int,
        actor: str,
        action: str,
        target_type: str,
        target_id: str,
        detail: str,
        request_id: str | None,
        reason: str | None = None,
        before_state: dict[str, object] | None = None,
        after_state: dict[str, object] | None = None,
    ) -> None:
        """Write one immutable governance audit event in the current transaction."""
        connection.execute(
            audit_logs.insert().values(
                organization_id=organization_id,
                actor_type="ADMIN",
                actor_id=None,
                action=action,
                target_type=target_type,
                target_id=target_id,
                detail=detail,
                request_id=request_id,
                reason=reason,
                before_state=before_state,
                after_state=after_state,
            )
        )

    # -- components ----------------------------------------------------------

    def list_components(self, organization_id: int) -> list[ComponentRow]:
        with self._engine.connect() as connection:
            rows = (
                connection.execute(
                    select(components)
                    .where(components.c.organization_id == organization_id)
                    .order_by(components.c.component_code)
                )
                .mappings()
                .all()
            )
        return [self._component_from_row(row) for row in rows]

    def create_component(
        self,
        *,
        organization_id: int,
        component_code: str,
        display_name: str,
        idempotency_key: str | None,
        request_hash: str,
        created_at: datetime,
        actor: str,
        request_id: str | None,
    ) -> ComponentCreateResult:
        def _run(connection: Any) -> ComponentCreateResult:
            replayed_row = self._metadata_replay(
                connection,
                table=components,
                organization_id=organization_id,
                scope_column="organization_id",
                scope_value=organization_id,
                idempotency_key=idempotency_key,
                request_hash=request_hash,
                label="component creation",
            )
            if replayed_row is not None:
                return ComponentCreateResult(
                    component=self._component_from_row(replayed_row), replayed=True
                )
            duplicate = connection.execute(
                select(components.c.id).where(
                    and_(
                        components.c.organization_id == organization_id,
                        components.c.component_code == component_code,
                    )
                )
            ).scalar_one_or_none()
            if duplicate is not None:
                raise MetadataCodeExistsError(f"component already exists: {component_code}")
            row = (
                connection.execute(
                    components.insert()
                    .values(
                        organization_id=organization_id,
                        component_code=component_code,
                        display_name=display_name,
                        idempotency_key=idempotency_key,
                        request_hash=request_hash,
                        created_at=created_at,
                    )
                    .returning(*components.c)
                )
                .mappings()
                .one()
            )
            self._audit_metadata(
                connection,
                organization_id=organization_id,
                actor=actor,
                action="COMPONENT_CREATED",
                target_type="component",
                target_id=component_code,
                detail=f"component_code={component_code}",
                request_id=request_id,
                after_state={"component_code": component_code, "display_name": display_name},
            )
            return ComponentCreateResult(component=self._component_from_row(row), replayed=False)

        return self._metadata_write_mapped(_run)

    # -- products ------------------------------------------------------------

    def list_products(self, organization_id: int) -> list[ProductSummaryRow]:
        with self._engine.connect() as connection:
            product_rows = (
                connection.execute(
                    select(products)
                    .where(products.c.organization_id == organization_id)
                    .order_by(products.c.product_code)
                )
                .mappings()
                .all()
            )
            version_rows = (
                connection.execute(
                    select(
                        product_versions.c.product_id,
                        product_versions.c.version_id,
                        product_versions.c.version,
                        product_versions.c.status,
                    )
                    .where(product_versions.c.organization_id == organization_id)
                    .order_by(product_versions.c.product_id, product_versions.c.version.desc())
                )
                .mappings()
                .all()
            )
        latest: dict[int, RowMapping] = {}
        counts: dict[int, int] = {}
        for row in version_rows:
            product_id = int(row["product_id"])
            latest.setdefault(product_id, row)
            counts[product_id] = counts.get(product_id, 0) + 1
        return [
            ProductSummaryRow(
                id=int(product["id"]),
                organization_id=int(product["organization_id"]),
                product_code=str(product["product_code"]),
                name=str(product["name"]),
                created_at=self._parse_dt(product["created_at"]),
                version_count=counts.get(int(product["id"]), 0),
                latest_version_id=(
                    str(latest[int(product["id"])]["version_id"])
                    if int(product["id"]) in latest
                    else None
                ),
                latest_version_number=(
                    int(latest[int(product["id"])]["version"])
                    if int(product["id"]) in latest
                    else None
                ),
                latest_version_status=(
                    str(latest[int(product["id"])]["status"])
                    if int(product["id"]) in latest
                    else None
                ),
            )
            for product in product_rows
        ]

    def create_product(
        self,
        *,
        organization_id: int,
        product_code: str,
        name: str,
        idempotency_key: str | None,
        request_hash: str,
        created_at: datetime,
        actor: str,
        request_id: str | None,
    ) -> ProductCreateResult:
        def _run(connection: Any) -> ProductCreateResult:
            replayed_row = self._metadata_replay(
                connection,
                table=products,
                organization_id=organization_id,
                scope_column="organization_id",
                scope_value=organization_id,
                idempotency_key=idempotency_key,
                request_hash=request_hash,
                label="product creation",
            )
            if replayed_row is not None:
                return ProductCreateResult(
                    product=self._product_from_row(replayed_row), replayed=True
                )
            duplicate = connection.execute(
                select(products.c.id).where(
                    and_(
                        products.c.organization_id == organization_id,
                        products.c.product_code == product_code,
                    )
                )
            ).scalar_one_or_none()
            if duplicate is not None:
                raise MetadataCodeExistsError(f"product already exists: {product_code}")
            row = (
                connection.execute(
                    products.insert()
                    .values(
                        organization_id=organization_id,
                        product_code=product_code,
                        name=name,
                        idempotency_key=idempotency_key,
                        request_hash=request_hash,
                        created_at=created_at,
                    )
                    .returning(*products.c)
                )
                .mappings()
                .one()
            )
            self._audit_metadata(
                connection,
                organization_id=organization_id,
                actor=actor,
                action="PRODUCT_CREATED",
                target_type="product",
                target_id=product_code,
                detail=f"product_code={product_code}",
                request_id=request_id,
                after_state={"product_code": product_code, "name": name},
            )
            return ProductCreateResult(product=self._product_from_row(row), replayed=False)

        return self._metadata_write_mapped(_run)

    def get_product(self, organization_id: int, product_id: int) -> ProductRow | None:
        with self._engine.connect() as connection:
            row = (
                connection.execute(
                    select(products).where(
                        and_(
                            products.c.id == product_id,
                            products.c.organization_id == organization_id,
                        )
                    )
                )
                .mappings()
                .first()
            )
        return self._product_from_row(row) if row is not None else None

    def get_product_detail(self, organization_id: int, product_id: int) -> ProductDetailRow | None:
        product = self.get_product(organization_id, product_id)
        if product is None:
            return None
        with self._engine.connect() as connection:
            versions = []
            for row in (
                connection.execute(
                    select(product_versions.c.version_id)
                    .where(
                        and_(
                            product_versions.c.organization_id == organization_id,
                            product_versions.c.product_id == product_id,
                        )
                    )
                    .order_by(product_versions.c.version)
                )
                .mappings()
                .all()
            ):
                version = self._load_product_version(
                    connection,
                    organization_id=organization_id,
                    version_id=str(row["version_id"]),
                )
                if version is not None:
                    versions.append(version)
        return ProductDetailRow(product=product, versions=versions)

    def create_product_version(
        self,
        *,
        organization_id: int,
        product_id: int,
        barcodes: list[str],
        required_components: list[ProductComponentInput],
        idempotency_key: str | None,
        request_hash: str,
        created_at: datetime,
        actor: str,
        request_id: str | None,
    ) -> ProductVersionCreateResult:
        def _run(connection: Any) -> ProductVersionCreateResult:
            product = connection.execute(
                select(products.c.id).where(
                    and_(products.c.id == product_id, products.c.organization_id == organization_id)
                )
            ).scalar_one_or_none()
            if product is None:
                raise ProductNotFoundError(f"product {product_id} does not exist")

            if not required_components:
                raise InvalidComponentError("a product version needs at least one component")
            if len(required_components) > 64:
                raise InvalidComponentError("a product version may list at most 64 components")
            if len(barcodes) > 100:
                raise InvalidComponentError("a product version may map at most 100 barcodes")
            seen_codes: set[str] = set()
            resolved: list[tuple[int, int]] = []
            for component in required_components:
                if component.component_code in seen_codes:
                    raise InvalidComponentError(f"duplicate component: {component.component_code}")
                seen_codes.add(component.component_code)
                if not 1 <= component.expected_count <= 64:
                    raise InvalidComponentError(
                        f"expected_count for {component.component_code} must be 1..64"
                    )
                component_id = connection.execute(
                    select(components.c.id).where(
                        and_(
                            components.c.organization_id == organization_id,
                            components.c.component_code == component.component_code,
                        )
                    )
                ).scalar_one_or_none()
                if component_id is None:
                    raise InvalidComponentError(f"unknown component: {component.component_code}")
                resolved.append((int(component_id), component.expected_count))
            for barcode in barcodes:
                if not barcode or len(barcode) > 256:
                    raise InvalidComponentError("barcode values must be 1..256 characters")

            replayed_row = self._metadata_replay(
                connection,
                table=product_versions,
                organization_id=organization_id,
                scope_column="product_id",
                scope_value=product_id,
                idempotency_key=idempotency_key,
                request_hash=request_hash,
                label="product version creation",
            )
            if replayed_row is not None:
                version = self._load_product_version(
                    connection,
                    organization_id=organization_id,
                    version_id=str(replayed_row["version_id"]),
                )
                if version is None:
                    raise MetadataVersionNotFoundError(
                        "the created product version could not be reloaded"
                    )
                return ProductVersionCreateResult(version=version, replayed=True)

            version_number = self._next_version(
                connection,
                table=product_versions,
                scope_column="product_id",
                scope_value=product_id,
            )
            version_id = str(uuid4())
            row = (
                connection.execute(
                    product_versions.insert()
                    .values(
                        organization_id=organization_id,
                        product_id=product_id,
                        version_id=version_id,
                        version=version_number,
                        status="DRAFT",
                        idempotency_key=idempotency_key,
                        request_hash=request_hash,
                        created_at=created_at,
                    )
                    .returning(*product_versions.c)
                )
                .mappings()
                .one()
            )
            version_pk = int(row["id"])
            for component_id, expected_count in resolved:
                connection.execute(
                    product_version_components.insert().values(
                        product_version_id=version_pk,
                        component_id=component_id,
                        expected_count=expected_count,
                    )
                )
            for barcode in barcodes:
                connection.execute(
                    product_version_barcodes.insert().values(
                        organization_id=organization_id,
                        product_version_id=version_pk,
                        barcode_value=barcode,
                        status="DRAFT",
                    )
                )
            self._audit_metadata(
                connection,
                organization_id=organization_id,
                actor=actor,
                action="PRODUCT_VERSION_DRAFTED",
                target_type="product_version",
                target_id=version_id,
                detail=f"version={version_number}",
                request_id=request_id,
                after_state={"version": version_number, "status": "DRAFT"},
            )
            version = self._load_product_version(
                connection, organization_id=organization_id, version_id=version_id
            )
            if version is None:
                raise MetadataVersionNotFoundError(
                    "the created product version could not be reloaded"
                )
            return ProductVersionCreateResult(version=version, replayed=False)

        return self._metadata_write_mapped(_run)

    def get_product_version(
        self, organization_id: int, version_id: str
    ) -> ProductVersionRow | None:
        with self._engine.connect() as connection:
            return self._load_product_version(
                connection, organization_id=organization_id, version_id=version_id
            )

    def publish_product_version(
        self,
        *,
        organization_id: int,
        version_id: str,
        published_by: str,
        publish_reason: str,
        published_at: datetime,
        actor: str,
        request_id: str | None,
    ) -> PublishResult:
        def _run(connection: Any) -> PublishResult:
            row = (
                connection.execute(
                    select(product_versions).where(
                        and_(
                            product_versions.c.organization_id == organization_id,
                            product_versions.c.version_id == version_id,
                        )
                    )
                )
                .mappings()
                .first()
            )
            if row is None:
                raise MetadataVersionNotFoundError(f"product version {version_id} does not exist")
            if str(row["status"]) == "PUBLISHED":
                return PublishResult(version_id=version_id, status="PUBLISHED", replayed=True)
            version_pk = int(row["id"])
            version_number = int(row["version"])
            component_count = connection.execute(
                select(func.count(product_version_components.c.id)).where(
                    product_version_components.c.product_version_id == version_pk
                )
            ).scalar_one()
            if component_count == 0:
                raise InvalidComponentError(
                    "a published product version needs at least one component"
                )
            for barcode_row in (
                connection.execute(
                    select(product_version_barcodes.c.barcode_value).where(
                        product_version_barcodes.c.product_version_id == version_pk
                    )
                )
                .mappings()
                .all()
            ):
                barcode = str(barcode_row["barcode_value"])
                conflict = connection.execute(
                    select(product_version_barcodes.c.id).where(
                        and_(
                            product_version_barcodes.c.organization_id == organization_id,
                            product_version_barcodes.c.barcode_value == barcode,
                            product_version_barcodes.c.status == "PUBLISHED",
                            product_version_barcodes.c.product_version_id != version_pk,
                        )
                    )
                ).first()
                if conflict is not None:
                    raise AmbiguousBarcodeError(
                        f"barcode {barcode} already maps to another published product version"
                    )
            connection.execute(
                product_versions.update()
                .where(product_versions.c.id == version_pk)
                .values(
                    status="PUBLISHED",
                    published_at=published_at,
                    published_by=published_by,
                    publish_reason=publish_reason,
                )
            )
            connection.execute(
                product_version_barcodes.update()
                .where(product_version_barcodes.c.product_version_id == version_pk)
                .values(status="PUBLISHED")
            )
            self._audit_metadata(
                connection,
                organization_id=organization_id,
                actor=actor,
                action="PRODUCT_PUBLISHED",
                target_type="product_version",
                target_id=version_id,
                detail=f"version={version_number}",
                request_id=request_id,
                reason=publish_reason,
                before_state={"version": version_number, "status": "DRAFT"},
                after_state={"version": version_number, "status": "PUBLISHED"},
            )
            return PublishResult(version_id=version_id, status="PUBLISHED", replayed=False)

        return self._metadata_write_mapped(_run)

    # -- rules ---------------------------------------------------------------

    def list_rules(self, organization_id: int) -> list[RuleSummaryRow]:
        with self._engine.connect() as connection:
            rule_rows = (
                connection.execute(
                    select(rules)
                    .where(rules.c.organization_id == organization_id)
                    .order_by(rules.c.rule_code)
                )
                .mappings()
                .all()
            )
            version_rows = (
                connection.execute(
                    select(
                        rule_versions.c.rule_id,
                        rule_versions.c.version_id,
                        rule_versions.c.version,
                        rule_versions.c.status,
                    )
                    .where(rule_versions.c.organization_id == organization_id)
                    .order_by(rule_versions.c.rule_id, rule_versions.c.version.desc())
                )
                .mappings()
                .all()
            )
        latest: dict[int, RowMapping] = {}
        counts: dict[int, int] = {}
        for row in version_rows:
            rule_id = int(row["rule_id"])
            latest.setdefault(rule_id, row)
            counts[rule_id] = counts.get(rule_id, 0) + 1
        return [
            RuleSummaryRow(
                id=int(rule["id"]),
                organization_id=int(rule["organization_id"]),
                rule_code=str(rule["rule_code"]),
                name=str(rule["name"]),
                created_at=self._parse_dt(rule["created_at"]),
                version_count=counts.get(int(rule["id"]), 0),
                latest_version_id=(
                    str(latest[int(rule["id"])]["version_id"])
                    if int(rule["id"]) in latest
                    else None
                ),
                latest_version_number=(
                    int(latest[int(rule["id"])]["version"]) if int(rule["id"]) in latest else None
                ),
                latest_version_status=(
                    str(latest[int(rule["id"])]["status"]) if int(rule["id"]) in latest else None
                ),
            )
            for rule in rule_rows
        ]

    def create_rule(
        self,
        *,
        organization_id: int,
        rule_code: str,
        name: str,
        idempotency_key: str | None,
        request_hash: str,
        created_at: datetime,
        actor: str,
        request_id: str | None,
    ) -> RuleCreateResult:
        def _run(connection: Any) -> RuleCreateResult:
            replayed_row = self._metadata_replay(
                connection,
                table=rules,
                organization_id=organization_id,
                scope_column="organization_id",
                scope_value=organization_id,
                idempotency_key=idempotency_key,
                request_hash=request_hash,
                label="rule creation",
            )
            if replayed_row is not None:
                return RuleCreateResult(rule=self._rule_from_row(replayed_row), replayed=True)
            duplicate = connection.execute(
                select(rules.c.id).where(
                    and_(
                        rules.c.organization_id == organization_id,
                        rules.c.rule_code == rule_code,
                    )
                )
            ).scalar_one_or_none()
            if duplicate is not None:
                raise MetadataCodeExistsError(f"rule already exists: {rule_code}")
            row = (
                connection.execute(
                    rules.insert()
                    .values(
                        organization_id=organization_id,
                        rule_code=rule_code,
                        name=name,
                        idempotency_key=idempotency_key,
                        request_hash=request_hash,
                        created_at=created_at,
                    )
                    .returning(*rules.c)
                )
                .mappings()
                .one()
            )
            self._audit_metadata(
                connection,
                organization_id=organization_id,
                actor=actor,
                action="RULE_CREATED",
                target_type="rule",
                target_id=rule_code,
                detail=f"rule_code={rule_code}",
                request_id=request_id,
                after_state={"rule_code": rule_code, "name": name},
            )
            return RuleCreateResult(rule=self._rule_from_row(row), replayed=False)

        return self._metadata_write_mapped(_run)

    def get_rule(self, organization_id: int, rule_id: int) -> RuleRow | None:
        with self._engine.connect() as connection:
            row = (
                connection.execute(
                    select(rules).where(
                        and_(rules.c.id == rule_id, rules.c.organization_id == organization_id)
                    )
                )
                .mappings()
                .first()
            )
        return self._rule_from_row(row) if row is not None else None

    def get_rule_detail(self, organization_id: int, rule_id: int) -> RuleDetailRow | None:
        rule = self.get_rule(organization_id, rule_id)
        if rule is None:
            return None
        with self._engine.connect() as connection:
            versions = []
            for row in (
                connection.execute(
                    select(rule_versions.c.version_id)
                    .where(
                        and_(
                            rule_versions.c.organization_id == organization_id,
                            rule_versions.c.rule_id == rule_id,
                        )
                    )
                    .order_by(rule_versions.c.version)
                )
                .mappings()
                .all()
            ):
                version = self._load_rule_version(
                    connection,
                    organization_id=organization_id,
                    version_id=str(row["version_id"]),
                )
                if version is not None:
                    versions.append(version)
        return RuleDetailRow(rule=rule, versions=versions)

    def create_rule_version(
        self,
        *,
        organization_id: int,
        rule_id: int,
        product_version_id: str,
        barcode_required: bool,
        minimum_usable_frames: int,
        mandatory_gates: dict[str, bool],
        component_policies: list[RulePolicyInput],
        compatible_component_model_version_ids: list[str],
        idempotency_key: str | None,
        request_hash: str,
        created_at: datetime,
        actor: str,
        request_id: str | None,
    ) -> RuleVersionCreateResult:
        def _run(connection: Any) -> RuleVersionCreateResult:
            rule = connection.execute(
                select(rules.c.id).where(
                    and_(rules.c.id == rule_id, rules.c.organization_id == organization_id)
                )
            ).scalar_one_or_none()
            if rule is None:
                raise RuleNotFoundError(f"rule {rule_id} does not exist")
            product_version_pk = connection.execute(
                select(product_versions.c.id).where(
                    and_(
                        product_versions.c.organization_id == organization_id,
                        product_versions.c.version_id == product_version_id,
                    )
                )
            ).scalar_one_or_none()
            if product_version_pk is None:
                raise MetadataVersionNotFoundError(
                    f"product version {product_version_id} does not exist"
                )

            if not component_policies:
                raise InvalidPolicyError("a rule version needs at least one component policy")
            if len(component_policies) > 64:
                raise InvalidPolicyError("a rule version may list at most 64 component policies")
            if len(mandatory_gates) > 16:
                raise InvalidPolicyError("a rule version may declare at most 16 mandatory gates")
            if not 1 <= minimum_usable_frames <= 1000:
                raise InvalidPolicyError("minimum_usable_frames must be 1..1000")
            if len(compatible_component_model_version_ids) > 32:
                raise InvalidPolicyError("a rule version may list at most 32 compatible models")

            seen_codes: set[str] = set()
            policy_rows: list[tuple[int, RulePolicyInput]] = []
            for policy in component_policies:
                if policy.component_code in seen_codes:
                    raise InvalidPolicyError(f"duplicate component policy: {policy.component_code}")
                seen_codes.add(policy.component_code)
                if not 0.0 < policy.medium_confidence <= policy.high_confidence <= 1.0:
                    raise InvalidPolicyError(
                        f"confidence thresholds for {policy.component_code} must satisfy "
                        "0 < medium <= high <= 1"
                    )
                if not 1 <= policy.minimum_medium_detections <= 64:
                    raise InvalidPolicyError(
                        f"minimum_medium_detections for {policy.component_code} must be 1..64"
                    )
                if not 1 <= policy.expected_count <= 64:
                    raise InvalidPolicyError(
                        f"expected_count for {policy.component_code} must be 1..64"
                    )
                component_id = connection.execute(
                    select(components.c.id).where(
                        and_(
                            components.c.organization_id == organization_id,
                            components.c.component_code == policy.component_code,
                        )
                    )
                ).scalar_one_or_none()
                if component_id is None:
                    raise InvalidPolicyError(f"unknown component: {policy.component_code}")
                policy_rows.append((int(component_id), policy))

            compat_model_pks: list[int] = []
            for model_version_id in compatible_component_model_version_ids:
                model_pk = connection.execute(
                    select(model_versions.c.id).where(
                        and_(
                            model_versions.c.organization_id == organization_id,
                            model_versions.c.version_id == model_version_id,
                        )
                    )
                ).scalar_one_or_none()
                if model_pk is None:
                    raise InvalidPolicyError(f"unknown model version: {model_version_id}")
                compat_model_pks.append(int(model_pk))

            replayed_row = self._metadata_replay(
                connection,
                table=rule_versions,
                organization_id=organization_id,
                scope_column="rule_id",
                scope_value=rule_id,
                idempotency_key=idempotency_key,
                request_hash=request_hash,
                label="rule version creation",
            )
            if replayed_row is not None:
                version = self._load_rule_version(
                    connection,
                    organization_id=organization_id,
                    version_id=str(replayed_row["version_id"]),
                )
                if version is None:
                    raise MetadataVersionNotFoundError(
                        "the created rule version could not be reloaded"
                    )
                return RuleVersionCreateResult(version=version, replayed=True)

            content_sha256 = self._canonical_hash(
                {
                    "product_version_id": product_version_id,
                    "barcode_required": barcode_required,
                    "minimum_usable_frames": minimum_usable_frames,
                    "uncertain_maps_to_ng": True,
                    "mandatory_gates": dict(sorted(mandatory_gates.items())),
                    "component_policies": [
                        {
                            "component_code": policy.component_code,
                            "high_confidence": policy.high_confidence,
                            "medium_confidence": policy.medium_confidence,
                            "minimum_medium_detections": policy.minimum_medium_detections,
                            "require_adjacent_frames": policy.require_adjacent_frames,
                            "expected_count": policy.expected_count,
                        }
                        for policy in sorted(component_policies, key=lambda p: p.component_code)
                    ],
                    "compatible_component_model_version_ids": sorted(
                        compatible_component_model_version_ids
                    ),
                }
            )
            version_number = self._next_version(
                connection, table=rule_versions, scope_column="rule_id", scope_value=rule_id
            )
            version_id = str(uuid4())
            row = (
                connection.execute(
                    rule_versions.insert()
                    .values(
                        organization_id=organization_id,
                        rule_id=rule_id,
                        product_version_id=int(product_version_pk),
                        version_id=version_id,
                        version=version_number,
                        status="DRAFT",
                        barcode_required=barcode_required,
                        minimum_usable_frames=minimum_usable_frames,
                        uncertain_maps_to_ng=True,
                        mandatory_gates=mandatory_gates,
                        content_sha256=content_sha256,
                        idempotency_key=idempotency_key,
                        request_hash=request_hash,
                        created_at=created_at,
                    )
                    .returning(*rule_versions.c)
                )
                .mappings()
                .one()
            )
            version_pk = int(row["id"])
            for component_id, policy in policy_rows:
                connection.execute(
                    rule_component_policies.insert().values(
                        rule_version_id=version_pk,
                        component_id=component_id,
                        high_confidence=policy.high_confidence,
                        medium_confidence=policy.medium_confidence,
                        minimum_medium_detections=policy.minimum_medium_detections,
                        require_adjacent_frames=policy.require_adjacent_frames,
                        expected_count=policy.expected_count,
                    )
                )
            for model_pk in compat_model_pks:
                connection.execute(
                    rule_model_compatibilities.insert().values(
                        rule_version_id=version_pk, model_version_id=model_pk
                    )
                )
            self._audit_metadata(
                connection,
                organization_id=organization_id,
                actor=actor,
                action="RULE_VERSION_DRAFTED",
                target_type="rule_version",
                target_id=version_id,
                detail=f"version={version_number}",
                request_id=request_id,
                after_state={"version": version_number, "status": "DRAFT"},
            )
            version = self._load_rule_version(
                connection, organization_id=organization_id, version_id=version_id
            )
            if version is None:
                raise MetadataVersionNotFoundError("the created rule version could not be reloaded")
            return RuleVersionCreateResult(version=version, replayed=False)

        return self._metadata_write_mapped(_run)

    def get_rule_version(self, organization_id: int, version_id: str) -> RuleVersionRow | None:
        with self._engine.connect() as connection:
            return self._load_rule_version(
                connection, organization_id=organization_id, version_id=version_id
            )

    def publish_rule_version(
        self,
        *,
        organization_id: int,
        version_id: str,
        published_by: str,
        publish_reason: str,
        published_at: datetime,
        actor: str,
        request_id: str | None,
    ) -> PublishResult:
        def _run(connection: Any) -> PublishResult:
            row = (
                connection.execute(
                    select(rule_versions).where(
                        and_(
                            rule_versions.c.organization_id == organization_id,
                            rule_versions.c.version_id == version_id,
                        )
                    )
                )
                .mappings()
                .first()
            )
            if row is None:
                raise MetadataVersionNotFoundError(f"rule version {version_id} does not exist")
            if str(row["status"]) == "PUBLISHED":
                return PublishResult(version_id=version_id, status="PUBLISHED", replayed=True)
            version_pk = int(row["id"])
            version_number = int(row["version"])
            product_version_pk = int(row["product_version_id"])

            product_version = (
                connection.execute(
                    select(product_versions.c.status).where(
                        and_(
                            product_versions.c.id == product_version_pk,
                            product_versions.c.organization_id == organization_id,
                        )
                    )
                )
                .mappings()
                .first()
            )
            if product_version is None or str(product_version["status"]) != "PUBLISHED":
                raise IncompatibleVersionError(
                    "the referenced product version must be published first"
                )

            required_codes = {
                str(comp["component_code"])
                for comp in connection.execute(
                    select(components.c.component_code)
                    .join(
                        product_version_components,
                        product_version_components.c.component_id == components.c.id,
                    )
                    .where(product_version_components.c.product_version_id == product_version_pk)
                )
                .mappings()
                .all()
            }
            policy_codes = {
                str(policy["component_code"])
                for policy in connection.execute(
                    select(components.c.component_code)
                    .join(
                        rule_component_policies,
                        rule_component_policies.c.component_id == components.c.id,
                    )
                    .where(rule_component_policies.c.rule_version_id == version_pk)
                )
                .mappings()
                .all()
            }
            if required_codes != policy_codes:
                missing = sorted(required_codes - policy_codes)
                extra = sorted(policy_codes - required_codes)
                detail = []
                if missing:
                    detail.append(f"missing policies: {missing}")
                if extra:
                    detail.append(f"unexpected policies: {extra}")
                raise InvalidPolicyError("; ".join(detail) or "policy set mismatch")

            compat_rows = (
                connection.execute(
                    select(rule_model_compatibilities.c.model_version_id).where(
                        rule_model_compatibilities.c.rule_version_id == version_pk
                    )
                )
                .mappings()
                .all()
            )
            if not compat_rows:
                raise InvalidPolicyError(
                    "a published rule must declare at least one compatible component model"
                )
            for compat in compat_rows:
                model_version = (
                    connection.execute(
                        select(
                            model_versions.c.status,
                            model_versions.c.class_names,
                            model_packages.c.task,
                        )
                        .join(
                            model_packages, model_packages.c.id == model_versions.c.model_package_id
                        )
                        .where(
                            and_(
                                model_versions.c.id == int(compat["model_version_id"]),
                                model_versions.c.organization_id == organization_id,
                            )
                        )
                    )
                    .mappings()
                    .first()
                )
                if model_version is None or str(model_version["status"]) != "PUBLISHED":
                    raise IncompatibleVersionError(
                        "a compatible component model must be published first"
                    )
                if str(model_version["task"]) != "COMPONENT_DETECTION":
                    raise IncompatibleVersionError(
                        "a rule may only reference COMPONENT_DETECTION models"
                    )
                classes = {str(item) for item in (model_version["class_names"] or [])}
                if not required_codes.issubset(classes):
                    missing_classes = sorted(required_codes - classes)
                    raise IncompatibleVersionError(
                        "a compatible component model does not cover required components: "
                        f"{missing_classes}"
                    )

            connection.execute(
                rule_versions.update()
                .where(rule_versions.c.id == version_pk)
                .values(
                    status="PUBLISHED",
                    published_at=published_at,
                    published_by=published_by,
                    publish_reason=publish_reason,
                )
            )
            self._audit_metadata(
                connection,
                organization_id=organization_id,
                actor=actor,
                action="RULE_PUBLISHED",
                target_type="rule_version",
                target_id=version_id,
                detail=f"version={version_number}",
                request_id=request_id,
                reason=publish_reason,
                before_state={"version": version_number, "status": "DRAFT"},
                after_state={"version": version_number, "status": "PUBLISHED"},
            )
            return PublishResult(version_id=version_id, status="PUBLISHED", replayed=False)

        return self._metadata_write_mapped(_run)

    # -- models --------------------------------------------------------------

    def list_models(self, organization_id: int) -> list[ModelSummaryRow]:
        with self._engine.connect() as connection:
            package_rows = (
                connection.execute(
                    select(model_packages)
                    .where(model_packages.c.organization_id == organization_id)
                    .order_by(model_packages.c.model_code)
                )
                .mappings()
                .all()
            )
            version_rows = (
                connection.execute(
                    select(
                        model_versions.c.model_package_id,
                        model_versions.c.version_id,
                        model_versions.c.version,
                        model_versions.c.status,
                    )
                    .where(model_versions.c.organization_id == organization_id)
                    .order_by(model_versions.c.model_package_id, model_versions.c.version.desc())
                )
                .mappings()
                .all()
            )
        latest: dict[int, RowMapping] = {}
        counts: dict[int, int] = {}
        for row in version_rows:
            package_id = int(row["model_package_id"])
            latest.setdefault(package_id, row)
            counts[package_id] = counts.get(package_id, 0) + 1
        return [
            ModelSummaryRow(
                id=int(package["id"]),
                organization_id=int(package["organization_id"]),
                model_code=str(package["model_code"]),
                name=str(package["name"]),
                task=str(package["task"]),
                created_at=self._parse_dt(package["created_at"]),
                version_count=counts.get(int(package["id"]), 0),
                latest_version_id=(
                    str(latest[int(package["id"])]["version_id"])
                    if int(package["id"]) in latest
                    else None
                ),
                latest_version_number=(
                    int(latest[int(package["id"])]["version"])
                    if int(package["id"]) in latest
                    else None
                ),
                latest_version_status=(
                    str(latest[int(package["id"])]["status"])
                    if int(package["id"]) in latest
                    else None
                ),
            )
            for package in package_rows
        ]

    def create_model_package(
        self,
        *,
        organization_id: int,
        model_code: str,
        name: str,
        task: str,
        idempotency_key: str | None,
        request_hash: str,
        created_at: datetime,
        actor: str,
        request_id: str | None,
    ) -> ModelCreateResult:
        def _run(connection: Any) -> ModelCreateResult:
            replayed_row = self._metadata_replay(
                connection,
                table=model_packages,
                organization_id=organization_id,
                scope_column="organization_id",
                scope_value=organization_id,
                idempotency_key=idempotency_key,
                request_hash=request_hash,
                label="model package creation",
            )
            if replayed_row is not None:
                return ModelCreateResult(
                    package=self._model_package_from_row(replayed_row), replayed=True
                )
            duplicate = connection.execute(
                select(model_packages.c.id).where(
                    and_(
                        model_packages.c.organization_id == organization_id,
                        model_packages.c.model_code == model_code,
                    )
                )
            ).scalar_one_or_none()
            if duplicate is not None:
                raise MetadataCodeExistsError(f"model package already exists: {model_code}")
            row = (
                connection.execute(
                    model_packages.insert()
                    .values(
                        organization_id=organization_id,
                        model_code=model_code,
                        name=name,
                        task=task,
                        idempotency_key=idempotency_key,
                        request_hash=request_hash,
                        created_at=created_at,
                    )
                    .returning(*model_packages.c)
                )
                .mappings()
                .one()
            )
            self._audit_metadata(
                connection,
                organization_id=organization_id,
                actor=actor,
                action="MODEL_PACKAGE_CREATED",
                target_type="model_package",
                target_id=model_code,
                detail=f"model_code={model_code}",
                request_id=request_id,
                after_state={"model_code": model_code, "name": name, "task": task},
            )
            return ModelCreateResult(package=self._model_package_from_row(row), replayed=False)

        return self._metadata_write_mapped(_run)

    def get_model_package(self, organization_id: int, model_id: int) -> ModelPackageRow | None:
        with self._engine.connect() as connection:
            row = (
                connection.execute(
                    select(model_packages).where(
                        and_(
                            model_packages.c.id == model_id,
                            model_packages.c.organization_id == organization_id,
                        )
                    )
                )
                .mappings()
                .first()
            )
        return self._model_package_from_row(row) if row is not None else None

    def get_model_detail(self, organization_id: int, model_id: int) -> ModelDetailRow | None:
        package = self.get_model_package(organization_id, model_id)
        if package is None:
            return None
        with self._engine.connect() as connection:
            versions = []
            for row in (
                connection.execute(
                    select(model_versions.c.version_id)
                    .where(
                        and_(
                            model_versions.c.organization_id == organization_id,
                            model_versions.c.model_package_id == model_id,
                        )
                    )
                    .order_by(model_versions.c.version)
                )
                .mappings()
                .all()
            ):
                version = self._load_model_version(
                    connection,
                    organization_id=organization_id,
                    version_id=str(row["version_id"]),
                )
                if version is not None:
                    versions.append(version)
        return ModelDetailRow(package=package, versions=versions)

    def create_model_version(
        self,
        *,
        organization_id: int,
        model_package_id: int,
        manifest: dict[str, object],
        idempotency_key: str | None,
        request_hash: str,
        created_at: datetime,
        actor: str,
        request_id: str | None,
    ) -> ModelVersionCreateResult:
        def _run(connection: Any) -> ModelVersionCreateResult:
            package = (
                connection.execute(
                    select(model_packages).where(
                        and_(
                            model_packages.c.id == model_package_id,
                            model_packages.c.organization_id == organization_id,
                        )
                    )
                )
                .mappings()
                .first()
            )
            if package is None:
                raise ModelNotFoundError(f"model package {model_package_id} does not exist")
            self._validate_manifest(manifest, expected_task=str(package["task"]))

            replayed_row = self._metadata_replay(
                connection,
                table=model_versions,
                organization_id=organization_id,
                scope_column="model_package_id",
                scope_value=model_package_id,
                idempotency_key=idempotency_key,
                request_hash=request_hash,
                label="model version creation",
            )
            if replayed_row is not None:
                version = self._load_model_version(
                    connection,
                    organization_id=organization_id,
                    version_id=str(replayed_row["version_id"]),
                )
                if version is None:
                    raise MetadataVersionNotFoundError(
                        "the created model version could not be reloaded"
                    )
                return ModelVersionCreateResult(version=version, replayed=True)

            manifest_sha256 = self._canonical_hash(manifest)
            version_number = self._next_version(
                connection,
                table=model_versions,
                scope_column="model_package_id",
                scope_value=model_package_id,
            )
            version_id = str(uuid4())
            (
                connection.execute(
                    model_versions.insert()
                    .values(
                        organization_id=organization_id,
                        model_package_id=model_package_id,
                        version_id=version_id,
                        version=version_number,
                        status="DRAFT",
                        semantic_version=str(manifest["semantic_version"]),
                        edge_version_label=str(manifest["edge_version_label"]),
                        runtime=str(manifest["runtime"]),
                        input_width=int(cast(int, manifest["input_width"])),
                        input_height=int(cast(int, manifest["input_height"])),
                        class_names=list(cast(list[str], manifest["class_names"])),
                        artifacts=list(cast(list[dict[str, object]], manifest["artifacts"])),
                        datasets=list(cast(list[dict[str, object]], manifest["datasets"])),
                        split_strategy=str(manifest["split_strategy"]),
                        source_revision=str(manifest["source_revision"]),
                        training_config_revision=str(manifest["training_config_revision"]),
                        metrics=list(cast(list[dict[str, object]], manifest["metrics"])),
                        limitations=list(cast(list[str], manifest["limitations"])),
                        manifest_sha256=manifest_sha256,
                        idempotency_key=idempotency_key,
                        request_hash=request_hash,
                        created_at=created_at,
                    )
                    .returning(*model_versions.c)
                )
                .mappings()
                .one()
            )
            self._audit_metadata(
                connection,
                organization_id=organization_id,
                actor=actor,
                action="MODEL_VERSION_DRAFTED",
                target_type="model_version",
                target_id=version_id,
                detail=f"version={version_number}",
                request_id=request_id,
                after_state={"version": version_number, "status": "DRAFT"},
            )
            version = self._load_model_version(
                connection, organization_id=organization_id, version_id=version_id
            )
            if version is None:
                raise MetadataVersionNotFoundError(
                    "the created model version could not be reloaded"
                )
            return ModelVersionCreateResult(version=version, replayed=False)

        return self._metadata_write_mapped(_run)

    @staticmethod
    def _validate_manifest(manifest: dict[str, object], *, expected_task: str) -> None:
        """Validate a declarative model manifest (C5, design 14 ModelManifest).

        Validation covers structure, bounds, uniqueness, and checksum format
        only: C5 never fetches or verifies artifact bytes, so publication never
        claims the artifact was validated server-side.
        """
        task = manifest.get("task")
        if task != expected_task:
            raise InvalidManifestError(
                f"manifest task {task!r} does not match package task {expected_task!r}"
            )
        semantic_version = manifest.get("semantic_version")
        if (
            not isinstance(semantic_version, str)
            or not semantic_version
            or len(semantic_version) > 32
        ):
            raise InvalidManifestError("semantic_version must be a non-empty string up to 32 chars")
        edge_label = manifest.get("edge_version_label")
        if not isinstance(edge_label, str) or not edge_label or len(edge_label) > 64:
            raise InvalidManifestError(
                "edge_version_label must be a non-empty string up to 64 chars"
            )
        runtime = manifest.get("runtime")
        if not isinstance(runtime, str) or not runtime or len(runtime) > 64:
            raise InvalidManifestError("runtime must be a non-empty string up to 64 chars")
        width, height = manifest.get("input_width"), manifest.get("input_height")
        if (
            not isinstance(width, int)
            or not isinstance(height, int)
            or not (0 < width <= 8192 and 0 < height <= 8192)
        ):
            raise InvalidManifestError("input_width and input_height must be integers in 1..8192")
        class_names = manifest.get("class_names")
        if not isinstance(class_names, list) or not class_names or len(class_names) > 256:
            raise InvalidManifestError("class_names must be a non-empty list up to 256 entries")
        seen_classes: set[str] = set()
        for class_name in class_names:
            if not isinstance(class_name, str) or not class_name or len(class_name) > 64:
                raise InvalidManifestError(
                    "each class name must be a non-empty string up to 64 chars"
                )
            if class_name in seen_classes:
                raise InvalidManifestError(f"duplicate class name: {class_name}")
            seen_classes.add(class_name)
        artifacts = manifest.get("artifacts")
        if not isinstance(artifacts, list) or not artifacts or len(artifacts) > 32:
            raise InvalidManifestError("artifacts must be a non-empty list up to 32 entries")
        seen_artifact_names: set[str] = set()
        for artifact in artifacts:
            if not isinstance(artifact, dict):
                raise InvalidManifestError("each artifact must be an object")
            name = artifact.get("name")
            uri = artifact.get("uri")
            checksum = artifact.get("sha256")
            size = artifact.get("size_bytes")
            if not isinstance(name, str) or not name or len(name) > 128:
                raise InvalidManifestError(
                    "artifact name must be a non-empty string up to 128 chars"
                )
            if name in seen_artifact_names:
                raise InvalidManifestError(f"duplicate artifact name: {name}")
            seen_artifact_names.add(name)
            if not isinstance(uri, str) or not uri or len(uri) > 512:
                raise InvalidManifestError(
                    "artifact uri must be a non-empty string up to 512 chars"
                )
            normalized = _normalize_sha256(checksum)
            if normalized is None:
                raise InvalidManifestError("artifact sha256 must be a 64-character hex value")
            artifact["sha256"] = normalized
            if not isinstance(size, int) or size < 0:
                raise InvalidManifestError("artifact size_bytes must be a non-negative integer")
        datasets = manifest.get("datasets")
        allowed_purposes = {"TRAIN", "VALIDATION", "TEST", "ACCEPTANCE"}
        if not isinstance(datasets, list) or len(datasets) > 32:
            raise InvalidManifestError("datasets must be a list up to 32 entries")
        for dataset in datasets:
            if not isinstance(dataset, dict):
                raise InvalidManifestError("each dataset must be an object")
            purpose = dataset.get("purpose")
            version = dataset.get("dataset_version")
            uri = dataset.get("manifest_uri")
            if purpose not in allowed_purposes:
                raise InvalidManifestError(f"invalid dataset purpose: {purpose!r}")
            if not isinstance(version, str) or not version or len(version) > 64:
                raise InvalidManifestError(
                    "dataset_version must be a non-empty string up to 64 chars"
                )
            if not isinstance(uri, str) or not uri or len(uri) > 512:
                raise InvalidManifestError(
                    "manifest_uri must be a non-empty string up to 512 chars"
                )
        for key in ("split_strategy", "source_revision", "training_config_revision"):
            value = manifest.get(key)
            if not isinstance(value, str) or not value or len(value) > 128:
                raise InvalidManifestError(f"{key} must be a non-empty string up to 128 chars")
        metrics = manifest.get("metrics")
        if not isinstance(metrics, list) or len(metrics) > 64:
            raise InvalidManifestError("metrics must be a list up to 64 entries")
        for metric in metrics:
            if not isinstance(metric, dict):
                raise InvalidManifestError("each metric must be an object")
            name = metric.get("name")
            value = metric.get("value")
            scope = metric.get("scope")
            if not isinstance(name, str) or not name or len(name) > 64:
                raise InvalidManifestError("metric name must be a non-empty string up to 64 chars")
            if not isinstance(value, (int, float)):
                raise InvalidManifestError("metric value must be a number")
            if not isinstance(scope, str) or not scope or len(scope) > 64:
                raise InvalidManifestError("metric scope must be a non-empty string up to 64 chars")
        limitations = manifest.get("limitations")
        if not isinstance(limitations, list) or len(limitations) > 64:
            raise InvalidManifestError("limitations must be a list up to 64 entries")
        for limitation in limitations:
            if not isinstance(limitation, str) or len(limitation) > 512:
                raise InvalidManifestError("each limitation must be a string up to 512 chars")

    def get_model_version(self, organization_id: int, version_id: str) -> ModelVersionRow | None:
        with self._engine.connect() as connection:
            return self._load_model_version(
                connection, organization_id=organization_id, version_id=version_id
            )

    def publish_model_version(
        self,
        *,
        organization_id: int,
        version_id: str,
        published_by: str,
        publish_reason: str,
        published_at: datetime,
        actor: str,
        request_id: str | None,
    ) -> PublishResult:
        def _run(connection: Any) -> PublishResult:
            row = (
                connection.execute(
                    select(model_versions).where(
                        and_(
                            model_versions.c.organization_id == organization_id,
                            model_versions.c.version_id == version_id,
                        )
                    )
                )
                .mappings()
                .first()
            )
            if row is None:
                raise MetadataVersionNotFoundError(f"model version {version_id} does not exist")
            if str(row["status"]) == "PUBLISHED":
                return PublishResult(version_id=version_id, status="PUBLISHED", replayed=True)
            version_pk = int(row["id"])
            version_number = int(row["version"])
            connection.execute(
                model_versions.update()
                .where(model_versions.c.id == version_pk)
                .values(
                    status="PUBLISHED",
                    published_at=published_at,
                    published_by=published_by,
                    publish_reason=publish_reason,
                )
            )
            # Declarative registration: C5 never verifies artifact bytes, so the
            # audit states exactly that scope and never claims validation.
            self._audit_metadata(
                connection,
                organization_id=organization_id,
                actor=actor,
                action="MODEL_PUBLISHED",
                target_type="model_version",
                target_id=version_id,
                detail=f"version={version_number} declarative registration; artifact bytes not verified",
                request_id=request_id,
                reason=publish_reason,
                before_state={"version": version_number, "status": "DRAFT"},
                after_state={"version": version_number, "status": "PUBLISHED"},
            )
            return PublishResult(version_id=version_id, status="PUBLISHED", replayed=False)

        return self._metadata_write_mapped(_run)

    # -- desired configuration ----------------------------------------------

    def get_device_by_identity(self, organization_id: int, device_id: str) -> DeviceRow | None:
        """Resolve the edge device UUID to its registered row, or None (C5)."""
        with self._engine.connect() as connection:
            row = (
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
        return self._device_from_row(row) if row is not None else None

    def get_desired_configuration(
        self, organization_id: int, device_row_id: int
    ) -> DesiredConfigurationRow | None:
        with self._engine.connect() as connection:
            row = (
                connection.execute(
                    select(
                        desired_configurations,
                        devices.c.device_id,
                        devices.c.name,
                        product_versions.c.version_id.label("product_version_public_id"),
                        _DESIRED_PRODUCT_MODEL_VERSIONS.c.version_id.label(
                            "product_model_version_public_id"
                        ),
                        _DESIRED_COMPONENT_MODEL_VERSIONS.c.version_id.label(
                            "component_model_version_public_id"
                        ),
                        rule_versions.c.version_id.label("rule_version_public_id"),
                    )
                    .join(devices, devices.c.id == desired_configurations.c.device_row_id)
                    .join(
                        product_versions,
                        product_versions.c.id == desired_configurations.c.product_version_id,
                    )
                    .join(
                        _DESIRED_PRODUCT_MODEL_VERSIONS,
                        _DESIRED_PRODUCT_MODEL_VERSIONS.c.id
                        == desired_configurations.c.product_model_version_id,
                    )
                    .join(
                        _DESIRED_COMPONENT_MODEL_VERSIONS,
                        _DESIRED_COMPONENT_MODEL_VERSIONS.c.id
                        == desired_configurations.c.component_model_version_id,
                    )
                    .join(
                        rule_versions,
                        rule_versions.c.id == desired_configurations.c.rule_version_id,
                    )
                    .where(
                        and_(
                            desired_configurations.c.organization_id == organization_id,
                            desired_configurations.c.device_row_id == device_row_id,
                        )
                    )
                )
                .mappings()
                .first()
            )
        return self._desired_configuration_from_row(row) if row is not None else None

    def list_desired_configurations(self, organization_id: int) -> list[DesiredConfigurationRow]:
        with self._engine.connect() as connection:
            rows = (
                connection.execute(
                    select(
                        desired_configurations,
                        devices.c.device_id,
                        devices.c.name,
                        product_versions.c.version_id.label("product_version_public_id"),
                        _DESIRED_PRODUCT_MODEL_VERSIONS.c.version_id.label(
                            "product_model_version_public_id"
                        ),
                        _DESIRED_COMPONENT_MODEL_VERSIONS.c.version_id.label(
                            "component_model_version_public_id"
                        ),
                        rule_versions.c.version_id.label("rule_version_public_id"),
                    )
                    .join(devices, devices.c.id == desired_configurations.c.device_row_id)
                    .join(
                        product_versions,
                        product_versions.c.id == desired_configurations.c.product_version_id,
                    )
                    .join(
                        _DESIRED_PRODUCT_MODEL_VERSIONS,
                        _DESIRED_PRODUCT_MODEL_VERSIONS.c.id
                        == desired_configurations.c.product_model_version_id,
                    )
                    .join(
                        _DESIRED_COMPONENT_MODEL_VERSIONS,
                        _DESIRED_COMPONENT_MODEL_VERSIONS.c.id
                        == desired_configurations.c.component_model_version_id,
                    )
                    .join(
                        rule_versions,
                        rule_versions.c.id == desired_configurations.c.rule_version_id,
                    )
                    .where(desired_configurations.c.organization_id == organization_id)
                    .order_by(devices.c.device_id)
                )
                .mappings()
                .all()
            )
        return [self._desired_configuration_from_row(row) for row in rows]

    def set_desired_configuration(
        self,
        *,
        organization_id: int,
        device_row_id: int,
        if_match_revision: int,
        product_version_id: str,
        product_model_version_id: str,
        component_model_version_id: str,
        rule_version_id: str,
        reason: str,
        assigned_by: str,
        assigned_at: datetime,
        actor: str,
        request_id: str | None,
    ) -> DesiredConfigurationRow:
        def _run(connection: Any) -> DesiredConfigurationRow:
            device_exists = connection.execute(
                select(devices.c.id).where(devices.c.id == device_row_id)
            ).scalar_one_or_none()
            if device_exists is None:
                raise DeviceNotFoundError("the device does not exist")
            existing = (
                connection.execute(
                    select(desired_configurations).where(
                        desired_configurations.c.device_row_id == device_row_id
                    )
                )
                .mappings()
                .first()
            )
            current_revision = int(existing["revision"]) if existing is not None else 0
            if if_match_revision != current_revision:
                raise RevisionMismatchError(
                    f"expected revision {if_match_revision}, current revision {current_revision}"
                )

            product_version = (
                connection.execute(
                    select(product_versions).where(
                        and_(
                            product_versions.c.organization_id == organization_id,
                            product_versions.c.version_id == product_version_id,
                        )
                    )
                )
                .mappings()
                .first()
            )
            if product_version is None:
                raise MetadataVersionNotFoundError(
                    f"product version {product_version_id} does not exist"
                )
            if str(product_version["status"]) != "PUBLISHED":
                raise IncompatibleVersionError("the desired product version must be published")
            product_version_pk = int(product_version["id"])
            product_code = connection.execute(
                select(products.c.product_code).where(
                    products.c.id == int(product_version["product_id"])
                )
            ).scalar_one()

            rule_version = (
                connection.execute(
                    select(rule_versions).where(
                        and_(
                            rule_versions.c.organization_id == organization_id,
                            rule_versions.c.version_id == rule_version_id,
                        )
                    )
                )
                .mappings()
                .first()
            )
            if rule_version is None:
                raise MetadataVersionNotFoundError(f"rule version {rule_version_id} does not exist")
            if str(rule_version["status"]) != "PUBLISHED":
                raise IncompatibleVersionError("the desired rule version must be published")
            if int(rule_version["product_version_id"]) != product_version_pk:
                raise IncompatibleVersionError(
                    "the desired rule version does not apply to the selected product version"
                )
            rule_pk = int(rule_version["id"])

            product_model = (
                connection.execute(
                    select(
                        model_versions.c.id,
                        model_versions.c.status,
                        model_versions.c.class_names,
                        model_packages.c.task,
                    )
                    .join(model_packages, model_packages.c.id == model_versions.c.model_package_id)
                    .where(
                        and_(
                            model_versions.c.organization_id == organization_id,
                            model_versions.c.version_id == product_model_version_id,
                        )
                    )
                )
                .mappings()
                .first()
            )
            if product_model is None:
                raise MetadataVersionNotFoundError(
                    f"product model version {product_model_version_id} does not exist"
                )
            if str(product_model["status"]) != "PUBLISHED":
                raise IncompatibleVersionError(
                    "the desired product model version must be published"
                )
            if str(product_model["task"]) != "PRODUCT_DETECTION":
                raise IncompatibleVersionError(
                    "the desired product model must be a PRODUCT_DETECTION model"
                )
            product_model_classes = {str(item) for item in (product_model["class_names"] or [])}
            if product_code not in product_model_classes:
                raise IncompatibleVersionError(
                    f"the product model classes do not include product {product_code}"
                )
            product_model_pk = int(product_model["id"])

            component_model = (
                connection.execute(
                    select(
                        model_versions.c.id,
                        model_versions.c.status,
                        model_versions.c.class_names,
                        model_packages.c.task,
                    )
                    .join(model_packages, model_packages.c.id == model_versions.c.model_package_id)
                    .where(
                        and_(
                            model_versions.c.organization_id == organization_id,
                            model_versions.c.version_id == component_model_version_id,
                        )
                    )
                )
                .mappings()
                .first()
            )
            if component_model is None:
                raise MetadataVersionNotFoundError(
                    f"component model version {component_model_version_id} does not exist"
                )
            if str(component_model["status"]) != "PUBLISHED":
                raise IncompatibleVersionError(
                    "the desired component model version must be published"
                )
            if str(component_model["task"]) != "COMPONENT_DETECTION":
                raise IncompatibleVersionError(
                    "the desired component model must be a COMPONENT_DETECTION model"
                )
            component_model_pk = int(component_model["id"])
            component_model_classes = {str(item) for item in (component_model["class_names"] or [])}
            required_codes = {
                str(comp["component_code"])
                for comp in connection.execute(
                    select(components.c.component_code)
                    .join(
                        product_version_components,
                        product_version_components.c.component_id == components.c.id,
                    )
                    .where(product_version_components.c.product_version_id == product_version_pk)
                )
                .mappings()
                .all()
            }
            if not required_codes.issubset(component_model_classes):
                missing_classes = sorted(required_codes - component_model_classes)
                raise IncompatibleVersionError(
                    "the component model classes do not cover required components: "
                    f"{missing_classes}"
                )
            compatible = connection.execute(
                select(rule_model_compatibilities.c.id).where(
                    and_(
                        rule_model_compatibilities.c.rule_version_id == rule_pk,
                        rule_model_compatibilities.c.model_version_id == component_model_pk,
                    )
                )
            ).scalar_one_or_none()
            if compatible is None:
                raise IncompatibleVersionError(
                    "the desired rule does not list the component model as compatible"
                )

            before_state: dict[str, object] | None = None
            if existing is not None:
                before_state = {
                    "revision": int(existing["revision"]),
                    "product_version_id": str(
                        connection.execute(
                            select(product_versions.c.version_id).where(
                                product_versions.c.id == int(existing["product_version_id"])
                            )
                        ).scalar_one()
                    ),
                }
                # Conditional update is the PostgreSQL concurrency backstop:
                # the revision predicate makes a stale If-Match a no-op rather
                # than a last-write-wins overwrite.
                result = connection.execute(
                    desired_configurations.update()
                    .where(
                        and_(
                            desired_configurations.c.device_row_id == device_row_id,
                            desired_configurations.c.revision == current_revision,
                        )
                    )
                    .values(
                        revision=current_revision + 1,
                        product_version_id=product_version_pk,
                        product_model_version_id=product_model_pk,
                        component_model_version_id=component_model_pk,
                        rule_version_id=rule_pk,
                        reason=reason,
                        assigned_by=assigned_by,
                        assigned_at=assigned_at,
                    )
                )
                new_revision = current_revision + 1
            else:
                connection.execute(
                    desired_configurations.insert().values(
                        organization_id=organization_id,
                        device_row_id=device_row_id,
                        revision=1,
                        product_version_id=product_version_pk,
                        product_model_version_id=product_model_pk,
                        component_model_version_id=component_model_pk,
                        rule_version_id=rule_pk,
                        reason=reason,
                        assigned_by=assigned_by,
                        assigned_at=assigned_at,
                    )
                )
                new_revision = 1

            # M1 records desire only: the audit and the record never claim
            # download, validation, or activation (C1 invariant 11).
            self._audit_metadata(
                connection,
                organization_id=organization_id,
                actor=actor,
                action="DESIRED_CONFIGURATION_ASSIGNED",
                target_type="device",
                target_id=str(device_row_id),
                detail=(
                    f"revision={new_revision} desired bundle; "
                    "manual installation required, not activation"
                ),
                request_id=request_id,
                reason=reason,
                before_state=before_state,
                after_state={
                    "revision": new_revision,
                    "product_version_id": product_version_id,
                    "rule_version_id": rule_version_id,
                },
            )
            row = (
                connection.execute(
                    select(
                        desired_configurations,
                        devices.c.device_id,
                        devices.c.name,
                        product_versions.c.version_id.label("product_version_public_id"),
                        _DESIRED_PRODUCT_MODEL_VERSIONS.c.version_id.label(
                            "product_model_version_public_id"
                        ),
                        _DESIRED_COMPONENT_MODEL_VERSIONS.c.version_id.label(
                            "component_model_version_public_id"
                        ),
                        rule_versions.c.version_id.label("rule_version_public_id"),
                    )
                    .join(devices, devices.c.id == desired_configurations.c.device_row_id)
                    .join(
                        product_versions,
                        product_versions.c.id == desired_configurations.c.product_version_id,
                    )
                    .join(
                        _DESIRED_PRODUCT_MODEL_VERSIONS,
                        _DESIRED_PRODUCT_MODEL_VERSIONS.c.id
                        == desired_configurations.c.product_model_version_id,
                    )
                    .join(
                        _DESIRED_COMPONENT_MODEL_VERSIONS,
                        _DESIRED_COMPONENT_MODEL_VERSIONS.c.id
                        == desired_configurations.c.component_model_version_id,
                    )
                    .join(
                        rule_versions,
                        rule_versions.c.id == desired_configurations.c.rule_version_id,
                    )
                    .where(
                        and_(
                            desired_configurations.c.organization_id == organization_id,
                            desired_configurations.c.device_row_id == device_row_id,
                        )
                    )
                )
                .mappings()
                .one()
            )
            return self._desired_configuration_from_row(row)

        return self._metadata_write_mapped(_run)

    # -- metadata loaders and mappers ----------------------------------------

    def _load_product_version(
        self, connection: Any, *, organization_id: int, version_id: str
    ) -> ProductVersionRow | None:
        row = (
            connection.execute(
                select(product_versions).where(
                    and_(
                        product_versions.c.organization_id == organization_id,
                        product_versions.c.version_id == version_id,
                    )
                )
            )
            .mappings()
            .first()
        )
        if row is None:
            return None
        product_code = str(
            connection.execute(
                select(products.c.product_code).where(products.c.id == int(row["product_id"]))
            ).scalar_one()
        )
        components_rows = (
            connection.execute(
                select(components.c.component_code, product_version_components.c.expected_count)
                .join(
                    product_version_components,
                    product_version_components.c.component_id == components.c.id,
                )
                .where(product_version_components.c.product_version_id == int(row["id"]))
                .order_by(components.c.component_code)
            )
            .mappings()
            .all()
        )
        barcode_rows = (
            connection.execute(
                select(product_version_barcodes.c.barcode_value).where(
                    product_version_barcodes.c.product_version_id == int(row["id"])
                )
            )
            .scalars()
            .all()
        )
        return self._product_version_from_row(
            row,
            product_code=product_code,
            components=[
                ProductComponentRow(
                    component_code=str(comp["component_code"]),
                    expected_count=int(comp["expected_count"]),
                )
                for comp in components_rows
            ],
            barcodes=[str(barcode) for barcode in barcode_rows],
        )

    def _load_rule_version(
        self, connection: Any, *, organization_id: int, version_id: str
    ) -> RuleVersionRow | None:
        row = (
            connection.execute(
                select(rule_versions).where(
                    and_(
                        rule_versions.c.organization_id == organization_id,
                        rule_versions.c.version_id == version_id,
                    )
                )
            )
            .mappings()
            .first()
        )
        if row is None:
            return None
        rule_code = str(
            connection.execute(
                select(rules.c.rule_code).where(rules.c.id == int(row["rule_id"]))
            ).scalar_one()
        )
        product_version_id = str(
            connection.execute(
                select(product_versions.c.version_id).where(
                    product_versions.c.id == int(row["product_version_id"])
                )
            ).scalar_one()
        )
        policy_rows = (
            connection.execute(
                select(
                    components.c.component_code,
                    rule_component_policies.c.high_confidence,
                    rule_component_policies.c.medium_confidence,
                    rule_component_policies.c.minimum_medium_detections,
                    rule_component_policies.c.require_adjacent_frames,
                    rule_component_policies.c.expected_count,
                )
                .join(
                    rule_component_policies,
                    rule_component_policies.c.component_id == components.c.id,
                )
                .where(rule_component_policies.c.rule_version_id == int(row["id"]))
                .order_by(components.c.component_code)
            )
            .mappings()
            .all()
        )
        compat_rows = (
            connection.execute(
                select(model_versions.c.version_id)
                .join(
                    rule_model_compatibilities,
                    rule_model_compatibilities.c.model_version_id == model_versions.c.id,
                )
                .where(rule_model_compatibilities.c.rule_version_id == int(row["id"]))
                .order_by(model_versions.c.version_id)
            )
            .scalars()
            .all()
        )
        return self._rule_version_from_row(
            row,
            rule_code=rule_code,
            product_version_id=product_version_id,
            component_policies=[
                RulePolicyRow(
                    component_code=str(policy["component_code"]),
                    high_confidence=float(policy["high_confidence"]),
                    medium_confidence=float(policy["medium_confidence"]),
                    minimum_medium_detections=int(policy["minimum_medium_detections"]),
                    require_adjacent_frames=bool(policy["require_adjacent_frames"]),
                    expected_count=int(policy["expected_count"]),
                )
                for policy in policy_rows
            ],
            compatible_model_version_ids=[str(model_id) for model_id in compat_rows],
        )

    def _load_model_version(
        self, connection: Any, *, organization_id: int, version_id: str
    ) -> ModelVersionRow | None:
        row = (
            connection.execute(
                select(model_versions).where(
                    and_(
                        model_versions.c.organization_id == organization_id,
                        model_versions.c.version_id == version_id,
                    )
                )
            )
            .mappings()
            .first()
        )
        if row is None:
            return None
        package_row = (
            connection.execute(
                select(model_packages.c.model_code, model_packages.c.task).where(
                    model_packages.c.id == int(row["model_package_id"])
                )
            )
            .mappings()
            .one()
        )
        return self._model_version_from_row(
            row,
            model_code=str(package_row["model_code"]),
            task=str(package_row["task"]),
        )

    @staticmethod
    def _component_from_row(row: RowMapping) -> ComponentRow:
        return ComponentRow(
            id=int(row["id"]),
            organization_id=int(row["organization_id"]),
            component_code=str(row["component_code"]),
            display_name=str(row["display_name"]),
            created_at=CentralRepository._parse_dt(row["created_at"]),
        )

    @staticmethod
    def _product_from_row(row: RowMapping) -> ProductRow:
        return ProductRow(
            id=int(row["id"]),
            organization_id=int(row["organization_id"]),
            product_code=str(row["product_code"]),
            name=str(row["name"]),
            created_at=CentralRepository._parse_dt(row["created_at"]),
        )

    @staticmethod
    def _product_version_from_row(
        row: RowMapping,
        *,
        product_code: str,
        components: list[ProductComponentRow],
        barcodes: list[str],
    ) -> ProductVersionRow:
        return ProductVersionRow(
            id=int(row["id"]),
            organization_id=int(row["organization_id"]),
            product_id=int(row["product_id"]),
            product_code=product_code,
            version_id=str(row["version_id"]),
            version=int(row["version"]),
            status=str(row["status"]),
            barcodes=barcodes,
            components=components,
            published_at=CentralRepository._row_to_optional_dt(row["published_at"]),
            published_by=str(row["published_by"]) if row["published_by"] is not None else None,
            publish_reason=str(row["publish_reason"])
            if row["publish_reason"] is not None
            else None,
            created_at=CentralRepository._parse_dt(row["created_at"]),
        )

    @staticmethod
    def _rule_from_row(row: RowMapping) -> RuleRow:
        return RuleRow(
            id=int(row["id"]),
            organization_id=int(row["organization_id"]),
            rule_code=str(row["rule_code"]),
            name=str(row["name"]),
            created_at=CentralRepository._parse_dt(row["created_at"]),
        )

    @staticmethod
    def _rule_version_from_row(
        row: RowMapping,
        *,
        rule_code: str,
        product_version_id: str,
        component_policies: list[RulePolicyRow],
        compatible_model_version_ids: list[str],
    ) -> RuleVersionRow:
        return RuleVersionRow(
            id=int(row["id"]),
            organization_id=int(row["organization_id"]),
            rule_id=int(row["rule_id"]),
            rule_code=rule_code,
            product_version_id=product_version_id,
            version_id=str(row["version_id"]),
            version=int(row["version"]),
            status=str(row["status"]),
            barcode_required=bool(row["barcode_required"]),
            minimum_usable_frames=int(row["minimum_usable_frames"]),
            uncertain_maps_to_ng=bool(row["uncertain_maps_to_ng"]),
            mandatory_gates=dict(row["mandatory_gates"] or {}),
            component_policies=component_policies,
            compatible_model_version_ids=compatible_model_version_ids,
            content_sha256=str(row["content_sha256"]),
            published_at=CentralRepository._row_to_optional_dt(row["published_at"]),
            published_by=str(row["published_by"]) if row["published_by"] is not None else None,
            publish_reason=str(row["publish_reason"])
            if row["publish_reason"] is not None
            else None,
            created_at=CentralRepository._parse_dt(row["created_at"]),
        )

    @staticmethod
    def _model_package_from_row(row: RowMapping) -> ModelPackageRow:
        return ModelPackageRow(
            id=int(row["id"]),
            organization_id=int(row["organization_id"]),
            model_code=str(row["model_code"]),
            name=str(row["name"]),
            task=str(row["task"]),
            created_at=CentralRepository._parse_dt(row["created_at"]),
        )

    @staticmethod
    def _model_version_from_row(row: RowMapping, *, model_code: str, task: str) -> ModelVersionRow:
        return ModelVersionRow(
            id=int(row["id"]),
            organization_id=int(row["organization_id"]),
            model_package_id=int(row["model_package_id"]),
            model_code=model_code,
            task=task,
            version_id=str(row["version_id"]),
            version=int(row["version"]),
            status=str(row["status"]),
            semantic_version=str(row["semantic_version"]),
            edge_version_label=str(row["edge_version_label"]),
            runtime=str(row["runtime"]),
            input_width=int(row["input_width"]),
            input_height=int(row["input_height"]),
            class_names=[str(item) for item in (row["class_names"] or [])],
            artifacts=[dict(item) for item in (row["artifacts"] or [])],
            datasets=[dict(item) for item in (row["datasets"] or [])],
            split_strategy=str(row["split_strategy"]),
            source_revision=str(row["source_revision"]),
            training_config_revision=str(row["training_config_revision"]),
            metrics=[dict(item) for item in (row["metrics"] or [])],
            limitations=[str(item) for item in (row["limitations"] or [])],
            manifest_sha256=str(row["manifest_sha256"]),
            published_at=CentralRepository._row_to_optional_dt(row["published_at"]),
            published_by=str(row["published_by"]) if row["published_by"] is not None else None,
            publish_reason=str(row["publish_reason"])
            if row["publish_reason"] is not None
            else None,
            created_at=CentralRepository._parse_dt(row["created_at"]),
        )

    @staticmethod
    def _desired_configuration_from_row(row: RowMapping) -> DesiredConfigurationRow:
        return DesiredConfigurationRow(
            id=int(row["id"]),
            organization_id=int(row["organization_id"]),
            device_row_id=int(row["device_row_id"]),
            device_id=str(row["device_id"]),
            device_name=str(row["name"]),
            revision=int(row["revision"]),
            product_version_id=str(row["product_version_public_id"]),
            product_model_version_id=str(row["product_model_version_public_id"]),
            component_model_version_id=str(row["component_model_version_public_id"]),
            rule_version_id=str(row["rule_version_public_id"]),
            reason=str(row["reason"]),
            assigned_by=str(row["assigned_by"]),
            assigned_at=CentralRepository._parse_dt(row["assigned_at"]),
            created_at=CentralRepository._parse_dt(row["created_at"]),
        )

    @staticmethod
    def _row_to_optional_dt(value: object) -> datetime | None:
        return CentralRepository._parse_dt(value) if value is not None else None

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
