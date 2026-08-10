"""Typed response schemas for the central API (contract 05)."""

from __future__ import annotations

from typing import Literal

from assemblyvision_domain.models import APIModel


class HealthLive(APIModel):
    """Liveness response; never blocks on dependencies."""

    status: Literal["ok"]


class ReadinessReport(APIModel):
    """Readiness response naming each checked dependency.

    ``checks`` maps dependency names to ``"ok"`` only; failure details are
    returned through the RFC 7807 problem body of the 503 response.
    """

    status: Literal["ok"]
    checks: dict[str, str]
