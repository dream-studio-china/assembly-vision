"""Inspection runtime state and control endpoints (design 15.3.1)."""

from __future__ import annotations

from uuid import uuid4

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from assemblyvision_edge.api.deps import get_repository, get_runtime
from assemblyvision_edge.api.problems import ApiProblem
from assemblyvision_edge.api.state import EdgeRuntime
from assemblyvision_edge.persistence.repository import EdgeRepository

router = APIRouter(prefix="/inspection", tags=["inspection"])


class PauseRequest(BaseModel):
    reason: str = Field(min_length=1)


class ResumeRequest(BaseModel):
    reason: str = Field(min_length=1)


def _control_envelope(
    runtime: EdgeRuntime,
    repository: EdgeRepository,
    operation_id: str,
    detail: str | None,
) -> dict[str, object]:
    return {
        "accepted": True,
        "operation_id": operation_id,
        "detail": detail,
        "state": runtime.inspection_state(repository.latest_business_result()),
    }


@router.get("/state")
def inspection_state(
    runtime: EdgeRuntime = Depends(get_runtime),
    repository: EdgeRepository = Depends(get_repository),
) -> dict[str, object]:
    return runtime.inspection_state(repository.latest_business_result())


@router.post("/pause")
def pause_inspection(
    body: PauseRequest,
    runtime: EdgeRuntime = Depends(get_runtime),
    repository: EdgeRepository = Depends(get_repository),
) -> dict[str, object]:
    if runtime.paused:
        raise ApiProblem(
            status_code=409, code="ALREADY_PAUSED", detail="inspection is already paused"
        )
    runtime.pause(body.reason)
    return _control_envelope(runtime, repository, str(uuid4()), body.reason)


@router.post("/resume")
def resume_inspection(
    body: ResumeRequest,
    runtime: EdgeRuntime = Depends(get_runtime),
    repository: EdgeRepository = Depends(get_repository),
) -> dict[str, object]:
    if not runtime.paused:
        raise ApiProblem(
            status_code=409,
            code="PRECONDITION_FAILED",
            detail="inspection is not paused",
        )
    if runtime.pipeline is None:
        raise ApiProblem(
            status_code=409,
            code="PRECONDITION_FAILED",
            detail="inspection engine is not ready",
        )
    runtime.resume()
    return _control_envelope(runtime, repository, str(uuid4()), body.reason)
