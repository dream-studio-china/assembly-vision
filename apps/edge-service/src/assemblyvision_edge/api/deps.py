"""FastAPI dependency accessors for the edge API."""

from __future__ import annotations

from typing import Annotated, cast

from fastapi import Depends, Request

from assemblyvision_edge.api.logging_buffer import LogBuffer
from assemblyvision_edge.api.problems import ApiProblem
from assemblyvision_edge.api.settings import ServerSettings
from assemblyvision_edge.api.state import EdgeRuntime
from assemblyvision_edge.persistence.repository import EdgeRepository


def get_repository(request: Request) -> EdgeRepository:
    return cast(EdgeRepository, request.app.state.repository)


def get_runtime(request: Request) -> EdgeRuntime:
    return cast(EdgeRuntime, request.app.state.runtime)


def get_log_buffer(request: Request) -> LogBuffer:
    return cast(LogBuffer, request.app.state.log_buffer)


def get_settings(request: Request) -> ServerSettings:
    return cast(ServerSettings, request.app.state.settings)


def require_viewer(
    request: Request,
    settings: Annotated[ServerSettings, Depends(get_settings)],
) -> None:
    """Require the configured edge viewer credential on every route except
    ``/health/live`` (design 15.2.1). Loopback binding is not authentication.

    When ``settings.api_token`` is set, a matching ``Authorization: Bearer``
    header is mandatory. When it is not configured the service runs in the
    documented M1 development mode and the health snapshot reports that no
    credential is configured (ADR-012).
    """
    if not settings.api_token:
        return
    expected = f"Bearer {settings.api_token}"
    if request.headers.get("Authorization") != expected:
        raise ApiProblem(
            status_code=401,
            code="UNAUTHENTICATED",
            detail="a valid edge API token is required",
        )
