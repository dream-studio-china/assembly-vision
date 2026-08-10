"""Health endpoints (C1a, design 05 section 10).

``/health/live`` is process liveness and never blocks on dependencies;
``/health/ready`` probes PostgreSQL schema state, object-store bucket access,
and pilot credential configuration, returning 503 with an RFC 7807 problem
while any dependency is unavailable.
"""

from __future__ import annotations

from fastapi import APIRouter, Request

from central_service.api.problems import ApiProblem
from central_service.api.readiness import ReadinessResult
from central_service.api.schemas import HealthLive, ReadinessReport

router = APIRouter(prefix="/health", tags=["health"])


@router.get("/live", response_model=HealthLive)
def health_live() -> HealthLive:
    """Process liveness only; never blocks on dependencies."""
    return HealthLive(status="ok")


@router.get("/ready", response_model=ReadinessReport)
def health_ready(request: Request) -> ReadinessReport:
    """Report readiness, failing closed when any dependency is unavailable."""
    result: ReadinessResult = request.app.state.readiness()
    if not result.ok:
        failing = ", ".join(check.name for check in result.checks if not check.ok)
        raise ApiProblem(
            status_code=503,
            code="NOT_READY",
            detail=f"required central dependencies are unavailable: {failing}",
        )
    return ReadinessReport(
        status="ok", checks={check.name: check.detail for check in result.checks}
    )
