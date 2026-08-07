"""Inspection history and detail endpoints (design 15.3.2, 16.5)."""

from __future__ import annotations

from typing import Annotated

from assemblyvision_domain.models import InspectionRecord, MediaMetadata
from fastapi import APIRouter, Depends, Query

from assemblyvision_edge.api.deps import get_repository
from assemblyvision_edge.api.problems import ApiProblem
from assemblyvision_edge.api.schemas import InspectionSummary, Page, Problem
from assemblyvision_edge.persistence.repository import EdgeRepository

router = APIRouter(prefix="/inspections", tags=["inspections"])


@router.get("", response_model=Page[InspectionSummary])
def list_inspections(
    business_result: str | None = None,
    internal_decision: str | None = None,
    barcode: str | None = None,
    product: str | None = None,
    from_: Annotated[str | None, Query(alias="from")] = None,
    to: str | None = None,
    cursor: str | None = None,
    limit: int = 50,
    repository: EdgeRepository = Depends(get_repository),
) -> Page[InspectionSummary]:
    page = repository.list_inspections(
        business_result=business_result,
        internal_decision=internal_decision,
        barcode=barcode,
        product=product,
        from_iso=from_,
        to_iso=to,
        cursor=cursor,
        limit=limit,
    )
    return Page(
        items=[
            InspectionSummary(
                inspection_id=str(s.inspection_id),
                completed_at=s.completed_at,
                business_result=s.business_result,
                internal_decision=s.internal_decision,
                barcode=s.barcode,
                product_code=s.product_code,
                sn=s.sn,
                reason_summary=s.reason_summary,
                latency_ms=s.latency_ms,
                upload_state=s.upload_state,
                model_rule_versions=s.model_rule_versions,
            )
            for s in page.items
        ],
        next_cursor=page.next_cursor,
    )


@router.get(
    "/{inspection_id}",
    response_model=InspectionRecord,
    responses={404: {"model": Problem, "description": "Inspection not found"}},
)
def get_inspection(
    inspection_id: str,
    repository: EdgeRepository = Depends(get_repository),
) -> InspectionRecord:
    record = repository.get_inspection_full(inspection_id)
    if record is None:
        raise ApiProblem(
            status_code=404, code="INSPECTION_NOT_FOUND", detail=f"no inspection {inspection_id}"
        )
    return record


@router.get("/{inspection_id}/media", response_model=list[MediaMetadata])
def list_inspection_media(
    inspection_id: str,
    repository: EdgeRepository = Depends(get_repository),
) -> list[MediaMetadata]:
    if repository.get_inspection(inspection_id) is None:
        raise ApiProblem(
            status_code=404, code="INSPECTION_NOT_FOUND", detail=f"no inspection {inspection_id}"
        )
    return repository.list_inspection_media(inspection_id)
