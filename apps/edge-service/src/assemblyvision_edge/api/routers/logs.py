"""Bounded structured log endpoint (design 15.3.3)."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from assemblyvision_edge.api.deps import get_log_buffer
from assemblyvision_edge.api.logging_buffer import LogBuffer
from assemblyvision_edge.api.schemas import LogEvent, Page

router = APIRouter(prefix="/logs", tags=["logs"])


@router.get("", response_model=Page[LogEvent])
def list_logs(
    limit: int = 100,
    buffer: LogBuffer = Depends(get_log_buffer),
) -> Page[LogEvent]:
    events = buffer.snapshot(limit)
    return Page(
        items=[
            LogEvent(
                logged_at=e.logged_at,
                level=e.level,
                component=e.component,
                message=e.message,
                trace_id=e.trace_id,
            )
            for e in events
        ],
        next_cursor=None,
    )
