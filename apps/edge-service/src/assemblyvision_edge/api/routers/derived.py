"""Derived read endpoints used by the operator dashboard (M1).

Traceability, statistics, and image references are computed from the local
inspection index so the dashboard shows real data without the mock workflow
client.
"""

from __future__ import annotations

from typing import Annotated

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
    from_: Annotated[str | None, Query(alias="from")] = None,
    to: str | None = None,
    line: str | None = None,
    repository: EdgeRepository = Depends(get_repository),
) -> StatisticsSummary:
    if line is not None:
        raise ApiProblem(
            status_code=400,
            code="UNSUPPORTED_FILTER",
            detail="line filtering is not supported until line identity exists",
        )
    counts = repository.statistics(from_iso=from_, to_iso=to)
    total = counts["total"]
    ng = counts["ng"]
    pass_count = total - ng
    return StatisticsSummary(
        total_inspections=total,
        pass_count=pass_count,
        ng_count=ng,
        pass_rate=pass_count / total if total else 0.0,
    )


@router.get("/inspections/{inspection_id}/images", response_model=InspectionImages)
def inspection_images(
    inspection_id: str,
    request: Request,
    repository: EdgeRepository = Depends(get_repository),
) -> InspectionImages:
    media = repository.list_inspection_media(inspection_id)
    if not media:
        return InspectionImages(
            inspection_id=inspection_id, original="", detection="", annotated=""
        )
    by_kind: dict[str, str] = {
        m.kind: f"{request.base_url}api/v1/media/{m.media_id}/content" for m in media
    }
    annotated = by_kind.get("ANNOTATED_FRAME")
    return InspectionImages(
        inspection_id=inspection_id,
        original=by_kind.get("KEY_FRAME", ""),
        detection=annotated or by_kind.get("PRODUCT_ROI", ""),
        annotated=by_kind.get("PRODUCT_ROI", annotated or ""),
    )
