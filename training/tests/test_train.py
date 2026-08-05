"""Training dry-run test on synthetic YOLO data (1 epoch, CPU)."""

from __future__ import annotations

from pathlib import Path

import pytest
from assemblyvision_training.train import train_detector


@pytest.mark.slow
def test_training_dry_run_on_synthetic(yolo_dataset_dir: Path, tmp_path: Path) -> None:
    """Verify that training runs without crashing on a tiny synthetic dataset."""
    project = tmp_path / "runs"
    best = train_detector(
        dataset_dir=yolo_dataset_dir,
        model_size="n",
        epochs=1,
        imgsz=32,
        device="cpu",
        project_dir=project,
        run_name="dry-run",
    )
    assert best.is_file()
    assert best.stat().st_size > 0
