"""Derived read endpoints used by the operator dashboard (M1).

Traceability, statistics, and image references are computed from the local
inspection index so the dashboard shows real data without the mock workflow
client.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated, Literal

from assemblyvision_domain.models import MediaMetadata
from fastapi import APIRouter, Depends, Query, Request

from assemblyvision_edge.api.deps import get_repository
from assemblyvision_edge.api.problems import ApiProblem
from assemblyvision_edge.api.schemas import (
    InspectionImages,
    StatisticsSummary,
    TraceabilityAttempt,
    TraceabilityView,
)
from assemblyvision_edge.persistence.repository import EdgeRepository

router = APIRouter(tags=["derived"])


@router.get("/traceability/{sn}", response_model=TraceabilityView)
def traceability(
    sn: str,
    repository: EdgeRepository = Depends(get_repository),
) -> TraceabilityView:
    records = repository.list_by_barcode(sn)
    if not records:
        raise ApiProblem(status_code=404, code="SN_NOT_FOUND", detail=f"no traceability for {sn}")
    attempts = []
    for index, record in enumerate(records, start=1):
        result = "PASS" if record.decision.business_result.value == "OK" else "NG"
        attempts.append(
            TraceabilityAttempt(
                attempt=index,
                inspection_id=str(record.inspection_id),
                timestamp=record.completed_at.isoformat(),
                result=result,
                reason=",".join(record.decision.reason_codes) or "-",
                operator="-",
            )
        )
    final_status = "PASS" if records[-1].decision.business_result.value == "OK" else "NG"
    return TraceabilityView(sn=sn, final_status=final_status, attempts=attempts)


@router.get("/statistics", response_model=StatisticsSummary)
def statistics(
    from_: Annotated[datetime | None, Query(alias="from")] = None,
    to: Annotated[datetime | None, Query()] = None,
    line: str | None = None,
    repository: EdgeRepository = Depends(get_repository),
) -> StatisticsSummary:
    if line is not None:
        raise ApiProblem(
            status_code=400,
            code="UNSUPPORTED_FILTER",
            detail="line filtering is not supported until line identity exists",
        )
    if from_ is not None and from_.tzinfo is None:
        raise ApiProblem(
            status_code=400,
            code="INVALID_FILTER",
            detail="'from' must be a timezone-aware UTC timestamp",
        )
    if to is not None and to.tzinfo is None:
        raise ApiProblem(
            status_code=400,
            code="INVALID_FILTER",
            detail="'to' must be a timezone-aware UTC timestamp",
        )
    from_iso = from_.astimezone(UTC).isoformat() if from_ is not None else None
    to_iso = to.astimezone(UTC).isoformat() if to is not None else None
    if from_iso is not None and to_iso is not None and from_iso > to_iso:
        raise ApiProblem(
            status_code=400,
            code="INVALID_RANGE",
            detail="'from' must not be after 'to'",
        )
    counts = repository.statistics(from_iso=from_iso, to_iso=to_iso)
    total = counts["total"]
    ng = counts["ng"]
    pass_count = total - ng
    return StatisticsSummary(
        total_inspections=total,
        pass_count=pass_count,
        ng_count=ng,
        pass_rate=pass_count / total if total else 0.0,
    )


def _image_slot(
    media_by_kind: dict[str, MediaMetadata], kind: str, base_url: str
) -> tuple[str, Literal["AVAILABLE", "PURGED", "UNAVAILABLE"]]:
    """Return (content URL, slot status) for one image kind (F14).

    Purged media never produces a content URL: the endpoint would otherwise
    hand the UI a link that returns 410 and renders as a broken image.
    """
    item = media_by_kind.get(kind)
    if item is None:
        return "", "UNAVAILABLE"
    if item.lifecycle.value == "AVAILABLE":
        return f"{base_url}{item.media_id}/content", "AVAILABLE"
    if item.lifecycle.value == "PURGED":
        return "", "PURGED"
    return "", "UNAVAILABLE"


@router.get("/inspections/{inspection_id}/images", response_model=InspectionImages)
def inspection_images(
    inspection_id: str,
    request: Request,
    repository: EdgeRepository = Depends(get_repository),
) -> InspectionImages:
    media = repository.list_inspection_media(inspection_id)
    by_kind: dict[str, MediaMetadata] = {m.kind: m for m in media}
    base = f"{request.base_url}api/v1/media/"
    original, original_status = _image_slot(by_kind, "KEY_FRAME", base)
    detection, detection_status = _image_slot(by_kind, "PRODUCT_ROI", base)
    annotated, annotated_status = _image_slot(by_kind, "ANNOTATED_FRAME", base)
    return InspectionImages(
        inspection_id=inspection_id,
        original=original,
        detection=detection,
        annotated=annotated,
        original_status=original_status,
        detection_status=detection_status,
        annotated_status=annotated_status,
    )
