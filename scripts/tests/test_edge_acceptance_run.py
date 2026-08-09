"""Tests for the E6 edge acceptance runner script."""

from __future__ import annotations

import importlib.util
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

_SCRIPT = Path(__file__).resolve().parents[1] / "edge-acceptance-run.py"


def _load_runner() -> ModuleType:
    spec = importlib.util.spec_from_file_location("edge_acceptance_run", _SCRIPT)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {_SCRIPT}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


runner = _load_runner()


def _options(*, pytest_enabled: bool = True, docker_image_check_enabled: bool = True) -> Any:
    return runner.RunOptions(
        Path("."), pytest_enabled, True, True, True, docker_image_check_enabled
    )


def _environment() -> Any:
    return runner.EnvironmentEvidence(
        git_revision="abc",
        git_branch="main",
        python_version="3.13",
        uv_version="uv",
        timestamp_utc=datetime(2026, 1, 1, tzinfo=UTC),
        host_platform="test",
    )


def _lock() -> Any:
    return runner.ArtifactLock(
        state="complete",
        detail="locked",
        checksums=dict.fromkeys(runner._REQUIRED_ARTIFACT_NAMES, "sha256:abc"),
    )


def test_registry_contains_each_e6_matrix_id_exactly_once() -> None:
    ids = [item.id for item in runner.ACCEPTANCE_ITEMS]
    assert {item_id for item_id in ids if item_id.startswith("E6-")} == {
        f"E6-A{number}" for number in range(1, 28)
    }
    assert len([item_id for item_id in ids if item_id.startswith("E6-")]) == 27
    assert len(ids) == len(set(ids))


def test_registry_matrix_classifications_and_requirements() -> None:
    by_id = {item.id: item for item in runner.ACCEPTANCE_ITEMS}
    for number in (1, 2, 3, 5, 6, 7, 8, 9):
        assert by_id[f"E6-A{number}"].classification == runner.CLASS_CUSTOMER_DATA_REQUIRED
    for number in (4, 18, 20, 26, 27):
        assert by_id[f"E6-A{number}"].classification == runner.CLASS_HARDWARE_REQUIRED
    assert by_id["E6-A16"].classification == runner.CLASS_CENTRAL_REQUIRED
    for number in (*range(1, 10), 16, 18, 20, 26, 27):
        assert by_id[f"E6-A{number}"].required_environment


def test_targeted_pytest_nodes_are_explicit_and_not_gate_dependencies() -> None:
    expected = {
        "E6-A10": "apps/edge-service/tests/test_pipeline.py::test_no_product_is_failsafe_ng",
        "E6-A11": "apps/edge-service/tests/test_product_window.py::TestIdentityContinuity::test_multi_product_frame_aborts_active_window",
        "E6-A12": "apps/edge-service/tests/test_upload_scheduler.py::TestLongOutageDrain::test_prolonged_offline_inspection_restart_and_duplicate_free_drain",
        "E6-A13": "apps/edge-service/tests/test_upload_scheduler.py::TestRetryBehavior::test_network_interruption_schedules_retry",
        "E6-A14": "apps/edge-service/tests/test_upload_scheduler.py::TestCircuitBreaker::test_retryable_failures_open_circuit_and_stop_attempts",
        "E6-A15": "apps/edge-service/tests/test_upload_scheduler.py::TestRetryBehavior::test_network_interruption_schedules_retry",
        "E6-A17": "apps/edge-service/tests/test_upload_scheduler.py::TestRestartRecovery::test_restart_reclaims_and_drains",
        "E6-A19": "apps/edge-service/tests/test_retention_config.py::TestRuntimeFailSafe::test_stop_mode_forces_inspection_not_ready",
        "E6-A21": "apps/edge-service/tests/test_storage_integrity.py::TestDatabaseIntegrity::test_corrupt_database_fails_closed",
        "E6-A22": "apps/edge-service/tests/test_backup.py::test_backup_restore_round_trip_preserves_pending_evidence",
        "E6-A25": "apps/edge-service/tests/test_storage_integrity.py::TestIntegrityScan::test_checksum_mismatch_is_faulted_when_verified",
    }
    by_id = {item.id: item for item in runner.ACCEPTANCE_ITEMS}
    assert {
        item_id: item.pytest_node_ids[0] for item_id, item in by_id.items() if item.pytest_node_ids
    } == expected
    assert all(not by_id[item_id].depends_on for item_id in expected)


def test_pytest_node_runner_generates_targeted_command(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[list[str]] = []

    def fake_command(argv: list[str], **_: Any) -> Any:
        calls.append(argv)
        return runner.CommandResult(0, "", "")

    monkeypatch.setattr(runner, "run_command", fake_command)
    monkeypatch.setattr(runner, "_which", lambda _: "/usr/bin/uv")
    item = next(item for item in runner.ACCEPTANCE_ITEMS if item.id == "E6-A10")
    assert runner.run_pytest_nodes(item, _options()).status == runner.PASS
    assert calls == [["uv", "run", "pytest", *item.pytest_node_ids]]


def test_e6_a24_is_not_executed_with_honest_requirement() -> None:
    item = next(item for item in runner.ACCEPTANCE_ITEMS if item.id == "E6-A24")
    result = runner._execute_item(item, _options())
    assert result.status == runner.NOT_EXECUTED
    assert "clock-drift harness" in result.detail


def test_parse_artifact_lock_checksums_and_validates_input(tmp_path: Path) -> None:
    artifacts: list[str] = []
    for name in ("application", "product-model", "component-model", "rule", "configuration"):
        artifact = tmp_path / f"{name}.bin"
        artifact.write_bytes(b"model")
        artifacts.append(f"{name}={artifact}")
    acceptance_manifest = tmp_path / "acceptance.json"
    acceptance_manifest.write_bytes(b"manifest")
    lock = runner.parse_artifact_lock(artifacts, acceptance_manifest)
    assert lock.state == "complete"
    assert set(lock.checksums) == runner._REQUIRED_ARTIFACT_NAMES
    with pytest.raises(ValueError, match="invalid artifact"):
        runner.parse_artifact_lock(["bad name=path"], None)
    with pytest.raises(ValueError, match="does not exist"):
        runner.parse_artifact_lock(["missing=nope"], None)


def test_parse_artifact_lock_is_incomplete_without_artifacts() -> None:
    assert runner.parse_artifact_lock([], None).state == "incomplete"


def test_parse_artifact_lock_is_incomplete_when_required_artifacts_are_missing(
    tmp_path: Path,
) -> None:
    artifact = tmp_path / "application.bin"
    artifact.write_bytes(b"application")
    lock = runner.parse_artifact_lock([f"application={artifact}"], None)
    assert lock.state == "incomplete"
    assert "component-model" in lock.detail


def test_manifest_contains_required_typed_item_evidence() -> None:
    item = next(item for item in runner.ACCEPTANCE_ITEMS if item.id == "E6-A10")
    now = datetime(2026, 1, 1, tzinfo=UTC)
    manifest = runner.build_manifest(
        environment=_environment(),
        item_results=[(item, runner.RunResult("PASS", "ok", 1.5), now, now)],
        label="run-1",
        artifact_lock=_lock(),
    )
    evidence = manifest.items[0]
    assert manifest.schema_version == 2
    assert evidence.executed_assertions == list(item.pytest_node_ids)
    assert evidence.evidence_links == []
    assert evidence.artifact_checksums == dict.fromkeys(
        runner._REQUIRED_ARTIFACT_NAMES, "sha256:abc"
    )
    assert evidence.started_at == now
    assert evidence.finished_at == now


def test_write_atomic_refuses_to_clobber(tmp_path: Path) -> None:
    target = tmp_path / "evidence.json"
    runner.write_atomic(target, "first\n")
    with pytest.raises(FileExistsError):
        runner.write_atomic(target, "second\n")
    assert target.read_text(encoding="utf-8") == "first\n"
    assert list(tmp_path.glob("*.tmp")) == []


def test_exit_code_is_incomplete_for_skipped_local_gate_and_missing_artifacts() -> None:
    item = next(item for item in runner.ACCEPTANCE_ITEMS if item.id == "AUT-02")
    now = datetime.now(UTC)
    skipped = [(item, runner.RunResult("SKIP", "skipped", 0.0), now, now)]
    assert runner._exit_code(skipped, _lock()) == 2
    passed = [(item, runner.RunResult("PASS", "passed", 0.0), now, now)]
    assert runner._exit_code(passed, runner.parse_artifact_lock([], None)) == 2
    assert runner._exit_code(passed, _lock()) == 0
    failed = [(item, runner.RunResult("FAIL", "failed", 0.0), now, now)]
    assert runner._exit_code(failed, _lock()) == 1


def test_main_writes_run_specific_outputs_without_executing_gates(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    artifact_args: list[str] = []
    for name in ("application", "product-model", "component-model", "rule", "configuration"):
        artifact = tmp_path / f"{name}.bin"
        artifact.write_text("locked", encoding="utf-8")
        artifact_args.extend(["--artifact", f"{name}={artifact}"])
    acceptance_manifest = tmp_path / "acceptance.json"
    acceptance_manifest.write_text("{}", encoding="utf-8")
    now = datetime.now(UTC)
    item = next(item for item in runner.ACCEPTANCE_ITEMS if item.id == "AUT-01")
    monkeypatch.setattr(runner, "collect_environment", lambda _: _environment())
    monkeypatch.setattr(
        runner, "run_acceptance", lambda _: [(item, runner.RunResult("PASS", "ok", 0.0), now, now)]
    )
    args = [
        "--out",
        str(tmp_path),
        *artifact_args,
        "--acceptance-manifest",
        str(acceptance_manifest),
    ]
    assert runner.main(args) == 0
    assert runner.main(args) == 0
    evidence = sorted(tmp_path.glob("edge-acceptance-evidence-*.json"))
    summaries = sorted(tmp_path.glob("edge-acceptance-summary-*.txt"))
    assert len(evidence) == len(summaries) == 2
    assert (
        json.loads(evidence[0].read_text(encoding="utf-8"))["artifact_lock"]["state"] == "complete"
    )
