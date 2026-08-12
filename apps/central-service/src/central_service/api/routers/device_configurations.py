"""Desired configuration routes (C5, M1): one device at a time.

M1 records desire only: there is no remote download, validation, or
activation endpoint, and the record never changes edge behavior. Assignments
replace the previous desired state under an If-Match revision guard and write
an immutable audit event. The API and UI must never present assignment as
proof of download, validation, or activation.
"""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Header, Request

from central_service.api.deps import (
    NOT_FOUND_RESPONSES,
    SECURITY,
    UNAUTHENTICATED_RESPONSES,
    _require_admin,
    get_repository,
)
from central_service.api.problems import ApiProblem
from central_service.api.routers.metadata import (
    _desired_configuration_out,
    _metadata_problem,
)
from central_service.api.schemas import (
    DesiredConfigurationIn,
    DesiredConfigurationOut,
    DesiredConfigurationPage,
)
from central_service.persistence.repository import (
    AdministratorRow,
    CentralRepository,
    DesiredConfigurationNotFoundError,
    DeviceNotFoundError,
)

router = APIRouter(tags=["device-configurations"])


@router.get(
    "/device-configurations",
    response_model=DesiredConfigurationPage,
    openapi_extra={"security": SECURITY},
    responses=UNAUTHENTICATED_RESPONSES,
)
def list_desired_configurations(
    repository: CentralRepository = Depends(get_repository),
    administrator: AdministratorRow = Depends(_require_admin),
) -> DesiredConfigurationPage:
    """All current desired bundles in the organization (C5, read view)."""
    return DesiredConfigurationPage(
        items=[
            _desired_configuration_out(row)
            for row in repository.list_desired_configurations(administrator.organization_id)
        ]
    )


@router.get(
    "/devices/{device_id}/desired-configuration",
    response_model=DesiredConfigurationOut,
    openapi_extra={"security": SECURITY},
    responses={
        **UNAUTHENTICATED_RESPONSES,
        **NOT_FOUND_RESPONSES,
    },
)
def get_desired_configuration(
    device_id: str,
    repository: CentralRepository = Depends(get_repository),
    administrator: AdministratorRow = Depends(_require_admin),
) -> DesiredConfigurationOut:
    """The current desired bundle for one device (C5)."""
    device = repository.get_device_by_identity(administrator.organization_id, device_id)
    if device is None:
        raise ApiProblem(
            status_code=404,
            code="DEVICE_NOT_FOUND",
            detail="the device does not exist in this organization",
        )
    row = repository.get_desired_configuration(administrator.organization_id, device.id)
    if row is None:
        raise ApiProblem(
            status_code=404,
            code="DESIRED_CONFIGURATION_NOT_FOUND",
            detail="this device has no desired configuration assignment",
        )
    return _desired_configuration_out(row)


@router.put(
    "/devices/{device_id}/desired-configuration",
    response_model=DesiredConfigurationOut,
    status_code=200,
    openapi_extra={"security": SECURITY},
    responses={
        **UNAUTHENTICATED_RESPONSES,
        **NOT_FOUND_RESPONSES,
        409: {
            "description": "An incompatible version bundle",
            "content": {
                "application/problem+json": {"schema": {"$ref": "#/components/schemas/Problem"}}
            },
        },
        412: {
            "description": "The If-Match revision is stale",
            "content": {
                "application/problem+json": {"schema": {"$ref": "#/components/schemas/Problem"}}
            },
        },
    },
)
def put_desired_configuration(
    device_id: str,
    body: DesiredConfigurationIn,
    request: Request,
    repository: CentralRepository = Depends(get_repository),
    administrator: AdministratorRow = Depends(_require_admin),
    if_match: str | None = Header(default=None, alias="If-Match"),
) -> DesiredConfigurationOut:
    """Record the desired bundle for one device (M1, C5).

    ``If-Match`` carries the current revision (``0`` for the first
    assignment); a stale revision returns ``412 REVISION_MISMATCH``. The
    record is desired state only and never changes edge behavior.
    """
    device = repository.get_device_by_identity(administrator.organization_id, device_id)
    if device is None:
        raise ApiProblem(
            status_code=404,
            code="DEVICE_NOT_FOUND",
            detail="the device does not exist in this organization",
        )
    if if_match is None or not if_match.strip():
        raise ApiProblem(
            status_code=422,
            code="IF_MATCH_REQUIRED",
            detail="an If-Match revision header is required (0 for the first assignment)",
        )
    try:
        if_match_revision = int(if_match)
    except ValueError as exc:
        raise ApiProblem(
            status_code=422,
            code="IF_MATCH_INVALID",
            detail="If-Match must be an integer revision",
        ) from exc
    try:
        row = repository.set_desired_configuration(
            organization_id=administrator.organization_id,
            device_row_id=device.id,
            if_match_revision=if_match_revision,
            product_version_id=body.product_version_id,
            product_model_version_id=body.product_model_version_id,
            component_model_version_id=body.component_model_version_id,
            rule_version_id=body.rule_version_id,
            reason=body.reason,
            assigned_by=administrator.username,
            assigned_at=datetime.now(UTC),
            actor=administrator.username,
            request_id=request.state.request_id,
        )
    except DeviceNotFoundError as exc:
        raise ApiProblem(
            status_code=404,
            code="DEVICE_NOT_FOUND",
            detail="the device does not exist in this organization",
        ) from exc
    except DesiredConfigurationNotFoundError as exc:
        raise ApiProblem(
            status_code=404,
            code="DESIRED_CONFIGURATION_NOT_FOUND",
            detail="this device has no desired configuration assignment",
        ) from exc
    except Exception as exc:  # noqa: BLE001 - mapped to a problem response below
        raise _metadata_problem(exc) from exc
    return _desired_configuration_out(row)
