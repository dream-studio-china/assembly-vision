"""Typed response schemas for the central API (contract 05)."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from assemblyvision_domain.models import APIModel


class HealthLive(APIModel):
    """Liveness response; never blocks on dependencies."""

    status: Literal["ok"]


class Problem(APIModel):
    """RFC 7807 error body (contract 05 section 6).

    ``request_id`` correlates the response with the request log; ``errors``
    carries bounded per-field validation details. Credentials, object keys,
    internal paths, SQL, and stack traces are never included.
    """

    type: str
    title: str
    status: int
    detail: str
    code: str
    request_id: str
    errors: list[dict[str, str]]


class ReadinessReport(APIModel):
    """Readiness response naming each checked dependency.

    ``checks`` maps dependency names to ``"ok"`` only; failure details are
    returned through the RFC 7807 problem body of the 503 response.
    """

    status: Literal["ok"]
    checks: dict[str, str]


class AdminMe(APIModel):
    """The authenticated pilot administrator (``GET /api/v1/auth/me``)."""

    administrator_id: int
    organization_id: int
    username: str


class SiteOut(APIModel):
    """A production site within the administrator's organization."""

    id: int
    organization_id: int
    name: str
    created_at: datetime


class LineOut(APIModel):
    """A production line within the administrator's organization."""

    id: int
    site_id: int
    organization_id: int
    name: str
    created_at: datetime


class DeviceOut(APIModel):
    """A registered edge device; credentials are never exposed."""

    id: int
    organization_id: int
    site_id: int
    production_line_id: int
    device_id: str
    name: str
    status: str
    created_at: datetime


class UploadReceiptOut(APIModel):
    """Verified central receipt for one accepted edge upload (task C1 5.3).

    Every field is echoed from the request so the edge scheduler can validate
    the receipt against the payload it actually sent; a MEDIA receipt always
    carries a non-empty ``central_object_id`` (C2b), which is null for
    INSPECTION receipts.
    """

    idempotency_key: str
    object_id: str
    kind: Literal["INSPECTION", "MEDIA"]
    checksum_sha256: str | None
    size_bytes: int
    central_object_id: str | None = None
