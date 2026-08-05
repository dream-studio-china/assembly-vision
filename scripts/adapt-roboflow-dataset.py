#!/usr/bin/env python
"""Adapt a Roboflow YOLOv8 export into the AssemblyVision dataset layout.

Roboflow "YOLOv8 PyTorch" exports come as:
  <src>/{images,labels}/{train,val,test}/ + <src>/data.yaml

Our pipeline needs two-stage datasets:
  dataset_product/     class "product" = union of component boxes (+ margin)
  dataset_components/  the real component classes (generic "missing" classes dropped)

The design forbids training a generic missing-component class; absence is
inferred from the absence of the real component's box. Images that carry a
"missing*" label become NG evidence (one required component absent).

Usage:
  uv run python scripts/adapt-roboflow-dataset.py <src> <out> \
      [--drop-missing] [--required 'chip,capacitor,boot']
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

try:
    import yaml
except ImportError:  # pragma: no cover
    yaml = None  # type: ignore[assignment]

PRODUCT_MARGIN_RATIO = 0.05


def _load_names(data_yaml: Path) -> list[str]:
    if yaml is None:
        raise RuntimeError("PyYAML is required (uv sync)")
    raw = yaml.safe_load(data_yaml.read_text(encoding="utf-8"))
    if not isinstance(raw, dict) or "names" not in raw:
        raise ValueError(f"data.yaml has no names: {data_yaml}")
    return [str(n) for n in raw["names"]]


def _box_coords(line: str, img_w: int, img_h: int) -> tuple[float, float, float, float]:
    parts = line.split()
    cx, cy, w, h = (float(v) for v in parts[1:5])
    return (cx - w / 2) * img_w, (cy - h / 2) * img_h, (cx + w / 2) * img_w, (cy + h / 2) * img_h


def _union_bbox(coords: list[tuple[float, float, float, float]], img_w: int, img_h: int) -> tuple[float, float, float, float]:
    x1 = min(c[0] for c in coords)
    y1 = min(c[1] for c in coords)
    x2 = max(c[2] for c in coords)
    y2 = max(c[3] for c in coords)
    mx = (x2 - x1) * PRODUCT_MARGIN_RATIO
    my = (y2 - y1) * PRODUCT_MARGIN_RATIO
    return (max(0.0, x1 - mx), max(0.0, y1 - my), min(img_w, x2 + mx), min(img_h, y2 + my))


def _norm(coords: tuple[float, float, float, float], img_w: int, img_h: int) -> tuple[float, float, float, float]:
    x1, y1, x2, y2 = coords
    cx = (x1 + x2) / 2 / img_w
    cy = (y1 + y2) / 2 / img_h
    return (cx, cy, (x2 - x1) / img_w, (y2 - y1) / img_h)


def adapt(src: Path, out: Path, drop_missing: bool, required: list[str] | None) -> None:
    if yaml is None:
        raise RuntimeError("PyYAML is required (uv sync)")
    names = _load_names(src / "data.yaml")
    drop = {n for n in names if drop_missing and "missing" in n.lower()}
    keep = [n for n in names if n not in drop]

    comp_order = required if required else keep
    missing_in_data = [n for n in comp_order if n not in keep]
    if missing_in_data:
        print(f"WARNING: required classes not present in dataset: {missing_in_data}")

    splits = [d.name for d in (src / "images").iterdir() if d.is_dir() and d.name in ("train", "val", "test")]

    for split in ("train", "val"):
        for ds in ("dataset_product", "dataset_components"):
            (out / ds / "images" / split).mkdir(parents=True)
            (out / ds / "labels" / split).mkdir(parents=True)

    test_img_dir = out / "test"
    test_img_dir.mkdir(parents=True)
    expected: dict[str, dict[str, Any]] = {}

    for split in splits:
        img_dir = src / "images" / split
        lbl_dir = src / "labels" / split
        out_split = "train" if split == "train" else "val"
        for img_path in sorted(img_dir.iterdir()):
            if not img_path.is_file():
                continue
            lbl_path = lbl_dir / f"{img_path.stem}.txt"
            from PIL import Image

            with Image.open(img_path) as handle:
                img_w, img_h = handle.size

            coords: dict[str, list[tuple[float, float, float, float]]] = {n: [] for n in keep}
            if lbl_path.is_file():
                for line in lbl_path.read_text(encoding="utf-8").strip().splitlines():
                    if not line.strip():
                        continue
                    cls_id = int(line.split()[0])
                    if cls_id >= len(names):
                        continue
                    name = names[cls_id]
                    if name in keep:
                        coords[name].append(_box_coords(line, img_w, img_h))

            # product = union of all kept component boxes
            all_coords = [c for lst in coords.values() for c in lst]
            if all_coords:
                union = _norm(_union_bbox(all_coords, img_w, img_h), img_w, img_h)
                (out / "dataset_product" / "labels" / out_split / f"{img_path.stem}.txt").write_text(
                    f"0 {union[0]:.6f} {union[1]:.6f} {union[2]:.6f} {union[3]:.6f}\n", encoding="utf-8"
                )
                (out / "dataset_product" / "images" / out_split / img_path.name).write_bytes(img_path.read_bytes())

            lines = []
            for i, name in enumerate(comp_order):
                for coord in coords.get(name, []):
                    n = _norm(coord, img_w, img_h)
                    lines.append(f"{i} {n[0]:.6f} {n[1]:.6f} {n[2]:.6f} {n[3]:.6f}")
            if lines:
                (out / "dataset_components" / "labels" / out_split / f"{img_path.stem}.txt").write_text(
                    "\n".join(lines) + "\n", encoding="utf-8"
                )
                (out / "dataset_components" / "images" / out_split / img_path.name).write_bytes(img_path.read_bytes())

            # held-out test copy (all images, incl. missing-component ones)
            if split == "test":
                (test_img_dir / img_path.name).write_bytes(img_path.read_bytes())
                present = {n for n in comp_order if coords.get(n)}
                expected[img_path.name] = {
                    "ok": present == set(comp_order),
                    "present": sorted(present),
                    "missing": sorted(set(comp_order) - present),
                }

    def _data(names_out: list[str], images_root: Path) -> dict[str, Any]:
        return {
            "nc": len(names_out),
            "names": names_out,
            "train": str((images_root / "train").resolve()),
            "val": str((images_root / "val").resolve()),
        }

    (out / "dataset_product" / "data.yaml").write_text(
        yaml.dump(_data(["product"], out / "dataset_product" / "images"), default_flow_style=False), encoding="utf-8"
    )
    (out / "dataset_components" / "data.yaml").write_text(
        yaml.dump(_data(comp_order, out / "dataset_components" / "images"), default_flow_style=False), encoding="utf-8"
    )
    if expected:
        (out / "test-expected.json").write_text(json.dumps(expected, indent=2), encoding="utf-8")

    print(f"adapted -> {out}")
    print(f"  product:    train={len(list((out/'dataset_product/images/train').glob('*')))} val={len(list((out/'dataset_product/images/val').glob('*')))}")
    print(f"  components: train={len(list((out/'dataset_components/images/train').glob('*')))} val={len(list((out/'dataset_components/images/val').glob('*')))}")
    print(f"  dropped classes: {sorted(drop)}")
    print(f"  component order: {comp_order}")
    print(f"  held-out test images: {len(expected)} (expected labels in test-expected.json)")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Adapt a Roboflow YOLOv8 export for AssemblyVision")
    parser.add_argument("src", type=Path, help="Roboflow YOLOv8 export directory")
    parser.add_argument("out", type=Path, help="Output dataset directory")
    parser.add_argument("--drop-missing", action="store_true", help="Drop generic '*missing*' classes")
    parser.add_argument("--required", type=str, default="", help="Comma-separated required component classes (order = class ids)")
    args = parser.parse_args(argv)
    required = [n.strip() for n in args.required.split(",") if n.strip()] if args.required else None
    adapt(args.src, args.out, args.drop_missing, required)
    return 0


if __name__ == "__main__":
    sys.exit(main())
