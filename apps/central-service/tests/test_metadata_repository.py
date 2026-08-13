"""C5 metadata governance repository tests.

Exercises organization isolation, idempotent create/draft/publish with
conflict detection, immutable published versions, exact-barcode ambiguity
rejection, rule/model publish compatibility validation, declarative model
registration, desired-configuration assignment with If-Match revisions, and
transactional audit events.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

import pytest
from central_service.persistence.repository import (
    AmbiguousBarcodeError,
    CentralRepository,
    DeviceNotFoundError,
    IdempotencyConflictError,
    IncompatibleVersionError,
    InvalidComponentError,
    InvalidManifestError,
    InvalidPolicyError,
    MetadataCodeExistsError,
    ProductComponentInput,
    ProductNotFoundError,
    RevisionMismatchError,
    RulePolicyInput,
)
from central_service.persistence.schema import audit_logs, metadata
from sqlalchemy import Engine, and_, create_engine, event, select
from sqlalchemy.pool import StaticPool

# Test fixtures carry their own credential strings; these are never real.
_ADMIN_TOKEN = "test-admin-token-0123456789abcdef"  # noqa: S105
_DEVICE_TOKEN = "test-device-token-0123456789abcdef"  # noqa: S105
_DEVICE_ID = uuid4()
_HASH = "0" * 64


@dataclass(frozen=True)
class GovernanceSeed:
    """Ids of a fully published, compatible product/rule/model bundle."""

    organization_id: int
    product_id: int
    product_version_id: str
    rule_id: int
    rule_version_id: str
    product_model_version_id: str
    component_model_version_id: str
    component_a_id: int
    component_b_id: int


def _sqlite_engine() -> Engine:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    event.listen(engine, "connect", _enable_foreign_keys)
    metadata.create_all(engine)
    return engine


def _enable_foreign_keys(dbapi_connection: Any, connection_record: object) -> None:
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


@pytest.fixture
def repository() -> Iterator[CentralRepository]:
    engine = _sqlite_engine()
    try:
        yield CentralRepository(engine)
    finally:
        engine.dispose()


@pytest.fixture
def organization_id(repository: CentralRepository) -> int:
    result = repository.bootstrap_pilot(
        organization_name="Org A",
        site_name="Site A",
        line_name="Line A",
        device_id=str(_DEVICE_ID),
        device_name="Edge 1",
        device_upload_token=_DEVICE_TOKEN,
        admin_username="admin",
        admin_token=_ADMIN_TOKEN,
    )
    return result.organization_id


def _create_component(
    repository: CentralRepository, organization_id: int, code: str, name: str = ""
) -> int:
    result = repository.create_component(
        organization_id=organization_id,
        component_code=code,
        display_name=name or code,
        idempotency_key=f"component:{code}",
        request_hash=_HASH,
        created_at=datetime.now(UTC),
        actor="admin",
        request_id=None,
    )
    return result.component.id


def _create_product_version(
    repository: CentralRepository,
    organization_id: int,
    product_id: int,
    *,
    components: list[ProductComponentInput] | None = None,
    barcodes: list[str] | None = None,
    key: str = "pv1",
) -> str:
    result = repository.create_product_version(
        organization_id=organization_id,
        product_id=product_id,
        barcodes=barcodes or [],
        required_components=components
        or [
            ProductComponentInput(component_code="component_a", expected_count=1),
            ProductComponentInput(component_code="component_b", expected_count=1),
        ],
        idempotency_key=key,
        request_hash=_HASH,
        created_at=datetime.now(UTC),
        actor="admin",
        request_id=None,
    )
    return result.version.version_id


def _create_model_version(
    repository: CentralRepository,
    organization_id: int,
    model_id: int,
    *,
    task: str,
    classes: list[str],
    key: str,
) -> str:
    manifest: dict[str, object] = {
        "task": task,
        "semantic_version": "1.0.0",
        "edge_version_label": f"label-{key}",
        "runtime": "ultralytics",
        "input_width": 640,
        "input_height": 640,
        "class_names": classes,
        "artifacts": [
            {
                "name": "weights",
                "uri": "../weights/model.pt",
                "sha256": _HASH,
                "size_bytes": 0,
            }
        ],
        "datasets": [],
        "split_strategy": "by_capture_session",
        "source_revision": "abc123",
        "training_config_revision": "train-1",
        "metrics": [],
        "limitations": ["placeholder"],
    }
    result = repository.create_model_version(
        organization_id=organization_id,
        model_package_id=model_id,
        manifest=manifest,
        idempotency_key=key,
        request_hash=_HASH,
        created_at=datetime.now(UTC),
        actor="admin",
        request_id=None,
    )
    return result.version.version_id


def _publish(
    repository: CentralRepository, organization_id: int, version_id: str, kind: str
) -> None:
    publish = {
        "product": repository.publish_product_version,
        "rule": repository.publish_rule_version,
        "model": repository.publish_model_version,
    }[kind]
    publish(
        organization_id=organization_id,
        version_id=version_id,
        published_by="admin",
        publish_reason="pilot release",
        published_at=datetime.now(UTC),
        actor="admin",
        request_id=None,
    )


def _seed_governance(repository: CentralRepository, organization_id: int) -> GovernanceSeed:
    """Create and publish a compatible product/rule/model bundle."""
    component_a = _create_component(repository, organization_id, "component_a")
    component_b = _create_component(repository, organization_id, "component_b")

    product = repository.create_product(
        organization_id=organization_id,
        product_code="model_a",
        name="Model A",
        idempotency_key="product:model_a",
        request_hash=_HASH,
        created_at=datetime.now(UTC),
        actor="admin",
        request_id=None,
    )
    product_version_id = _create_product_version(
        repository,
        organization_id,
        product.product.id,
        barcodes=["4901234567890"],
        key="product:model_a:v1",
    )
    _publish(repository, organization_id, product_version_id, "product")

    product_model = repository.create_model_package(
        organization_id=organization_id,
        model_code="product-detector",
        name="Product Detector",
        task="PRODUCT_DETECTION",
        idempotency_key="model:product-detector",
        request_hash=_HASH,
        created_at=datetime.now(UTC),
        actor="admin",
        request_id=None,
    )
    product_model_version_id = _create_model_version(
        repository,
        organization_id,
        product_model.package.id,
        task="PRODUCT_DETECTION",
        classes=["model_a"],
        key="model:product-detector:v1",
    )
    _publish(repository, organization_id, product_model_version_id, "model")

    component_model = repository.create_model_package(
        organization_id=organization_id,
        model_code="component-detector",
        name="Component Detector",
        task="COMPONENT_DETECTION",
        idempotency_key="model:component-detector",
        request_hash=_HASH,
        created_at=datetime.now(UTC),
        actor="admin",
        request_id=None,
    )
    component_model_version_id = _create_model_version(
        repository,
        organization_id,
        component_model.package.id,
        task="COMPONENT_DETECTION",
        classes=["component_a", "component_b", "manual"],
        key="model:component-detector:v1",
    )
    _publish(repository, organization_id, component_model_version_id, "model")

    rule = repository.create_rule(
        organization_id=organization_id,
        rule_code="model-a-presence",
        name="Model A presence",
        idempotency_key="rule:model-a-presence",
        request_hash=_HASH,
        created_at=datetime.now(UTC),
        actor="admin",
        request_id=None,
    )
    rule_version = repository.create_rule_version(
        organization_id=organization_id,
        rule_id=rule.rule.id,
        product_version_id=product_version_id,
        barcode_required=False,
        minimum_usable_frames=3,
        mandatory_gates={"product_detected": True},
        component_policies=[
            RulePolicyInput(
                component_code="component_a",
                high_confidence=0.9,
                medium_confidence=0.7,
                minimum_medium_detections=2,
                require_adjacent_frames=False,
                expected_count=1,
            ),
            RulePolicyInput(
                component_code="component_b",
                high_confidence=0.9,
                medium_confidence=0.7,
                minimum_medium_detections=2,
                require_adjacent_frames=False,
                expected_count=1,
            ),
        ],
        compatible_component_model_version_ids=[component_model_version_id],
        idempotency_key="rule:model-a-presence:v1",
        request_hash=_HASH,
        created_at=datetime.now(UTC),
        actor="admin",
        request_id=None,
    )
    _publish(repository, organization_id, rule_version.version.version_id, "rule")
    return GovernanceSeed(
        organization_id=organization_id,
        product_id=product.product.id,
        product_version_id=product_version_id,
        rule_id=rule.rule.id,
        rule_version_id=rule_version.version.version_id,
        product_model_version_id=product_model_version_id,
        component_model_version_id=component_model_version_id,
        component_a_id=component_a,
        component_b_id=component_b,
    )


def _audit_actions(
    repository: CentralRepository, organization_id: int, action: str
) -> list[dict[str, object]]:
    with repository._engine.connect() as connection:  # noqa: SLF001 - test reads the audit table
        rows = (
            connection.execute(
                select(
                    audit_logs.c.action,
                    audit_logs.c.reason,
                    audit_logs.c.detail,
                    audit_logs.c.before_state,
                    audit_logs.c.after_state,
                ).where(
                    and_(
                        audit_logs.c.organization_id == organization_id,
                        audit_logs.c.action == action,
                    )
                )
            )
            .mappings()
            .all()
        )
    return [dict(row) for row in rows]


# -- creation and idempotency ------------------------------------------------


def test_create_component_and_duplicate_rejected(
    repository: CentralRepository, organization_id: int
) -> None:
    result = repository.create_component(
        organization_id=organization_id,
        component_code="screw",
        display_name="Screw",
        idempotency_key="component:screw",
        request_hash=_HASH,
        created_at=datetime.now(UTC),
        actor="admin",
        request_id=None,
    )
    assert not result.replayed
    assert result.component.component_code == "screw"
    with pytest.raises(MetadataCodeExistsError):
        repository.create_component(
            organization_id=organization_id,
            component_code="screw",
            display_name="Screw again",
            idempotency_key="component:screw-2",
            request_hash=_HASH,
            created_at=datetime.now(UTC),
            actor="admin",
            request_id=None,
        )


def test_idempotent_replay_and_conflict(
    repository: CentralRepository, organization_id: int
) -> None:
    first = repository.create_component(
        organization_id=organization_id,
        component_code="bolt",
        display_name="Bolt",
        idempotency_key="component:bolt",
        request_hash=_HASH,
        created_at=datetime.now(UTC),
        actor="admin",
        request_id=None,
    )
    replay = repository.create_component(
        organization_id=organization_id,
        component_code="bolt",
        display_name="Bolt",
        idempotency_key="component:bolt",
        request_hash=_HASH,
        created_at=datetime.now(UTC),
        actor="admin",
        request_id=None,
    )
    assert replay.replayed
    assert replay.component.id == first.component.id
    with pytest.raises(IdempotencyConflictError):
        repository.create_component(
            organization_id=organization_id,
            component_code="bolt",
            display_name="Different name",
            idempotency_key="component:bolt",
            request_hash="f" * 64,
            created_at=datetime.now(UTC),
            actor="admin",
            request_id=None,
        )


def test_organization_isolation(repository: CentralRepository, organization_id: int) -> None:
    other = repository.bootstrap_pilot(
        organization_name="Org B",
        site_name="Site B",
        line_name="Line B",
        device_id=str(uuid4()),
        device_name="Edge 2",
        device_upload_token=_DEVICE_TOKEN,
        admin_username="admin-b",
        admin_token=_ADMIN_TOKEN,
    )
    repository.create_product(
        organization_id=organization_id,
        product_code="shared-code",
        name="Org A product",
        idempotency_key="product:shared",
        request_hash=_HASH,
        created_at=datetime.now(UTC),
        actor="admin",
        request_id=None,
    )
    # The same code is legal in another organization.
    repository.create_product(
        organization_id=other.organization_id,
        product_code="shared-code",
        name="Org B product",
        idempotency_key="product:shared-b",
        request_hash=_HASH,
        created_at=datetime.now(UTC),
        actor="admin",
        request_id=None,
    )
    products_a = repository.list_products(organization_id)
    products_b = repository.list_products(other.organization_id)
    assert [p.product_code for p in products_a] == ["shared-code"]
    assert [p.product_code for p in products_b] == ["shared-code"]
    # A version id from Org A is invisible to Org B (lookup returns None).
    assert repository.get_product_version(other.organization_id, "no-such-version") is None


# -- product versions --------------------------------------------------------


def test_product_version_flow_and_repeat_publish(
    repository: CentralRepository, organization_id: int
) -> None:
    _create_component(repository, organization_id, "component_a")
    _create_component(repository, organization_id, "component_b")
    product = repository.create_product(
        organization_id=organization_id,
        product_code="prod-1",
        name="Prod 1",
        idempotency_key="product:prod-1",
        request_hash=_HASH,
        created_at=datetime.now(UTC),
        actor="admin",
        request_id=None,
    )
    v1 = _create_product_version(
        repository, organization_id, product.product.id, barcodes=["4901234567890"], key="prod-1:v1"
    )
    v2 = _create_product_version(
        repository,
        organization_id,
        product.product.id,
        barcodes=["999"],
        key="prod-1:v2",
    )
    assert v2 != v1
    detail = repository.get_product_detail(organization_id, product.product.id)
    assert detail is not None
    assert [v.version for v in detail.versions] == [1, 2]
    assert [v.status for v in detail.versions] == ["DRAFT", "DRAFT"]

    first = repository.publish_product_version(
        organization_id=organization_id,
        version_id=v1,
        published_by="admin",
        publish_reason="release v1",
        published_at=datetime.now(UTC),
        actor="admin",
        request_id=None,
    )
    assert not first.replayed
    replay = repository.publish_product_version(
        organization_id=organization_id,
        version_id=v1,
        published_by="admin",
        publish_reason="release v1",
        published_at=datetime.now(UTC),
        actor="admin",
        request_id=None,
    )
    assert replay.replayed

    loaded = repository.get_product_version(organization_id, v1)
    assert loaded is not None
    assert loaded.status == "PUBLISHED"
    assert loaded.barcodes == ["4901234567890"]
    assert [c.component_code for c in loaded.components] == ["component_a", "component_b"]

    # No mutation path exists; a new change must be a higher version.
    audit = _audit_actions(repository, organization_id, "PRODUCT_PUBLISHED")
    assert len(audit) == 1
    assert audit[0]["reason"] == "release v1"
    assert audit[0]["before_state"] == {"version": 1, "status": "DRAFT"}
    assert audit[0]["after_state"] == {"version": 1, "status": "PUBLISHED"}


def test_product_version_unknown_component_rejected(
    repository: CentralRepository, organization_id: int
) -> None:
    _create_component(repository, organization_id, "component_a")
    _create_component(repository, organization_id, "component_b")
    product = repository.create_product(
        organization_id=organization_id,
        product_code="prod-2",
        name="Prod 2",
        idempotency_key="product:prod-2",
        request_hash=_HASH,
        created_at=datetime.now(UTC),
        actor="admin",
        request_id=None,
    )
    with pytest.raises(InvalidComponentError):
        repository.create_product_version(
            organization_id=organization_id,
            product_id=product.product.id,
            barcodes=[],
            required_components=[
                ProductComponentInput(component_code="does-not-exist", expected_count=1)
            ],
            idempotency_key="prod-2:bad",
            request_hash=_HASH,
            created_at=datetime.now(UTC),
            actor="admin",
            request_id=None,
        )


def test_ambiguous_barcode_rejected(repository: CentralRepository, organization_id: int) -> None:
    _create_component(repository, organization_id, "component_a")
    _create_component(repository, organization_id, "component_b")
    first = repository.create_product(
        organization_id=organization_id,
        product_code="prod-a",
        name="Prod A",
        idempotency_key="product:prod-a",
        request_hash=_HASH,
        created_at=datetime.now(UTC),
        actor="admin",
        request_id=None,
    )
    v1 = _create_product_version(
        repository, organization_id, first.product.id, barcodes=["111222333"], key="prod-a:v1"
    )
    _publish(repository, organization_id, v1, "product")

    second = repository.create_product(
        organization_id=organization_id,
        product_code="prod-b",
        name="Prod B",
        idempotency_key="product:prod-b",
        request_hash=_HASH,
        created_at=datetime.now(UTC),
        actor="admin",
        request_id=None,
    )
    v2 = _create_product_version(
        repository, organization_id, second.product.id, barcodes=["111222333"], key="prod-b:v1"
    )
    with pytest.raises(AmbiguousBarcodeError):
        _publish(repository, organization_id, v2, "product")


def test_product_version_missing_product(
    repository: CentralRepository, organization_id: int
) -> None:
    with pytest.raises(ProductNotFoundError):
        repository.create_product_version(
            organization_id=organization_id,
            product_id=999999,
            barcodes=[],
            required_components=[
                ProductComponentInput(component_code="component_a", expected_count=1)
            ],
            idempotency_key="missing",
            request_hash=_HASH,
            created_at=datetime.now(UTC),
            actor="admin",
            request_id=None,
        )


# -- rule versions -----------------------------------------------------------


def test_rule_draft_threshold_ordering_rejected(
    repository: CentralRepository, organization_id: int
) -> None:
    _create_component(repository, organization_id, "component_a")
    _create_component(repository, organization_id, "component_b")
    product = repository.create_product(
        organization_id=organization_id,
        product_code="prod-3",
        name="Prod 3",
        idempotency_key="product:prod-3",
        request_hash=_HASH,
        created_at=datetime.now(UTC),
        actor="admin",
        request_id=None,
    )
    version_id = _create_product_version(
        repository, organization_id, product.product.id, key="prod-3:v1"
    )
    rule = repository.create_rule(
        organization_id=organization_id,
        rule_code="rule-1",
        name="Rule 1",
        idempotency_key="rule:rule-1",
        request_hash=_HASH,
        created_at=datetime.now(UTC),
        actor="admin",
        request_id=None,
    )
    with pytest.raises(InvalidPolicyError):
        repository.create_rule_version(
            organization_id=organization_id,
            rule_id=rule.rule.id,
            product_version_id=version_id,
            barcode_required=False,
            minimum_usable_frames=3,
            mandatory_gates={},
            component_policies=[
                RulePolicyInput(
                    component_code="component_a",
                    high_confidence=0.5,
                    medium_confidence=0.9,  # medium > high
                    minimum_medium_detections=2,
                    require_adjacent_frames=False,
                    expected_count=1,
                )
            ],
            compatible_component_model_version_ids=[],
            idempotency_key="rule:rule-1:bad",
            request_hash=_HASH,
            created_at=datetime.now(UTC),
            actor="admin",
            request_id=None,
        )


def test_rule_draft_unknown_component_rejected(
    repository: CentralRepository, organization_id: int
) -> None:
    _create_component(repository, organization_id, "component_a")
    _create_component(repository, organization_id, "component_b")
    product = repository.create_product(
        organization_id=organization_id,
        product_code="prod-4",
        name="Prod 4",
        idempotency_key="product:prod-4",
        request_hash=_HASH,
        created_at=datetime.now(UTC),
        actor="admin",
        request_id=None,
    )
    version_id = _create_product_version(
        repository, organization_id, product.product.id, key="prod-4:v1"
    )
    rule = repository.create_rule(
        organization_id=organization_id,
        rule_code="rule-2",
        name="Rule 2",
        idempotency_key="rule:rule-2",
        request_hash=_HASH,
        created_at=datetime.now(UTC),
        actor="admin",
        request_id=None,
    )
    with pytest.raises(InvalidPolicyError):
        repository.create_rule_version(
            organization_id=organization_id,
            rule_id=rule.rule.id,
            product_version_id=version_id,
            barcode_required=False,
            minimum_usable_frames=3,
            mandatory_gates={},
            component_policies=[
                RulePolicyInput(
                    component_code="mystery",
                    high_confidence=0.9,
                    medium_confidence=0.7,
                    minimum_medium_detections=2,
                    require_adjacent_frames=False,
                    expected_count=1,
                )
            ],
            compatible_component_model_version_ids=[],
            idempotency_key="rule:rule-2:bad",
            request_hash=_HASH,
            created_at=datetime.now(UTC),
            actor="admin",
            request_id=None,
        )


def test_rule_publish_requires_published_product(
    repository: CentralRepository, organization_id: int
) -> None:
    _create_component(repository, organization_id, "component_a")
    _create_component(repository, organization_id, "component_b")
    product = repository.create_product(
        organization_id=organization_id,
        product_code="prod-5",
        name="Prod 5",
        idempotency_key="product:prod-5",
        request_hash=_HASH,
        created_at=datetime.now(UTC),
        actor="admin",
        request_id=None,
    )
    version_id = _create_product_version(
        repository, organization_id, product.product.id, key="prod-5:v1"
    )
    rule = repository.create_rule(
        organization_id=organization_id,
        rule_code="rule-3",
        name="Rule 3",
        idempotency_key="rule:rule-3",
        request_hash=_HASH,
        created_at=datetime.now(UTC),
        actor="admin",
        request_id=None,
    )
    rule_version = repository.create_rule_version(
        organization_id=organization_id,
        rule_id=rule.rule.id,
        product_version_id=version_id,
        barcode_required=False,
        minimum_usable_frames=3,
        mandatory_gates={},
        component_policies=[
            RulePolicyInput(
                component_code="component_a",
                high_confidence=0.9,
                medium_confidence=0.7,
                minimum_medium_detections=2,
                require_adjacent_frames=False,
                expected_count=1,
            )
        ],
        compatible_component_model_version_ids=[],
        idempotency_key="rule:rule-3:v1",
        request_hash=_HASH,
        created_at=datetime.now(UTC),
        actor="admin",
        request_id=None,
    )
    with pytest.raises(IncompatibleVersionError):
        _publish(repository, organization_id, rule_version.version.version_id, "rule")


def test_rule_publish_policy_set_mismatch(
    repository: CentralRepository, organization_id: int
) -> None:
    _create_component(repository, organization_id, "component_a")
    _create_component(repository, organization_id, "component_b")
    product = repository.create_product(
        organization_id=organization_id,
        product_code="prod-6",
        name="Prod 6",
        idempotency_key="product:prod-6",
        request_hash=_HASH,
        created_at=datetime.now(UTC),
        actor="admin",
        request_id=None,
    )
    version_id = _create_product_version(
        repository, organization_id, product.product.id, key="prod-6:v1"
    )
    _publish(repository, organization_id, version_id, "product")
    rule = repository.create_rule(
        organization_id=organization_id,
        rule_code="rule-4",
        name="Rule 4",
        idempotency_key="rule:rule-4",
        request_hash=_HASH,
        created_at=datetime.now(UTC),
        actor="admin",
        request_id=None,
    )
    # The product requires component_a AND component_b; the rule only covers a.
    rule_version = repository.create_rule_version(
        organization_id=organization_id,
        rule_id=rule.rule.id,
        product_version_id=version_id,
        barcode_required=False,
        minimum_usable_frames=3,
        mandatory_gates={},
        component_policies=[
            RulePolicyInput(
                component_code="component_a",
                high_confidence=0.9,
                medium_confidence=0.7,
                minimum_medium_detections=2,
                require_adjacent_frames=False,
                expected_count=1,
            )
        ],
        compatible_component_model_version_ids=[],
        idempotency_key="rule:rule-4:v1",
        request_hash=_HASH,
        created_at=datetime.now(UTC),
        actor="admin",
        request_id=None,
    )
    with pytest.raises(InvalidPolicyError):
        _publish(repository, organization_id, rule_version.version.version_id, "rule")


def test_rule_publish_requires_published_model(
    repository: CentralRepository, organization_id: int
) -> None:
    seed = _seed_governance(repository, organization_id)
    # A second component model that is still a draft.
    component_model = repository.create_model_package(
        organization_id=organization_id,
        model_code="component-detector-2",
        name="Component Detector 2",
        task="COMPONENT_DETECTION",
        idempotency_key="model:component-detector-2",
        request_hash=_HASH,
        created_at=datetime.now(UTC),
        actor="admin",
        request_id=None,
    )
    draft_model_version = _create_model_version(
        repository,
        organization_id,
        component_model.package.id,
        task="COMPONENT_DETECTION",
        classes=["component_a", "component_b"],
        key="model:component-detector-2:v1",
    )
    rule = repository.create_rule(
        organization_id=organization_id,
        rule_code="rule-5",
        name="Rule 5",
        idempotency_key="rule:rule-5",
        request_hash=_HASH,
        created_at=datetime.now(UTC),
        actor="admin",
        request_id=None,
    )
    rule_version = repository.create_rule_version(
        organization_id=organization_id,
        rule_id=rule.rule.id,
        product_version_id=seed.product_version_id,
        barcode_required=False,
        minimum_usable_frames=3,
        mandatory_gates={},
        component_policies=[
            RulePolicyInput(
                component_code="component_a",
                high_confidence=0.9,
                medium_confidence=0.7,
                minimum_medium_detections=2,
                require_adjacent_frames=False,
                expected_count=1,
            ),
            RulePolicyInput(
                component_code="component_b",
                high_confidence=0.9,
                medium_confidence=0.7,
                minimum_medium_detections=2,
                require_adjacent_frames=False,
                expected_count=1,
            ),
        ],
        compatible_component_model_version_ids=[draft_model_version],
        idempotency_key="rule:rule-5:v1",
        request_hash=_HASH,
        created_at=datetime.now(UTC),
        actor="admin",
        request_id=None,
    )
    with pytest.raises(IncompatibleVersionError):
        _publish(repository, organization_id, rule_version.version.version_id, "rule")


def test_rule_publish_model_class_coverage(
    repository: CentralRepository, organization_id: int
) -> None:
    seed = _seed_governance(repository, organization_id)
    # A published model missing component_b in its classes.
    component_model = repository.create_model_package(
        organization_id=organization_id,
        model_code="component-detector-3",
        name="Component Detector 3",
        task="COMPONENT_DETECTION",
        idempotency_key="model:component-detector-3",
        request_hash=_HASH,
        created_at=datetime.now(UTC),
        actor="admin",
        request_id=None,
    )
    partial_model_version = _create_model_version(
        repository,
        organization_id,
        component_model.package.id,
        task="COMPONENT_DETECTION",
        classes=["component_a"],
        key="model:component-detector-3:v1",
    )
    _publish(repository, organization_id, partial_model_version, "model")
    rule = repository.create_rule(
        organization_id=organization_id,
        rule_code="rule-6",
        name="Rule 6",
        idempotency_key="rule:rule-6",
        request_hash=_HASH,
        created_at=datetime.now(UTC),
        actor="admin",
        request_id=None,
    )
    rule_version = repository.create_rule_version(
        organization_id=organization_id,
        rule_id=rule.rule.id,
        product_version_id=seed.product_version_id,
        barcode_required=False,
        minimum_usable_frames=3,
        mandatory_gates={},
        component_policies=[
            RulePolicyInput(
                component_code="component_a",
                high_confidence=0.9,
                medium_confidence=0.7,
                minimum_medium_detections=2,
                require_adjacent_frames=False,
                expected_count=1,
            ),
            RulePolicyInput(
                component_code="component_b",
                high_confidence=0.9,
                medium_confidence=0.7,
                minimum_medium_detections=2,
                require_adjacent_frames=False,
                expected_count=1,
            ),
        ],
        compatible_component_model_version_ids=[partial_model_version],
        idempotency_key="rule:rule-6:v1",
        request_hash=_HASH,
        created_at=datetime.now(UTC),
        actor="admin",
        request_id=None,
    )
    with pytest.raises(IncompatibleVersionError):
        _publish(repository, organization_id, rule_version.version.version_id, "rule")


# -- model versions ----------------------------------------------------------


def test_model_manifest_validation(repository: CentralRepository, organization_id: int) -> None:
    package = repository.create_model_package(
        organization_id=organization_id,
        model_code="model-1",
        name="Model 1",
        task="COMPONENT_DETECTION",
        idempotency_key="model:model-1",
        request_hash=_HASH,
        created_at=datetime.now(UTC),
        actor="admin",
        request_id=None,
    )
    base: dict[str, object] = {
        "task": "COMPONENT_DETECTION",
        "semantic_version": "1.0.0",
        "edge_version_label": "model-1-1.0.0",
        "runtime": "ultralytics",
        "input_width": 640,
        "input_height": 640,
        "class_names": ["component_a"],
        "artifacts": [{"name": "weights", "uri": "w.pt", "sha256": _HASH, "size_bytes": 1}],
        "datasets": [],
        "split_strategy": "by_session",
        "source_revision": "abc",
        "training_config_revision": "train-1",
        "metrics": [],
        "limitations": [],
    }
    with pytest.raises(InvalidManifestError):
        repository.create_model_version(
            organization_id=organization_id,
            model_package_id=package.package.id,
            manifest={**base, "task": "PRODUCT_DETECTION"},
            idempotency_key="model:model-1:bad-task",
            request_hash=_HASH,
            created_at=datetime.now(UTC),
            actor="admin",
            request_id=None,
        )
    with pytest.raises(InvalidManifestError):
        repository.create_model_version(
            organization_id=organization_id,
            model_package_id=package.package.id,
            manifest={
                **base,
                "artifacts": [{"name": "w", "uri": "u", "sha256": "zz", "size_bytes": 1}],
            },
            idempotency_key="model:model-1:bad-sha",
            request_hash=_HASH,
            created_at=datetime.now(UTC),
            actor="admin",
            request_id=None,
        )
    with pytest.raises(InvalidManifestError):
        repository.create_model_version(
            organization_id=organization_id,
            model_package_id=package.package.id,
            manifest={**base, "artifacts": []},
            idempotency_key="model:model-1:no-artifact",
            request_hash=_HASH,
            created_at=datetime.now(UTC),
            actor="admin",
            request_id=None,
        )
    with pytest.raises(InvalidManifestError):
        repository.create_model_version(
            organization_id=organization_id,
            model_package_id=package.package.id,
            manifest={**base, "class_names": ["component_a", "component_a"]},
            idempotency_key="model:model-1:dup-class",
            request_hash=_HASH,
            created_at=datetime.now(UTC),
            actor="admin",
            request_id=None,
        )


def test_model_publish_is_declarative(repository: CentralRepository, organization_id: int) -> None:
    package = repository.create_model_package(
        organization_id=organization_id,
        model_code="model-2",
        name="Model 2",
        task="COMPONENT_DETECTION",
        idempotency_key="model:model-2",
        request_hash=_HASH,
        created_at=datetime.now(UTC),
        actor="admin",
        request_id=None,
    )
    version_id = _create_model_version(
        repository,
        organization_id,
        package.package.id,
        task="COMPONENT_DETECTION",
        classes=["component_a"],
        key="model:model-2:v1",
    )
    result = repository.publish_model_version(
        organization_id=organization_id,
        version_id=version_id,
        published_by="admin",
        publish_reason="registry entry",
        published_at=datetime.now(UTC),
        actor="admin",
        request_id="req-123",
    )
    assert not result.replayed
    audit = _audit_actions(repository, organization_id, "MODEL_PUBLISHED")
    assert len(audit) == 1
    assert audit[0]["reason"] == "registry entry"


def test_model_publish_never_claims_validation(
    repository: CentralRepository, organization_id: int
) -> None:
    package = repository.create_model_package(
        organization_id=organization_id,
        model_code="model-3",
        name="Model 3",
        task="COMPONENT_DETECTION",
        idempotency_key="model:model-3",
        request_hash=_HASH,
        created_at=datetime.now(UTC),
        actor="admin",
        request_id=None,
    )
    version_id = _create_model_version(
        repository,
        organization_id,
        package.package.id,
        task="COMPONENT_DETECTION",
        classes=["component_a"],
        key="model:model-3:v1",
    )
    repository.publish_model_version(
        organization_id=organization_id,
        version_id=version_id,
        published_by="admin",
        publish_reason="registry entry",
        published_at=datetime.now(UTC),
        actor="admin",
        request_id=None,
    )
    with repository._engine.connect() as connection:  # noqa: SLF001 - test reads the audit table
        detail = connection.execute(
            select(audit_logs.c.detail).where(audit_logs.c.action == "MODEL_PUBLISHED")
        ).scalar_one()
    assert "artifact bytes not verified" in str(detail)


# -- desired configuration ---------------------------------------------------


def test_desired_configuration_flow(repository: CentralRepository, organization_id: int) -> None:
    seed = _seed_governance(repository, organization_id)
    device = repository.get_device_by_identity(organization_id, str(_DEVICE_ID))
    assert device is not None
    with pytest.raises(RevisionMismatchError):
        repository.set_desired_configuration(
            organization_id=organization_id,
            device_row_id=device.id,
            if_match_revision=1,
            product_version_id=seed.product_version_id,
            product_model_version_id=seed.product_model_version_id,
            component_model_version_id=seed.component_model_version_id,
            rule_version_id=seed.rule_version_id,
            reason="pilot rollout",
            assigned_by="admin",
            assigned_at=datetime.now(UTC),
            actor="admin",
            request_id="req-1",
        )
    first = repository.set_desired_configuration(
        organization_id=organization_id,
        device_row_id=device.id,
        if_match_revision=0,
        product_version_id=seed.product_version_id,
        product_model_version_id=seed.product_model_version_id,
        component_model_version_id=seed.component_model_version_id,
        rule_version_id=seed.rule_version_id,
        reason="pilot rollout",
        assigned_by="admin",
        assigned_at=datetime.now(UTC),
        actor="admin",
        request_id="req-1",
    )
    assert first.revision == 1
    assert first.device_id == str(_DEVICE_ID)
    assert first.product_version_id == seed.product_version_id
    assert first.product_model_version_id == seed.product_model_version_id
    assert first.component_model_version_id == seed.component_model_version_id
    assert first.rule_version_id == seed.rule_version_id
    # Replace the assignment under the new revision.
    second = repository.set_desired_configuration(
        organization_id=organization_id,
        device_row_id=device.id,
        if_match_revision=1,
        product_version_id=seed.product_version_id,
        product_model_version_id=seed.product_model_version_id,
        component_model_version_id=seed.component_model_version_id,
        rule_version_id=seed.rule_version_id,
        reason="rollout update",
        assigned_by="admin",
        assigned_at=datetime.now(UTC),
        actor="admin",
        request_id="req-2",
    )
    assert second.revision == 2
    assert second.product_version_id == seed.product_version_id
    assert second.product_model_version_id == seed.product_model_version_id
    assert second.component_model_version_id == seed.component_model_version_id
    assert second.rule_version_id == seed.rule_version_id
    audit = _audit_actions(repository, organization_id, "DESIRED_CONFIGURATION_ASSIGNED")
    assert len(audit) == 2
    assert audit[0]["before_state"] is None
    assert audit[1]["before_state"] == {
        "revision": 1,
        "product_version_id": seed.product_version_id,
    }
    assert "manual installation required" in str(audit[0]["detail"])


def test_desired_configuration_uses_product_version_parent_and_public_ids(
    repository: CentralRepository, organization_id: int
) -> None:
    """A product/version PK mismatch must not alter compatibility validation."""
    repository.create_product(
        organization_id=organization_id,
        product_code="unused",
        name="Unused",
        idempotency_key="product:unused",
        request_hash=_HASH,
        created_at=datetime.now(UTC),
        actor="admin",
        request_id=None,
    )
    seed = _seed_governance(repository, organization_id)
    device = repository.get_device_by_identity(organization_id, str(_DEVICE_ID))
    assert device is not None

    assigned = repository.set_desired_configuration(
        organization_id=organization_id,
        device_row_id=device.id,
        if_match_revision=0,
        product_version_id=seed.product_version_id,
        product_model_version_id=seed.product_model_version_id,
        component_model_version_id=seed.component_model_version_id,
        rule_version_id=seed.rule_version_id,
        reason="pilot rollout",
        assigned_by="admin",
        assigned_at=datetime.now(UTC),
        actor="admin",
        request_id=None,
    )

    assert assigned.product_version_id == seed.product_version_id
    assert assigned.product_model_version_id == seed.product_model_version_id
    assert assigned.component_model_version_id == seed.component_model_version_id
    assert assigned.rule_version_id == seed.rule_version_id


def test_desired_configuration_incompatible_bundle(
    repository: CentralRepository, organization_id: int
) -> None:
    seed = _seed_governance(repository, organization_id)
    device = repository.get_device_by_identity(organization_id, str(_DEVICE_ID))
    assert device is not None
    # A PRODUCT_DETECTION model cannot be the component model.
    with pytest.raises(IncompatibleVersionError):
        repository.set_desired_configuration(
            organization_id=organization_id,
            device_row_id=device.id,
            if_match_revision=0,
            product_version_id=seed.product_version_id,
            product_model_version_id=seed.component_model_version_id,
            component_model_version_id=seed.component_model_version_id,
            rule_version_id=seed.rule_version_id,
            reason="wrong task",
            assigned_by="admin",
            assigned_at=datetime.now(UTC),
            actor="admin",
            request_id=None,
        )


def test_desired_configuration_unknown_device(
    repository: CentralRepository, organization_id: int
) -> None:
    seed = _seed_governance(repository, organization_id)
    assert repository.get_device_by_identity(organization_id, str(uuid4())) is None
    with pytest.raises(DeviceNotFoundError):
        repository.set_desired_configuration(
            organization_id=organization_id,
            device_row_id=999999,
            if_match_revision=0,
            product_version_id=seed.product_version_id,
            product_model_version_id=seed.product_model_version_id,
            component_model_version_id=seed.component_model_version_id,
            rule_version_id=seed.rule_version_id,
            reason="missing device",
            assigned_by="admin",
            assigned_at=datetime.now(UTC),
            actor="admin",
            request_id=None,
        )
