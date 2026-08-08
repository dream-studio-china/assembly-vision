"""Component dataset preparation: ROI cropping and box coordinate remapping."""

from __future__ import annotations

import json
import logging
import shutil
from pathlib import Path
from typing import Any
from uuid import uuid4

import yaml
from assemblyvision_domain.errors import ConfigError
from assemblyvision_domain.models import BoundingBox, ModelManifest
from assemblyvision_vision.manifests import (
    load_model_manifest,
    verify_manifest_artifact,
    verify_model_class_map,
)
from assemblyvision_vision.roi.geometry import Box, apply_transform
from assemblyvision_vision.roi.roi_engine import ROIConfig, ROIEngine
from PIL import Image

from assemblyvision_training.dataset import SUPPORTED_SUFFIXES

log = logging.getLogger("assemblyvision.training")

PRODUCT_CLASS = "product"


def prepare_component_dataset(
    *,
    dataset_dir: Path,
    product_manifest: Path,
    roi_config: ROIConfig,
    output_dir: Path,
    confidence_threshold: float = 0.5,
    iou_threshold: float = 0.5,
    device: str | None = None,
) -> None:
    """Publish a complete ROI dataset without retaining partial output.

    The destination may be absent or empty. Preparation runs in a sibling
    staging directory and publishes only after all output files are complete.
    """
    if output_dir.exists() and any(output_dir.iterdir()):
        raise ConfigError(
            f"output directory {output_dir} is not empty; refusing to write into a stale dataset"
        )
    staging_dir = output_dir.parent / f".{output_dir.name}.staging-{uuid4().hex}"
    try:
        _prepare_component_dataset_into(
            dataset_dir=dataset_dir,
            product_manifest=product_manifest,
            roi_config=roi_config,
            output_dir=staging_dir,
            confidence_threshold=confidence_threshold,
            iou_threshold=iou_threshold,
            device=device,
        )
        if output_dir.exists():
            output_dir.rmdir()
        staging_dir.rename(output_dir)
    except Exception:
        shutil.rmtree(staging_dir, ignore_errors=True)
        raise


def _prepare_component_dataset_into(
    *,
    dataset_dir: Path,
    product_manifest: Path,
    roi_config: ROIConfig,
    output_dir: Path,
    confidence_threshold: float,
    iou_threshold: float,
    device: str | None,
) -> None:
    """Generate a component training set from full-frame labels.

    The product detector is loaded from a **verified** manifest (weights
    checksum and class map are checked) and runs with manifest-derived
    inference settings, mirroring the runtime stage-one selection policy
    (PR-003 P2): candidates are filtered to the ``product`` class at the
    declared confidence, and a frame with zero or multiple products is
    recorded as an exclusion rather than guessing a box. Ambiguous samples are
    listed in an explicit ``exclusions.json``.

    A ``manifest.json`` lists every produced file so dataset membership is
    auditable.
    """
    manifest = load_model_manifest(product_manifest)
    if manifest.task != "PRODUCT_DETECTION":
        raise ConfigError(f"manifest task {manifest.task!r} is not PRODUCT_DETECTION")
    if PRODUCT_CLASS not in manifest.class_names:
        raise ConfigError(
            f"manifest class_names missing {PRODUCT_CLASS!r}: a prepared product detector "
            "must independently localize the full product"
        )
    weights = verify_manifest_artifact(manifest, product_manifest)

    from ultralytics import YOLO  # type: ignore[attr-defined]

    model = YOLO(str(weights))
    verify_model_class_map(model.names, manifest)
    engine = ROIEngine(roi_config)
    try:
        source_data = yaml.safe_load((dataset_dir / "data.yaml").read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise ConfigError(f"cannot load component dataset manifest: {exc}") from exc
    if not isinstance(source_data, dict) or not isinstance(source_data.get("names"), list):
        raise ConfigError("component dataset data.yaml must contain a class-name list")
    component_class_names = [str(name) for name in source_data["names"]]

    produced: dict[str, list[str]] = {"train": [], "val": []}
    exclusions: dict[str, dict[str, str]] = {}

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
            product_box = _select_product_box(
                model,
                frame,
                manifest,
                confidence_threshold,
                iou_threshold,
                device,
            )
            if product_box is None:
                exclusions[f"{split}/{img_path.name}"] = {
                    "reason": "NO_PRODUCT_OR_AMBIGUOUS",
                    "detail": "no unambiguous product detection at the declared confidence",
                }
                continue

            try:
                generated = engine.generate(frame, uuid4(), product_box)
            except Exception:
                exclusions[f"{split}/{img_path.name}"] = {
                    "reason": "ROI_INVALID",
                    "detail": "ROI generation failed",
                }
                continue

            roi_labels = _remap_labels(
                lbl_path,
                frame.width,
                frame.height,
                generated.roi_image.width,
                generated.roi_image.height,
                generated.result.transform_full_to_roi,
            )
            # A valid ROI with no remapped component boxes is a negative
            # training crop (for example a missing-component product); it must
            # be kept with an empty label file, not dropped.
            generated.roi_image.save(out_img_dir / img_path.name)
            out_lbl = out_lbl_dir / f"{img_path.stem}.txt"
            out_lbl.write_text(
                "\n".join(roi_labels) + ("\n" if roi_labels else ""), encoding="utf-8"
            )
            produced[split].append(img_path.name)

    out_data = {
        "nc": len(component_class_names),
        "names": component_class_names,
        "train": "images/train",
        "val": "images/val",
    }
    (output_dir / "data.yaml").write_text(
        yaml.dump(out_data, default_flow_style=False), encoding="utf-8"
    )
    (output_dir / "exclusions.json").write_text(
        json.dumps(exclusions, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    (output_dir / "manifest.json").write_text(
        json.dumps(
            {
                "product_manifest": str(product_manifest),
                "product_model_version_label": manifest.model_version_label,
                "confidence_threshold": confidence_threshold,
                "iou_threshold": iou_threshold,
                "files": produced,
                "exclusions": exclusions,
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )


def _select_product_box(
    model: Any,
    frame: Image.Image,
    manifest: ModelManifest,
    confidence_threshold: float,
    iou_threshold: float,
    device: str | None,
) -> BoundingBox | None:
    """Mirror the runtime product-detector selection policy.

    Candidates are the ``product`` class at or above the declared confidence;
    zero or multiple candidates is ambiguous and yields no box (exclusion),
    never a guessed largest-box selection (PR-003 P2).
    """
    results = model(
        frame,
        imgsz=(manifest.input_height, manifest.input_width),
        conf=confidence_threshold,
        iou=iou_threshold,
        device=device,
        verbose=False,
    )
    if not results:
        return None
    boxes = getattr(results[0], "boxes", None)
    if boxes is None or len(boxes) == 0:
        return None
    candidates: list[tuple[float, float, float, float, float]] = []
    for i in range(len(boxes)):
        cls_id = int(boxes.cls[i].item())
        conf = float(boxes.conf[i].item())
        x1, y1, x2, y2 = (float(v) for v in boxes.xyxy[i].tolist())
        if (
            0 <= cls_id < len(manifest.class_names)
            and manifest.class_names[cls_id] == PRODUCT_CLASS
            and conf >= confidence_threshold
        ):
            candidates.append((conf, x1, y1, x2, y2))
    if len(candidates) != 1:
        return None
    _, x1, y1, x2, y2 = candidates[0]
    return BoundingBox(
        x_min=x1,
        y_min=y1,
        x_max=x2,
        y_max=y2,
        image_width=frame.width,
        image_height=frame.height,
    )


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
        if (
            mapped.x_min < 0
            or mapped.y_min < 0
            or mapped.x_max > roi_width
            or mapped.y_max > roi_height
        ):
            continue
        if mapped.width <= 0 or mapped.height <= 0:
            continue
        cx_roi = (mapped.x_min + mapped.x_max) / 2 / roi_width
        cy_roi = (mapped.y_min + mapped.y_max) / 2 / roi_height
        w_roi = mapped.width / roi_width
        h_roi = mapped.height / roi_height
        lines.append(f"{cls_id} {cx_roi:.6f} {cy_roi:.6f} {w_roi:.6f} {h_roi:.6f}")
    return lines
