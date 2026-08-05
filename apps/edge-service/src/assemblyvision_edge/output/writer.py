"""Evidence and media output writer."""

from __future__ import annotations

import hashlib
import io
import json
from collections.abc import Sequence
from pathlib import Path
from typing import Literal
from uuid import uuid4

from assemblyvision_domain.errors import OutputError
from assemblyvision_domain.models import (
    BoundingBox,
    InspectionRecord,
    MediaLifecycle,
    MediaMetadata,
)
from PIL import Image, ImageDraw

MediaKind = Literal["KEY_FRAME", "ANNOTATED_FRAME", "PRODUCT_ROI", "NG_CLIP", "ROLLING_VIDEO"]
_PRODUCT_COLOR = (0, 255, 0)
_COMPONENT_COLOR = (255, 64, 64)


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _atomic_write_bytes(path: Path, data: bytes) -> None:
    tmp = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    try:
        tmp.write_bytes(data)
        tmp.rename(path)
    except OSError as exc:
        tmp.unlink(missing_ok=True)
        raise OutputError(f"cannot persist {path}") from exc


def _draw_rect(
    draw: ImageDraw.ImageDraw, box: BoundingBox, color: tuple[int, int, int], label: str
) -> None:
    draw.rectangle((box.x_min, box.y_min, box.x_max, box.y_max), outline=color, width=3)
    draw.text((box.x_min, max(0, box.y_min - 14)), label, fill=color)


def annotate_full_frame(
    image: Image.Image,
    product_box: BoundingBox | None,
    component_boxes: Sequence[tuple[str, BoundingBox]],
) -> Image.Image:
    """Draw product and component boxes onto a copy of the full frame."""
    canvas = image.copy()
    draw = ImageDraw.Draw(canvas)
    if product_box is not None:
        _draw_rect(draw, product_box, _PRODUCT_COLOR, "product")
    for code, box in component_boxes:
        _draw_rect(draw, box, _COMPONENT_COLOR, code)
    return canvas


class OutputWriter:
    """Persists inspection JSON and evidence media atomically."""

    def __init__(self, output_root: Path) -> None:
        self._output_root = output_root

    def save(
        self,
        record: InspectionRecord,
        *,
        full_frame: Image.Image | None,
        roi_image: Image.Image | None,
        annotated: Image.Image | None,
    ) -> InspectionRecord:
        """Persist media first, then the inspection record, and return it updated."""
        inspection_dir = self._output_root / str(record.inspection_id)
        try:
            inspection_dir.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise OutputError(f"cannot create output directory {inspection_dir}") from exc
        media: list[MediaMetadata] = []
        if full_frame is not None:
            media.append(self._save_image(inspection_dir, "key_frame.jpg", full_frame, "KEY_FRAME"))
        if roi_image is not None:
            media.append(
                self._save_image(inspection_dir, "product_roi.jpg", roi_image, "PRODUCT_ROI")
            )
        if annotated is not None:
            media.append(
                self._save_image(
                    inspection_dir, "annotated_frame.jpg", annotated, "ANNOTATED_FRAME"
                )
            )
        record.media = media
        payload = json.dumps(record.model_dump(mode="json"), indent=2, sort_keys=True) + "\n"
        _atomic_write_bytes(inspection_dir / "inspection.json", payload.encode("utf-8"))
        return record

    def _save_image(
        self,
        inspection_dir: Path,
        name: str,
        image: Image.Image,
        kind: MediaKind,
    ) -> MediaMetadata:
        try:
            buffer = io.BytesIO()
            image.save(buffer, format="JPEG", quality=90)
            data = buffer.getvalue()
        except OSError as exc:
            raise OutputError(f"cannot encode image {name}") from exc
        _atomic_write_bytes(inspection_dir / name, data)
        relative = f"{inspection_dir.name}/{name}"
        return MediaMetadata(
            media_id=uuid4(),
            kind=kind,
            lifecycle=MediaLifecycle.AVAILABLE,
            relative_path=relative,
            mime_type="image/jpeg",
            size_bytes=len(data),
            checksum_sha256=_sha256_bytes(data),
        )
