"""FastAPI authentication dependencies for the central API (C1b).

Pilot administrators authenticate with their durable bearer credential or a
short-lived HttpOnly session cookie; registered devices authenticate with
their per-device upload token. The two credential kinds are stored and
verified separately and can never authorize each other's routes: the admin
dependency resolves only administrator rows/sessions, and the device
dependency resolves only active registered devices.
"""

from __future__ import annotations

from typing import Annotated, Any, cast

from fastapi import Depends, Request

from central_service.api.problems import ApiProblem
from central_service.api.settings import CentralSettings
from central_service.persistence.repository import (
    AdministratorRow,
    CentralRepository,
    DeviceRow,
)

SESSION_COOKIE_NAME = "av_central_admin_session"

# OpenAPI security requirement applied to every pilot-authenticated route.
# The scheme itself is registered on the schema in ``app.py`` so generated
# clients model the bearer/session authentication boundary.
SECURITY: list[dict[str, list[str]]] = [{"PilotBearer": []}]

# RFC 7807 problem responses the protected routes can actually return; the
# Problem schema is declared in ``schemas.py`` so it lands in the OpenAPI.
UNAUTHENTICATED_RESPONSES: dict[int | str, dict[str, Any]] = {
    401: {
        "description": "A valid pilot administrator credential or session is required",
        "content": {
            "application/problem+json": {"schema": {"$ref": "#/components/schemas/Problem"}}
        },
    }
}

NOT_FOUND_RESPONSES: dict[int | str, dict[str, Any]] = {
    404: {
        "description": "The requested resource does not exist in this organization",
        "content": {
            "application/problem+json": {"schema": {"$ref": "#/components/schemas/Problem"}}
        },
    }
}


def get_repository(request: Request) -> CentralRepository:
    return cast(CentralRepository, request.app.state.repository)


def get_settings(request: Request) -> CentralSettings:
    return cast(CentralSettings, request.app.state.settings)


def _bearer_token(request: Request) -> str | None:
    """Return the bearer token from ``Authorization``, or None."""
    header = request.headers.get("Authorization")
    if not header or not header.startswith("Bearer "):
        return None
    token = header[len("Bearer ") :].strip()
    return token if token else None


def _admin_bearer(request: Request, repository: CentralRepository) -> AdministratorRow | None:
    token = _bearer_token(request)
    if token is None:
        return None
    return repository.authenticate_administrator(token)


def _admin_session(request: Request, repository: CentralRepository) -> AdministratorRow | None:
    session_token = request.cookies.get(SESSION_COOKIE_NAME)
    if not session_token:
        return None
    return repository.resolve_admin_session(session_token)


def _require_admin(
    request: Request,
    repository: Annotated[CentralRepository, Depends(get_repository)],
) -> AdministratorRow:
    """Require a pilot administrator credential or session (bearer or cookie)."""
    administrator = _admin_bearer(request, repository) or _admin_session(request, repository)
    if administrator is None:
        raise ApiProblem(
            status_code=401,
            code="UNAUTHENTICATED",
            detail="a valid pilot administrator credential is required",
        )
    return administrator


def _require_device(
    request: Request,
    repository: Annotated[CentralRepository, Depends(get_repository)],
) -> DeviceRow:
    """Require a registered active device upload token (C2a ingest routes)."""
    token = _bearer_token(request)
    if token is None:
        raise ApiProblem(
            status_code=401,
            code="UNAUTHENTICATED",
            detail="a device upload credential is required",
        )
    device = repository.authenticate_device(token)
    if device is None:
        raise ApiProblem(
            status_code=401,
            code="UNAUTHENTICATED",
            detail="unknown or disabled device upload credential",
        )
    return device
