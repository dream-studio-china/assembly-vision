#!/usr/bin/env python
"""Adapt an X-AnyLabeling YOLO export into the AssemblyVision dataset layout.

X-AnyLabeling exports YOLO datasets as images + label files with a
``classes.txt`` (or a ``data.yaml`` with ``names``). Two directory layouts are
accepted (images-first and split-first):

  <src>/{images,labels}/{train,val,test}/      (images-first)
  <src>/{train,val,test}/{images,labels}/      (split-first)
  <src>/classes.txt  (or <src>/data.yaml)

Our pipeline needs two-stage datasets:
  dataset_product/     class "product" (an independently annotated full-product box)
  dataset_components/  the real component classes (generic "missing" classes dropped)

The design forbids training a generic missing-component class; absence is
inferred from the absence of the real component's box. A product class must be
annotated independently of the components: stage one must localize the complete
product even when a component is missing, so the product box can never be
derived from the union of present component boxes. The held-out ``test`` split
is never copied into training or validation; it becomes the verification set.

Usage:
  uv run python scripts/adapt-xanylabeling.py <src> <out> \
      [--product-class product] [--required 'chip,capacitor,boot']
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import shutil
import sys
from pathlib import Path
from typing import Any
from uuid import uuid4

try:
    import yaml
except ImportError:  # pragma: no cover
    yaml = None  # type: ignore[assignment]

_SPLIT_ALIASES = {"train": "train", "val": "val", "valid": "val", "test": "test"}
_SUPPORTED_IMAGE_SUFFIXES = frozenset({".jpg", ".jpeg", ".png", ".bmp", ".tif", ".tiff", ".webp"})


def _load_names(src: Path) -> list[str]:
    """Read class names from data.yaml 'names' or classes.txt."""
    data_yaml = src / "data.yaml"
    if data_yaml.is_file() and yaml is not None:
        raw = yaml.safe_load(data_yaml.read_text(encoding="utf-8"))
        if isinstance(raw, dict):
            names = raw.get("names")
            if isinstance(names, list) and names:
                return [str(n) for n in names]
    classes_txt = src / "classes.txt"
    if classes_txt.is_file():
        names = [
            line.strip()
            for line in classes_txt.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        if names:
            return names
    raise ValueError(
        f"cannot determine class names from {src}: provide data.yaml 'names' or classes.txt"
    )


def _resolve_layout(src: Path) -> tuple[Path, Path, list[tuple[str, str]]]:
    """Return (image_root, label_root, [(source_split, canonical_split), ...]).

    Accepts images-first (images/{split}) and split-first ({split}/images)
    layouts; ``valid`` is canonicalized to ``val``.
    """
    splits: list[tuple[str, str]] = []
    images_first = src / "images"
    if images_first.is_dir():
        label_root = src / "labels"
        for d in sorted(images_first.iterdir()):
            if d.is_dir() and d.name in _SPLIT_ALIASES:
                splits.append((d.name, _SPLIT_ALIASES[d.name]))
        return images_first, label_root, splits
    for d in sorted(src.iterdir()):
        if d.is_dir() and d.name in _SPLIT_ALIASES and (d / "images").is_dir():
            splits.append((d.name, _SPLIT_ALIASES[d.name]))
    return src, src, splits


def _parse_label_file(
    path: Path, names: list[str], img_w: int, img_h: int
) -> list[tuple[str, tuple[float, float, float, float]]]:
    """Parse one YOLO label file strictly (PR-003 P1).

    Every line must have exactly five finite fields, a class id in range, and a
    positive-area box inside the image. Any invalid source annotation rejects
    the whole adaptation instead of being silently dropped (a dropped
    annotation could otherwise become fabricated missing-component ground
    truth).
    """
    parsed: list[tuple[str, tuple[float, float, float, float]]] = []
    for lineno, line in enumerate(path.read_text(encoding="utf-8").strip().splitlines(), 1):
        line = line.strip()
        if not line:
            continue
        parts = line.split()
        if len(parts) != 5:
            raise ValueError(f"{path.name} line {lineno}: expected 5 fields, got {len(parts)}")
        try:
            cls_id = int(parts[0])
            cx, cy, w, h = (float(v) for v in parts[1:5])
        except ValueError as exc:
            raise ValueError(f"{path.name} line {lineno}: invalid numeric value: {exc}") from exc
        if not all(math.isfinite(v) for v in (cx, cy, w, h)):
            raise ValueError(f"{path.name} line {lineno}: coordinates must be finite")
        if not (0 <= cls_id < len(names)):
            raise ValueError(
                f"{path.name} line {lineno}: class id {cls_id} out of range [0, {len(names) - 1}]"
            )
        if w <= 0.0 or h <= 0.0:
            raise ValueError(f"{path.name} line {lineno}: width and height must be positive")
        x1 = (cx - w / 2) * img_w
        y1 = (cy - h / 2) * img_h
        x2 = (cx + w / 2) * img_w
        y2 = (cy + h / 2) * img_h
        eps = 1e-4
        if not (-eps <= x1 <= x2 <= img_w + eps and -eps <= y1 <= y2 <= img_h + eps):
            raise ValueError(f"{path.name} line {lineno}: box extends outside the image bounds")
        parsed.append((names[cls_id], (x1, y1, x2, y2)))
    return parsed


def _norm(
    coords: tuple[float, float, float, float], img_w: int, img_h: int
) -> tuple[float, float, float, float]:
    x1, y1, x2, y2 = coords
    cx = (x1 + x2) / 2 / img_w
    cy = (y1 + y2) / 2 / img_h
    return (cx, cy, (x2 - x1) / img_w, (y2 - y1) / img_h)


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _check_disjoint(
    checksums: dict[str, set[str]], split_a: str, split_b: str, dataset: str
) -> None:
    """Fail when two splits of one dataset share byte-identical images."""
    overlap = checksums.get(split_a, set()) & checksums.get(split_b, set())
    if overlap:
        raise ValueError(
            f"split overlap in {dataset!r} between {split_a!r} and {split_b!r}: "
            f"{len(overlap)} duplicate checksums; held-out/test data must stay disjoint from training"
        )


def _check_stem_collisions(img_dir: Path) -> None:
    """Fail when one split contains two image files with the same stem.

    Output labels are named after the image stem, so colliding stems would
    silently overwrite each other's label files and fabricate ground truth.
    """
    stems: dict[str, list[str]] = {}
    for img_path in sorted(img_dir.iterdir()):
        if not img_path.is_file() or img_path.suffix.lower() not in _SUPPORTED_IMAGE_SUFFIXES:
            continue
        stems.setdefault(img_path.stem, []).append(img_path.name)
    collisions = {stem: names for stem, names in stems.items() if len(names) > 1}
    if collisions:
        detail = "; ".join(f"{stem} -> {', '.join(names)}" for stem, names in collisions.items())
        raise ValueError(f"image stem collision in {img_dir}: {detail}")


def adapt(src: Path, out: Path, required: list[str] | None, product_class: str = "product") -> None:
    """Adapt into a staging directory and atomically publish on success."""
    _reject_non_empty(out)
    staging_dir = out.parent / f".{out.name}.staging-{uuid4().hex}"
    try:
        _adapt_into(src, staging_dir, required, product_class, reported_output=out)
        if out.exists():
            out.rmdir()
        staging_dir.rename(out)
    except Exception:
        shutil.rmtree(staging_dir, ignore_errors=True)
        raise


def _adapt_into(
    src: Path,
    out: Path,
    required: list[str] | None,
    product_class: str,
    *,
    reported_output: Path,
) -> None:
    names = _load_names(src)
    if product_class not in names:
        raise ValueError(
            f"export has no product class {product_class!r}; the two-stage pipeline requires "
            "an independently annotated full-product box (the union of component boxes is rejected)"
        )
    drop = {n for n in names if "missing" in n.lower()}
    keep = [n for n in names if n not in drop and n != product_class]

    comp_order = required if required else keep
    missing_in_data = [n for n in comp_order if n not in keep]
    if missing_in_data:
        raise ValueError(f"required component classes not present in dataset: {missing_in_data}")

    images_root, labels_root, splits = _resolve_layout(src)
    if not splits:
        raise ValueError(
            f"no train/val/test splits found in {src}; expected images/<split> or <split>/images"
        )
    canonical = [name for _, name in splits]
    if len(set(canonical)) != len(canonical):
        raise ValueError(
            "duplicate canonical splits in export; a split may appear only once "
            "(for example both 'val' and 'valid')"
        )
    if yaml is None:
        raise RuntimeError("PyYAML is required (uv sync)")

    for split in ("train", "val"):
        for ds in ("dataset_product", "dataset_components"):
            (out / ds / "images" / split).mkdir(parents=True)
            (out / ds / "labels" / split).mkdir(parents=True)

    test_img_dir = out / "test"
    test_img_dir.mkdir(parents=True)
    expected: dict[str, dict[str, Any]] = {}
    checksums: dict[str, dict[str, set[str]]] = {}
    files: dict[str, list[str]] = {"product": [], "components": [], "test": []}
    background_negatives: dict[str, int] = {"train": 0, "val": 0}
    from PIL import Image

    for src_split, split in splits:
        img_dir = (
            images_root / src_split / "images" if labels_root is src else images_root / src_split
        )
        lbl_dir = (
            labels_root / src_split / "labels" if labels_root is src else labels_root / src_split
        )
        is_test = split == "test"
        _check_stem_collisions(img_dir)
        for img_path in sorted(img_dir.iterdir()):
            if not img_path.is_file():
                continue
            lbl_path = lbl_dir / f"{img_path.stem}.txt"
            with Image.open(img_path) as handle:
                img_w, img_h = handle.size

            if not lbl_path.is_file():
                raise ValueError(
                    f"{img_path.name} has no label file; image/label pairing is required "
                    "(add an explicit empty label file for background negatives)"
                )
            parsed = _parse_label_file(lbl_path, names, img_w, img_h)
            coords: dict[str, list[tuple[float, float, float, float]]] = {n: [] for n in keep}
            for name, box in parsed:
                if name in keep:
                    coords[name].append(box)
            product_coords = [box for name, box in parsed if name == product_class]

            if is_test:
                data = img_path.read_bytes()
                (test_img_dir / img_path.name).write_bytes(data)
                files["test"].append(img_path.name)
                present = {n for n in comp_order if coords.get(n)}
                expected[img_path.name] = {
                    "ok": present == set(comp_order),
                    "present": sorted(present),
                    "missing": sorted(set(comp_order) - present),
                }
                checksums.setdefault("test", {}).setdefault("test", set()).add(_sha256_bytes(data))
                continue

            data = img_path.read_bytes()
            # Component dataset: keep every train/val image, including empty-label
            # negatives, so prepare-components can generate negative ROI crops.
            lines = []
            for i, name in enumerate(comp_order):
                for coord in coords.get(name, []):
                    n = _norm(coord, img_w, img_h)
                    lines.append(f"{i} {n[0]:.6f} {n[1]:.6f} {n[2]:.6f} {n[3]:.6f}")
            (out / "dataset_components" / "labels" / split / f"{img_path.stem}.txt").write_text(
                "\n".join(lines) + ("\n" if lines else ""), encoding="utf-8"
            )
            (out / "dataset_components" / "images" / split / img_path.name).write_bytes(data)
            files["components"].append(f"{split}/{img_path.name}")
            checksums.setdefault("components", {}).setdefault(split, set()).add(_sha256_bytes(data))

            # Product dataset: keep images with an independent full-product box,
            # plus explicit background negatives (empty annotations) with an
            # empty product label file. An image that has component labels but
            # no independent product box is a data error.
            if product_coords:
                best = _largest_product_box(product_coords)
                n = _norm(best, img_w, img_h)
                (out / "dataset_product" / "labels" / split / f"{img_path.stem}.txt").write_text(
                    f"0 {n[0]:.6f} {n[1]:.6f} {n[2]:.6f} {n[3]:.6f}\n", encoding="utf-8"
                )
            elif parsed:
                raise ValueError(
                    f"{img_path.name} has component annotations but no {product_class!r} "
                    "product box; every product image must be annotated independently"
                )
            else:
                (out / "dataset_product" / "labels" / split / f"{img_path.stem}.txt").write_text(
                    "", encoding="utf-8"
                )
                background_negatives[split] += 1
            (out / "dataset_product" / "images" / split / img_path.name).write_bytes(data)
            files["product"].append(f"{split}/{img_path.name}")
            checksums.setdefault("product", {}).setdefault(split, set()).add(_sha256_bytes(data))

    for dataset in ("components", "product"):
        _check_disjoint(checksums.get(dataset, {}), "train", "val", dataset)
    held_out = checksums.get("test", {}).get("test", set())
    for dataset in ("components", "product"):
        train_val = checksums.get(dataset, {}).get("train", set()) | checksums.get(dataset, {}).get(
            "val", set()
        )
        overlap = held_out & train_val
        if overlap:
            raise ValueError(
                f"held-out test images overlap {dataset!r} training/validation data: "
                f"{len(overlap)} duplicate checksums"
            )

    def _data(names_out: list[str], images_root_out: Path) -> dict[str, Any]:
        return {
            "nc": len(names_out),
            "names": names_out,
            "train": str((images_root_out / "train").resolve()),
            "val": str((images_root_out / "val").resolve()),
        }

    (out / "dataset_product" / "data.yaml").write_text(
        yaml.dump(_data(["product"], out / "dataset_product" / "images"), default_flow_style=False),
        encoding="utf-8",
    )
    (out / "dataset_components" / "data.yaml").write_text(
        yaml.dump(
            _data(comp_order, out / "dataset_components" / "images"), default_flow_style=False
        ),
        encoding="utf-8",
    )
    if expected:
        (out / "test-expected.json").write_text(json.dumps(expected, indent=2), encoding="utf-8")
    (out / "manifest.json").write_text(
        json.dumps(
            {
                "source": str(src),
                "product_class": product_class,
                "required_components": comp_order,
                "dropped_classes": sorted(drop),
                "files": files,
                "product_background_negatives": background_negatives,
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )

    print(f"adapted -> {reported_output}")
    print(
        f"  product:    train={len(list((out / 'dataset_product/images/train').glob('*')))} val={len(list((out / 'dataset_product/images/val').glob('*')))}"
    )
    print(
        f"  components: train={len(list((out / 'dataset_components/images/train').glob('*')))} val={len(list((out / 'dataset_components/images/val').glob('*')))}"
    )
    print(
        f"  product background negatives kept: train={background_negatives['train']} val={background_negatives['val']}"
    )
    print(f"  dropped generic missing classes: {sorted(drop)}")
    print(f"  product class: {product_class!r}; component order: {comp_order}")
    print(f"  held-out test images: {len(expected)} (expected labels in test-expected.json)")


def _reject_non_empty(directory: Path) -> None:
    """Refuse to write into a populated destination (PR-003 P2)."""
    if directory.exists() and any(directory.iterdir()):
        raise ValueError(
            f"output directory {directory} is not empty; refusing to mix a new dataset with stale files"
        )


def _largest_product_box(
    coords: list[tuple[float, float, float, float]],
) -> tuple[float, float, float, float]:
    return max(coords, key=lambda c: (c[2] - c[0]) * (c[3] - c[1]))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Adapt an X-AnyLabeling YOLO export for AssemblyVision"
    )
    parser.add_argument("src", type=Path, help="X-AnyLabeling YOLO export directory")
    parser.add_argument("out", type=Path, help="Output dataset directory")
    parser.add_argument(
        "--product-class",
        type=str,
        default="product",
        help="Name of the independently annotated full-product class (default: product)",
    )
    parser.add_argument(
        "--required",
        type=str,
        default="",
        help="Comma-separated required component classes (order = class ids)",
    )
    args = parser.parse_args(argv)
    required = [n.strip() for n in args.required.split(",") if n.strip()] if args.required else None
    adapt(args.src, args.out, required, args.product_class)
    return 0


if __name__ == "__main__":
    sys.exit(main())
