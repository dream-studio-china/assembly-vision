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
_SESSION_MAX = 500
_AUTH_MAX_FAILURES = 5
_AUTH_LOCKOUT_WINDOW = timedelta(minutes=1)


def get_repository(request: Request) -> EdgeRepository:
    return cast(EdgeRepository, request.app.state.repository)


def get_runtime(request: Request) -> EdgeRuntime:
    return cast(EdgeRuntime, request.app.state.runtime)


def get_log_buffer(request: Request) -> LogBuffer:
    return cast(LogBuffer, request.app.state.log_buffer)


def get_settings(request: Request) -> ServerSettings:
    return cast(ServerSettings, request.app.state.settings)


def _client_ip(request: Request) -> str:
    return request.client.host if request.client is not None else "unknown"


def _has_valid_bearer_token(request: Request, settings: ServerSettings) -> bool:
    if not settings.api_token:
        return True
    try:
        return secrets.compare_digest(
            request.headers.get("Authorization", ""), f"Bearer {settings.api_token}"
        )
    except TypeError:
        # Non-ASCII header values are never valid credentials; treat them as
        # an authentication failure instead of a 500.
        return False


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


def _is_rate_limited(request: Request) -> bool:
    """Return True when the client exceeded the failed-attempt budget.

    Failed attempts are recorded per client address and expire after the
    lockout window, so a brute-force loop is throttled while a client that
    stops failing recovers (AUDIT-001 4.5).
    """
    failures = cast(dict[str, list[datetime]], request.app.state.auth_failures)
    now = datetime.now(UTC)
    recent = [ts for ts in failures.get(_client_ip(request), []) if now - ts < _AUTH_LOCKOUT_WINDOW]
    failures[_client_ip(request)] = recent
    return len(recent) >= _AUTH_MAX_FAILURES


def _record_auth_failure(request: Request) -> None:
    failures = cast(dict[str, list[datetime]], request.app.state.auth_failures)
    bucket = failures.setdefault(_client_ip(request), [])
    bucket.append(datetime.now(UTC))
    # Keep only the failures inside the lockout window plus one, so the map
    # cannot grow without bound.
    del bucket[: max(0, len(bucket) - (_AUTH_MAX_FAILURES + 1))]


def _clear_auth_failures(request: Request) -> None:
    failures = cast(dict[str, list[datetime]], request.app.state.auth_failures)
    failures.pop(_client_ip(request), None)


def create_viewer_session(request: Request, settings: ServerSettings) -> str | None:
    """Create a short-lived same-origin session after bearer authentication."""
    if not settings.api_token:
        return None
    if not _has_valid_bearer_token(request, settings):
        _record_auth_failure(request)
        raise _auth_error(request)
    _clear_auth_failures(request)
    session_id = secrets.token_urlsafe(32)
    sessions = cast(dict[str, datetime], request.app.state.viewer_sessions)
    now = datetime.now(UTC)
    for expired in [sid for sid, expires in sessions.items() if expires <= now]:
        del sessions[expired]
    if len(sessions) >= _SESSION_MAX:
        oldest = min(sessions, key=lambda sid: sessions[sid])
        del sessions[oldest]
    sessions[session_id] = now + _SESSION_TTL
    return session_id


def viewer_session_cookie_name() -> str:
    return _SESSION_COOKIE


def viewer_session_ttl_seconds() -> int:
    return int(_SESSION_TTL.total_seconds())


def _auth_error(request: Request) -> ApiProblem:
    """Return 401 for a bad credential, or 429 once the failure budget is spent."""
    if _is_rate_limited(request):
        return ApiProblem(
            status_code=429,
            code="RATE_LIMITED",
            detail="too many failed authentication attempts; try again later",
        )
    return ApiProblem(
        status_code=401,
        code="UNAUTHENTICATED",
        detail="a valid edge API token is required",
    )


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
    if _has_valid_bearer_token(request, settings) or _has_valid_session(request):
        _clear_auth_failures(request)
        return
    _record_auth_failure(request)
    raise _auth_error(request)
