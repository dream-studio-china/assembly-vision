"""Derived read endpoints used by the operator dashboard (M1).

Traceability, statistics, image references, and the confidence-drift analysis
(design 15.3.6) are computed from the local inspection index so the dashboard
shows real data without the mock workflow client.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Annotated, Literal

from assemblyvision_domain.models import MediaMetadata
from fastapi import APIRouter, Depends, Query, Request

from assemblyvision_edge.api.deps import get_repository
from assemblyvision_edge.api.problems import ApiProblem
from assemblyvision_edge.api.schemas import (
    ComponentConfidenceDrift,
    ConfidenceComparison,
    ConfidenceDriftReport,
    ConfidenceDriftScope,
    ConfidencePeriod,
    DriftAssessment,
    InspectionImages,
    StatisticsSummary,
    TraceabilityAttempt,
    TraceabilityView,
)
from assemblyvision_edge.persistence.repository import (
    ComponentConfidenceDelta,
    ConfidencePeriodStats,
    EdgeRepository,
)

router = APIRouter(tags=["derived"])


@router.get("/traceability/{sn}", response_model=TraceabilityView)
def traceability(
    sn: str,
    repository: EdgeRepository = Depends(get_repository),
) -> TraceabilityView:
    records = repository.list_by_barcode(sn)
    if not records:
        raise ApiProblem(status_code=404, code="SN_NOT_FOUND", detail=f"no traceability for {sn}")
    attempts = []
    for index, record in enumerate(records, start=1):
        result = "PASS" if record.decision.business_result.value == "OK" else "NG"
        attempts.append(
            TraceabilityAttempt(
                attempt=index,
                inspection_id=str(record.inspection_id),
                timestamp=record.completed_at.isoformat(),
                result=result,
                reason=",".join(record.decision.reason_codes) or "-",
                operator="-",
            )
        )
    final_status = "PASS" if records[-1].decision.business_result.value == "OK" else "NG"
    return TraceabilityView(sn=sn, final_status=final_status, attempts=attempts)


@router.get("/statistics", response_model=StatisticsSummary)
def statistics(
    from_: Annotated[datetime | None, Query(alias="from")] = None,
    to: Annotated[datetime | None, Query()] = None,
    line: str | None = None,
    repository: EdgeRepository = Depends(get_repository),
) -> StatisticsSummary:
    if line is not None:
        raise ApiProblem(
            status_code=400,
            code="UNSUPPORTED_FILTER",
            detail="line filtering is not supported until line identity exists",
        )
    if from_ is not None and from_.tzinfo is None:
        raise ApiProblem(
            status_code=400,
            code="INVALID_FILTER",
            detail="'from' must be a timezone-aware UTC timestamp",
        )
    if to is not None and to.tzinfo is None:
        raise ApiProblem(
            status_code=400,
            code="INVALID_FILTER",
            detail="'to' must be a timezone-aware UTC timestamp",
        )
    from_iso = from_.astimezone(UTC).isoformat() if from_ is not None else None
    to_iso = to.astimezone(UTC).isoformat() if to is not None else None
    if from_iso is not None and to_iso is not None and from_iso > to_iso:
        raise ApiProblem(
            status_code=400,
            code="INVALID_RANGE",
            detail="'from' must not be after 'to'",
        )
    counts = repository.statistics(from_iso=from_iso, to_iso=to_iso)
    total = counts["total"]
    ng = counts["ng"]
    pass_count = total - ng
    return StatisticsSummary(
        total_inspections=total,
        pass_count=pass_count,
        ng_count=ng,
        pass_rate=pass_count / total if total else 0.0,
    )


def _local_day_bounds(now: datetime, tz_offset_minutes: int) -> tuple[datetime, datetime, datetime]:
    """Return (previous_7d_start, yesterday_start, today_start) in UTC.

    Day boundaries are computed in the operator-local timezone defined by
    ``tz_offset_minutes`` so "today" matches the line's local calendar. All
    three returned instants are the UTC moments of the local midnight.
    """
    offset = timedelta(minutes=tz_offset_minutes)
    local_now = now + offset
    local_today_start = local_now.replace(hour=0, minute=0, second=0, microsecond=0)
    today_start = (local_today_start - offset).astimezone(UTC)
    yesterday_start = today_start - timedelta(days=1)
    previous_7d_start = today_start - timedelta(days=7)
    return previous_7d_start, yesterday_start, today_start


def _relative_drop(today: ConfidencePeriodStats, baseline: ConfidencePeriodStats) -> float | None:
    """Relative percent change of the weighted mean, or None when undefined."""
    if today.weighted_mean is None or baseline.weighted_mean is None:
        return None
    if baseline.weighted_mean <= 0.0:
        return None
    return (today.weighted_mean - baseline.weighted_mean) / baseline.weighted_mean * 100.0


def _assess_drift(today: ConfidencePeriodStats, baseline: ConfidencePeriodStats) -> DriftAssessment:
    """Heuristic drift label against the previous-7-day baseline (15.3.6).

    Thresholds are decision-support heuristics, not an accuracy claim: 2 % and
    5 % relative change bound the minor/noticeable bands.
    """
    level: Literal[
        "stable",
        "minor_drop",
        "noticeable_drop",
        "minor_rise",
        "noticeable_rise",
        "insufficient_data",
    ]
    relative = _relative_drop(today, baseline)
    if relative is None:
        return DriftAssessment(
            level="insufficient_data",
            detail=(
                "insufficient confidence evidence in today or the previous "
                "7-day window to compare; keep collecting before judging drift"
            ),
        )
    if relative <= -5.0:
        level = "noticeable_drop"
        detail = (
            f"today's weighted-mean confidence is {abs(relative):.1f}% below the "
            "previous-7-day mean; a persistent drop can indicate an "
            "acquisition-environment change (conveyor, camera focus/angle, "
            "lighting) - verify with frame quality and media before acting"
        )
    elif relative <= -2.0:
        level = "minor_drop"
        detail = (
            f"today's weighted-mean confidence is {abs(relative):.1f}% below the "
            "previous-7-day mean; monitor the trend"
        )
    elif relative >= 5.0:
        level = "noticeable_rise"
        detail = (
            f"today's weighted-mean confidence is {relative:.1f}% above the previous-7-day mean"
        )
    elif relative >= 2.0:
        level = "minor_rise"
        detail = (
            f"today's weighted-mean confidence is {relative:.1f}% above the previous-7-day mean"
        )
    else:
        level = "stable"
        detail = "no material change in the weighted-mean confidence"
    return DriftAssessment(level=level, detail=detail)


def _comparison(
    today: ConfidencePeriodStats, baseline: ConfidencePeriodStats
) -> ConfidenceComparison:
    relative = _relative_drop(today, baseline)
    delta = (
        today.weighted_mean - baseline.weighted_mean
        if today.weighted_mean is not None and baseline.weighted_mean is not None
        else None
    )
    return ConfidenceComparison(
        weighted_mean_delta=delta,
        weighted_mean_relative_percent=relative,
        today_evidence_count=today.evidence_count,
        baseline_evidence_count=baseline.evidence_count,
    )


def _period_schema(stats: ConfidencePeriodStats, from_iso: str, to_iso: str) -> ConfidencePeriod:
    return ConfidencePeriod(
        from_iso=from_iso,
        to_iso=to_iso,
        inspection_count=stats.inspection_count,
        evidence_count=stats.evidence_count,
        weighted_mean=stats.weighted_mean,
        median=stats.median,
    )


def _component_schema(item: ComponentConfidenceDelta) -> ComponentConfidenceDrift:
    return ComponentConfidenceDrift(
        component_code=item.component_code,
        today_weighted_mean=item.today_weighted_mean,
        baseline_weighted_mean=item.baseline_weighted_mean,
        delta=item.delta,
        today_evidence_count=item.today_evidence_count,
        baseline_evidence_count=item.baseline_evidence_count,
    )


@router.get("/statistics/confidence-drift", response_model=ConfidenceDriftReport)
def confidence_drift(
    request: Request,
    product_code: str | None = None,
    rule_version_id: str | None = None,
    component_code: str | None = None,
    tz_offset_minutes: Annotated[int, Query(ge=-840, le=840)] = 0,
    repository: EdgeRepository = Depends(get_repository),
) -> ConfidenceDriftReport:
    """Confidence drift analysis for one product/rule on this device (15.3.6).

    Compares today's weighted-mean detection confidence with yesterday and
    with the previous 7 days under the premise of the same product and rule
    version, so a change reflects the acquisition environment rather than a
    product-rule switch. The assessment is a heuristic hint, not a root-cause
    or accuracy claim.
    """
    now: datetime = request.app.state.clock()
    if now.tzinfo is None:
        now = now.replace(tzinfo=UTC)
    previous_7d_start, yesterday_start, today_start = _local_day_bounds(now, tz_offset_minutes)
    now_iso = now.isoformat()
    today_start_iso = today_start.isoformat()
    yesterday_start_iso = yesterday_start.isoformat()
    previous_7d_start_iso = previous_7d_start.isoformat()

    today = repository.confidence_period_stats(
        from_iso=today_start_iso,
        to_iso=now_iso,
        product_code=product_code,
        rule_version_id=rule_version_id,
        component_code=component_code,
    )
    yesterday = repository.confidence_period_stats(
        from_iso=yesterday_start_iso,
        to_iso=today_start_iso,
        product_code=product_code,
        rule_version_id=rule_version_id,
        component_code=component_code,
    )
    previous_7d = repository.confidence_period_stats(
        from_iso=previous_7d_start_iso,
        to_iso=today_start_iso,
        product_code=product_code,
        rule_version_id=rule_version_id,
        component_code=component_code,
    )
    components = repository.component_confidence_deltas(
        today_from_iso=today_start_iso,
        today_to_iso=now_iso,
        baseline_from_iso=previous_7d_start_iso,
        baseline_to_iso=today_start_iso,
        product_code=product_code,
        rule_version_id=rule_version_id,
        component_code=component_code,
    )
    assessment = _assess_drift(today, previous_7d)
    device = request.app.state.runtime.device_id
    return ConfidenceDriftReport(
        scope=ConfidenceDriftScope(
            device_id=str(device),
            product_code=product_code,
            rule_version_id=rule_version_id,
            tz_offset_minutes=tz_offset_minutes,
            as_of_iso=now_iso,
        ),
        periods={
            "today": _period_schema(today, today_start_iso, now_iso),
            "yesterday": _period_schema(yesterday, yesterday_start_iso, today_start_iso),
            "previous_7d": _period_schema(previous_7d, previous_7d_start_iso, today_start_iso),
        },
        comparison={
            "today_vs_yesterday": _comparison(today, yesterday),
            "today_vs_previous_7d": _comparison(today, previous_7d),
        },
        components=[_component_schema(item) for item in components],
        assessment=assessment,
    )


def _image_slot(
    media_by_kind: dict[str, MediaMetadata], kind: str, base_url: str
) -> tuple[str, Literal["AVAILABLE", "PURGED", "UNAVAILABLE"]]:
    """Return (content URL, slot status) for one image kind (F14).

    Purged media never produces a content URL: the endpoint would otherwise
    hand the UI a link that returns 410 and renders as a broken image.
    """
    item = media_by_kind.get(kind)
    if item is None:
        return "", "UNAVAILABLE"
    if item.lifecycle.value == "AVAILABLE":
        return f"{base_url}{item.media_id}/content", "AVAILABLE"
    if item.lifecycle.value == "PURGED":
        return "", "PURGED"
    return "", "UNAVAILABLE"


@router.get("/inspections/{inspection_id}/images", response_model=InspectionImages)
def inspection_images(
    inspection_id: str,
    request: Request,
    repository: EdgeRepository = Depends(get_repository),
) -> InspectionImages:
    if repository.get_inspection(inspection_id) is None:
        raise ApiProblem(
            status_code=404,
            code="INSPECTION_NOT_FOUND",
            detail=f"no inspection {inspection_id}",
        )
    media = repository.list_inspection_media(inspection_id)
    by_kind: dict[str, MediaMetadata] = {m.kind: m for m in media}
    base = f"{request.base_url}api/v1/media/"
    original, original_status = _image_slot(by_kind, "KEY_FRAME", base)
    detection, detection_status = _image_slot(by_kind, "PRODUCT_ROI", base)
    annotated, annotated_status = _image_slot(by_kind, "ANNOTATED_FRAME", base)
    return InspectionImages(
        inspection_id=inspection_id,
        original=original,
        detection=detection,
        annotated=annotated,
        original_status=original_status,
        detection_status=detection_status,
        annotated_status=annotated_status,
    )
