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


def test_train_detector_raises_when_no_weights_produced(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A missing returned artifact must fail clearly instead of silently failing."""

    class _FakeModel:
        def __init__(self, *args: object, **kwargs: object) -> None:
            pass

        def train(self, **kwargs: object) -> None:
            return None

    from assemblyvision_training import train as train_mod

    def fake_ensure_cached(model_size: str) -> Path:
        base = tmp_path / "base.pt"
        base.write_bytes(b"base")
        return base

    monkeypatch.setattr(train_mod, "_ensure_cached", fake_ensure_cached)
    monkeypatch.setattr(train_mod, "YOLO", _FakeModel)

    with pytest.raises(FileNotFoundError, match="produced no weight file"):
        train_detector(
            dataset_dir=tmp_path,
            model_size="n",
            epochs=1,
            imgsz=32,
            device="cpu",
            project_dir=tmp_path / "runs",
            run_name="empty",
        )
