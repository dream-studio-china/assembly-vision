"""E4b trigger/barcode/identity seam tests (design 07.4, PR-015 F1).

Covers the deterministic mock trigger source, frame-identity correlation, the
trigger configuration parsing, and the identity-sealed product-window behavior
when frames are fed from a mock trigger sequence (one window per identity,
fail-closed on missing identity).
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from assemblyvision_edge.config import _parse_trigger_source
from assemblyvision_edge.temporal.aggregator import TemporalAggregationConfig
from assemblyvision_edge.temporal.window_manager import FrameObservation, ProductWindowManager
from assemblyvision_edge.trigger.source import (
    IdentityCorrelator,
    MockProductSpec,
    MockTriggerSource,
)
from assemblyvision_vision.sources.frame_source import CapturedFrame
from PIL import Image


def _frame(sequence: int) -> CapturedFrame:
    return CapturedFrame(
        monotonic_ts_ns=sequence * 1_000_000_000,
        wall_clock_utc=datetime.now(UTC),
        sequence=sequence,
        pixel_format="RGB",
        status="OK",
        image=Image.new("RGB", (4, 4)),
    )


def _observation(sequence: int, product_identity: str | None) -> FrameObservation:
    return FrameObservation(
        frame_id=uuid4(),
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
        multi_product=False,
    )


def _window_config(*, maximum_window_ms: int = 1000) -> TemporalAggregationConfig:
    return TemporalAggregationConfig(
        window_strategy="identity",
        minimum_valid_frames=1,
        maximum_window_ms=maximum_window_ms,
        components={},
    )


class TestMockTriggerSource:
    def test_events_advance_frame_offsets_with_barcode(self) -> None:
        source = MockTriggerSource(
            [
                MockProductSpec(identity="SN-1", frames=5, barcode="111"),
                MockProductSpec(identity="SN-2", frames=3),
            ]
        )
        events = source.events()
        first = next(events)
        second = next(events)
        third = next(events)  # loop repeats the list
        assert first.identity == "SN-1" and first.frame_offset == 0 and first.barcode == "111"
        assert second.identity == "SN-2" and second.frame_offset == 5
        assert third.identity == "SN-1" and third.frame_offset == 8

    def test_non_looping_stream_ends(self) -> None:
        source = MockTriggerSource([MockProductSpec(identity="SN-1", frames=2)], loop=False)
        events = source.events()
        assert next(events).identity == "SN-1"
        with pytest.raises(StopIteration):
            next(events)

    def test_invalid_spec_is_rejected(self) -> None:
        with pytest.raises(ValueError, match="identity"):
            MockProductSpec(identity="", frames=1)
        with pytest.raises(ValueError, match="frames"):
            MockProductSpec(identity="SN-1", frames=0)
        with pytest.raises(ValueError, match="at least one"):
            MockTriggerSource([])


class TestIdentityCorrelator:
    def test_stamps_frames_with_current_identity(self) -> None:
        source = MockTriggerSource(
            [MockProductSpec(identity="SN-1", frames=2), MockProductSpec(identity="SN-2", frames=2)]
        )
        correlator = IdentityCorrelator(source)
        assert correlator.annotate(_frame(0)).product_identity == "SN-1"
        assert correlator.annotate(_frame(1)).product_identity == "SN-1"
        # Frame 2 is the second product boundary.
        assert correlator.annotate(_frame(2)).product_identity == "SN-2"
        assert correlator.annotate(_frame(3)).product_identity == "SN-2"

    def test_frames_after_non_looping_stream_have_no_identity(self) -> None:
        source = MockTriggerSource([MockProductSpec(identity="SN-1", frames=2)], loop=False)
        correlator = IdentityCorrelator(source)
        assert correlator.annotate(_frame(0)).product_identity == "SN-1"
        assert correlator.annotate(_frame(1)).product_identity == "SN-1"
        # Stream ended: no identity, so the identity-sealed window fails closed.
        assert correlator.annotate(_frame(2)).product_identity is None


class TestTriggerConfigParsing:
    def test_mock_trigger_config_parses(self) -> None:
        config = _parse_trigger_source(
            {
                "source": "mock",
                "products": [
                    {"identity": "SN-1", "barcode": "111", "frames": 5},
                    {"identity": "SN-2", "frames": 3},
                ],
            },
            "instances[0].trigger",
        )
        assert config is not None
        assert config.source == "mock"
        assert len(config.products) == 2
        assert config.products[0].identity == "SN-1"
        assert config.products[0].barcode == "111"
        assert config.products[0].frames == 5

    def test_none_returns_none(self) -> None:
        assert _parse_trigger_source(None, "x") is None

    def test_unknown_source_is_rejected(self) -> None:
        from assemblyvision_domain.errors import ConfigError

        with pytest.raises(ConfigError, match="mock"):
            _parse_trigger_source({"source": "plc", "products": []}, "x.trigger")

    def test_empty_products_are_rejected(self) -> None:
        from assemblyvision_domain.errors import ConfigError

        with pytest.raises(ConfigError, match="products"):
            _parse_trigger_source({"source": "mock", "products": []}, "x.trigger")

    def test_invalid_frames_are_rejected(self) -> None:
        from assemblyvision_domain.errors import ConfigError

        with pytest.raises(ConfigError, match="frames"):
            _parse_trigger_source(
                {"source": "mock", "products": [{"identity": "SN-1", "frames": 0}]},
                "x.trigger",
            )


class TestIdentitySealedWindowFromMockTrigger:
    def test_one_window_per_identity_and_fail_closed_after_stream(self) -> None:
        """A mock-fed identity stream seals one window per product (E4b)."""
        source = MockTriggerSource(
            [
                MockProductSpec(identity="SN-1", frames=2),
                MockProductSpec(identity="SN-2", frames=2),
            ],
            loop=False,
        )
        correlator = IdentityCorrelator(source)
        manager = ProductWindowManager(_window_config(), device_id=UUID(int=1))
        closed: list[str | None] = []
        now = 0.0
        for sequence in range(6):
            identity = correlator.annotate(_frame(sequence)).product_identity
            result = manager.feed(_observation(sequence, identity), now)
            now += 0.1
            if result is not None:
                closed.append(result.identity)
        # Frames 0-1 seal SN-1, frames 2-3 seal SN-2; frames 4-5 have no
        # identity and the active window aborts as an identity-missing NG.
        assert closed == ["SN-1", "SN-2"]
        # The final window aborted (identity missing) and released no product.
        assert manager.active_window is None
