"""Component dataset preparation: ROI cropping and box coordinate remapping."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any
from uuid import uuid4

import yaml
from assemblyvision_domain.models import BoundingBox
from assemblyvision_vision.roi.geometry import Box, apply_transform
from assemblyvision_vision.roi.roi_engine import ROIConfig, ROIEngine

from assemblyvision_training.dataset import SUPPORTED_SUFFIXES

log = logging.getLogger("assemblyvision.training")


def prepare_component_dataset(
    *,
    dataset_dir: Path,
    product_weights: Path,
    roi_config: ROIConfig,
    output_dir: Path,
) -> None:
    """Generate a component training set from full-frame labels.

    Uses the trained product detector to locate each product, crops the ROI,
    and remaps full-frame YOLO component labels into ROI coordinates.

    Output layout mirrors the input YOLO dataset structure with ROI images
    and labels under ``output_dir/images/{train,val}`` and
    ``output_dir/labels/{train,val}``.
    """
    from PIL import Image
    from ultralytics import YOLO  # type: ignore[attr-defined]

    data = yaml.safe_load((dataset_dir / "data.yaml").read_text(encoding="utf-8"))
    class_names: list[str] = [str(n) for n in data["names"]]

    model = YOLO(str(product_weights))
    engine = ROIEngine(roi_config)

    for split in ("train", "val"):
        img_dir = dataset_dir / "images" / split
        lbl_dir = dataset_dir / "labels" / split
        out_img_dir = output_dir / "images" / split
        out_lbl_dir = output_dir / "labels" / split
        out_img_dir.mkdir(parents=True, exist_ok=True)
        out_lbl_dir.mkdir(parents=True, exist_ok=True)

        if not img_dir.is_dir():
            log.warning("images/%s not found, skipping", split)
            continue

        for img_path in sorted(img_dir.iterdir()):
            if not img_path.is_file() or img_path.suffix.lower() not in SUPPORTED_SUFFIXES:
                continue
            lbl_path = lbl_dir / f"{img_path.stem}.txt"
            if not lbl_path.is_file():
                log.warning("no label for %s, skipping", img_path.name)
                continue

            frame = Image.open(img_path).convert("RGB")

            results = model(frame, verbose=False, conf=0.10)
            boxes = results[0].boxes  # type: ignore[index, union-attr]
            if boxes is None or len(boxes) == 0:
                log.warning("no product detected in %s, skipping", img_path.name)
                continue

            best_idx = _largest_box_index(boxes)
            x1, y1, x2, y2 = (float(v) for v in boxes.xyxy[best_idx].tolist())
            product_box = BoundingBox(
                x_min=x1, y_min=y1, x_max=x2, y_max=y2,
                image_width=frame.width, image_height=frame.height,
            )

            try:
                generated = engine.generate(frame, uuid4(), product_box)
            except Exception:
                log.warning("ROI invalid for %s, skipping", img_path.name)
                continue

            roi_labels = _remap_labels(
                lbl_path,
                frame.width,
                frame.height,
                generated.roi_image.width,
                generated.roi_image.height,
                generated.result.transform_full_to_roi,
            )
            if not roi_labels:
                continue

            generated.roi_image.save(out_img_dir / img_path.name)
            out_lbl = out_lbl_dir / f"{img_path.stem}.txt"
            out_lbl.write_text("\n".join(roi_labels) + "\n", encoding="utf-8")

    out_data = {
        "nc": len(class_names),
        "names": class_names,
        "train": str((output_dir / "images" / "train").resolve()),
        "val": str((output_dir / "images" / "val").resolve()),
    }
    (output_dir / "data.yaml").write_text(yaml.dump(out_data, default_flow_style=False), encoding="utf-8")


def _largest_box_index(boxes: Any) -> int:
    best = 0
    best_area = -1.0
    for i in range(len(boxes)):
        x1, y1, x2, y2 = (float(v) for v in boxes.xyxy[i].tolist())
        area = (x2 - x1) * (y2 - y1)
        if area > best_area:
            best_area = area
            best = i
    return best


def _remap_labels(
    lbl_path: Path,
    frame_width: int,
    frame_height: int,
    roi_width: int,
    roi_height: int,
    transform: tuple[float, float, float, float, float, float],
) -> list[str]:
    lines = []
    for line in lbl_path.read_text(encoding="utf-8").strip().splitlines():
        line = line.strip()
        if not line:
            continue
        parts = line.split()
        cls_id = int(parts[0])
        cx, cy, w, h = float(parts[1]), float(parts[2]), float(parts[3]), float(parts[4])
        px_cx = cx * frame_width
        px_cy = cy * frame_height
        px_w = w * frame_width
        px_h = h * frame_height
        box = Box(px_cx - px_w / 2, px_cy - px_h / 2, px_cx + px_w / 2, px_cy + px_h / 2)
        mapped = apply_transform(box, transform)
        if mapped.x_min < 0 or mapped.y_min < 0 or mapped.x_max > roi_width or mapped.y_max > roi_height:
            continue
        if mapped.width <= 0 or mapped.height <= 0:
            continue
        cx_roi = (mapped.x_min + mapped.x_max) / 2 / roi_width
        cy_roi = (mapped.y_min + mapped.y_max) / 2 / roi_height
        w_roi = mapped.width / roi_width
        h_roi = mapped.height / roi_height
        lines.append(f"{cls_id} {cx_roi:.6f} {cy_roi:.6f} {w_roi:.6f} {h_roi:.6f}")
    return lines
