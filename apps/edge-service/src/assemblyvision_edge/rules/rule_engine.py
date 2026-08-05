"""Deterministic rule engine.

The rule engine converts resolved identity, pipeline status, and per-component
evidence into a deterministic inspection decision. It is independent of YOLO,
the database, and FastAPI (docs/design/11-rule-engine.md and contract 01).
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated, Literal
from uuid import UUID, uuid5

from assemblyvision_domain import reason_codes as rc
from assemblyvision_domain.errors import RuleEvaluationError
from assemblyvision_domain.models import (
    AggregatedComponentEvidence,
    APIModel,
    BusinessResult,
    InspectionDecision,
    InternalDecision,
)
from pydantic import Field, model_validator

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

    @model_validator(mode="after")
    def validate_spatial_bounds(self) -> ComponentRequirement:
        if (
            self.min_box_area_ratio is not None
            and self.max_box_area_ratio is not None
            and self.min_box_area_ratio > self.max_box_area_ratio
        ):
            raise ValueError("min_box_area_ratio cannot exceed max_box_area_ratio")
        zone = self.allowed_zone
        if zone is not None:
            zx1, zy1, zx2, zy2 = zone
            if not (0.0 <= zx1 < zx2 <= 1.0 and 0.0 <= zy1 < zy2 <= 1.0):
                raise ValueError("allowed_zone must be a normalized [x1, y1, x2, y2] box")
        return self


class RuleDefinition(APIModel):
    """Versioned, immutable rule document (docs/design/11-rule-engine.md)."""

    schema_version: Literal[1]
    rule_id: str = Field(min_length=1)
    rule_version: Annotated[int, Field(ge=1)]
    product_type: str = Field(min_length=1)
    compatible_component_model_versions: Annotated[list[str], Field(min_length=1)]
    barcode_required: bool = False
    required_components: dict[str, ComponentRequirement]
    mandatory_gates: dict[str, bool] = Field(default_factory=dict)

    @model_validator(mode="after")
    def require_components(self) -> RuleDefinition:
        if not self.required_components:
            raise ValueError("a rule must declare at least one required component")
        return self


class RuleContext(APIModel):
    """Typed evidence snapshot evaluated by the rule engine."""

    product_identity_verified: bool = False
    component_model_version: str
    gates: dict[str, bool] = Field(default_factory=dict)
    components: dict[str, AggregatedComponentEvidence] = Field(default_factory=dict)


def rule_version_id(rule: RuleDefinition) -> UUID:
    """Deterministic UUID for a rule version, stable across runs."""
    return uuid5(
        UUID("6ba7b811-9dad-11d1-80b4-00c04fd430c8"), f"{rule.rule_id}:{rule.rule_version}"
    )


def _spatial_violation(
    requirement: ComponentRequirement, evidence: AggregatedComponentEvidence
) -> bool:
    """Return True when PRESENT evidence violates a declared spatial constraint.

    A constraint that cannot be evaluated against the supplied evidence is
    treated as a violation so that the rule can never release an OK.
    """
    if (
        requirement.min_box_area_ratio is None
        and requirement.max_box_area_ratio is None
        and requirement.allowed_zone is None
    ):
        return False
    for i in range(evidence.detection_count):
        if i >= len(evidence.box_area_ratios) or i >= len(evidence.box_centers):
            return True
        ratio = evidence.box_area_ratios[i]
        if requirement.min_box_area_ratio is not None and ratio < requirement.min_box_area_ratio:
            return True
        if requirement.max_box_area_ratio is not None and ratio > requirement.max_box_area_ratio:
            return True
        if requirement.allowed_zone is not None:
            zx1, zy1, zx2, zy2 = requirement.allowed_zone
            cx, cy = evidence.box_centers[i]
            if not (zx1 <= cx <= zx2 and zy1 <= cy <= zy2):
                return True
    return False


class RuleEngine:
    """Stateless deterministic evaluator with no permissive default."""

    @staticmethod
    def evaluate(context: RuleContext, rule: RuleDefinition) -> InspectionDecision:
        try:
            reasons: list[str] = []
            missing: list[str] = []
            low_confidence: list[str] = []
            if rule.schema_version != 1:
                reasons.append(rc.CONFIG_INVALID)
            if not rule.required_components:
                reasons.append(rc.CONFIG_INVALID)
            compatible_versions = getattr(rule, "compatible_component_model_versions", [])
            if context.component_model_version not in compatible_versions:
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
                if evidence.detection_count != requirement.expected_count:
                    reasons.append(rc.component_reason(rc.COMPONENT_COUNT_INVALID, key))
                    missing.append(key)
                    continue
                if _spatial_violation(requirement, evidence):
                    reasons.append(rc.component_reason(rc.COMPONENT_SPATIAL_INVALID, key))
                    missing.append(key)
            internal = InternalDecision.NG if reasons else InternalDecision.OK
            return InspectionDecision(
                internal_decision=internal,
                business_result=BusinessResult.NG
                if internal is not InternalDecision.OK
                else BusinessResult.OK,
                missing_components=sorted(missing),
                low_confidence_components=sorted(low_confidence),
                reason_codes=sorted(reasons),
                decided_at=datetime.now(UTC),
            )
        except Exception as exc:
            raise RuleEvaluationError(f"rule evaluation failed: {exc}") from exc
