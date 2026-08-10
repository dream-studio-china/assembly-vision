"""Deterministic barcode evidence resolution for the edge pipeline."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from assemblyvision_domain import reason_codes as rc
from assemblyvision_domain.models import BarcodeResult, ProductResolution

from assemblyvision_edge.barcode.models import BarcodeObservation, BarcodeSource
from assemblyvision_edge.config import BarcodeIdentityConfig


@dataclass(frozen=True, slots=True)
class ResolvedBarcodeIdentity:
    """Barcode/domain identity evidence ready for pipeline and rule evaluation."""

    barcode_result: BarcodeResult
    product_resolution: ProductResolution
    verified: bool
    reason_codes: tuple[str, ...]


def resolve_barcode_identity(
    observations: tuple[BarcodeObservation, ...],
    config: BarcodeIdentityConfig,
    active_product_type: str,
) -> ResolvedBarcodeIdentity:
    """Resolve exact mapped identity; all ambiguous or incompatible evidence fails closed."""
    reads = [observation for observation in observations if observation.text is not None]
    if not reads:
        return _unverified("NOT_READ", "UNKNOWN", rc.BARCODE_UNREADABLE)
    if (
        any(observation.is_ambiguous for observation in reads)
        or len({read.text for read in reads}) != 1
    ):
        return _unverified("CONFLICT", "CONFLICT", rc.PRODUCT_MAPPING_AMBIGUOUS)
    if (
        any(read.source is BarcodeSource.ZXING_CPP for read in reads)
        and config.allowed_symbologies
        and any(
            read.source is BarcodeSource.ZXING_CPP
            and read.symbology not in config.allowed_symbologies
            for read in reads
        )
    ):
        return _unverified("NOT_READ", "UNKNOWN", rc.BARCODE_UNREADABLE)
    read = reads[0]
    barcode_value = read.text
    if barcode_value is None:
        return _unverified("NOT_READ", "UNKNOWN", rc.BARCODE_UNREADABLE)
    product_code = config.mappings.get(barcode_value)
    if product_code is None or product_code != active_product_type:
        return _unverified(
            "READ",
            "UNKNOWN",
            rc.PRODUCT_TYPE_UNKNOWN,
            value=barcode_value,
            symbology=read.symbology,
        )
    return ResolvedBarcodeIdentity(
        barcode_result=BarcodeResult(status="READ", value=barcode_value, symbology=read.symbology),
        product_resolution=ProductResolution(
            status="RESOLVED", source="BARCODE", product_code=product_code
        ),
        verified=True,
        reason_codes=(),
    )


def _unverified(
    barcode_status: Literal["READ", "NOT_READ", "CONFLICT", "NOT_REQUIRED"],
    resolution_status: Literal["RESOLVED", "UNKNOWN", "CONFLICT"],
    reason: str,
    *,
    value: str | None = None,
    symbology: str | None = None,
) -> ResolvedBarcodeIdentity:
    return ResolvedBarcodeIdentity(
        barcode_result=BarcodeResult(status=barcode_status, value=value, symbology=symbology),
        product_resolution=ProductResolution(
            status=resolution_status, source="NONE", product_code=None
        ),
        verified=False,
        reason_codes=(reason,),
    )
