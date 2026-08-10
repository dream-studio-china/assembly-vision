"""Protocols for barcode decoder adapters."""

from __future__ import annotations

from typing import Protocol

from PIL import Image

from assemblyvision_edge.barcode.models import BarcodeObservation


class BarcodeDecoder(Protocol):
    """Decodes barcode evidence from one PIL image without making decisions."""

    def decode(self, image: Image.Image) -> tuple[BarcodeObservation, ...]: ...
