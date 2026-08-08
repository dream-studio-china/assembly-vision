"""Same-origin viewer-session bootstrap for the token-protected M1 dashboard."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request, Response

from assemblyvision_edge.api.deps import (
    create_viewer_session,
    get_settings,
    viewer_session_cookie_name,
    viewer_session_ttl_seconds,
)
from assemblyvision_edge.api.settings import ServerSettings

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/session", status_code=204)
def create_session(
    request: Request,
    response: Response,
    settings: ServerSettings = Depends(get_settings),
) -> None:
    """Exchange a configured bearer token for an HttpOnly same-origin session."""
    session_id = create_viewer_session(request, settings)
    if session_id is None:
        return
    response.set_cookie(
        key=viewer_session_cookie_name(),
        value=session_id,
        max_age=viewer_session_ttl_seconds(),
        httponly=True,
        samesite="strict",
        secure=request.url.scheme == "https",
        path="/",
    )
