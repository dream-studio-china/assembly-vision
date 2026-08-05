"""Deterministic rule engine.

The rule engine converts resolved identity, pipeline status, and per-component
evidence into a deterministic inspection decision. It is independent of YOLO,
the database, and FastAPI (docs/design/11-rule-engine.md and contract 01).
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated
from uuid import UUID, uuid5

from pydantic import Field

from assemblyvision_edge.domain import reason_codes as rc
from assemblyvision_edge.domain.errors import RuleEvaluationError
from assemblyvision_edge.domain.models import (
    AggregatedComponentEvidence,
    APIModel,
    BusinessResult,
    InspectionDecision,
    InternalDecision,
)

_COMPONENT_REASON_PREFIX = {
    "MISSING": rc.COMPONENT_MISSING,
    "UNCERTAIN": rc.COMPONENT_UNCERTAIN,
    "PRESENT": rc.COMPONENT_UNVERIFIABLE,
}


class ComponentRequirement(APIModel):
    """Required component specification inside a rule."""

    expected_count: Annotated[int, Field(ge=1)] = 1
    min_box_area_ratio: Annotated[float, Field(ge=0.0)] | None = None
    max_box_area_ratio: Annotated[float, Field(ge=0.0, le=1.0)] | None = None
    allowed_zone: tuple[float, float, float, float] | None = None


class RuleDefinition(APIModel):
    """Versioned, immutable rule document (docs/design/11-rule-engine.md)."""

    schema_version: int
    rule_id: str = Field(min_length=1)
    rule_version: Annotated[int, Field(ge=1)]
    product_type: str = Field(min_length=1)
    compatible_component_model_versions: list[str] = Field(default_factory=list)
    barcode_required: bool = False
    required_components: dict[str, ComponentRequirement]
    mandatory_gates: dict[str, bool] = Field(default_factory=dict)


class RuleContext(APIModel):
    """Typed evidence snapshot evaluated by the rule engine."""

    product_identity_verified: bool = False
    component_model_version: str
    gates: dict[str, bool] = Field(default_factory=dict)
    components: dict[str, AggregatedComponentEvidence] = Field(default_factory=dict)


def rule_version_id(rule: RuleDefinition) -> UUID:
    """Deterministic UUID for a rule version, stable across runs."""
    return uuid5(UUID("6ba7b811-9dad-11d1-80b4-00c04fd430c8"), f"{rule.rule_id}:{rule.rule_version}")


class RuleEngine:
    """Stateless deterministic evaluator with no permissive default."""

    @staticmethod
    def evaluate(context: RuleContext, rule: RuleDefinition) -> InspectionDecision:
        try:
            reasons: list[str] = []
            missing: list[str] = []
            low_confidence: list[str] = []
            if rule.compatible_component_model_versions and context.component_model_version not in rule.compatible_component_model_versions:
                reasons.append(rc.VERSION_INCOMPATIBLE)
            if rule.barcode_required and not context.product_identity_verified:
                reasons.append(rc.PRODUCT_IDENTITY_UNVERIFIED)
            for gate, expected in rule.mandatory_gates.items():
                if context.gates.get(gate, False) is not expected:
                    reasons.append(rc.gate_failed(gate))
            for key, requirement in rule.required_components.items():
                evidence = context.components.get(key)
                if evidence is None:
                    reasons.append(rc.component_reason(rc.COMPONENT_UNVERIFIABLE, key))
                    missing.append(key)
                    continue
                if evidence.state != "PRESENT":
                    prefix = _COMPONENT_REASON_PREFIX[evidence.state]
                    reasons.append(rc.component_reason(prefix, key))
                    if evidence.state == "MISSING":
                        missing.append(key)
                    else:
                        low_confidence.append(key)
                    continue
                if evidence.detection_count < requirement.expected_count:
                    reasons.append(rc.component_reason(rc.COMPONENT_COUNT_INVALID, key))
                    missing.append(key)
            internal = InternalDecision.NG if reasons else InternalDecision.OK
            return InspectionDecision(
                internal_decision=internal,
                business_result=BusinessResult.NG if internal is not InternalDecision.OK else BusinessResult.OK,
                missing_components=sorted(missing),
                low_confidence_components=sorted(low_confidence),
                reason_codes=sorted(reasons),
                decided_at=datetime.now(UTC),
            )
        except Exception as exc:
            raise RuleEvaluationError(f"rule evaluation failed: {exc}") from exc
