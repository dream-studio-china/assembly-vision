"""ZXing-cpp barcode decoder adapter."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from typing import Protocol, cast

from PIL import Image

from assemblyvision_edge.barcode.models import (
    BarcodeError,
    BarcodeErrorCode,
    BarcodeObservation,
    BarcodeSource,
)


class ZXingDecodedBarcode(Protocol):
    """The small ZXing-cpp result surface used by this adapter."""

    @property
    def text(self) -> str: ...

    @property
    def format(self) -> object: ...


BarcodeReader = Callable[[Image.Image], Sequence[ZXingDecodedBarcode]]


class ZXingCppBarcodeDecoder:
    """Decode image barcodes through the optional ``zxing-cpp`` binding."""

    def __init__(
        self,
        reader: BarcodeReader | None = None,
        *,
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._reader = reader
        self._now = now

    def decode(self, image: Image.Image) -> tuple[BarcodeObservation, ...]:
        """Return all reads, or one explicit observation when decoding is unavailable or fails."""
        observed_at = self._timestamp()
        try:
            reader = self._reader or self._load_reader()
        except ModuleNotFoundError:
            return (self._failure(observed_at, BarcodeErrorCode.DECODER_UNAVAILABLE),)
        except Exception:
            return (self._failure(observed_at, BarcodeErrorCode.DECODER_FAILURE),)

        try:
            decoded = tuple(reader(image))
        except Exception:
            return (self._failure(observed_at, BarcodeErrorCode.DECODER_FAILURE),)
        if not decoded:
            return (self._failure(observed_at, BarcodeErrorCode.NO_BARCODE_DETECTED),)

        is_ambiguous = len(decoded) > 1
        return tuple(self._observation(result, observed_at, is_ambiguous) for result in decoded)

    @staticmethod
    def _load_reader() -> BarcodeReader:
        from zxingcpp import read_barcodes  # type: ignore[import-not-found]

        return cast(BarcodeReader, read_barcodes)

    def _timestamp(self) -> datetime:
        timestamp = self._now()
        if timestamp.tzinfo is None or timestamp.utcoffset() is None:
            raise ValueError("barcode decoder clock must return a timezone-aware timestamp")
        return timestamp.astimezone(UTC)

    @staticmethod
    def _failure(observed_at: datetime, code: BarcodeErrorCode) -> BarcodeObservation:
        messages = {
            BarcodeErrorCode.DECODER_UNAVAILABLE: "ZXing-cpp is unavailable",
            BarcodeErrorCode.DECODER_FAILURE: "ZXing-cpp barcode decoding failed",
            BarcodeErrorCode.NO_BARCODE_DETECTED: "ZXing-cpp did not detect a barcode",
        }
        return BarcodeObservation(
            text=None,
            symbology=None,
            source=BarcodeSource.ZXING_CPP,
            observed_at=observed_at,
            errors=(BarcodeError(code=code, message=messages[code]),),
        )

    @staticmethod
    def _observation(
        result: ZXingDecodedBarcode, observed_at: datetime, is_ambiguous: bool
    ) -> BarcodeObservation:
        try:
            text = result.text
            barcode_format = result.format
            # zxing-cpp renders its enum as ``BarcodeFormat.Code128``. The
            # public configuration uses the stable enum member name instead.
            symbology = str(getattr(barcode_format, "name", barcode_format))
            return BarcodeObservation(
                text=text,
                symbology=symbology,
                source=BarcodeSource.ZXING_CPP,
                observed_at=observed_at,
                is_ambiguous=is_ambiguous,
            )
        except (AttributeError, TypeError, ValueError):
            return BarcodeObservation(
                text=None,
                symbology=None,
                source=BarcodeSource.ZXING_CPP,
                observed_at=observed_at,
                errors=(
                    BarcodeError(
                        code=BarcodeErrorCode.INVALID_DECODED_VALUE,
                        message="ZXing-cpp returned an invalid decoded barcode",
                    ),
                ),
                is_ambiguous=is_ambiguous,
            )
