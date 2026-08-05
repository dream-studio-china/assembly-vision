"""YOLO detection training wrapper."""

from __future__ import annotations

import shutil
from pathlib import Path

from ultralytics import YOLO  # type: ignore[attr-defined]

_CACHE_DIR = Path("training/.cache")


def _model_path(model_size: str) -> Path:
    cache = (_CACHE_DIR / "weights").resolve()
    cache.mkdir(parents=True, exist_ok=True)
    return cache / f"yolo11{model_size}.pt"


def _ensure_cached(model_size: str) -> Path:
    path = _model_path(model_size)
    if path.is_file():
        return path
    _ = YOLO(f"yolo11{model_size}.pt")
    cwd_copy = Path(f"yolo11{model_size}.pt").resolve()
    if cwd_copy.is_file():
        shutil.move(str(cwd_copy), str(path))
    return path


def train_detector(
    *,
    dataset_dir: Path,
    model_size: str,
    epochs: int,
    imgsz: int,
    device: str,
    project_dir: Path,
    run_name: str,
) -> Path:
    """Train a YOLO detection model.

    Returns the path to the best weights file (best.pt).
    """
    model_path = _ensure_cached(model_size)
    model = YOLO(str(model_path))
    _ = model.train(
        data=str(dataset_dir / "data.yaml"),
        epochs=epochs,
        imgsz=imgsz,
        device=device,
        project=str(project_dir),
        name=run_name,
        exist_ok=True,
    )
    best_path = project_dir / run_name / "weights" / "best.pt"
    if not best_path.is_file():
        candidates = sorted((project_dir / run_name / "weights").glob("*.pt"))
        if candidates:
            return candidates[0]
        raise FileNotFoundError(f"training produced no weight file in {project_dir / run_name / 'weights'}")
    return best_path
