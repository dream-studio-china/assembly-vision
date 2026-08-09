"""WebSocket runtime event channel (design 15.5/15.6, E4a).

``WS /api/v1/ws/runtime`` streams ephemeral event envelopes to authenticated
dashboard connections. REST remains authoritative: the socket never carries
commands or durable state, a sequence gap always means events were lost and
the client must refetch REST, and the server disconnects slow consumers
instead of blocking event publishers (E4 task invariants 1-4).
"""

from __future__ import annotations

import asyncio
from datetime import datetime
from typing import cast

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from assemblyvision_edge.api.deps import _bearer_valid, _session_valid
from assemblyvision_edge.api.events import RuntimeEventBus, _Disconnect
from assemblyvision_edge.api.settings import ServerSettings

router = APIRouter(tags=["runtime-events"])


@router.websocket("/ws/runtime")
async def runtime_events(websocket: WebSocket) -> None:
    """Stream runtime event envelopes to one authenticated connection."""
    settings = cast(ServerSettings, websocket.app.state.settings)
    if not _ws_authenticated(websocket, settings):
        # 4401 is the standard WebSocket unauthorized close code; reject before
        # accepting so no event is ever sent to an unauthenticated socket.
        await websocket.close(code=4401)
        return
    await websocket.accept()
    bus = cast(RuntimeEventBus, websocket.app.state.event_bus)
    loop = asyncio.get_running_loop()
    queue = bus.subscribe(loop)
    try:
        while True:
            item = await queue.get()
            if isinstance(item, _Disconnect):
                # The consumer fell behind the bounded buffer; drop it rather
                # than blocking the publisher or growing memory (E4 invariant 2).
                await websocket.close(code=1008)
                return
            await websocket.send_json(item.to_dict())
    except WebSocketDisconnect:
        pass
    finally:
        bus.unsubscribe(queue)


def _ws_authenticated(websocket: WebSocket, settings: ServerSettings) -> bool:
    """Require the same viewer credential/session as the REST API (ADR-012)."""
    if not settings.api_token:
        return True
    sessions = cast(dict[str, datetime], websocket.app.state.viewer_sessions)
    return _bearer_valid(websocket.headers, settings) or _session_valid(websocket.cookies, sessions)
