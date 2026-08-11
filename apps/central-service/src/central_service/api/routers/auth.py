"""Pilot administrator authentication routes (C1b).

``POST /api/v1/auth/session`` exchanges a durable administrator bearer
credential for a short-lived HttpOnly same-origin session cookie so the
admin-web browser never stores the long-lived token. ``GET /api/v1/auth/me``
returns the authenticated administrator and works with either the bearer
credential or the session cookie. The session cookie is marked Secure from
deployment configuration (``AV_CENTRAL_SECURE_COOKIES``), never from the
request scheme, because TLS is terminated outside the API process.
"""

from __future__ import annotations

from datetime import timedelta

from fastapi import APIRouter, Depends, Request, Response

from central_service.api.deps import (
    SECURITY,
    SESSION_COOKIE_NAME,
    UNAUTHENTICATED_RESPONSES,
    _admin_bearer,
    _require_admin,
    get_repository,
    get_settings,
)
from central_service.api.problems import ApiProblem
from central_service.api.schemas import AdminMe
from central_service.api.settings import CentralSettings
from central_service.persistence.repository import AdministratorRow, CentralRepository

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post(
    "/session",
    status_code=204,
    openapi_extra={"security": SECURITY},
    responses=UNAUTHENTICATED_RESPONSES,
)
def create_admin_session(
    request: Request,
    response: Response,
    repository: CentralRepository = Depends(get_repository),
    settings: CentralSettings = Depends(get_settings),
) -> None:
    """Exchange a pilot administrator bearer credential for a session cookie."""
    administrator = _admin_bearer(request, repository)
    if administrator is None:
        raise ApiProblem(
            status_code=401,
            code="UNAUTHENTICATED",
            detail="a valid pilot administrator credential is required",
        )
    ttl = timedelta(minutes=settings.admin_session_ttl_minutes)
    session_token = repository.create_admin_session(
        administrator.id, administrator.organization_id, ttl
    )
    response.set_cookie(
        key=SESSION_COOKIE_NAME,
        value=session_token,
        max_age=int(ttl.total_seconds()),
        httponly=True,
        samesite="strict",
        secure=settings.secure_cookies,
        path="/",
    )


@router.get(
    "/me",
    response_model=AdminMe,
    openapi_extra={"security": SECURITY},
    responses=UNAUTHENTICATED_RESPONSES,
)
def get_me(
    administrator: AdministratorRow = Depends(_require_admin),
) -> AdminMe:
    """Return the authenticated pilot administrator identity."""
    return AdminMe(
        administrator_id=administrator.id,
        organization_id=administrator.organization_id,
        username=administrator.username,
    )
