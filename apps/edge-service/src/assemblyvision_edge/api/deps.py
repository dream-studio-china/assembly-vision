"""FastAPI dependency accessors for the edge API."""

from __future__ import annotations

import secrets
from datetime import UTC, datetime, timedelta
from typing import Annotated, cast

from fastapi import Depends, Request

from assemblyvision_edge.api.logging_buffer import LogBuffer
from assemblyvision_edge.api.problems import ApiProblem
from assemblyvision_edge.api.settings import ServerSettings
from assemblyvision_edge.api.state import EdgeRuntime
from assemblyvision_edge.persistence.repository import EdgeRepository

_SESSION_COOKIE = "av_edge_viewer_session"
_SESSION_TTL = timedelta(hours=8)


def get_repository(request: Request) -> EdgeRepository:
    return cast(EdgeRepository, request.app.state.repository)


def get_runtime(request: Request) -> EdgeRuntime:
    return cast(EdgeRuntime, request.app.state.runtime)


def get_log_buffer(request: Request) -> LogBuffer:
    return cast(LogBuffer, request.app.state.log_buffer)


def get_settings(request: Request) -> ServerSettings:
    return cast(ServerSettings, request.app.state.settings)


def _has_valid_bearer_token(request: Request, settings: ServerSettings) -> bool:
    if not settings.api_token:
        return True
    return secrets.compare_digest(
        request.headers.get("Authorization", ""), f"Bearer {settings.api_token}"
    )


def _has_valid_session(request: Request) -> bool:
    session_id = request.cookies.get(_SESSION_COOKIE)
    if not session_id:
        return False
    sessions = cast(dict[str, datetime], request.app.state.viewer_sessions)
    expires_at = sessions.get(session_id)
    if expires_at is None:
        return False
    if expires_at <= datetime.now(UTC):
        del sessions[session_id]
        return False
    return True


def create_viewer_session(request: Request, settings: ServerSettings) -> str | None:
    """Create a short-lived same-origin session after bearer authentication."""
    if not settings.api_token:
        return None
    if not _has_valid_bearer_token(request, settings):
        raise ApiProblem(
            status_code=401,
            code="UNAUTHENTICATED",
            detail="a valid edge API token is required",
        )
    session_id = secrets.token_urlsafe(32)
    sessions = cast(dict[str, datetime], request.app.state.viewer_sessions)
    sessions[session_id] = datetime.now(UTC) + _SESSION_TTL
    return session_id


def viewer_session_cookie_name() -> str:
    return _SESSION_COOKIE


def viewer_session_ttl_seconds() -> int:
    return int(_SESSION_TTL.total_seconds())


def require_viewer(
    request: Request,
    settings: Annotated[ServerSettings, Depends(get_settings)],
) -> None:
    """Require the configured edge viewer credential on every route except
    ``/health/live`` (design 15.2.1). Loopback binding is not authentication.

    When ``settings.api_token`` is set, a matching ``Authorization: Bearer``
    header or a short-lived same-origin viewer session is mandatory. When it is
    not configured the service runs in the documented M1 development mode.
    """
    if not settings.api_token:
        return
    if not _has_valid_bearer_token(request, settings) and not _has_valid_session(request):
        raise ApiProblem(
            status_code=401,
            code="UNAUTHENTICATED",
            detail="a valid edge API token is required",
        )
