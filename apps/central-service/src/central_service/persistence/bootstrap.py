"""Idempotent pilot bootstrap for the central server (C1b).

Exactly one pilot organization, site, line, registered device, upload
credential, and administrator are created through an explicit bootstrap run
(CLI subcommand or Compose one-shot service) - never implicitly from an
upload request. Existing rows are reused by name/identity; an existing device
or administrator is never re-keyed. Credentials are always provided
explicitly by the operator through settings or CLI options: the bootstrap
never generates secrets, so no credential ever appears in process or
container logs.
"""

from __future__ import annotations

from dataclasses import dataclass

from central_service.api.settings import CentralSettings
from central_service.persistence.repository import CentralRepository, PilotBootstrapResult

MIN_TOKEN_LENGTH = 16

DEFAULT_ORGANIZATION_NAME = "Pilot Organization"
DEFAULT_SITE_NAME = "Pilot Site"
DEFAULT_LINE_NAME = "Line 1"
DEFAULT_DEVICE_ID = "edge-device-001"
DEFAULT_DEVICE_NAME = "Edge Device 1"
DEFAULT_ADMIN_USERNAME = "pilot-admin"


class BootstrapError(Exception):
    """Raised when the pilot bootstrap request is invalid or fails closed."""


@dataclass(frozen=True)
class BootstrapPlan:
    """Fully resolved bootstrap inputs (credentials always operator-provided)."""

    organization_name: str
    site_name: str
    line_name: str
    device_id: str
    device_name: str
    device_upload_token: str
    admin_username: str
    admin_token: str


@dataclass(frozen=True)
class BootstrapOutcome:
    """Bootstrap result; credentials are never returned or printed."""

    result: PilotBootstrapResult


def resolve_plan(
    settings: CentralSettings,
    *,
    organization_name: str | None = None,
    site_name: str | None = None,
    line_name: str | None = None,
    device_id: str | None = None,
    device_name: str | None = None,
    device_upload_token: str | None = None,
    admin_username: str | None = None,
    admin_token: str | None = None,
) -> BootstrapPlan:
    """Resolve bootstrap inputs from explicit options, settings, or defaults.

    Credentials must be supplied by the operator (CLI option or
    ``AV_CENTRAL_ADMIN_TOKEN`` / ``AV_CENTRAL_DEVICE_UPLOAD_TOKEN``); a
    missing credential fails closed rather than being generated and echoed to
    a log. Explicitly provided empty names/identifiers also fail closed.
    """
    for option_name, value in (
        ("organization_name", organization_name),
        ("site_name", site_name),
        ("line_name", line_name),
        ("device_id", device_id),
        ("device_name", device_name),
        ("admin_username", admin_username),
    ):
        if value is not None and not str(value).strip():
            raise BootstrapError(f"{option_name} must not be empty")

    resolved_device_token = device_upload_token or settings.device_upload_token
    if resolved_device_token is None:
        raise BootstrapError(
            "device upload token is required (AV_CENTRAL_DEVICE_UPLOAD_TOKEN or "
            "--device-upload-token)"
        )

    resolved_admin_token = admin_token or settings.admin_token
    if resolved_admin_token is None:
        raise BootstrapError(
            "administrator token is required (AV_CENTRAL_ADMIN_TOKEN or --admin-token)"
        )

    plan = BootstrapPlan(
        organization_name=organization_name or DEFAULT_ORGANIZATION_NAME,
        site_name=site_name or DEFAULT_SITE_NAME,
        line_name=line_name or DEFAULT_LINE_NAME,
        device_id=device_id or DEFAULT_DEVICE_ID,
        device_name=device_name or DEFAULT_DEVICE_NAME,
        device_upload_token=resolved_device_token,
        admin_username=admin_username or DEFAULT_ADMIN_USERNAME,
        admin_token=resolved_admin_token,
    )
    _validate_plan(plan)
    return plan


def run_bootstrap(repository: CentralRepository, plan: BootstrapPlan) -> BootstrapOutcome:
    """Apply ``plan`` idempotently; the audit event commits with the rows."""
    result = repository.bootstrap_pilot(
        organization_name=plan.organization_name,
        site_name=plan.site_name,
        line_name=plan.line_name,
        device_id=plan.device_id,
        device_name=plan.device_name,
        device_upload_token=plan.device_upload_token,
        admin_username=plan.admin_username,
        admin_token=plan.admin_token,
    )
    return BootstrapOutcome(result=result)


def _validate_plan(plan: BootstrapPlan) -> None:
    if len(plan.device_upload_token) < MIN_TOKEN_LENGTH:
        raise BootstrapError("device upload token must be at least 16 characters")
    if len(plan.admin_token) < MIN_TOKEN_LENGTH:
        raise BootstrapError("admin token must be at least 16 characters")
    if not plan.organization_name.strip():
        raise BootstrapError("organization name must not be empty")
    if not plan.site_name.strip():
        raise BootstrapError("site name must not be empty")
    if not plan.line_name.strip():
        raise BootstrapError("line name must not be empty")
    if not plan.device_id.strip():
        raise BootstrapError("device id must not be empty")
    if not plan.admin_username.strip():
        raise BootstrapError("admin username must not be empty")
