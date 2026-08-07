"""FastAPI dependency accessors for the edge API."""

from __future__ import annotations

from typing import Any, cast

from fastapi import Request

from assemblyvision_edge.api.logging_buffer import LogBuffer
from assemblyvision_edge.api.state import EdgeRuntime
from assemblyvision_edge.persistence.repository import EdgeRepository


def get_repository(request: Request) -> EdgeRepository:
    return cast(EdgeRepository, request.app.state.repository)


def get_runtime(request: Request) -> EdgeRuntime:
    return cast(EdgeRuntime, request.app.state.runtime)


def get_log_buffer(request: Request) -> LogBuffer:
    return cast(LogBuffer, request.app.state.log_buffer)


def get_settings(request: Request) -> Any:
    return request.app.state.settings
