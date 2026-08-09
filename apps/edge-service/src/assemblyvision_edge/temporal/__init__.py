"""Edge product-window and temporal-aggregation implementation (design 10).

This module wires the deterministic per-component aggregator into the edge
runtime: a ``ProductWindowManager`` groups captured frames into one physical
product, and the aggregator resolves per-component evidence on window close.
"""

from __future__ import annotations

from assemblyvision_edge.temporal.aggregator import TemporalAggregator
from assemblyvision_edge.temporal.window_manager import (
    FrameObservation,
    ProductWindow,
    ProductWindowManager,
)

__all__ = [
    "FrameObservation",
    "ProductWindow",
    "ProductWindowManager",
    "TemporalAggregator",
]
