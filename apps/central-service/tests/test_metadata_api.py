"""C5 metadata governance API tests over the full FastAPI path.

Exercises unauthenticated 401s, idempotent create with replay/conflict,
product/rule/model draft+publish flows, validation problem codes, barcode
ambiguity, and desired-configuration assignment with If-Match revisions.
"""

from __future__ import annotations

from collections.abc import Iterator
from uuid import uuid4

import pytest
from central_service.api.app import create_app
from central_service.api.readiness import ReadinessCheck, ReadinessResult
from central_service.api.settings import CentralSettings
from central_service.persistence.bootstrap import resolve_plan, run_bootstrap
from central_service.persistence.repository import CentralRepository
from central_service.persistence.schema import metadata
from fastapi import FastAPI
from fastapi.testclient import TestClient
from ingest_fixtures import NoopObjectStorage
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

# Test fixtures carry their own credential strings; these are never real.
_ADMIN_TOKEN = "test-admin-token-0123456789abcdef"  # noqa: S105
_DEVICE_TOKEN = "test-device-token-0123456789abcdef"  # noqa: S105
_DEVICE_ID = uuid4()
_HASH = "0" * 64


@pytest.fixture
def repository() -> Iterator[CentralRepository]:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    metadata.create_all(engine)
    try:
        yield CentralRepository(engine)
    finally:
        engine.dispose()


@pytest.fixture
def client(repository: CentralRepository) -> Iterator[TestClient]:
    run_bootstrap(
        repository,
        resolve_plan(
            _settings(),
            admin_token=_ADMIN_TOKEN,
            device_upload_token=_DEVICE_TOKEN,
            device_id=str(_DEVICE_ID),
        ),
    )
    with TestClient(_app(repository)) as test_client:
        yield test_client


def _settings(**overrides: object) -> CentralSettings:
    values: dict[str, object] = {
        "database_url": "postgresql+psycopg://unused:unused@127.0.0.1:1/unused",
        "admin_session_ttl_minutes": 60,
        "secure_cookies": False,
    }
    values.update(overrides)
    return CentralSettings(**values)  # type: ignore[arg-type]


def _app(repository: CentralRepository) -> FastAPI:
    readiness = ReadinessResult(
        checks=(
            ReadinessCheck(name="database", ok=True, detail="ok"),
            ReadinessCheck(name="object_store", ok=True, detail="ok"),
            ReadinessCheck(name="credentials", ok=True, detail="ok"),
        )
    )
    return create_app(
        _settings(),
        readiness=lambda: readiness,
        repository=repository,
        storage=NoopObjectStorage(),
    )


def _admin_headers(**extra: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {_ADMIN_TOKEN}", **extra}


def _product_payload() -> dict[str, str]:
    return {"product_code": "model_a", "name": "Model A"}


def _component_payload() -> dict[str, str]:
    return {"component_code": "component_a", "display_name": "Component A"}


def _manifest_payload(
    task: str = "COMPONENT_DETECTION", classes: list[str] | None = None
) -> dict[str, object]:
    return {
        "task": task,
        "semantic_version": "1.0.0",
        "edge_version_label": "label-1.0.0",
        "runtime": "ultralytics",
        "input_width": 640,
        "input_height": 640,
        "class_names": classes or ["component_a"],
        "artifacts": [{"name": "weights", "uri": "w.pt", "sha256": _HASH, "size_bytes": 1}],
        "datasets": [],
        "split_strategy": "by_session",
        "source_revision": "abc123",
        "training_config_revision": "train-1",
        "metrics": [],
        "limitations": [],
    }


def _seed_product_chain(client: TestClient) -> str:
    """Create component, product, and a draft product version; returns its version_id."""
    client.post(
        "/api/v1/components",
        json=_component_payload(),
        headers=_admin_headers(**{"Idempotency-Key": "c1"}),
    )
    client.post(
        "/api/v1/components",
        json={"component_code": "component_b", "display_name": "B"},
        headers=_admin_headers(**{"Idempotency-Key": "c2"}),
    )
    product = client.post(
        "/api/v1/products",
        json=_product_payload(),
        headers=_admin_headers(**{"Idempotency-Key": "p1"}),
    )
    assert product.status_code == 201
    product_id = product.json()["id"]
    version = client.post(
        f"/api/v1/products/{product_id}/versions",
        json={
            "barcodes": ["4901234567890"],
            "components": [
                {"component_code": "component_a", "expected_count": 1},
                {"component_code": "component_b", "expected_count": 1},
            ],
        },
        headers=_admin_headers(**{"Idempotency-Key": "pv1"}),
    )
    assert version.status_code == 201
    return str(version.json()["version_id"])


def test_unauthenticated_rejected(client: TestClient) -> None:
    response = client.get("/api/v1/products")
    assert response.status_code == 401
    assert response.json()["code"] == "UNAUTHENTICATED"


def test_product_create_replay_and_conflict(client: TestClient) -> None:
    first = client.post(
        "/api/v1/products",
        json=_product_payload(),
        headers=_admin_headers(**{"Idempotency-Key": "key-1"}),
    )
    assert first.status_code == 201
    replay = client.post(
        "/api/v1/products",
        json=_product_payload(),
        headers=_admin_headers(**{"Idempotency-Key": "key-1"}),
    )
    assert replay.status_code == 200
    assert replay.json()["id"] == first.json()["id"]
    conflict = client.post(
        "/api/v1/products",
        json={"product_code": "other", "name": "Other"},
        headers=_admin_headers(**{"Idempotency-Key": "key-1"}),
    )
    assert conflict.status_code == 409
    assert conflict.json()["code"] == "IDEMPOTENCY_CONFLICT"
    duplicate = client.post(
        "/api/v1/products",
        json=_product_payload(),
        headers=_admin_headers(**{"Idempotency-Key": "key-2"}),
    )
    assert duplicate.status_code == 409
    assert duplicate.json()["code"] == "METADATA_CODE_EXISTS"


def test_product_version_draft_and_publish(client: TestClient) -> None:
    version_id = _seed_product_chain(client)
    publish = client.post(
        f"/api/v1/product-versions/{version_id}/publish",
        json={"reason": "pilot release"},
        headers=_admin_headers(),
    )
    assert publish.status_code == 200
    assert publish.json()["status"] == "PUBLISHED"
    assert publish.json()["barcodes"] == ["4901234567890"]
    # Repeated publish is idempotent.
    repeat = client.post(
        f"/api/v1/product-versions/{version_id}/publish",
        json={"reason": "pilot release"},
        headers=_admin_headers(),
    )
    assert repeat.status_code == 200
    # The published version is immutable: a new change is a higher version.
    product_id = publish.json()["product_id"]
    next_version = client.post(
        f"/api/v1/products/{product_id}/versions",
        json={
            "barcodes": [],
            "components": [
                {"component_code": "component_a", "expected_count": 1},
                {"component_code": "component_b", "expected_count": 1},
            ],
        },
        headers=_admin_headers(**{"Idempotency-Key": "pv2"}),
    )
    assert next_version.status_code == 201
    assert next_version.json()["version"] == 2


def test_product_version_invalid_component(client: TestClient) -> None:
    client.post(
        "/api/v1/components",
        json=_component_payload(),
        headers=_admin_headers(**{"Idempotency-Key": "c1"}),
    )
    product = client.post(
        "/api/v1/products",
        json=_product_payload(),
        headers=_admin_headers(**{"Idempotency-Key": "p1"}),
    )
    product_id = product.json()["id"]
    response = client.post(
        f"/api/v1/products/{product_id}/versions",
        json={"barcodes": [], "components": [{"component_code": "missing", "expected_count": 1}]},
        headers=_admin_headers(**{"Idempotency-Key": "pv-bad"}),
    )
    assert response.status_code == 422
    assert response.json()["code"] == "INVALID_COMPONENT"


def test_ambiguous_barcode(client: TestClient) -> None:
    first_version = _seed_product_chain(client)
    assert (
        client.post(
            f"/api/v1/product-versions/{first_version}/publish",
            json={"reason": "release"},
            headers=_admin_headers(),
        ).status_code
        == 200
    )
    second = client.post(
        "/api/v1/products",
        json={"product_code": "model_b", "name": "Model B"},
        headers=_admin_headers(**{"Idempotency-Key": "p2"}),
    )
    second_id = second.json()["id"]
    client.post(
        "/api/v1/components",
        json={"component_code": "component_c", "display_name": "C"},
        headers=_admin_headers(**{"Idempotency-Key": "c3"}),
    )
    draft = client.post(
        f"/api/v1/products/{second_id}/versions",
        json={
            "barcodes": ["4901234567890"],
            "components": [{"component_code": "component_c", "expected_count": 1}],
        },
        headers=_admin_headers(**{"Idempotency-Key": "pv-b"}),
    )
    assert draft.status_code == 201
    publish = client.post(
        f"/api/v1/product-versions/{draft.json()['version_id']}/publish",
        json={"reason": "release"},
        headers=_admin_headers(),
    )
    assert publish.status_code == 409
    assert publish.json()["code"] == "AMBIGUOUS_BARCODE_MAPPING"


def test_rule_and_model_flow(client: TestClient) -> None:
    product_version_id = _seed_product_chain(client)
    assert (
        client.post(
            f"/api/v1/product-versions/{product_version_id}/publish",
            json={"reason": "release"},
            headers=_admin_headers(),
        ).status_code
        == 200
    )

    model_package = client.post(
        "/api/v1/models",
        json={
            "model_code": "component-detector",
            "name": "Component Detector",
            "task": "COMPONENT_DETECTION",
        },
        headers=_admin_headers(**{"Idempotency-Key": "m1"}),
    )
    assert model_package.status_code == 201
    model_version = client.post(
        f"/api/v1/models/{model_package.json()['id']}/versions",
        json=_manifest_payload(classes=["component_a", "component_b"]),
        headers=_admin_headers(**{"Idempotency-Key": "mv1"}),
    )
    assert model_version.status_code == 201
    model_version_id = str(model_version.json()["version_id"])
    model_publish = client.post(
        f"/api/v1/model-versions/{model_version_id}/publish",
        json={"reason": "registry entry"},
        headers=_admin_headers(),
    )
    assert model_publish.status_code == 200
    assert model_publish.json()["status"] == "PUBLISHED"

    rule = client.post(
        "/api/v1/rules",
        json={"rule_code": "model-a-presence", "name": "Presence"},
        headers=_admin_headers(**{"Idempotency-Key": "r1"}),
    )
    assert rule.status_code == 201
    rule_version = client.post(
        f"/api/v1/rules/{rule.json()['id']}/versions",
        json={
            "product_version_id": product_version_id,
            "barcode_required": False,
            "minimum_usable_frames": 3,
            "mandatory_gates": {"product_detected": True},
            "component_policies": [
                {
                    "component_code": "component_a",
                    "high_confidence": 0.9,
                    "medium_confidence": 0.7,
                    "minimum_medium_detections": 2,
                    "require_adjacent_frames": False,
                    "expected_count": 1,
                },
                {
                    "component_code": "component_b",
                    "high_confidence": 0.9,
                    "medium_confidence": 0.7,
                    "minimum_medium_detections": 2,
                    "require_adjacent_frames": False,
                    "expected_count": 1,
                },
            ],
            "compatible_component_model_version_ids": [model_version_id],
        },
        headers=_admin_headers(**{"Idempotency-Key": "rv1"}),
    )
    assert rule_version.status_code == 201
    rule_version_id = str(rule_version.json()["version_id"])
    rule_publish = client.post(
        f"/api/v1/rule-versions/{rule_version_id}/publish",
        json={"reason": "pilot release"},
        headers=_admin_headers(),
    )
    assert rule_publish.status_code == 200
    assert rule_publish.json()["status"] == "PUBLISHED"
    assert rule_publish.json()["uncertain_maps_to_ng"] is True

    detail = client.get(f"/api/v1/rules/{rule.json()['id']}", headers=_admin_headers())
    assert detail.status_code == 200
    assert len(detail.json()["versions"]) == 1


def test_rule_publish_requires_published_product(client: TestClient) -> None:
    product_version_id = _seed_product_chain(client)  # stays DRAFT
    rule = client.post(
        "/api/v1/rules",
        json={"rule_code": "rule-x", "name": "Rule X"},
        headers=_admin_headers(**{"Idempotency-Key": "r-x"}),
    )
    rule_version = client.post(
        f"/api/v1/rules/{rule.json()['id']}/versions",
        json={
            "product_version_id": product_version_id,
            "barcode_required": False,
            "minimum_usable_frames": 3,
            "mandatory_gates": {},
            "component_policies": [
                {
                    "component_code": "component_a",
                    "high_confidence": 0.9,
                    "medium_confidence": 0.7,
                    "minimum_medium_detections": 2,
                    "require_adjacent_frames": False,
                    "expected_count": 1,
                },
                {
                    "component_code": "component_b",
                    "high_confidence": 0.9,
                    "medium_confidence": 0.7,
                    "minimum_medium_detections": 2,
                    "require_adjacent_frames": False,
                    "expected_count": 1,
                },
            ],
            "compatible_component_model_version_ids": [],
        },
        headers=_admin_headers(**{"Idempotency-Key": "rv-x"}),
    )
    publish = client.post(
        f"/api/v1/rule-versions/{rule_version.json()['version_id']}/publish",
        json={"reason": "release"},
        headers=_admin_headers(),
    )
    assert publish.status_code == 409
    assert publish.json()["code"] == "INCOMPATIBLE_VERSION"


def test_model_manifest_validation(client: TestClient) -> None:
    model_package = client.post(
        "/api/v1/models",
        json={"model_code": "detector", "name": "Detector", "task": "COMPONENT_DETECTION"},
        headers=_admin_headers(**{"Idempotency-Key": "m-bad"}),
    )
    response = client.post(
        f"/api/v1/models/{model_package.json()['id']}/versions",
        json={
            **_manifest_payload(),
            "artifacts": [{"name": "w", "uri": "u", "sha256": "not-a-checksum", "size_bytes": 1}],
        },
        headers=_admin_headers(**{"Idempotency-Key": "mv-bad"}),
    )
    assert response.status_code == 422
    assert response.json()["code"] == "INVALID_MANIFEST"


def test_desired_configuration_assignment(client: TestClient) -> None:
    product_version_id = _seed_product_chain(client)
    client.post(
        f"/api/v1/product-versions/{product_version_id}/publish",
        json={"reason": "release"},
        headers=_admin_headers(),
    )
    product_model = client.post(
        "/api/v1/models",
        json={
            "model_code": "product-detector",
            "name": "Product Detector",
            "task": "PRODUCT_DETECTION",
        },
        headers=_admin_headers(**{"Idempotency-Key": "pm"}),
    )
    product_model_version = client.post(
        f"/api/v1/models/{product_model.json()['id']}/versions",
        json=_manifest_payload(task="PRODUCT_DETECTION", classes=["model_a"]),
        headers=_admin_headers(**{"Idempotency-Key": "pmv"}),
    )
    client.post(
        f"/api/v1/model-versions/{product_model_version.json()['version_id']}/publish",
        json={"reason": "registry"},
        headers=_admin_headers(),
    )
    component_model = client.post(
        "/api/v1/models",
        json={
            "model_code": "component-detector",
            "name": "Component Detector",
            "task": "COMPONENT_DETECTION",
        },
        headers=_admin_headers(**{"Idempotency-Key": "cm"}),
    )
    component_model_version = client.post(
        f"/api/v1/models/{component_model.json()['id']}/versions",
        json=_manifest_payload(classes=["component_a", "component_b"]),
        headers=_admin_headers(**{"Idempotency-Key": "cmv"}),
    )
    component_model_version_id = str(component_model_version.json()["version_id"])
    client.post(
        f"/api/v1/model-versions/{component_model_version_id}/publish",
        json={"reason": "registry"},
        headers=_admin_headers(),
    )
    rule = client.post(
        "/api/v1/rules",
        json={"rule_code": "presence", "name": "Presence"},
        headers=_admin_headers(**{"Idempotency-Key": "r-a"}),
    )
    rule_version = client.post(
        f"/api/v1/rules/{rule.json()['id']}/versions",
        json={
            "product_version_id": product_version_id,
            "barcode_required": False,
            "minimum_usable_frames": 3,
            "mandatory_gates": {},
            "component_policies": [
                {
                    "component_code": "component_a",
                    "high_confidence": 0.9,
                    "medium_confidence": 0.7,
                    "minimum_medium_detections": 2,
                    "require_adjacent_frames": False,
                    "expected_count": 1,
                },
                {
                    "component_code": "component_b",
                    "high_confidence": 0.9,
                    "medium_confidence": 0.7,
                    "minimum_medium_detections": 2,
                    "require_adjacent_frames": False,
                    "expected_count": 1,
                },
            ],
            "compatible_component_model_version_ids": [component_model_version_id],
        },
        headers=_admin_headers(**{"Idempotency-Key": "rv-a"}),
    )
    rule_version_id = str(rule_version.json()["version_id"])
    client.post(
        f"/api/v1/rule-versions/{rule_version_id}/publish",
        json={"reason": "release"},
        headers=_admin_headers(),
    )

    bundle = {
        "product_version_id": product_version_id,
        "product_model_version_id": str(product_model_version.json()["version_id"]),
        "component_model_version_id": component_model_version_id,
        "rule_version_id": rule_version_id,
        "reason": "pilot rollout",
    }
    stale = client.put(
        f"/api/v1/devices/{_DEVICE_ID}/desired-configuration",
        json=bundle,
        headers=_admin_headers(**{"If-Match": "5"}),
    )
    assert stale.status_code == 412
    assert stale.json()["code"] == "REVISION_MISMATCH"

    assigned = client.put(
        f"/api/v1/devices/{_DEVICE_ID}/desired-configuration",
        json=bundle,
        headers=_admin_headers(**{"If-Match": "0"}),
    )
    assert assigned.status_code == 200
    assert assigned.json()["revision"] == 1
    assert assigned.json()["device_id"] == str(_DEVICE_ID)

    updated = client.put(
        f"/api/v1/devices/{_DEVICE_ID}/desired-configuration",
        json={**bundle, "reason": "rollout update"},
        headers=_admin_headers(**{"If-Match": "1"}),
    )
    assert updated.status_code == 200
    assert updated.json()["revision"] == 2

    fetched = client.get(
        f"/api/v1/devices/{_DEVICE_ID}/desired-configuration", headers=_admin_headers()
    )
    assert fetched.status_code == 200
    assert fetched.json()["revision"] == 2

    listed = client.get("/api/v1/device-configurations", headers=_admin_headers())
    assert listed.status_code == 200
    assert len(listed.json()["items"]) == 1


def test_desired_configuration_unknown_device(client: TestClient) -> None:
    bundle = {
        "product_version_id": str(uuid4()),
        "product_model_version_id": str(uuid4()),
        "component_model_version_id": str(uuid4()),
        "rule_version_id": str(uuid4()),
        "reason": "nobody",
    }
    response = client.put(
        f"/api/v1/devices/{uuid4()}/desired-configuration",
        json=bundle,
        headers=_admin_headers(**{"If-Match": "0"}),
    )
    assert response.status_code == 404
    assert response.json()["code"] == "DEVICE_NOT_FOUND"
