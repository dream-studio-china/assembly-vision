"""application/problem+json error helpers (contract 05 section 6)."""

from __future__ import annotations

from uuid import uuid4

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException


class ApiProblem(Exception):
    """An exception that maps directly to an RFC 7807 problem response."""

    def __init__(
        self,
        *,
        status_code: int,
        code: str,
        detail: str,
        title: str | None = None,
        errors: list[dict[str, str]] | None = None,
        headers: dict[str, str] | None = None,
    ) -> None:
        super().__init__(detail)
        self.status_code = status_code
        self.code = code
        self.detail = detail
        self.title = title or code.replace("_", " ").title()
        self.errors = errors or []
        self.headers = headers or {}


def _request_id(request: Request) -> str:
    header = request.headers.get("X-Request-ID")
    return header if header else str(uuid4())


def _problem_response(
    request: Request,
    *,
    status_code: int,
    title: str,
    detail: str,
    code: str,
    errors: list[dict[str, str]] | None = None,
    headers: dict[str, str] | None = None,
) -> JSONResponse:
    request_id = _request_id(request)
    return JSONResponse(
        status_code=status_code,
        content={
            "type": f"https://assemblyvision.example/problems/{code.lower()}",
            "title": title,
            "status": status_code,
            "detail": detail,
            "code": code,
            "request_id": request_id,
            "errors": errors or [],
        },
        media_type="application/problem+json",
        headers={"X-Request-ID": request_id, **(headers or {})},
    )


def install_problem_handlers(app: FastAPI) -> None:
    @app.exception_handler(ApiProblem)
    async def _api_problem(request: Request, exc: ApiProblem) -> JSONResponse:
        return _problem_response(
            request,
            status_code=exc.status_code,
            title=exc.title,
            detail=exc.detail,
            code=exc.code,
            errors=exc.errors,
            headers=exc.headers,
        )

    @app.exception_handler(StarletteHTTPException)
    async def _http_problem(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        code = exc.headers.get("X-Problem-Code") if exc.headers else None
        return _problem_response(
            request,
            status_code=exc.status_code,
            title=str(exc.detail),
            detail=str(exc.detail),
            code=code or f"HTTP_{exc.status_code}",
        )

    @app.exception_handler(RequestValidationError)
    async def _validation_problem(request: Request, exc: RequestValidationError) -> JSONResponse:
        errors = [
            {"field": ".".join(str(p) for p in err.get("loc", ())), "message": err.get("msg", "")}
            for err in exc.errors()
        ]
        return _problem_response(
            request,
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            title="Request validation failed",
            detail="The request body or query parameters are invalid",
            code="VALIDATION_FAILED",
            errors=errors,
        )
