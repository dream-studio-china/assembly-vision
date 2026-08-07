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
    ) -> None:
        super().__init__(detail)
        self.status_code = status_code
        self.code = code
        self.detail = detail
        self.title = title or code.replace("_", " ").title()
        self.errors = errors or []


def _request_id(request: Request) -> str:
    header = request.headers.get("X-Request-ID")
    return header if header else str(uuid4())


def install_problem_handlers(app: FastAPI) -> None:
    @app.exception_handler(ApiProblem)
    async def _api_problem(request: Request, exc: ApiProblem) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "type": f"https://assemblyvision.example/problems/{exc.code.lower()}",
                "title": exc.title,
                "status": exc.status_code,
                "detail": exc.detail,
                "code": exc.code,
                "request_id": _request_id(request),
                "errors": exc.errors,
            },
            media_type="application/problem+json",
        )

    @app.exception_handler(StarletteHTTPException)
    async def _http_problem(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        code = exc.headers.get("X-Problem-Code") if exc.headers else None
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "type": "https://assemblyvision.example/problems/http",
                "title": exc.detail,
                "status": exc.status_code,
                "detail": str(exc.detail),
                "code": code or f"HTTP_{exc.status_code}",
                "request_id": _request_id(request),
                "errors": [],
            },
            media_type="application/problem+json",
        )

    @app.exception_handler(RequestValidationError)
    async def _validation_problem(request: Request, exc: RequestValidationError) -> JSONResponse:
        errors = [
            {"field": ".".join(str(p) for p in err.get("loc", ())), "message": err.get("msg", "")}
            for err in exc.errors()
        ]
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            content={
                "type": "https://assemblyvision.example/problems/validation",
                "title": "Request validation failed",
                "status": status.HTTP_422_UNPROCESSABLE_ENTITY,
                "detail": "The request body or query parameters are invalid",
                "code": "VALIDATION_FAILED",
                "request_id": _request_id(request),
                "errors": errors,
            },
            media_type="application/problem+json",
        )
