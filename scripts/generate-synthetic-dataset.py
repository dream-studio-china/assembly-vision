#!/usr/bin/env python
"""Generate a realistic synthetic assembly dataset for framework testing.

Produces a YOLO-format dataset of an assembled "board" with components
(screw, chip, connector, diode) that may be present or missing. Because every
component is placed at a known location, labels are exact and free.

Output layout (ready for av-train):
  <out>/dataset_product/{images,labels}/{train,val}/   product class
  <out>/dataset_components/{images,labels}/{train,val}/ component classes
  <out>/dataset_product/data.yaml
  <out>/dataset_components/data.yaml
  <out>/test/             held-out images named ok_*.png / ng_missing_*.png

Usage:
  uv run python scripts/generate-synthetic-dataset.py /path/to/out [--n-train 30] [--n-val 8]
"""

from __future__ import annotations

import argparse
import math
import random
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

try:
    import yaml
except ImportError:  # pragma: no cover
    yaml = None  # type: ignore[assignment]

IMG_W, IMG_H = 800, 600
BOARD = (100, 70, 700, 530)  # product rectangle (x1, y1, x2, y2)

# Each component: (code, x1, y1, x2, y2) relative to no-shift base board
COMPONENTS = {
    "screw": (180, 130, 260, 210),
    "chip": (380, 150, 480, 250),
    "connector": (270, 320, 360, 410),
    "diode": (520, 330, 600, 400),
}


def _rounded_rect(
    draw: ImageDraw.ImageDraw,
    box: tuple[int, int, int, int],
    fill: tuple[int, int, int],
    radius: int = 10,
) -> None:
    x1, y1, x2, y2 = box
    draw.rounded_rectangle(box, radius=radius, fill=fill, outline=(0, 0, 0), width=2)


def _draw_board(draw: ImageDraw.ImageDraw) -> None:
    _rounded_rect(draw, BOARD, (28, 44, 74))
    draw.rectangle((BOARD[0] + 6, BOARD[1] + 6, BOARD[2] - 6, BOARD[3] - 6), fill=(40, 60, 92))
    for i in range(BOARD[0] + 12, BOARD[2] - 6, 14):
        for j in range(BOARD[1] + 12, BOARD[3] - 6, 14):
            c = 52 + (i * 7 + j * 11) % 12
            draw.point((i, j), fill=(c, c + 8, c + 16))


def _rotated_point(px: float, py: float, cx: float, cy: float, rad: float) -> tuple[float, float]:
    """Rotate a point around (cx, cy) by rad radians (image y-down)."""
    rx = (px - cx) * math.cos(rad) - (py - cy) * math.sin(rad) + cx
    ry = (px - cx) * math.sin(rad) + (py - cy) * math.cos(rad) + cy
    return rx, ry


def _rotated_aabb(
    x1: float, y1: float, x2: float, y2: float, cx: float, cy: float, rad: float
) -> tuple[float, float, float, float]:
    """Axis-aligned bounding box of a rectangle rotated around (cx, cy).

    The label must describe the drawn (rotated) shape, so both the drawing
    and the label derive from the same transform (AUDIT-001 section 6).
    """
    xs: list[float] = []
    ys: list[float] = []
    for px, py in ((x1, y1), (x2, y1), (x2, y2), (x1, y2)):
        rx, ry = _rotated_point(px, py, cx, cy, rad)
        xs.append(rx)
        ys.append(ry)
    return min(xs), min(ys), max(xs), max(ys)


def _draw_component(
    draw: ImageDraw.ImageDraw, code: str, x1: int, y1: int, x2: int, y2: int, rotation: int
) -> None:
    cx, cy = (x1 + x2) / 2, (y1 + y2) / 2
    rad = math.radians(rotation)
    pts = [
        _rotated_point(px, py, cx, cy, rad) for px, py in ((x1, y1), (x2, y1), (x2, y2), (x1, y2))
    ]
    if code == "screw":
        draw.polygon(pts, fill=(150, 150, 155), outline=(30, 30, 30))
        draw.ellipse((cx - 12, cy - 12, cx + 12, cy + 12), fill=(60, 60, 70))
        draw.line((cx - 8, cy - 8, cx + 8, cy + 8), fill=(20, 20, 20), width=3)
    elif code == "chip":
        draw.polygon(pts, fill=(25, 25, 30), outline=(5, 5, 5))
        for k in range(-4, 5, 2):
            draw.line((x1 + 6, y1 + k * 4, x1 + 6, y1 + k * 4 - 10), fill=(200, 200, 200), width=2)
    elif code == "connector":
        draw.polygon(pts, fill=(220, 220, 225), outline=(60, 60, 60))
        for k in range(4):
            draw.rectangle((x1 + 8, y1 + 8 + k * 22, x1 + 22, y1 + 20 + k * 22), fill=(30, 30, 30))
    else:  # diode
        draw.polygon(pts, fill=(90, 90, 95), outline=(20, 20, 20))
        draw.line((x1 + 10, cy, x2 - 10, cy), fill=(220, 200, 40), width=6)
        draw.polygon([(x2 - 18, cy - 10), (x2 - 18, cy + 10), (x2, cy)], fill=(220, 200, 40))


def _make_image(path: Path, present: set[str], dx: int, dy: int, rotations: dict[str, int]) -> None:
    im = Image.new("RGB", (IMG_W, IMG_H), (210, 210, 205))
    noise = Image.effect_noise((IMG_W, IMG_H), 18).convert("L")
    im = Image.blend(im, Image.merge("RGB", (noise, noise, noise)), 0.15)
    draw = ImageDraw.Draw(im)
    _draw_board(draw)
    for code, (x1, y1, x2, y2) in COMPONENTS.items():
        if code in present:
            _draw_component(draw, code, x1 + dx, y1 + dy, x2 + dx, y2 + dy, rotations[code])
    im = im.filter(ImageFilter.GaussianBlur(0.4))
    im.save(path)


def _write_labels(
    lbl_path: Path, present: set[str], dx: int, dy: int, rotations: dict[str, int]
) -> None:
    order = list(COMPONENTS)
    lines = []
    for code, (x1, y1, x2, y2) in COMPONENTS.items():
        if code in present:
            cx_px = (x1 + x2) / 2 + dx
            cy_px = (y1 + y2) / 2 + dy
            rad = math.radians(rotations[code])
            ax1, ay1, ax2, ay2 = _rotated_aabb(
                x1 + dx, y1 + dy, x2 + dx, y2 + dy, cx_px, cy_px, rad
            )
            cx = (ax1 + ax2) / 2 / IMG_W
            cy = (ay1 + ay2) / 2 / IMG_H
            w = (ax2 - ax1) / IMG_W
            h = (ay2 - ay1) / IMG_H
            lines.append(f"{order.index(code)} {cx:.6f} {cy:.6f} {w:.6f} {h:.6f}")
    lbl_path.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")


def _product_label(lbl_path: Path) -> None:
    cx = (BOARD[0] + BOARD[2]) / 2 / IMG_W
    cy = (BOARD[1] + BOARD[3]) / 2 / IMG_H
    w = (BOARD[2] - BOARD[0]) / IMG_W
    h = (BOARD[3] - BOARD[1]) / IMG_H
    lbl_path.write_text(f"0 {cx:.6f} {cy:.6f} {w:.6f} {h:.6f}\n", encoding="utf-8")


def _write_data_yaml(path: Path, names: list[str]) -> None:
    if yaml is None:
        raise RuntimeError("PyYAML is required (uv sync)")
    data = {
        "nc": len(names),
        "names": names,
        "train": "images/train",
        "val": "images/val",
    }
    path.write_text(yaml.dump(data, default_flow_style=False), encoding="utf-8")


def generate(out: Path, n_train: int, n_val: int) -> None:
    random.seed(2026)
    out.mkdir(parents=True, exist_ok=True)
    component_names = list(COMPONENTS)

    for split, _n in (("train", n_train), ("val", n_val)):
        for ds in ("dataset_product", "dataset_components"):
            (out / ds / "images" / split).mkdir(parents=True)
            (out / ds / "labels" / split).mkdir(parents=True)

    # Some training images have one component missing so the detector learns absence.
    missing_schedule = [
        None,
        None,
        None,
        None,
        None,
        None,
        None,
        None,
        {"screw"},
        None,
        {"chip"},
        None,
        {"connector"},
        None,
        {"diode"},
        None,
    ]

    idx = 0
    for split, n in (("train", n_train), ("val", n_val)):
        for i in range(n):
            dx = random.randint(-24, 24)
            dy = random.randint(-18, 18)
            rotations = {code: random.choice((-6, -3, 0, 3, 6)) for code in COMPONENTS}
            # Every schedule entry is reachable in training so each missing
            # scenario (screw/chip/connector/diode) actually occurs.
            missing = missing_schedule[i % len(missing_schedule)] if split == "train" else None
            present = set(component_names) - (missing or set())
            stem = f"img{idx:03d}"
            for ds in ("dataset_product", "dataset_components"):
                _make_image(out / ds / "images" / split / f"{stem}.png", present, dx, dy, rotations)
            _product_label(out / "dataset_product" / "labels" / split / f"{stem}.txt")
            _write_labels(
                out / "dataset_components" / "labels" / split / f"{stem}.txt",
                present,
                dx,
                dy,
                rotations,
            )
            idx += 1

    _write_data_yaml(out / "dataset_product" / "data.yaml", ["product"])
    _write_data_yaml(
        out / "dataset_components" / "data.yaml",
        component_names,
    )

    test = out / "test"
    test.mkdir(parents=True)
    for k in range(6):
        dx = random.randint(-15, 15)
        dy = random.randint(-10, 10)
        rotations = {code: random.choice((-6, -3, 0, 3, 6)) for code in COMPONENTS}
        _make_image(test / f"ok_{k:03d}.png", set(component_names), dx, dy, rotations)
        missing = set(component_names) - {random.choice(component_names)}
        _make_image(test / f"ng_missing_{k:03d}.png", missing, dx, dy, rotations)
    print(f"synthetic dataset generated under {out} ({n_train} train, {n_val} val, 12 test)")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Generate a synthetic assembly dataset")
    parser.add_argument("out", type=Path)
    parser.add_argument("--n-train", type=int, default=30)
    parser.add_argument("--n-val", type=int, default=8)
    args = parser.parse_args(argv)
    generate(args.out, args.n_train, args.n_val)
    return 0


if __name__ == "__main__":
    sys.exit(main())
