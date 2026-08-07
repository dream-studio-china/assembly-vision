"""Evidence and media output writer."""

from __future__ import annotations

import hashlib
import io
import json
import os
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


def _fsync_path(path: Path) -> None:
    """Flush a file to durable storage."""
    with path.open("rb") as handle:
        os.fsync(handle.fileno())


def _fsync_dir(path: Path) -> None:
    """Fsync a directory so a rename into it becomes durable."""
    fd = os.open(path, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _write_file_atomic(path: Path, data: bytes) -> None:
    """Write bytes to a temp file, flush, fsync, then rename in place."""
    tmp = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    try:
        with tmp.open("wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        tmp.rename(path)
    except OSError as exc:
        tmp.unlink(missing_ok=True)
        raise OutputError(f"cannot persist {path}") from exc


def _rmtree_quiet(path: Path) -> None:
    """Best-effort recursive removal used to clean a failed staging directory."""
    import shutil

    shutil.rmtree(path, ignore_errors=True)


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
        """Persist an inspection bundle atomically and return it updated.

        Media and the record JSON are written into a staging directory, fsynced,
        then the whole directory is renamed into place. A publish is rejected for
        an inspection ID that already exists so a retry can never combine newer
        media with an older record (PR-003 P2 bundle-atomic output).
        """
        final_dir = self._output_root / str(record.inspection_id)
        if final_dir.exists():
            raise OutputError(f"inspection {record.inspection_id} is already published")
        staging = self._output_root / f".staging-{record.inspection_id}-{uuid4().hex}"
        try:
            staging.mkdir(parents=True)
            media: list[MediaMetadata] = []
            if full_frame is not None:
                media.append(self._save_image(staging, "key_frame.jpg", full_frame, "KEY_FRAME"))
            if roi_image is not None:
                media.append(self._save_image(staging, "product_roi.jpg", roi_image, "PRODUCT_ROI"))
            if annotated is not None:
                media.append(
                    self._save_image(staging, "annotated_frame.jpg", annotated, "ANNOTATED_FRAME")
                )
            record.media = media
            payload = json.dumps(record.model_dump(mode="json"), indent=2, sort_keys=True) + "\n"
            _write_file_atomic(staging / "inspection.json", payload.encode("utf-8"))
            _fsync_dir(staging)
            staging.rename(final_dir)
            _fsync_dir(self._output_root)
        except (OSError, OutputError) as exc:
            _rmtree_quiet(staging)
            raise OutputError(f"cannot publish inspection {record.inspection_id}: {exc}") from exc
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
        _write_file_atomic(inspection_dir / name, data)
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
