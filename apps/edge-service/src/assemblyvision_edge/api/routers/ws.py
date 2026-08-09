"""WebSocket runtime event channel (design 15.5/15.6, E4a).

``WS /api/v1/ws/runtime`` streams ephemeral event envelopes to authenticated
dashboard connections. REST remains authoritative: the socket never carries
commands or durable state, a sequence gap always means events were lost and
the client must refetch REST, and the server disconnects slow consumers
instead of blocking event publishers (E4 task invariants 1-4).

Authentication (PR-023 F01): same-origin browsers use the HttpOnly viewer
session cookie and non-browser clients may use the bearer token. Browser
WebSocket cannot set an ``Authorization`` header and cross-origin connections
do not receive the same-origin cookie, so the dashboard exchanges its viewer
credential for a short-lived, single-use ticket over REST
(``POST /api/v1/ws/runtime/ticket``) and sends it as the negotiated
``Sec-WebSocket-Protocol`` value, never in the URL.
"""

from __future__ import annotations

import asyncio
import secrets
from datetime import UTC, datetime, timedelta
from typing import Any, cast

from fastapi import APIRouter, Depends, Request, WebSocket, WebSocketDisconnect
from pydantic import BaseModel

from assemblyvision_edge.api.deps import _bearer_valid, _session_valid, require_viewer
from assemblyvision_edge.api.events import RuntimeEventBus, RuntimeEventStats, _Disconnect
from assemblyvision_edge.api.settings import ServerSettings

router = APIRouter(tags=["runtime-events"])

_TICKET_TTL = timedelta(seconds=30)
_TICKET_MAX = 1000


class WsTicket(BaseModel):
    """One-time credential for one browser WebSocket connection (PR-023 F01)."""

    ticket: str
    expires_at: str
    channel: str = "runtime"


@router.get(
    "/ws/runtime/stats",
    dependencies=[Depends(require_viewer)],
    response_model=RuntimeEventStats,
)
def runtime_event_stats(request: Request) -> RuntimeEventStats:
    """Return authenticated runtime event channel observability (PR-023 F05).

    Lets an operator distinguish an idle dashboard from a failed event feed.
    Counters are process-local and never expose credentials or payloads.
    """
    bus = cast(RuntimeEventBus, request.app.state.event_bus)
    return bus.stats()


@router.post("/ws/runtime/ticket", dependencies=[Depends(require_viewer)])
def create_runtime_ticket(request: Request) -> WsTicket:
    """Issue a short-lived, single-use ticket for the runtime channel.

    The ticket is consumed atomically during socket acceptance, expires
    quickly, and is scoped to this channel only; the long-lived viewer
    credential is never placed in a URL or in browser storage.
    """
    now = datetime.now(UTC)
    tickets = cast(dict[str, datetime], request.app.state.ws_tickets)
    for expired in [key for key, expires in tickets.items() if expires <= now]:
        del tickets[expired]
    if len(tickets) >= _TICKET_MAX:
        oldest = min(tickets, key=lambda key: tickets[key])
        del tickets[oldest]
    ticket = secrets.token_urlsafe(32)
    expires_at = now + _TICKET_TTL
    tickets[ticket] = expires_at
    return WsTicket(ticket=ticket, expires_at=expires_at.isoformat())


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
    """Require the viewer credential/session or a one-time ticket (ADR-012)."""
    if not settings.api_token:
        return True
    sessions = cast(dict[str, datetime], websocket.app.state.viewer_sessions)
    if _bearer_valid(websocket.headers, settings) or _session_valid(websocket.cookies, sessions):
        return True
    return _consume_ticket(websocket)


def _consume_ticket(websocket: WebSocket) -> bool:
    """Validate and atomically consume one runtime ticket from the handshake.

    ``dict.pop`` is atomic under the GIL, so a ticket is single-use even when
    two sockets present it concurrently (PR-023 F01).
    """
    tickets = cast(dict[str, datetime], websocket.app.state.ws_tickets)
    ticket = _extract_ticket(websocket.headers)
    if not ticket:
        return False
    expires_at = tickets.pop(ticket, None)
    if expires_at is None:
        return False
    return expires_at > datetime.now(UTC)


def _extract_ticket(headers: Any) -> str | None:
    """Return the ticket sent as the sole negotiated subprotocol."""
    raw = headers.get("sec-websocket-protocol")
    if not raw:
        return None
    # The dashboard sends exactly one protocol value: the ticket itself.
    return str(raw).split(",")[0].strip() or None
