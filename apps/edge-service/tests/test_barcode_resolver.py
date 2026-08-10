"""Focused barcode identity resolution tests."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from assemblyvision_domain import reason_codes as rc
from assemblyvision_edge.barcode import BarcodeObservation, BarcodeSource, resolve_barcode_identity
from assemblyvision_edge.config import BarcodeIdentityConfig


def _config() -> BarcodeIdentityConfig:
    return BarcodeIdentityConfig(
        enabled=True,
        required=True,
        allowed_symbologies=("QRCode", "Code128"),
        mapping_file=Path("barcodes.yaml"),
        mappings={"ABC": "model_a"},
    )


def _read(value: str, symbology: str = "QRCode") -> BarcodeObservation:
    return BarcodeObservation(value, symbology, BarcodeSource.ZXING_CPP, datetime.now(UTC))


def test_exact_mapped_barcode_verifies_active_product() -> None:
    resolved = resolve_barcode_identity((_read("ABC"),), _config(), "model_a")

    assert resolved.verified is True
    assert resolved.barcode_result.status == "READ"
    assert resolved.product_resolution.product_code == "model_a"


def test_conflicting_or_unknown_barcode_fails_closed() -> None:
    conflict = resolve_barcode_identity((_read("ABC"), _read("OTHER")), _config(), "model_a")
    unknown = resolve_barcode_identity((_read("NOPE"),), _config(), "model_a")

    assert conflict.verified is False
    assert conflict.reason_codes == (rc.PRODUCT_MAPPING_AMBIGUOUS,)
    assert unknown.verified is False
    assert unknown.reason_codes == (rc.PRODUCT_TYPE_UNKNOWN,)


def test_mapped_product_must_match_active_rule_and_visual_symbology_must_be_allowed() -> None:
    mismatch = resolve_barcode_identity((_read("ABC"),), _config(), "model_b")
    unsupported = resolve_barcode_identity((_read("ABC", "DataMatrix"),), _config(), "model_a")

    assert mismatch.verified is False
    assert mismatch.reason_codes == (rc.PRODUCT_TYPE_UNKNOWN,)
    assert unsupported.verified is False
    assert unsupported.reason_codes == (rc.BARCODE_UNREADABLE,)


def test_all_visual_reads_must_use_an_allowed_symbology() -> None:
    resolved = resolve_barcode_identity(
        (_read("ABC", "QRCode"), _read("ABC", "DataMatrix")), _config(), "model_a"
    )

    assert resolved.verified is False
    assert resolved.reason_codes == (rc.BARCODE_UNREADABLE,)
