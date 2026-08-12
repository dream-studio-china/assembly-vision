"""Typed ingestion failure that maps to an RFC 7807 problem response.

Never carries credentials, object keys, internal paths, SQL, or stack traces
(contract 08, C1 invariant 10).
"""

from __future__ import annotations


class IngestError(Exception):
    """A rejected upload envelope or payload with its problem-response shape."""

    def __init__(
        self,
        *,
        status_code: int,
        code: str,
        detail: str,
        headers: dict[str, str] | None = None,
        errors: list[dict[str, str]] | None = None,
    ) -> None:
        super().__init__(detail)
        self.status_code = status_code
        self.code = code
        self.detail = detail
        self.headers = headers or {}
        self.errors = errors or []
