"""Derived read endpoints used by the operator dashboard (M1).

Traceability, statistics, and image references are computed from the local
inspection index so the dashboard shows real data without the mock workflow
client.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request

from assemblyvision_edge.api.deps import get_repository
from assemblyvision_edge.api.problems import ApiProblem
from assemblyvision_edge.persistence.repository import EdgeRepository

router = APIRouter(tags=["derived"])


@router.get("/traceability/{sn}")
def traceability(
    sn: str,
    repository: EdgeRepository = Depends(get_repository),
) -> dict[str, object]:
    records = repository.list_by_barcode(sn)
    if not records:
        raise ApiProblem(status_code=404, code="SN_NOT_FOUND", detail=f"no traceability for {sn}")
    attempts = []
    for index, record in enumerate(records, start=1):
        result = "PASS" if record.decision.business_result.value == "OK" else "NG"
        attempts.append(
            {
                "attempt": index,
                "inspection_id": str(record.inspection_id),
                "timestamp": record.completed_at.isoformat(),
                "result": result,
                "reason": ",".join(record.decision.reason_codes) or "-",
                "operator": "-",
            }
        )
    final_status = "PASS" if records[-1].decision.business_result.value == "OK" else "NG"
    return {"sn": sn, "final_status": final_status, "attempts": attempts}


@router.get("/statistics")
def statistics(
    from_: str | None = None,
    to: str | None = None,
    line: str | None = None,
    repository: EdgeRepository = Depends(get_repository),
) -> dict[str, object]:
    counts = repository.statistics(from_iso=from_, to_iso=to)
    total = counts["total"]
    ng = counts["ng"]
    pass_count = total - ng
    return {
        "total_inspections": total,
        "pass_count": pass_count,
        "ng_count": ng,
        "pass_rate": pass_count / total if total else 0.0,
    }


@router.get("/inspections/{inspection_id}/images")
def inspection_images(
    inspection_id: str,
    request: Request,
    repository: EdgeRepository = Depends(get_repository),
) -> dict[str, object]:
    media = repository.list_inspection_media(inspection_id)
    if not media:
        return {"inspection_id": inspection_id, "original": "", "detection": "", "annotated": ""}
    by_kind: dict[str, str] = {
        m.kind: f"{request.base_url}api/v1/media/{m.media_id}/content" for m in media
    }
    annotated = by_kind.get("ANNOTATED_FRAME")
    return {
        "inspection_id": inspection_id,
        "original": by_kind.get("KEY_FRAME", ""),
        "detection": annotated or by_kind.get("PRODUCT_ROI", ""),
        "annotated": by_kind.get("PRODUCT_ROI", annotated or ""),
    }
