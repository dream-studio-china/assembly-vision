"""Tests for the av-train CLI improvement hints."""

from __future__ import annotations

import argparse
from collections.abc import Callable
from pathlib import Path

import pytest
from assemblyvision_training import cli
from assemblyvision_training.cli import _print_improvement_hints


def test_component_hints_suggest_rule_bump(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    rule = tmp_path / "product-rule.yaml"
    rule.write_text(
        "schema_version: 1\nrule_id: demo\nrule_version: 3\n"
        "compatible_component_model_versions: [component-yolo-0.1.0]\n",
        encoding="utf-8",
    )
    _print_improvement_hints(
        "COMPONENT_DETECTION", Path("models/weights/component-yolo-0.2.0.pt"), rule
    )
    out = capsys.readouterr().out
    assert "component_detection.model_version: 'component-yolo-0.2.0'" in out
    assert "rule_version 3 -> 4" in out
    assert "'component-yolo-0.2.0'" in out


def test_product_hints_mention_roi_regeneration(capsys: pytest.CaptureFixture[str]) -> None:
    _print_improvement_hints(
        "PRODUCT_DETECTION", Path("models/weights/product-yolo-0.2.0.pt"), None
    )
    out = capsys.readouterr().out
    assert "product_detection.model_version: 'product-yolo-0.2.0'" in out
    assert "prepare-components" in out
    assert "verify" in out


def test_prepare_records_legacy_missing_label_opt_in(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    product_manifest = tmp_path / "product-manifest.json"
    product_manifest.write_text("{}", encoding="utf-8")
    calls: dict[str, object] = {}

    def validate(dataset: Path, allow_missing_labels: bool) -> object:
        calls["validated"] = (dataset, allow_missing_labels)
        return object()

    def prepare(**kwargs: object) -> None:
        calls["prepared"] = kwargs

    monkeypatch.setattr(cli, "_validate_and_record", validate)
    monkeypatch.setattr(cli, "prepare_component_dataset", prepare)
    args = argparse.Namespace(
        dataset=tmp_path / "dataset",
        allow_missing_labels=True,
        product_manifest=product_manifest,
        margin_x=0.05,
        margin_y=0.05,
        min_area=10_000,
        min_retention=0.80,
        out_dir=tmp_path / "out",
        conf=0.4,
        iou=0.6,
        device="cpu",
    )

    assert cli._run_prepare(args) == 0
    assert calls["validated"] == (args.dataset, True)
    prepared = calls["prepared"]
    assert isinstance(prepared, dict)
    assert prepared["product_manifest"] == product_manifest
    assert prepared["confidence_threshold"] == 0.4
    assert prepared["iou_threshold"] == 0.6


class _Info:
    class_names = ["product"]
    train_images = 3
    val_images = 1


def _fake_train_factory(tmp_path: Path, calls: dict[str, object]) -> Callable[..., Path]:
    def fake_train(**kwargs: object) -> Path:
        calls["project_dir"] = kwargs["project_dir"]
        calls["run_name"] = kwargs["run_name"]
        best = tmp_path / "best.pt"
        best.write_bytes(b"weights")
        return best

    return fake_train


def _monkeypatch_training(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, calls: dict[str, object]
) -> None:
    def fake_validate(dataset: Path, allow_missing_labels: bool) -> object:
        return _Info()

    def fake_place(best: Path, weights_path: Path) -> None:
        calls["weights_path"] = weights_path

    def fake_manifest(**kwargs: object) -> object:
        calls["imgsz"] = kwargs["imgsz"]
        from types import SimpleNamespace

        return SimpleNamespace(model_version_id="test-version")

    monkeypatch.setattr(cli, "_validate_and_record", fake_validate)
    monkeypatch.setattr(cli, "train_detector", _fake_train_factory(tmp_path, calls))
    monkeypatch.setattr(cli, "place_weights", fake_place)
    monkeypatch.setattr(cli, "write_manifest", fake_manifest)


def test_product_resolves_project_dir_for_relative_out_weights(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: dict[str, object] = {}
    _monkeypatch_training(monkeypatch, tmp_path, calls)
    args = argparse.Namespace(
        dataset=tmp_path / "dataset",
        allow_missing_labels=False,
        semver="1.0.0",
        out_weights=Path("models/weights/product-yolo.pt"),
        out_manifest=Path("models/manifests/product-manifest.json"),
        imgsz=640,
        rule=None,
        model_size="n",
        epochs=1,
        device="cpu",
        seed=0,
        no_augment=True,
    )
    assert cli._run_product(args) == 0
    assert calls["project_dir"] == Path("models/weights").resolve() / ".train-runs"
    assert calls["run_name"] == "product"
    assert calls["imgsz"] == 640


def test_component_resolves_project_dir_for_relative_out_weights(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: dict[str, object] = {}
    _monkeypatch_training(monkeypatch, tmp_path, calls)
    args = argparse.Namespace(
        dataset=tmp_path / "dataset",
        allow_missing_labels=False,
        semver="1.0.0",
        out_weights=Path("models/weights/component-yolo.pt"),
        out_manifest=Path("models/manifests/component-manifest.json"),
        imgsz=320,
        rule=None,
        model_size="n",
        epochs=1,
        device="cpu",
        seed=0,
        no_augment=True,
    )
    assert cli._run_component(args) == 0
    assert calls["project_dir"] == Path("models/weights").resolve() / ".train-runs"
    assert calls["run_name"] == "component"
    assert calls["imgsz"] == 320
