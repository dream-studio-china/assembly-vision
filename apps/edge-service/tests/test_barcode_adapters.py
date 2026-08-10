"""Focused tests for isolated barcode input adapters."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone

import pytest
from assemblyvision_edge.barcode import (
    BarcodeErrorCode,
    BarcodeObservation,
    BarcodeSource,
    KeyboardBarcodeInputAdapter,
    ZXingCppBarcodeDecoder,
)
from PIL import Image


class _DecodedBarcode:
    def __init__(self, text: str, format: object) -> None:
        self.text = text
        self.format = format


class _EnumFormat:
    name = "Code128"

    def __str__(self) -> str:
        return "BarcodeFormat.Code128"


def _timestamp() -> datetime:
    return datetime(2026, 8, 10, 12, 0, tzinfo=UTC)


def test_zxing_decoder_returns_typed_ambiguous_observations() -> None:
    decoder = ZXingCppBarcodeDecoder(
        lambda image: [_DecodedBarcode("first", "QRCode"), _DecodedBarcode("second", "Code128")],
        now=_timestamp,
    )

    observations = decoder.decode(Image.new("RGB", (20, 20)))

    assert [observation.text for observation in observations] == ["first", "second"]
    assert [observation.symbology for observation in observations] == ["QRCode", "Code128"]
    assert all(observation.source is BarcodeSource.ZXING_CPP for observation in observations)
    assert all(observation.observed_at == _timestamp() for observation in observations)
    assert all(observation.is_ambiguous for observation in observations)
    assert all(not observation.errors for observation in observations)


def test_zxing_decoder_uses_the_stable_format_member_name() -> None:
    decoder = ZXingCppBarcodeDecoder(
        lambda image: [_DecodedBarcode("instance-1", _EnumFormat())], now=_timestamp
    )

    observation = decoder.decode(Image.new("RGB", (20, 20)))[0]

    assert observation.symbology == "Code128"


def test_zxing_decoder_returns_failure_evidence_for_missing_or_invalid_results() -> None:
    no_read = ZXingCppBarcodeDecoder(lambda image: [], now=_timestamp).decode(
        Image.new("RGB", (1, 1))
    )
    invalid = ZXingCppBarcodeDecoder(
        lambda image: [_DecodedBarcode("", "QRCode")], now=_timestamp
    ).decode(Image.new("RGB", (1, 1)))

    assert no_read[0].text is None
    assert no_read[0].errors[0].code is BarcodeErrorCode.NO_BARCODE_DETECTED
    assert invalid[0].text is None
    assert invalid[0].errors[0].code is BarcodeErrorCode.INVALID_DECODED_VALUE


def test_zxing_decoder_converts_reader_failures_to_typed_error() -> None:
    def fail(image: Image.Image) -> list[_DecodedBarcode]:
        raise RuntimeError("decoder failed")

    observation = ZXingCppBarcodeDecoder(fail, now=_timestamp).decode(Image.new("RGB", (1, 1)))[0]

    assert observation.errors[0].code is BarcodeErrorCode.DECODER_FAILURE


def test_zxing_decoder_converts_load_failures_to_typed_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_load() -> object:
        raise RuntimeError("binding failed to load")

    monkeypatch.setattr(ZXingCppBarcodeDecoder, "_load_reader", staticmethod(fail_load))

    observation = ZXingCppBarcodeDecoder(now=_timestamp).decode(Image.new("RGB", (1, 1)))[0]

    assert observation.errors[0].code is BarcodeErrorCode.DECODER_FAILURE


def test_keyboard_adapter_buffers_input_until_configured_terminator() -> None:
    adapter = KeyboardBarcodeInputAdapter(now=_timestamp)

    assert adapter.feed("ABC") == ()
    observations = adapter.feed("123\r\nXYZ\n")

    assert [observation.text for observation in observations] == ["ABC123", "XYZ"]
    assert all(observation.symbology == "SIMULATED_KEYBOARD" for observation in observations)
    assert all(
        observation.source is BarcodeSource.SIMULATED_KEYBOARD_INPUT for observation in observations
    )
    assert all(not observation.is_ambiguous for observation in observations)


def test_keyboard_adapter_reports_empty_terminated_input() -> None:
    observation = KeyboardBarcodeInputAdapter(now=_timestamp).feed("\n")[0]

    assert observation.text is None
    assert observation.errors[0].code is BarcodeErrorCode.EMPTY_SIMULATED_INPUT


@pytest.mark.parametrize("terminators", [(), ("",), ("\n", "\n"), ("\r", "\r\n")])
def test_keyboard_adapter_rejects_ambiguous_terminator_configuration(
    terminators: tuple[str, ...],
) -> None:
    with pytest.raises(ValueError):
        KeyboardBarcodeInputAdapter(terminators)


def test_observation_requires_valid_read_fields_and_normalizes_timestamp() -> None:
    eastern = datetime(2026, 8, 10, 8, 0, tzinfo=timezone(timedelta(hours=-4)))
    observation = BarcodeObservation(
        text="ABC",
        symbology="Code128",
        source=BarcodeSource.ZXING_CPP,
        observed_at=eastern,
    )

    assert observation.observed_at == _timestamp()
    with pytest.raises(ValueError, match="symbology"):
        BarcodeObservation(
            text="ABC",
            symbology=None,
            source=BarcodeSource.ZXING_CPP,
            observed_at=_timestamp(),
        )
