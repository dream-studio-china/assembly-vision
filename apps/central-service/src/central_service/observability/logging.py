"""Structured logging setup and request correlation for the central server.

Every log record emitted while a request is in flight carries the same
``request_id`` (bound by the HTTP middleware through a context variable, C6)
so device, inspection, media, receipt, and audit correlation can be traced
across the request log and the ``audit_logs.request_id`` column. Business
identifiers on individual records keep the correlation complete.
"""

from __future__ import annotations

import contextvars
import logging

_FORMAT = "%(asctime)s %(levelname)-5.5s [%(name)s] %(message)s%(request_id)s"

# Per-request correlation id; the middleware sets it for the duration of the
# request and the log filter appends it to every record.
_request_id: contextvars.ContextVar[str] = contextvars.ContextVar("central_request_id", default="")


def set_request_id(request_id: str) -> None:
    """Bind the correlation id for the current request (C6)."""
    _request_id.set(request_id)


def clear_request_id() -> None:
    """Unbind the correlation id at the end of a request."""
    _request_id.set("")


def get_request_id() -> str:
    """The correlation id bound to the current request, or empty (C6)."""
    return _request_id.get()


class _RequestIdFilter(logging.Filter):
    """Append the bound request id to a record, when one is set."""

    def filter(self, record: logging.LogRecord) -> bool:
        request_id = _request_id.get()
        record.request_id = f" request_id={request_id}" if request_id else ""
        return True


def configure_logging(level: int = logging.INFO) -> None:
    """Configure root logging with a consistent, correlation-aware format."""
    root = logging.getLogger()
    if root.handlers:
        return
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter(_FORMAT))
    handler.addFilter(_RequestIdFilter())
    root.addHandler(handler)
    root.setLevel(level)
