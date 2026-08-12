"""Dashboard summary and timeseries routes (C3, design 17).

Explicit scope/time filters with sample counts; empty data stays empty and no
accuracy or recall metric is invented. Every query is scoped server-side to
the authenticated administrator's organization.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends

from central_service.api.deps import (
    SECURITY,
    UNAUTHENTICATED_RESPONSES,
    _require_admin,
    get_repository,
)
from central_service.api.routers.inspections import _filter_from_query
from central_service.api.schemas import (
    DashboardSummaryOut,
    DashboardTimeseriesOut,
    DeviceStatusOut,
    TimeseriesPointOut,
)
from central_service.persistence.repository import AdministratorRow, CentralRepository

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


@router.get(
    "/summary",
    response_model=DashboardSummaryOut,
    openapi_extra={"security": SECURITY},
    responses=UNAUTHENTICATED_RESPONSES,
)
def dashboard_summary(
    repository: CentralRepository = Depends(get_repository),
    administrator: AdministratorRow = Depends(_require_admin),
    site_id: int | None = None,
    line_id: int | None = None,
    device_row_id: int | None = None,
    from_at: datetime | None = None,
    to_at: datetime | None = None,
    business_result: Literal["OK", "NG"] | None = None,
) -> DashboardSummaryOut:
    """Overview counts for the selected scope/period (C3)."""
    filter_ = _filter_from_query(
        site_id=site_id,
        line_id=line_id,
        device_row_id=device_row_id,
        from_at=from_at,
        to_at=to_at,
        business_result=business_result,
    )
    summary = repository.dashboard_summary(administrator.organization_id, filter_)
    return DashboardSummaryOut(
        inspection_count=summary.inspection_count,
        ok_count=summary.ok_count,
        ng_count=summary.ng_count,
        uncertain_count=summary.uncertain_count,
        avg_upload_delay_ms=summary.avg_upload_delay_ms,
    )


@router.get(
    "/timeseries",
    response_model=DashboardTimeseriesOut,
    openapi_extra={"security": SECURITY},
    responses=UNAUTHENTICATED_RESPONSES,
)
def dashboard_timeseries(
    repository: CentralRepository = Depends(get_repository),
    administrator: AdministratorRow = Depends(_require_admin),
    site_id: int | None = None,
    line_id: int | None = None,
    device_row_id: int | None = None,
    from_at: datetime | None = None,
    to_at: datetime | None = None,
    business_result: Literal["OK", "NG"] | None = None,
) -> DashboardTimeseriesOut:
    """Daily outcome counts for the selected scope/period (C3)."""
    filter_ = _filter_from_query(
        site_id=site_id,
        line_id=line_id,
        device_row_id=device_row_id,
        from_at=from_at,
        to_at=to_at,
        business_result=business_result,
    )
    points = repository.dashboard_timeseries(administrator.organization_id, filter_)
    return DashboardTimeseriesOut(
        points=[
            TimeseriesPointOut(
                bucket=point.bucket,
                ok_count=point.ok_count,
                ng_count=point.ng_count,
                uncertain_count=point.uncertain_count,
            )
            for point in points
        ]
    )


@router.get(
    "/devices",
    response_model=list[DeviceStatusOut],
    openapi_extra={"security": SECURITY},
    responses=UNAUTHENTICATED_RESPONSES,
)
def dashboard_devices(
    repository: CentralRepository = Depends(get_repository),
    administrator: AdministratorRow = Depends(_require_admin),
) -> list[DeviceStatusOut]:
    """Per-device last-seen and volume for the overview (C3, design 17)."""
    return [
        DeviceStatusOut(
            device_id=row.device_id,
            name=row.name,
            last_seen_at=row.last_seen_at,
            inspection_count=row.inspection_count,
        )
        for row in repository.device_last_seen(administrator.organization_id)
    ]
