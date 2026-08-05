"""Tests for the deterministic rule engine."""

from __future__ import annotations

from assemblyvision_domain.models import BusinessResult, InternalDecision
from assemblyvision_edge.rules.rule_engine import RuleEngine

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
