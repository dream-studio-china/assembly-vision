"""Tests for the deterministic rule engine."""

from __future__ import annotations

import pytest
from assemblyvision_domain.models import BusinessResult, InternalDecision
from assemblyvision_edge.rules.rule_engine import RuleDefinition, RuleEngine

from tests.conftest import make_context, make_evidence, make_rule

ENGINE = RuleEngine()


def test_ok_when_all_present_and_gates_hold() -> None:
    rule = make_rule()
    context = make_context(
        components={
            "component_a": make_evidence("component_a", "PRESENT"),
            "component_b": make_evidence("component_b", "PRESENT"),
        }
    )
    decision = ENGINE.evaluate(context, rule)
    assert decision.internal_decision is InternalDecision.OK
    assert decision.business_result is BusinessResult.OK
    assert decision.reason_codes == []
    assert decision.missing_components == []
    assert decision.low_confidence_components == []


def test_missing_component_produces_ng() -> None:
    rule = make_rule()
    context = make_context(
        components={
            "component_a": make_evidence("component_a", "PRESENT"),
            "component_b": make_evidence("component_b", "MISSING"),
        }
    )
    decision = ENGINE.evaluate(context, rule)
    assert decision.business_result is BusinessResult.NG
    assert "COMPONENT_MISSING:component_b" in decision.reason_codes
    assert "component_b" in decision.missing_components


def test_uncertain_component_produces_ng() -> None:
    rule = make_rule()
    context = make_context(
        components={
            "component_a": make_evidence("component_a", "PRESENT"),
            "component_b": make_evidence("component_b", "UNCERTAIN"),
        }
    )
    decision = ENGINE.evaluate(context, rule)
    assert decision.business_result is BusinessResult.NG
    assert "COMPONENT_UNCERTAIN:component_b" in decision.reason_codes
    assert "component_b" in decision.low_confidence_components


def test_unverifiable_component_produces_ng() -> None:
    rule = make_rule()
    context = make_context(components={"component_a": make_evidence("component_a", "PRESENT")})
    decision = ENGINE.evaluate(context, rule)
    assert decision.business_result is BusinessResult.NG
    assert "COMPONENT_UNVERIFIABLE:component_b" in decision.reason_codes
    assert "component_b" in decision.missing_components


def test_count_invalid_produces_ng() -> None:
    rule = make_rule(
        required_components={
            "component_a": {"expected_count": 1},
            "component_b": {"expected_count": 2},
        }
    )
    context = make_context(
        components={
            "component_a": make_evidence("component_a", "PRESENT"),
            "component_b": make_evidence("component_b", "PRESENT", detection_count=1),
        }
    )
    decision = ENGINE.evaluate(context, rule)
    assert decision.business_result is BusinessResult.NG
    assert "COMPONENT_COUNT_INVALID:component_b" in decision.reason_codes


def test_count_exceeded_produces_ng() -> None:
    rule = make_rule(
        required_components={
            "component_a": {"expected_count": 1},
            "component_b": {"expected_count": 1},
        }
    )
    context = make_context(
        components={
            "component_a": make_evidence("component_a", "PRESENT"),
            "component_b": make_evidence("component_b", "PRESENT", detection_count=2),
        }
    )
    decision = ENGINE.evaluate(context, rule)
    assert decision.business_result is BusinessResult.NG
    assert "COMPONENT_COUNT_INVALID:component_b" in decision.reason_codes
    assert "component_b" in decision.missing_components


def test_min_area_ratio_violation_produces_ng() -> None:
    rule = make_rule(
        required_components={
            "component_a": {"expected_count": 1, "min_box_area_ratio": 0.5},
            "component_b": {"expected_count": 1},
        }
    )
    context = make_context(
        components={
            "component_a": make_evidence(
                "component_a", "PRESENT", box_area_ratios=[0.1], box_centers=[(0.5, 0.5)]
            ),
            "component_b": make_evidence("component_b", "PRESENT"),
        }
    )
    decision = ENGINE.evaluate(context, rule)
    assert decision.business_result is BusinessResult.NG
    assert "COMPONENT_SPATIAL_INVALID:component_a" in decision.reason_codes


def test_max_area_ratio_violation_produces_ng() -> None:
    rule = make_rule(
        required_components={
            "component_a": {"expected_count": 1, "max_box_area_ratio": 0.3},
            "component_b": {"expected_count": 1},
        }
    )
    context = make_context(
        components={
            "component_a": make_evidence(
                "component_a", "PRESENT", box_area_ratios=[0.8], box_centers=[(0.5, 0.5)]
            ),
            "component_b": make_evidence("component_b", "PRESENT"),
        }
    )
    decision = ENGINE.evaluate(context, rule)
    assert decision.business_result is BusinessResult.NG
    assert "COMPONENT_SPATIAL_INVALID:component_a" in decision.reason_codes


def test_allowed_zone_violation_produces_ng() -> None:
    rule = make_rule(
        required_components={
            "component_a": {"expected_count": 1, "allowed_zone": [0.2, 0.2, 0.8, 0.8]},
            "component_b": {"expected_count": 1},
        }
    )
    context = make_context(
        components={
            "component_a": make_evidence(
                "component_a", "PRESENT", box_area_ratios=[0.2], box_centers=[(0.05, 0.5)]
            ),
            "component_b": make_evidence("component_b", "PRESENT"),
        }
    )
    decision = ENGINE.evaluate(context, rule)
    assert decision.business_result is BusinessResult.NG
    assert "COMPONENT_SPATIAL_INVALID:component_a" in decision.reason_codes


def test_spatial_constraints_satisfied_produce_ok() -> None:
    rule = make_rule(
        required_components={
            "component_a": {
                "expected_count": 1,
                "min_box_area_ratio": 0.1,
                "max_box_area_ratio": 0.5,
                "allowed_zone": [0.2, 0.2, 0.8, 0.8],
            },
            "component_b": {"expected_count": 1},
        }
    )
    context = make_context(
        components={
            "component_a": make_evidence(
                "component_a", "PRESENT", box_area_ratios=[0.2], box_centers=[(0.5, 0.5)]
            ),
            "component_b": make_evidence("component_b", "PRESENT"),
        }
    )
    decision = ENGINE.evaluate(context, rule)
    assert decision.business_result is BusinessResult.OK
    assert decision.reason_codes == []


def test_spatial_constraint_with_missing_evidence_produces_ng() -> None:
    rule = make_rule(
        required_components={
            "component_a": {"expected_count": 1, "min_box_area_ratio": 0.1},
            "component_b": {"expected_count": 1},
        }
    )
    context = make_context(
        components={
            "component_a": make_evidence("component_a", "PRESENT"),
            "component_b": make_evidence("component_b", "PRESENT"),
        }
    )
    decision = ENGINE.evaluate(context, rule)
    assert decision.business_result is BusinessResult.NG
    assert "COMPONENT_SPATIAL_INVALID:component_a" in decision.reason_codes


def test_gate_failure_produces_ng() -> None:
    rule = make_rule()
    context = make_context(
        gates={"product_detected": False, "roi_valid": True},
        components={
            "component_a": make_evidence("component_a", "PRESENT"),
            "component_b": make_evidence("component_b", "PRESENT"),
        },
    )
    decision = ENGINE.evaluate(context, rule)
    assert decision.business_result is BusinessResult.NG
    assert "GATE_FAILED:product_detected" in decision.reason_codes


def test_version_incompatible_produces_ng() -> None:
    rule = make_rule()
    context = make_context(
        component_model_version="component-yolo-0.9.0",
        components={
            "component_a": make_evidence("component_a", "PRESENT"),
            "component_b": make_evidence("component_b", "PRESENT"),
        },
    )
    decision = ENGINE.evaluate(context, rule)
    assert decision.business_result is BusinessResult.NG
    assert "VERSION_INCOMPATIBLE" in decision.reason_codes


def test_barcode_required_unverified_produces_ng() -> None:
    rule = make_rule(barcode_required=True)
    context = make_context(
        product_identity_verified=False,
        components={
            "component_a": make_evidence("component_a", "PRESENT"),
            "component_b": make_evidence("component_b", "PRESENT"),
        },
    )
    decision = ENGINE.evaluate(context, rule)
    assert decision.business_result is BusinessResult.NG
    assert "PRODUCT_IDENTITY_UNVERIFIED" in decision.reason_codes


def test_reason_codes_are_sorted() -> None:
    rule = make_rule()
    context = make_context(
        gates={"product_detected": False, "roi_valid": False},
        components={
            "component_a": make_evidence("component_a", "MISSING"),
            "component_b": make_evidence("component_b", "UNCERTAIN"),
        },
    )
    decision = ENGINE.evaluate(context, rule)
    assert decision.reason_codes == sorted(decision.reason_codes)


def test_ok_implies_all_required_present_and_gates_true() -> None:
    for state_a in ("PRESENT", "MISSING", "UNCERTAIN"):
        for state_b in ("PRESENT", "MISSING", "UNCERTAIN"):
            rule = make_rule()
            context = make_context(
                components={
                    "component_a": make_evidence("component_a", state_a),
                    "component_b": make_evidence("component_b", state_b),
                }
            )
            decision = ENGINE.evaluate(context, rule)
            if decision.business_result is BusinessResult.OK:
                assert state_a == "PRESENT"
                assert state_b == "PRESENT"


def test_adding_component_without_evidence_cannot_preserve_ok() -> None:
    rule = make_rule(
        required_components={
            "component_a": {"expected_count": 1},
            "component_b": {"expected_count": 1},
        }
    )
    context = make_context(
        components={
            "component_a": make_evidence("component_a", "PRESENT"),
            "component_b": make_evidence("component_b", "PRESENT"),
        }
    )
    assert ENGINE.evaluate(context, rule).business_result is BusinessResult.OK
    extended_rule = make_rule(
        required_components={
            "component_a": {"expected_count": 1},
            "component_b": {"expected_count": 1},
            "manual": {"expected_count": 1},
        }
    )
    decision = ENGINE.evaluate(context, extended_rule)
    assert decision.business_result is BusinessResult.NG
    assert "COMPONENT_UNVERIFIABLE:manual" in decision.reason_codes


def test_empty_required_components_rejected_at_validation() -> None:
    from pydantic import ValidationError

    with pytest.raises(ValidationError, match="at least one required component"):
        RuleDefinition.model_validate(
            {
                "schema_version": 1,
                "rule_id": "permissive",
                "rule_version": 1,
                "product_type": "model_a",
                "required_components": {},
            }
        )


def test_empty_rule_cannot_produce_ok_in_engine() -> None:
    rule = RuleDefinition.model_construct(
        schema_version=1,
        rule_id="permissive",
        rule_version=1,
        product_type="model_a",
        required_components={},
    )
    decision = ENGINE.evaluate(make_context(components={}), rule)
    assert decision.business_result is BusinessResult.NG
    assert "CONFIG_INVALID" in decision.reason_codes
