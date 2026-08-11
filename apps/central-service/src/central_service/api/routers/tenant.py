"""Pilot administration tenant routes (C1b).

Organization-scoped read views over sites, production lines, and registered
devices. Every query is scoped server-side to the authenticated
administrator's organization; device upload credentials are never exposed.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from central_service.api.deps import (
    NOT_FOUND_RESPONSES,
    SECURITY,
    UNAUTHENTICATED_RESPONSES,
    _require_admin,
    get_repository,
)
from central_service.api.problems import ApiProblem
from central_service.api.schemas import DeviceOut, LineOut, SiteOut
from central_service.persistence.repository import AdministratorRow, CentralRepository

router = APIRouter(tags=["tenant"])


@router.get(
    "/sites",
    response_model=list[SiteOut],
    openapi_extra={"security": SECURITY},
    responses=UNAUTHENTICATED_RESPONSES,
)
def list_sites(
    repository: CentralRepository = Depends(get_repository),
    administrator: AdministratorRow = Depends(_require_admin),
) -> list[SiteOut]:
    return [
        SiteOut(
            id=site.id,
            organization_id=site.organization_id,
            name=site.name,
            created_at=site.created_at,
        )
        for site in repository.list_sites(administrator.organization_id)
    ]


@router.get(
    "/lines",
    response_model=list[LineOut],
    openapi_extra={"security": SECURITY},
    responses=UNAUTHENTICATED_RESPONSES,
)
def list_lines(
    site_id: int | None = None,
    repository: CentralRepository = Depends(get_repository),
    administrator: AdministratorRow = Depends(_require_admin),
) -> list[LineOut]:
    return [
        LineOut(
            id=line.id,
            site_id=line.site_id,
            organization_id=line.organization_id,
            name=line.name,
            created_at=line.created_at,
        )
        for line in repository.list_lines(administrator.organization_id, site_id)
    ]


@router.get(
    "/devices",
    response_model=list[DeviceOut],
    openapi_extra={"security": SECURITY},
    responses=UNAUTHENTICATED_RESPONSES,
)
def list_devices(
    repository: CentralRepository = Depends(get_repository),
    administrator: AdministratorRow = Depends(_require_admin),
) -> list[DeviceOut]:
    return [
        DeviceOut(
            id=device.id,
            organization_id=device.organization_id,
            site_id=device.site_id,
            production_line_id=device.production_line_id,
            device_id=device.device_id,
            name=device.name,
            status=device.status,
            created_at=device.created_at,
        )
        for device in repository.list_devices(administrator.organization_id)
    ]


@router.get(
    "/devices/{device_row_id}",
    response_model=DeviceOut,
    openapi_extra={"security": SECURITY},
    responses={**UNAUTHENTICATED_RESPONSES, **NOT_FOUND_RESPONSES},
)
def get_device(
    device_row_id: int,
    repository: CentralRepository = Depends(get_repository),
    administrator: AdministratorRow = Depends(_require_admin),
) -> DeviceOut:
    device = repository.get_device(administrator.organization_id, device_row_id)
    if device is None:
        raise ApiProblem(
            status_code=404,
            code="DEVICE_NOT_FOUND",
            detail="the device does not exist in this organization",
        )
    return DeviceOut(
        id=device.id,
        organization_id=device.organization_id,
        site_id=device.site_id,
        production_line_id=device.production_line_id,
        device_id=device.device_id,
        name=device.name,
        status=device.status,
        created_at=device.created_at,
    )
