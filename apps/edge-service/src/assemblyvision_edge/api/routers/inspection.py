"""Inspection runtime state endpoint (design 15.3.1, M1 read-only)."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from assemblyvision_edge.api.deps import get_repository, get_runtime
from assemblyvision_edge.api.schemas import InspectionRuntimeState
from assemblyvision_edge.api.state import EdgeRuntime
from assemblyvision_edge.persistence.repository import EdgeRepository

router = APIRouter(prefix="/inspection", tags=["inspection"])


@router.get("/state", response_model=InspectionRuntimeState)
def inspection_state(
    runtime: EdgeRuntime = Depends(get_runtime),
    repository: EdgeRepository = Depends(get_repository),
) -> InspectionRuntimeState:
    return InspectionRuntimeState.model_validate(
        runtime.inspection_state(repository.latest_business_result())
    )
