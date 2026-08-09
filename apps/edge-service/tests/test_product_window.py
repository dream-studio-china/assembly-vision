"""Tests for the product window manager (design 10, ADR-010)."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from assemblyvision_domain import reason_codes as rc
from assemblyvision_edge.temporal.aggregator import TemporalAggregationConfig
from assemblyvision_edge.temporal.window_manager import (
    FrameObservation,
    ProductWindowManager,
)


def _observation(
    sequence: int,
    frame_id: UUID | None = None,
    product_identity: str | None = None,
    multi_product: bool = False,
) -> FrameObservation:
    return FrameObservation(
        frame_id=frame_id or uuid4(),
        sequence=sequence,
        captured_at=datetime.now(UTC),
        quality_usable=True,
        product_detected=True,
        roi_valid=True,
        inference_valid=True,
        product_detection=None,
        roi_result=None,
        observations=[],
        reasons=[],
        product_identity=product_identity,
        multi_product=multi_product,
    )


def _config(
    *,
    minimum_valid_frames: int = 1,
    maximum_window_ms: int = 1000,
    reject_duplicates: bool = True,
    window_strategy: str = "time",
) -> TemporalAggregationConfig:
    return TemporalAggregationConfig(
        minimum_valid_frames=minimum_valid_frames,
        maximum_window_ms=maximum_window_ms,
        reject_duplicate_frame_ids=reject_duplicates,
        window_strategy=window_strategy,  # type: ignore[arg-type]
        components={},
    )


class TestWindowLifecycle:
    def test_frames_within_gap_stay_in_one_window(self) -> None:
        manager = ProductWindowManager(_config(maximum_window_ms=1000), uuid4())
        now = 1000.0
        assert manager.feed(_observation(1), now) is None
        assert manager.feed(_observation(2), now + 0.4) is None
        assert manager.feed(_observation(3), now + 0.9) is None
        assert manager.active_window is not None
        assert len(manager.active_window.frames) == 3

    def test_inactivity_gap_closes_window_and_starts_new(self) -> None:
        manager = ProductWindowManager(_config(maximum_window_ms=1000), uuid4())
        now = 1000.0
        assert manager.feed(_observation(1), now) is None
        assert manager.feed(_observation(2), now + 0.1) is None
        closed = manager.feed(_observation(3), now + 1.1)
        assert closed is not None
        assert closed.close_reason == "GAP"
        assert [f.sequence for f in closed.frames] == [1, 2]
        active = manager.active_window
        assert active is not None
        assert [f.sequence for f in active.frames] == [3]

    def test_max_duration_closes_window_even_with_continuous_frames(self) -> None:
        manager = ProductWindowManager(_config(maximum_window_ms=1000), uuid4())
        now = 1000.0
        assert manager.feed(_observation(1), now) is None
        # The frame at +0.9s arrives within the gap; the duration cap closes at
        # exactly the configured 1s window even though frames keep arriving.
        assert manager.feed(_observation(2), now + 0.9) is None
        closed = manager.feed(_observation(3), now + 1.0)
        assert closed is not None
        assert closed.close_reason == "MAX_DURATION"
        assert [f.sequence for f in closed.frames] == [1, 2]
        active = manager.active_window
        assert active is not None
        assert [f.sequence for f in active.frames] == [3]

    def test_windows_carry_distinct_inspection_ids(self) -> None:
        manager = ProductWindowManager(_config(maximum_window_ms=1000), uuid4())
        now = 1000.0
        manager.feed(_observation(1), now)
        closed = manager.feed(_observation(2), now + 1100)
        assert closed is not None
        active = manager.active_window
        assert active is not None
        assert closed.inspection_id != active.inspection_id

    def test_force_close_marks_interrupted_and_discards_frames(self) -> None:
        manager = ProductWindowManager(_config(maximum_window_ms=1000), uuid4())
        now = 1000.0
        manager.feed(_observation(1), now)
        manager.feed(_observation(2), now + 0.1)
        closed = manager.force_close()
        assert closed is not None
        assert closed.close_reason == "INTERRUPTED"
        assert closed.interrupted is True
        assert closed.frames == []
        assert manager.active_window is None

    def test_force_close_without_active_window_returns_none(self) -> None:
        manager = ProductWindowManager(_config(maximum_window_ms=1000), uuid4())
        assert manager.force_close() is None

    def test_expire_closes_idle_window_as_gap(self) -> None:
        manager = ProductWindowManager(_config(maximum_window_ms=1000), uuid4())
        now = 1000.0
        manager.feed(_observation(1), now)
        manager.feed(_observation(2), now + 0.1)
        assert manager.expire(now + 0.9) is None
        closed = manager.expire(now + 1.1)
        assert closed is not None
        assert closed.close_reason == "GAP"
        assert [f.sequence for f in closed.frames] == [1, 2]
        assert manager.active_window is None

    def test_expire_without_active_window_returns_none(self) -> None:
        manager = ProductWindowManager(_config(maximum_window_ms=1000), uuid4())
        assert manager.expire(5000.0) is None

    def test_stale_out_of_order_frame_dropped_and_counted(self) -> None:
        manager = ProductWindowManager(_config(maximum_window_ms=1000), uuid4())
        now = 1000.0
        manager.feed(_observation(1), now)
        assert manager.feed(_observation(2), now - 0.5) is None
        active = manager.active_window
        assert active is not None
        assert [f.sequence for f in active.frames] == [1]
        assert active.stale_frame_ids == 1
        assert manager.stale_frame_count == 1

    def test_stale_frame_after_expiry_cannot_open_new_window(self) -> None:
        manager = ProductWindowManager(_config(maximum_window_ms=1000), uuid4())
        now = 1000.0
        manager.feed(_observation(1), now)
        assert manager.expire(now + 1.1) is not None
        assert manager.active_window is None

        # This queued frame predates the finalized window and must never open a
        # new inspection that could become an unjustified later decision.
        assert manager.feed(_observation(2), now + 0.5) is None
        assert manager.active_window is None
        assert manager.stale_frame_count == 1


class TestDuplicateAndIdentity:
    def test_duplicate_frame_id_ignored_and_counted(self) -> None:
        manager = ProductWindowManager(_config(maximum_window_ms=1000), uuid4())
        shared = uuid4()
        now = 1000.0
        assert manager.feed(_observation(1, frame_id=shared), now) is None
        assert manager.feed(_observation(2, frame_id=shared), now + 0.1) is None
        active = manager.active_window
        assert active is not None
        assert len(active.frames) == 1
        assert active.duplicate_frame_ids == 1

    def test_duplicate_frames_counted_when_not_rejected(self) -> None:
        manager = ProductWindowManager(
            _config(maximum_window_ms=1000, reject_duplicates=False), uuid4()
        )
        shared = uuid4()
        now = 1000.0
        manager.feed(_observation(1, frame_id=shared), now)
        manager.feed(_observation(2, frame_id=shared), now + 0.1)
        assert manager.active_window is not None
        assert len(manager.active_window.frames) == 2


class TestIdentityContinuity:
    def test_same_identity_frames_stay_in_one_window(self) -> None:
        manager = ProductWindowManager(
            _config(maximum_window_ms=1000, window_strategy="identity"), uuid4()
        )
        now = 1000.0
        assert manager.feed(_observation(1, product_identity="prod-a"), now) is None
        assert manager.feed(_observation(2, product_identity="prod-a"), now + 0.1) is None
        active = manager.active_window
        assert active is not None
        assert active.identity == "prod-a"
        assert [f.sequence for f in active.frames] == [1, 2]

    def test_identity_transition_aborts_window_and_opens_new(self) -> None:
        manager = ProductWindowManager(
            _config(maximum_window_ms=1000, window_strategy="identity"), uuid4()
        )
        now = 1000.0
        manager.feed(_observation(1, product_identity="prod-a"), now)
        closed = manager.feed(_observation(2, product_identity="prod-b"), now + 0.1)
        assert closed is not None
        assert closed.close_reason == "IDENTITY_TRANSITION"
        assert rc.PRODUCT_IDENTITY_TRANSITION in closed.integrity_reason_codes
        assert [f.sequence for f in closed.frames] == [1]
        active = manager.active_window
        assert active is not None
        assert active.identity == "prod-b"
        assert [f.sequence for f in active.frames] == [2]

    def test_missing_identity_without_window_is_dropped(self) -> None:
        manager = ProductWindowManager(
            _config(maximum_window_ms=1000, window_strategy="identity"), uuid4()
        )
        assert manager.feed(_observation(1), 1000.0) is None
        assert manager.active_window is None

    def test_missing_identity_mid_window_aborts(self) -> None:
        manager = ProductWindowManager(
            _config(maximum_window_ms=1000, window_strategy="identity"), uuid4()
        )
        now = 1000.0
        manager.feed(_observation(1, product_identity="prod-a"), now)
        closed = manager.feed(_observation(2), now + 0.1)
        assert closed is not None
        assert closed.close_reason == "IDENTITY_MISSING"
        assert rc.PRODUCT_IDENTITY_MISSING in closed.integrity_reason_codes
        assert manager.active_window is None

    def test_multi_product_frame_aborts_active_window(self) -> None:
        manager = ProductWindowManager(
            _config(maximum_window_ms=1000, window_strategy="identity"), uuid4()
        )
        now = 1000.0
        manager.feed(_observation(1, product_identity="prod-a"), now)
        closed = manager.feed(_observation(2, multi_product=True), now + 0.1)
        assert closed is not None
        assert closed.close_reason == "MULTI_PRODUCT"
        assert rc.MULTIPLE_PRODUCTS in closed.integrity_reason_codes
        assert manager.active_window is None

    def test_time_strategy_ignores_identity_transitions(self) -> None:
        manager = ProductWindowManager(_config(maximum_window_ms=1000), uuid4())
        now = 1000.0
        manager.feed(_observation(1, product_identity="prod-a"), now)
        assert manager.feed(_observation(2, product_identity="prod-b"), now + 0.1) is None
        active = manager.active_window
        assert active is not None
        assert len(active.frames) == 2

    def test_force_close_marks_interrupted_with_integrity_reason(self) -> None:
        manager = ProductWindowManager(
            _config(maximum_window_ms=1000, window_strategy="identity"), uuid4()
        )
        manager.feed(_observation(1, product_identity="prod-a"), 1000.0)
        closed = manager.force_close()
        assert closed is not None
        assert closed.interrupted is True
        assert rc.INSPECTION_INTERRUPTED in closed.integrity_reason_codes


class TestConfigValidation:
    def test_invalid_window_ms_rejected(self) -> None:
        with pytest.raises(ValueError):
            _config(maximum_window_ms=0)

    def test_invalid_minimum_frames_rejected(self) -> None:
        with pytest.raises(ValueError):
            _config(minimum_valid_frames=0)
