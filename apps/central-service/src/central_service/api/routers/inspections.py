"""Inspection history and detail routes (C3).

Organization-scoped read views over centrally ingested inspections with
bounded filters and keyset pagination. Every query is scoped server-side to
the authenticated administrator's organization; media items carry short-lived
authorized URLs instead of bucket credentials or raw object keys.
"""

from __future__ import annotations

import base64
import json
from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Query

from central_service.api.deps import (
    NOT_FOUND_RESPONSES,
    SECURITY,
    UNAUTHENTICATED_RESPONSES,
    _require_admin,
    get_repository,
)
from central_service.api.problems import ApiProblem
from central_service.api.schemas import (
    ComponentEvidenceOut,
    InspectionDetailOut,
    InspectionPage,
    InspectionSummaryOut,
    MediaItemOut,
)
from central_service.persistence.repository import (
    AdministratorRow,
    CentralRepository,
    InspectionDetailRow,
    InspectionFilter,
    InspectionSummaryRow,
)

router = APIRouter(prefix="/inspections", tags=["inspections"])

_MAX_PAGE_SIZE = 200
_DEFAULT_PAGE_SIZE = 50
_MAX_BARCODE_LEN = 128
_MAX_TEXT_LEN = 128


def _parse_cursor(cursor: str, filter_: InspectionFilter) -> tuple[datetime, int] | None:
    """Decode a keyset cursor bound to the current filter fingerprint.

    Returns ``(completed_at, id)`` of the last row, or None for an invalid or
    mismatched cursor (caller turns it into 400 INVALID_CURSOR).
    """
    try:
        raw = base64.urlsafe_b64decode(cursor.encode("ascii"))
        data = json.loads(raw)
    except (ValueError, UnicodeDecodeError):
        return None
    if not isinstance(data, dict):
        return None
    if data.get("f") != filter_.fingerprint():
        return None
    completed_at = data.get("c")
    row_id = data.get("i")
    if not isinstance(completed_at, str) or not isinstance(row_id, int):
        return None
    try:
        parsed = datetime.fromisoformat(completed_at)
    except ValueError:
        return None
    return parsed, row_id


def _encode_cursor(filter_: InspectionFilter, last: InspectionSummaryRow) -> str:
    payload = json.dumps(
        {"f": filter_.fingerprint(), "c": last.completed_at.isoformat(), "i": last.id},
        separators=(",", ":"),
    )
    return base64.urlsafe_b64encode(payload.encode("utf-8")).decode("ascii")


def _filter_from_query(
    site_id: int | None = None,
    line_id: int | None = None,
    device_row_id: int | None = None,
    from_at: datetime | None = None,
    to_at: datetime | None = None,
    barcode: str | None = None,
    product: str | None = None,
    business_result: Literal["OK", "NG"] | None = None,
    internal_decision: Literal["OK", "NG", "UNCERTAIN"] | None = None,
    reason: str | None = None,
    model_version: str | None = None,
    rule_version: str | None = None,
) -> InspectionFilter:
    """Build the bounded C3 filter from validated query parameters."""
    if barcode is not None and len(barcode) > _MAX_BARCODE_LEN:
        raise ApiProblem(
            status_code=400,
            code="INVALID_FILTER",
            detail="barcode filter exceeds the maximum length",
        )
    if product is not None and len(product) > _MAX_TEXT_LEN:
        raise ApiProblem(
            status_code=400,
            code="INVALID_FILTER",
            detail="product filter exceeds the maximum length",
        )
    if reason is not None and len(reason) > _MAX_TEXT_LEN:
        raise ApiProblem(
            status_code=400,
            code="INVALID_FILTER",
            detail="reason filter exceeds the maximum length",
        )
    for label, value in (("model_version", model_version), ("rule_version", rule_version)):
        if value is not None:
            try:
                UUID(value)
            except ValueError as exc:
                raise ApiProblem(
                    status_code=400,
                    code="INVALID_FILTER",
                    detail=f"{label} must be a valid UUID",
                ) from exc
    return InspectionFilter(
        site_id=site_id,
        line_id=line_id,
        device_row_id=device_row_id,
        from_at=from_at,
        to_at=to_at,
        barcode=barcode,
        product_code=product,
        business_result=business_result,
        internal_decision=internal_decision,
        reason_code=reason,
        model_version_id=model_version,
        rule_version_id=rule_version,
    )


@router.get(
    "",
    response_model=InspectionPage,
    openapi_extra={"security": SECURITY},
    responses=UNAUTHENTICATED_RESPONSES,
)
def list_inspections(
    repository: CentralRepository = Depends(get_repository),
    administrator: AdministratorRow = Depends(_require_admin),
    site_id: int | None = None,
    line_id: int | None = None,
    device_row_id: int | None = None,
    from_at: datetime | None = None,
    to_at: datetime | None = None,
    barcode: str | None = None,
    product: str | None = None,
    business_result: Literal["OK", "NG"] | None = None,
    internal_decision: Literal["OK", "NG", "UNCERTAIN"] | None = None,
    reason: str | None = None,
    model_version: str | None = None,
    rule_version: str | None = None,
    cursor: str | None = None,
    limit: Annotated[int, Query(ge=1, le=_MAX_PAGE_SIZE)] = _DEFAULT_PAGE_SIZE,
) -> InspectionPage:
    """Cross-device inspection history with bounded filters (C3)."""
    filter_ = _filter_from_query(
        site_id=site_id,
        line_id=line_id,
        device_row_id=device_row_id,
        from_at=from_at,
        to_at=to_at,
        barcode=barcode,
        product=product,
        business_result=business_result,
        internal_decision=internal_decision,
        reason=reason,
        model_version=model_version,
        rule_version=rule_version,
    )
    after_completed_at: datetime | None = None
    after_id: int | None = None
    if cursor is not None:
        decoded = _parse_cursor(cursor, filter_)
        if decoded is None:
            raise ApiProblem(
                status_code=400,
                code="INVALID_CURSOR",
                detail="the cursor is invalid or does not match the filters",
            )
        after_completed_at, after_id = decoded
    items, has_more = repository.list_inspections(
        administrator.organization_id,
        filter_,
        after_completed_at=after_completed_at,
        after_id=after_id,
        limit=limit,
    )
    next_cursor = _encode_cursor(filter_, items[-1]) if has_more and items else None
    return InspectionPage(
        items=[_summary_out(item) for item in items],
        next_cursor=next_cursor,
    )


@router.get(
    "/{inspection_id}",
    response_model=InspectionDetailOut,
    openapi_extra={"security": SECURITY},
    responses={**UNAUTHENTICATED_RESPONSES, **NOT_FOUND_RESPONSES},
)
def get_inspection(
    inspection_id: str,
    repository: CentralRepository = Depends(get_repository),
    administrator: AdministratorRow = Depends(_require_admin),
) -> InspectionDetailOut:
    """Inspection detail with evidence, versions, and media (C3)."""
    try:
        UUID(inspection_id)
    except ValueError as exc:
        raise ApiProblem(
            status_code=404,
            code="INSPECTION_NOT_FOUND",
            detail="the inspection does not exist in this organization",
        ) from exc
    detail = repository.get_inspection_detail(administrator.organization_id, inspection_id)
    if detail is None:
        raise ApiProblem(
            status_code=404,
            code="INSPECTION_NOT_FOUND",
            detail="the inspection does not exist in this organization",
        )
    summary = detail.summary
    return InspectionDetailOut(
        inspection_id=summary.inspection_id,
        device_id=summary.device_id,
        site_id=summary.site_id,
        line_id=summary.production_line_id,
        device_sequence=summary.device_sequence,
        lifecycle_status=summary.lifecycle_status,
        started_at=summary.started_at,
        completed_at=summary.completed_at,
        received_at=summary.received_at,
        upload_delay_ms=summary.upload_delay_ms,
        barcode_status=summary.barcode_status,
        barcode_value=summary.barcode_value,
        product_resolution_status=summary.product_resolution_status,
        product_code=summary.product_code,
        internal_decision=summary.internal_decision,
        business_result=summary.business_result,
        reason_codes=detail.reason_codes,
        missing_components=detail.missing_components,
        low_confidence_components=detail.low_confidence_components,
        application_version=detail.application_version,
        product_model_version_id=detail.product_model_version_id,
        product_model_checksum_sha256=detail.product_model_checksum_sha256,
        component_model_version_id=detail.component_model_version_id,
        component_model_checksum_sha256=detail.component_model_checksum_sha256,
        rule_version_id=summary.rule_version_id,
        aggregation_policy_version=detail.aggregation_policy_version,
        processing_ms=detail.processing_ms,
        inference_metadata=detail.inference_metadata,
        components=[
            ComponentEvidenceOut(
                component_code=component.component_code,
                state=component.state,
                best_confidence=component.best_confidence,
                detection_count=component.detection_count,
                usable_frame_count=component.usable_frame_count,
                policy_reason_codes=component.policy_reason_codes,
            )
            for component in detail.components
        ],
        media=_media_out(detail),
        receipt_status=detail.receipt_status,
        receipt_created_at=detail.receipt_created_at,
    )


def _media_out(detail: InspectionDetailRow) -> list[MediaItemOut]:
    """Media bindings with authorized streaming URLs (C3).

    URLs point at the authenticated media route; AVAILABLE objects are
    streamed through the API, other lifecycle states expose no URL.
    """
    return [
        MediaItemOut(
            source_media_id=binding.source_media_id,
            kind=binding.media_kind,
            mime_type=binding.mime_type,
            size_bytes=binding.size_bytes,
            lifecycle=binding.lifecycle,
            url=(
                f"/api/v1/media/{binding.central_object_id}"
                if binding.lifecycle == "AVAILABLE"
                else None
            ),
        )
        for binding in detail.media
    ]


def _summary_out(item: InspectionSummaryRow) -> InspectionSummaryOut:
    return InspectionSummaryOut(
        inspection_id=item.inspection_id,
        device_id=item.device_id,
        site_id=item.site_id,
        line_id=item.production_line_id,
        device_sequence=item.device_sequence,
        started_at=item.started_at,
        completed_at=item.completed_at,
        received_at=item.received_at,
        upload_delay_ms=item.upload_delay_ms,
        barcode_value=item.barcode_value,
        product_code=item.product_code,
        internal_decision=item.internal_decision,
        business_result=item.business_result,
        rule_version_id=item.rule_version_id,
    )
    return InspectionSummaryOut(
        inspection_id=item.inspection_id,
        device_id=item.device_id,
        site_id=item.site_id,
        line_id=item.production_line_id,
        device_sequence=item.device_sequence,
        started_at=item.started_at,
        completed_at=item.completed_at,
        received_at=item.received_at,
        upload_delay_ms=item.upload_delay_ms,
        barcode_value=item.barcode_value,
        product_code=item.product_code,
        internal_decision=item.internal_decision,
        business_result=item.business_result,
        rule_version_id=item.rule_version_id,
    )
