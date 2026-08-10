"""Explicit simulated keyboard barcode input for development and tests."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from datetime import UTC, datetime

from assemblyvision_edge.barcode.models import (
    BarcodeError,
    BarcodeErrorCode,
    BarcodeObservation,
    BarcodeSource,
)


class KeyboardBarcodeInputAdapter:
    """Parse caller-supplied, terminated text without installing a keyboard hook."""

    def __init__(
        self,
        terminators: Sequence[str] = ("\r\n", "\n"),
        *,
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        normalized = tuple(terminators)
        if not normalized or any(not terminator for terminator in normalized):
            raise ValueError("at least one non-empty keyboard terminator is required")
        if len(set(normalized)) != len(normalized):
            raise ValueError("keyboard terminators must be unique")
        if any(
            first != second and second.startswith(first)
            for first in normalized
            for second in normalized
        ):
            raise ValueError("keyboard terminators cannot prefix another terminator")
        self._terminators = normalized
        self._now = now
        self._buffer = ""

    def feed(self, text: str) -> tuple[BarcodeObservation, ...]:
        """Consume supplied text and return observations for complete terminated lines only."""
        self._buffer += text
        observations: list[BarcodeObservation] = []
        while match := self._next_terminator():
            start, terminator = match
            line = self._buffer[:start]
            self._buffer = self._buffer[start + len(terminator) :]
            observations.append(self._line_observation(line))
        return tuple(observations)

    def _next_terminator(self) -> tuple[int, str] | None:
        matches = ((self._buffer.find(terminator), terminator) for terminator in self._terminators)
        present = [(position, terminator) for position, terminator in matches if position >= 0]
        if not present:
            return None
        return min(present, key=lambda match: (match[0], -len(match[1])))

    def _line_observation(self, line: str) -> BarcodeObservation:
        observed_at = self._now()
        if observed_at.tzinfo is None or observed_at.utcoffset() is None:
            raise ValueError("keyboard input clock must return a timezone-aware timestamp")
        if not line.strip():
            return BarcodeObservation(
                text=None,
                symbology=None,
                source=BarcodeSource.SIMULATED_KEYBOARD_INPUT,
                observed_at=observed_at,
                errors=(
                    BarcodeError(
                        code=BarcodeErrorCode.EMPTY_SIMULATED_INPUT,
                        message="simulated keyboard input was empty",
                    ),
                ),
            )
        return BarcodeObservation(
            text=line,
            symbology="SIMULATED_KEYBOARD",
            source=BarcodeSource.SIMULATED_KEYBOARD_INPUT,
            observed_at=observed_at,
        )
