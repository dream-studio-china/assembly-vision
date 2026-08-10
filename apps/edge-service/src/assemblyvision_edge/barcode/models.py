"""Typed barcode observations produced by edge input adapters."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum


class BarcodeSource(StrEnum):
    """Origin of a barcode observation."""

    ZXING_CPP = "ZXING_CPP"
    SIMULATED_KEYBOARD_INPUT = "SIMULATED_KEYBOARD_INPUT"


class BarcodeErrorCode(StrEnum):
    """Stable adapter-level barcode error categories."""

    DECODER_UNAVAILABLE = "DECODER_UNAVAILABLE"
    DECODER_FAILURE = "DECODER_FAILURE"
    INVALID_DECODED_VALUE = "INVALID_DECODED_VALUE"
    NO_BARCODE_DETECTED = "NO_BARCODE_DETECTED"
    EMPTY_SIMULATED_INPUT = "EMPTY_SIMULATED_INPUT"


@dataclass(frozen=True, slots=True)
class BarcodeError:
    """One stable error reported while collecting barcode evidence."""

    code: BarcodeErrorCode
    message: str

    def __post_init__(self) -> None:
        if not self.message.strip():
            raise ValueError("barcode error message must be non-empty")


@dataclass(frozen=True, slots=True)
class BarcodeObservation:
    """One timestamped barcode-read result or explicit failure evidence."""

    text: str | None
    symbology: str | None
    source: BarcodeSource
    observed_at: datetime
    errors: tuple[BarcodeError, ...] = ()
    is_ambiguous: bool = False

    def __post_init__(self) -> None:
        if self.observed_at.tzinfo is None or self.observed_at.utcoffset() is None:
            raise ValueError("barcode observation timestamp must be timezone-aware")
        object.__setattr__(self, "observed_at", self.observed_at.astimezone(UTC))

        if self.text is None:
            if self.symbology is not None:
                raise ValueError("barcode failure observations cannot include a symbology")
            if not self.errors:
                raise ValueError("barcode failure observations must include an error")
            return

        if not self.text.strip():
            raise ValueError("barcode text must be non-empty")
        if self.symbology is None or not self.symbology.strip():
            raise ValueError("decoded barcode observations must include a symbology")
