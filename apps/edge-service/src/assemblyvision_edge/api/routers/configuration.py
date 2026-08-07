"""Effective configuration endpoint (design 15.3.3)."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from assemblyvision_edge.api.deps import get_runtime
from assemblyvision_edge.api.state import EdgeRuntime

router = APIRouter(prefix="/configuration", tags=["configuration"])


@router.get("/effective")
def effective_configuration(
    runtime: EdgeRuntime = Depends(get_runtime),
) -> dict[str, object]:
    return runtime.effective_configuration()
