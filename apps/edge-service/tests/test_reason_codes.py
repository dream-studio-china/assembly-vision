"""Reason-code glossary consistency test (AUDIT-001 section 6).

Design 11.5 and reason_codes.py must stay in sync: the static codes are the
enforceable set, and the parameterized prefixes are part of the documented
format.
"""

from __future__ import annotations

from assemblyvision_domain import reason_codes as rc

# The canonical static codes enumerated in design 11.5. Adding a new reason
# code requires updating this test, design 11.5, and the appendices glossary.
DOCUMENTED_CODES = {
    # identity
    "BARCODE_UNREADABLE",
    "PRODUCT_TYPE_UNKNOWN",
    "PRODUCT_MAPPING_AMBIGUOUS",
    "PRODUCT_IDENTITY_UNVERIFIED",
    # pipeline
    "CAMERA_DISCONNECTED",
    "NO_PRODUCT",
    "MULTIPLE_PRODUCTS",
    "ROI_INVALID",
    "INSUFFICIENT_VALID_FRAMES",
    "INFERENCE_ERROR",
    "IMAGE_READ_ERROR",
    "PRODUCT_IDENTITY_MISSING",
    "PRODUCT_IDENTITY_TRANSITION",
    "WINDOW_MAX_DURATION_EXCEEDED",
    "COMPONENT_POLICY_MISSING",
    # component
    "COMPONENT_MISSING",
    "COMPONENT_UNCERTAIN",
    "COMPONENT_UNVERIFIABLE",
    "COMPONENT_COUNT_INVALID",
    "COMPONENT_SPATIAL_INVALID",
    # configuration
    "RULE_NOT_FOUND",
    "CONFIG_INVALID",
    "VERSION_INCOMPATIBLE",
    # system
    "INSPECTION_INTERRUPTED",
    "DECISION_PERSISTENCE_FAILED",
    "RULE_EVALUATION_ERROR",
}


def test_reason_code_module_matches_documented_canonical_set() -> None:
    actual = {
        value
        for name, value in vars(rc).items()
        if name.isupper() and isinstance(value, str) and not name.startswith("_")
    }
    assert actual == DOCUMENTED_CODES


def test_parameterized_reason_prefixes() -> None:
    assert rc.gate_failed("product_detected") == "GATE_FAILED:product_detected"
    assert rc.component_reason("COMPONENT_MISSING", "chip") == "COMPONENT_MISSING:chip"
    assert rc.component_reason("COMPONENT_SPATIAL_INVALID", "chip") == (
        "COMPONENT_SPATIAL_INVALID:chip"
    )
