"""Tests for the assemblyvision CLI dispatch and sad paths."""

from __future__ import annotations

import argparse
from pathlib import Path
from uuid import uuid4

import pytest
from assemblyvision_domain.errors import ConfigError
from assemblyvision_domain.models import BusinessResult, InspectionRecord
from assemblyvision_edge import cli

_RECORD_ID = "00000000-0000-4000-8000-0000000000dd"


class _FakePipeline:
    def __init__(self) -> None:
        self.ran: list[str] = []

    def inspect_image(self, source: object, path: Path, writer: object) -> InspectionRecord:
        self.ran.append(str(path))
        return _record_for(
            argparse.Namespace(inspection_id=str(uuid4()), business_result=BusinessResult.OK)
        )


def _record_for(args: argparse.Namespace) -> InspectionRecord:
    from datetime import UTC, datetime

    from assemblyvision_domain.models import (
        BarcodeResult,
        FrameQualitySummary,
        InspectionDecision,
        InspectionLifecycle,
        InternalDecision,
        ProductResolution,
    )

    now = datetime.now(UTC)
    return InspectionRecord(
        inspection_id=args.inspection_id,
        device_id=uuid4(),
        device_sequence=1,
        lifecycle_status=InspectionLifecycle.COMPLETED,
        started_at=now,
        completed_at=now,
        barcode_result=BarcodeResult(status="NOT_REQUIRED"),
        product_resolution=ProductResolution(
            status="RESOLVED", source="CONFIGURED_DEFAULT", product_code="model_a"
        ),
        frame_quality_summary=FrameQualitySummary(
            total_frame_count=1, usable_frame_count=1, rejected_frame_count=0
        ),
        application_version="0.1.0",
        product_model_version_id=uuid4(),
        product_model_checksum_sha256="0" * 64,
        component_model_version_id=uuid4(),
        component_model_checksum_sha256="0" * 64,
        rule_version_id=uuid4(),
        aggregation_policy_version="single-frame-mvp-1",
        evidence=[],
        decision=InspectionDecision(
            internal_decision=InternalDecision.OK,
            business_result=args.business_result,
            decided_at=now,
        ),
        synchronization_status="LOCAL_ONLY",
        processing_ms=1,
    )


def test_main_requires_subcommand() -> None:
    with pytest.raises(SystemExit) as exc_info:
        cli.main([])
    assert exc_info.value.code == 2


def test_main_unknown_command() -> None:
    with pytest.raises(SystemExit):
        cli.main(["frobnicate"])


def test_main_dispatches_serve(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    called: dict[str, object] = {}

    def fake_serve(args: argparse.Namespace) -> int:
        called["args"] = args
        return 7

    monkeypatch.setattr(cli, "_run_serve", fake_serve)
    assert cli.main(["serve", "--output", str(tmp_path)]) == 7
    assert called["args"].command == "serve"  # type: ignore[attr-defined]


def test_main_dispatches_inspect(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cli, "_run_inspect", lambda args: 3)
    assert (
        cli.main(
            ["inspect", "img.png", "--config", "c.yaml", "--rule", "r.yaml", "--output", "out"]
        )
        == 3
    )


def test_main_dispatches_verify(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cli, "_run_verify", lambda args: 4)
    assert (
        cli.main(["verify", "img.png", "--config", "c.yaml", "--rule", "r.yaml", "--output", "out"])
        == 4
    )


def test_inspect_returns_2_on_config_error(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def broken(args: object) -> object:
        raise ConfigError("bad config")

    monkeypatch.setattr(cli, "_build_pipeline", broken)
    args = argparse.Namespace(
        quiet=True, config=tmp_path / "c.yaml", rule=tmp_path / "r.yaml", output=tmp_path / "out"
    )
    assert cli._run_inspect(args) == 2


def test_inspect_returns_2_on_rule_config_mismatch(tmp_path: Path) -> None:
    from tests.conftest import EXAMPLE_PIPELINE

    rule = tmp_path / "rule.yaml"
    rule.write_text(
        "schema_version: 1\n"
        "rule_id: model-a-presence\n"
        "rule_version: 4\n"
        "product_type: model_a\n"
        "compatible_component_model_versions: [component-yolo-1.0.0]\n"
        "barcode_required: false\n"
        "required_components:\n"
        "  ghost:\n"
        "    expected_count: 1\n"
        "mandatory_gates:\n"
        "  product_detected: true\n"
        "  roi_valid: true\n"
        "  minimum_valid_frames_met: true\n",
        encoding="utf-8",
    )
    args = argparse.Namespace(
        quiet=True,
        config=EXAMPLE_PIPELINE,
        rule=rule,
        output=tmp_path / "out",
        paths=[str(tmp_path / "img.png")],
        device_id=None,
    )
    assert cli._run_inspect(args) == 2


def test_inspect_runs_and_counts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    image = tmp_path / "a.png"
    image.touch()
    pipeline = _FakePipeline()

    class _NgPipeline:
        def inspect_image(self, source: object, path: Path, writer: object) -> InspectionRecord:
            return _record_for(
                argparse.Namespace(inspection_id=str(uuid4()), business_result=BusinessResult.NG)
            )

    monkeypatch.setattr(cli, "_build_pipeline", lambda args: pipeline)
    args = argparse.Namespace(
        quiet=True,
        config=tmp_path / "c.yaml",
        rule=tmp_path / "r.yaml",
        output=tmp_path / "out",
        paths=[str(image)],
    )
    assert cli._run_inspect(args) == 0
    out = capsys.readouterr().out
    assert "a.png" in out

    # NG-only result still returns 0 (errors, not NG, decide the exit code).
    monkeypatch.setattr(cli, "_build_pipeline", lambda args: _NgPipeline())
    assert cli._run_inspect(args) == 0


def test_inspect_returns_1_on_pipeline_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    image = tmp_path / "a.png"
    image.touch()

    class _RaisingPipeline:
        def inspect_image(self, source: object, path: Path, writer: object) -> InspectionRecord:
            from assemblyvision_domain.errors import OutputError

            raise OutputError("cannot write")

    monkeypatch.setattr(cli, "_build_pipeline", lambda args: _RaisingPipeline())
    args = argparse.Namespace(
        quiet=True,
        config=tmp_path / "c.yaml",
        rule=tmp_path / "r.yaml",
        output=tmp_path / "out",
        paths=[str(image)],
    )
    assert cli._run_inspect(args) == 1


def test_verify_returns_2_on_config_error(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        cli, "_build_pipeline", lambda args: (_ for _ in ()).throw(ValueError("boom"))
    )
    args = argparse.Namespace(
        quiet=True,
        config=tmp_path / "c.yaml",
        rule=tmp_path / "r.yaml",
        output=tmp_path / "out",
        expected=None,
    )
    assert cli._run_verify(args) == 2


def test_collect_sources_dir_and_file(tmp_path: Path) -> None:
    (tmp_path / "dir").mkdir()
    (tmp_path / "dir" / "one.png").touch()
    (tmp_path / "dir" / "two.png").touch()
    (tmp_path / "single.png").touch()
    work = cli._collect_sources([str(tmp_path / "dir"), str(tmp_path / "single.png")])
    names = [path.name for _, path in work]
    assert set(names) == {"one.png", "two.png", "single.png"}


def test_serve_returns_2_when_create_app_raises(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def boom(settings: object) -> object:
        raise ConfigError("no pipeline")

    monkeypatch.setattr("assemblyvision_edge.api.app.create_app", boom)
    args = argparse.Namespace(
        output=tmp_path,
        db=None,
        config=None,
        rule=None,
        device_id=None,
        static=None,
        host="127.0.0.1",
        port=8000,
        api_token=None,
    )
    assert cli._run_serve(args) == 2


def test_main_module_runs(tmp_path: Path) -> None:
    import subprocess
    import sys

    result = subprocess.run(
        [sys.executable, "-m", "assemblyvision_edge", "--help"],
        capture_output=True,
        text=True,
        cwd=str(Path(__file__).resolve().parents[2]),
        env={"PATH": "/usr/bin:/bin"},
    )
    assert result.returncode == 0
    assert "usage" in result.stdout.lower()


def test_build_pipeline_success(monkeypatch: pytest.MonkeyPatch) -> None:
    from types import SimpleNamespace

    manifest = object()
    detector = object()
    pipeline = object()

    config = SimpleNamespace(
        product_manifest="product.json",
        component_manifest="component.json",
        product_detection=SimpleNamespace(model_version="product-yolo-1.0.0"),
        component_detection=SimpleNamespace(model_version="component-yolo-1.0.0"),
        components={"component_a": SimpleNamespace()},
        roi=object(),
    )

    monkeypatch.setattr(cli, "load_pipeline_config", lambda p: config)
    monkeypatch.setattr(cli, "load_rule_definition", lambda p: object())
    monkeypatch.setattr(cli, "load_model_manifest", lambda p: manifest)
    monkeypatch.setattr(cli, "validate_model_version_declaration", lambda *a, **k: None)
    monkeypatch.setattr(cli, "validate_rule_component_compatibility", lambda *a, **k: None)
    monkeypatch.setattr(
        cli, "ProductDetector", type("PD", (), {"from_manifest": lambda *a, **k: detector})
    )
    monkeypatch.setattr(
        cli, "ComponentDetector", type("CD", (), {"from_manifest": lambda *a, **k: detector})
    )
    monkeypatch.setattr(cli, "ROIEngine", lambda config: object())
    monkeypatch.setattr(cli, "InspectionPipeline", lambda **kwargs: pipeline)
    monkeypatch.setattr(cli, "RuleEngine", lambda: object())

    from pathlib import Path

    args = argparse.Namespace(config=Path("c.yaml"), rule=Path("r.yaml"), device_id=str(uuid4()))
    assert cli._build_pipeline(args) is pipeline


def test_verify_success_and_failure_paths(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from types import SimpleNamespace

    image = tmp_path / "a.png"
    image.touch()
    monkeypatch.setattr(cli, "_build_pipeline", lambda args: object())
    monkeypatch.setattr(cli, "load_expected", lambda path: {})
    monkeypatch.setattr(
        cli, "run_verify", lambda *a, **k: SimpleNamespace(false_negative=0, has_gaps=False)
    )
    monkeypatch.setattr(cli, "format_per_image", lambda report: "per-image")
    monkeypatch.setattr(cli, "format_report", lambda report: "report")

    args = argparse.Namespace(
        quiet=True,
        config=tmp_path / "c.yaml",
        rule=tmp_path / "r.yaml",
        output=tmp_path / "out",
        expected=None,
        paths=[str(image)],
    )
    assert cli._run_verify(args) == 0

    monkeypatch.setattr(
        "assemblyvision_edge.cli.run_verify",
        lambda *a, **k: SimpleNamespace(false_negative=1, has_gaps=True),
    )
    assert cli._run_verify(args) == 1


def test_verify_disables_filename_fallback_when_expected_supplied(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from types import SimpleNamespace

    image = tmp_path / "ng_old.png"
    image.touch()
    expected = tmp_path / "expected.json"
    expected.write_text('{"a.png": {"ok": true}}', encoding="utf-8")
    monkeypatch.setattr(cli, "_build_pipeline", lambda args: object())
    calls: dict[str, object] = {}

    def fake_run_verify(*args: object, **kwargs: object) -> object:
        calls["kwargs"] = kwargs
        return SimpleNamespace(false_negative=0, has_gaps=False)

    monkeypatch.setattr(cli, "run_verify", fake_run_verify)
    monkeypatch.setattr(cli, "load_expected", lambda p: {"a.png": object()})
    monkeypatch.setattr(cli, "format_per_image", lambda report: "")
    monkeypatch.setattr(cli, "format_report", lambda report: "")

    args = argparse.Namespace(
        quiet=True,
        config=tmp_path / "c.yaml",
        rule=tmp_path / "r.yaml",
        output=tmp_path / "out",
        expected=expected,
        paths=[str(image)],
    )
    assert cli._run_verify(args) == 0
    kwargs = calls["kwargs"]
    assert isinstance(kwargs, dict)
    assert kwargs.get("filename_fallback") is False


def test_serve_success_starts_uvicorn(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[dict[str, object]] = []

    def fake_run(app: object, **kwargs: object) -> None:
        calls.append(kwargs)

    monkeypatch.setattr("uvicorn.run", fake_run)
    monkeypatch.setattr("assemblyvision_edge.api.app.create_app", lambda settings: object())
    args = argparse.Namespace(
        output=tmp_path,
        db=None,
        config=None,
        rule=None,
        device_id=None,
        static=None,
        host="127.0.0.1",
        port=8000,
        api_token=None,
    )
    assert cli._run_serve(args) == 0
    assert calls and calls[0]["port"] == 8000
