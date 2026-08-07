"""Tests for the bounded log buffer incl. failure paths."""

from __future__ import annotations

import logging

from assemblyvision_edge.api.logging_buffer import LogBuffer, LogEvent


def test_emit_captures_and_snapshot_newest_first() -> None:
    buffer = LogBuffer(capacity=10)
    for i in range(3):
        buffer.emit(
            logging.LogRecord("edge.test", logging.INFO, "mod", 0, f"message {i}", (), None)
        )
    events = buffer.snapshot(10)
    assert len(events) == 3
    assert events[0].message == "message 2"
    assert events[-1].message == "message 0"


def test_log_event_fields() -> None:
    record = logging.LogRecord("edge.rule", logging.WARNING, "mod.py", 10, "rule failed", (), None)
    record.trace_id = "trace-1"
    event = LogEvent(record)
    assert event.level == "WARNING"
    assert event.component == "edge.rule"
    assert event.message == "rule failed"
    assert event.trace_id == "trace-1"
    assert event.logged_at.endswith("Z") or "+" in event.logged_at


def test_capacity_is_bounded() -> None:
    buffer = LogBuffer(capacity=3)
    for i in range(10):
        buffer.emit(logging.LogRecord("c", logging.INFO, "m", 0, str(i), (), None))
    events = buffer.snapshot(100)
    assert len(events) == 3
    assert [e.message for e in events] == ["9", "8", "7"]


def test_emit_never_raises_on_bad_record() -> None:
    buffer = LogBuffer(capacity=5)

    class BrokenRecord(logging.LogRecord):
        def getMessage(self) -> str:
            raise RuntimeError("broken")

    buffer.emit(BrokenRecord("c", logging.INFO, "m", 0, "x", (), None))
    # A second healthy event still lands after the failed capture.
    buffer.emit(logging.LogRecord("c", logging.INFO, "m", 0, "ok", (), None))
    events = buffer.snapshot(5)
    assert [e.message for e in events] == ["ok"]


def test_snapshot_respects_limit() -> None:
    buffer = LogBuffer(capacity=10)
    for i in range(6):
        buffer.emit(logging.LogRecord("c", logging.INFO, "m", 0, str(i), (), None))
    assert len(buffer.snapshot(2)) == 2


def test_buffer_installs_as_logging_handler(caplog: object) -> None:
    buffer = LogBuffer(capacity=5)
    logger = logging.getLogger("assemblyvision.buffertest")
    logger.addHandler(buffer)
    logger.setLevel(logging.INFO)
    try:
        logger.info("capture me")
        events = buffer.snapshot(5)
        assert any(e.message == "capture me" for e in events)
    finally:
        logger.removeHandler(buffer)
