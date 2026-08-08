"""Shared test helpers for the AssemblyVision MVP tests."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Literal
from uuid import UUID, uuid4

import pytest
from assemblyvision_domain.models import AggregatedComponentEvidence
from assemblyvision_edge.rules.rule_engine import ComponentRequirement, RuleContext, RuleDefinition


@pytest.fixture(autouse=True)
def _reset_rule_identity_registry() -> Iterator[None]:
    """Isolate the process-local rule-identity registry between tests."""
    from assemblyvision_edge import config as edge_config

    edge_config._RULE_IDENTITY_REGISTRY.clear()  # noqa: SLF001
    yield
    edge_config._RULE_IDENTITY_REGISTRY.clear()  # noqa: SLF001


REPO_ROOT = Path(__file__).resolve().parents[3]
EXAMPLE_PIPELINE = REPO_ROOT / "config/examples/pipeline.yaml"
EXAMPLE_RULE = REPO_ROOT / "config/examples/product-rule.yaml"
PRODUCT_MANIFEST = REPO_ROOT / "models/manifests/product-manifest.json"
COMPONENT_MANIFEST = REPO_ROOT / "models/manifests/component-manifest.json"


@pytest.fixture
def frame_id() -> UUID:
    return uuid4()


def make_rule(**overrides: object) -> RuleDefinition:
    base: dict[str, object] = {
        "schema_version": 1,
        "rule_id": "model-a-presence",
        "rule_version": 3,
        "product_type": "model_a",
        "compatible_component_model_versions": ["component-yolo-1.0.0"],
        "barcode_required": False,
        "required_components": {
            "component_a": ComponentRequirement(expected_count=1),
            "component_b": ComponentRequirement(expected_count=1),
        },
        "mandatory_gates": {"product_detected": True, "roi_valid": True},
    }
    base.update(overrides)
    return RuleDefinition.model_validate(base)


def make_context(
    component_model_version: str = "component-yolo-1.0.0", **overrides: object
) -> RuleContext:
    base: dict[str, object] = {
        "product_identity_verified": True,
        "component_model_version": component_model_version,
        "gates": {"product_detected": True, "roi_valid": True},
        "components": {},
    }
    base.update(overrides)
    return RuleContext.model_validate(base)


def make_evidence(
    component_code: str,
    state: Literal["PRESENT", "MISSING", "UNCERTAIN"],
    detection_count: int = 1,
    box_area_ratios: list[float] | None = None,
    box_centers: list[tuple[float, float]] | None = None,
) -> AggregatedComponentEvidence:
    return AggregatedComponentEvidence(
        component_code=component_code,
        state=state,
        best_confidence=0.9 if state == "PRESENT" else None,
        usable_frame_count=1,
        detection_count=detection_count,
        adjacent_detection_run=1 if detection_count else 0,
        supporting_frame_ids=[uuid4()],
        box_area_ratios=box_area_ratios or [],
        box_centers=box_centers or [],
    )
