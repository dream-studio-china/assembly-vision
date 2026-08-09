"""E2c storage pressure and fail-safe runtime tests (task E2c exit criteria).

Covers threshold validation, pressure-mode derivation for bytes and inodes,
the STOP fail-safe gate on device status, CLI environment parsing, and the
composition-root validation of storage/retention settings.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from assemblyvision_domain.errors import ConfigError
from assemblyvision_edge.api.settings import RetentionSettings, StorageSettings
from assemblyvision_edge.cli import _build_retention_settings, _build_storage_settings
from assemblyvision_edge.retention.storage import (
    PressureMode,
    StorageState,
    observe_storage,
)

from tests.test_state import _fake_pipeline, _settings


def _state(mode: PressureMode) -> StorageState:
    return StorageState(
        mode=mode,
        free_bytes=10,
        total_bytes=100,
        free_percent=10.0,
        free_inodes=10,
        total_inodes=100,
        inode_free_percent=10.0,
        warning_free_percent=20.0,
        critical_free_percent=10.0,
        stop_free_percent=5.0,
        observed_at="2026-06-01T12:00:00+00:00",
    )


class TestThresholdValidation:
    def test_strict_ordering_required(self) -> None:
        StorageSettings(20.0, 10.0, 5.0).validate()
        with pytest.raises(ConfigError, match="stop < critical < warning"):
            StorageSettings(5.0, 10.0, 20.0).validate()  # swapped
        with pytest.raises(ConfigError, match="stop < critical < warning"):
            StorageSettings(20.0, 20.0, 5.0).validate()  # equal
        with pytest.raises(ConfigError, match="stop < critical < warning"):
            StorageSettings(120.0, 10.0, 5.0).validate()  # out of range

    def test_retention_settings_require_positive_durations_when_enabled(self) -> None:
        from datetime import timedelta

        RetentionSettings(enabled=False, durations={"KEY_FRAME": timedelta(seconds=0)}).validate()
        with pytest.raises(ConfigError, match="positive"):
            RetentionSettings(
                enabled=True, durations={"KEY_FRAME": timedelta(seconds=0)}
            ).validate()
        with pytest.raises(ConfigError, match="at least one"):
            RetentionSettings(enabled=True, durations={}).validate()


class TestObserveStorage:
    def test_mode_from_free_bytes(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        import shutil
        from types import SimpleNamespace

        calls = {"free": 25}

        monkeypatch.setattr(
            shutil,
            "disk_usage",
            lambda _p: SimpleNamespace(total=100, free=calls["free"], used=100 - calls["free"]),
        )
        monkeypatch.setattr(
            "assemblyvision_edge.retention.storage.os.statvfs",
            lambda _p: SimpleNamespace(f_files=100, f_ffree=90),
        )

        settings = StorageSettings(20.0, 10.0, 5.0)
        for free, expected in [(25, "NORMAL"), (15, "WARNING"), (8, "CRITICAL"), (3, "STOP")]:
            calls["free"] = free
            assert observe_storage(tmp_path, settings).mode == expected

    def test_mode_from_free_inodes(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        import shutil
        from types import SimpleNamespace

        calls = {"inodes": 90}
        monkeypatch.setattr(
            shutil,
            "disk_usage",
            lambda _p: SimpleNamespace(total=100, free=90, used=10),
        )
        monkeypatch.setattr(
            "assemblyvision_edge.retention.storage.os.statvfs",
            lambda _p: SimpleNamespace(f_files=100, f_ffree=calls["inodes"]),
        )
        settings = StorageSettings(20.0, 10.0, 5.0)
        for inode_free, expected in [(25, "NORMAL"), (7, "CRITICAL"), (2, "STOP")]:
            calls["inodes"] = inode_free
            assert observe_storage(tmp_path, settings).mode == expected

    def test_measurement_failure_raises(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import shutil

        monkeypatch.setattr(shutil, "disk_usage", lambda _p: (_ for _ in ()).throw(OSError("boom")))
        from assemblyvision_edge.retention.storage import StorageObservationError

        with pytest.raises(StorageObservationError):
            observe_storage(tmp_path, StorageSettings())


class TestRuntimeFailSafe:
    def test_stop_mode_forces_inspection_not_ready(self, tmp_path: Path) -> None:
        from assemblyvision_edge.api.state import EdgeRuntime

        runtime = EdgeRuntime(_settings(tmp_path))
        runtime.pipeline = _fake_pipeline()
        status = runtime.device_status(upload_pending=0, storage=_state("STOP"), write_fault=False)
        assert status["inspection_ready"] is False
        assert status["storage_mode"] == "STOP"
        assert "DISK_STOP" in status["alerts"]
        assert "NOT_READY" in status["alerts"]

    def test_critical_and_warning_modes_do_not_block_inspection(self, tmp_path: Path) -> None:
        from assemblyvision_edge.api.state import EdgeRuntime

        runtime = EdgeRuntime(_settings(tmp_path))
        runtime.pipeline = _fake_pipeline()
        critical = runtime.device_status(upload_pending=0, storage=_state("CRITICAL"))
        assert critical["inspection_ready"] is True
        assert "DISK_CRITICAL" in critical["alerts"]
        warning = runtime.device_status(upload_pending=0, storage=_state("WARNING"))
        assert warning["inspection_ready"] is True
        assert "DISK_WARNING" in warning["alerts"]

    def test_write_fault_forces_inspection_not_ready(self, tmp_path: Path) -> None:
        from assemblyvision_edge.api.state import EdgeRuntime

        runtime = EdgeRuntime(_settings(tmp_path))
        runtime.pipeline = _fake_pipeline()
        status = runtime.device_status(upload_pending=0, storage=_state("NORMAL"), write_fault=True)
        assert status["inspection_ready"] is False
        assert "STORAGE_WRITE_FAULT" in status["alerts"]

    def test_cleanup_fault_alert_from_delete_errors(self, tmp_path: Path) -> None:
        from assemblyvision_edge.api.state import EdgeRuntime
        from assemblyvision_edge.persistence.repository import RetentionMetrics
        from assemblyvision_edge.retention.worker import CleanupHealth

        runtime = EdgeRuntime(_settings(tmp_path))
        runtime.pipeline = _fake_pipeline()
        status = runtime.device_status(
            upload_pending=0,
            storage=_state("NORMAL"),
            cleanup=CleanupHealth(runs=1, purged_count=0, reclaimed_bytes=0, failure_count=1),
            cleanup_metrics=RetentionMetrics(
                eligible_count=0,
                eligible_bytes=0,
                deleting_count=0,
                delete_error_count=2,
                purged_count=0,
            ),
            cleanup_enabled=True,
        )
        assert status["cleanup_enabled"] is True
        assert status["cleanup_delete_error_count"] == 2
        assert "CLEANUP_FAULT" in status["alerts"]


class TestCliBuilders:
    def test_storage_env_validation(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("AV_EDGE_STORAGE_WARNING_FREE_PERCENT", "30")
        monkeypatch.setenv("AV_EDGE_STORAGE_CRITICAL_FREE_PERCENT", "15")
        monkeypatch.setenv("AV_EDGE_STORAGE_STOP_FREE_PERCENT", "5")
        settings = _build_storage_settings()
        assert settings is not None
        assert settings.warning_free_percent == 30.0
        assert settings.critical_free_percent == 15.0
        with pytest.raises(ConfigError, match="stop < critical < warning"):
            monkeypatch.setenv("AV_EDGE_STORAGE_STOP_FREE_PERCENT", "40")
            _build_storage_settings()

    def test_retention_env_requires_enabled_and_parses_durations(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("AV_EDGE_RETENTION_ENABLED", raising=False)
        monkeypatch.delenv("AV_EDGE_RETENTION_DURATIONS", raising=False)
        assert _build_retention_settings() is None

        monkeypatch.setenv("AV_EDGE_RETENTION_ENABLED", "true")
        monkeypatch.setenv("AV_EDGE_RETENTION_DURATIONS", '{"KEY_FRAME": "1d", "NG_CLIP": "30m"}')
        settings = _build_retention_settings()
        assert settings is not None
        assert settings.enabled is True
        assert settings.durations["KEY_FRAME"].total_seconds() == 86400
        assert settings.durations["NG_CLIP"].total_seconds() == 1800

        monkeypatch.setenv("AV_EDGE_RETENTION_DURATIONS", '{"KEY_FRAME": "1x"}')
        with pytest.raises(ConfigError, match="invalid duration"):
            _build_retention_settings()

    def test_retention_enabled_without_durations_is_rejected(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("AV_EDGE_RETENTION_ENABLED", "true")
        monkeypatch.delenv("AV_EDGE_RETENTION_DURATIONS", raising=False)
        with pytest.raises(ConfigError, match="at least one"):
            _build_retention_settings()


class TestCompositionRoot:
    def test_programmatic_invalid_storage_settings_fail_fast(self, tmp_path: Path) -> None:
        from assemblyvision_edge.api.app import create_app

        with pytest.raises(ConfigError):
            create_app(_settings(tmp_path, storage=StorageSettings(5.0, 10.0, 20.0)))

    def test_cleanup_worker_disabled_without_policy(self, tmp_path: Path) -> None:
        from assemblyvision_edge.api.app import create_app
        from fastapi.testclient import TestClient

        app = create_app(_settings(tmp_path, retention=None))
        with TestClient(app) as client:
            status = client.get("/api/v1/device/status").json()
        assert status["cleanup_enabled"] is False
        assert "storage_mode" in status

    def test_cleanup_worker_enabled_with_policy(self, tmp_path: Path) -> None:
        from datetime import timedelta

        from assemblyvision_edge.api.app import create_app
        from fastapi.testclient import TestClient

        retention = RetentionSettings(enabled=True, durations={"KEY_FRAME": timedelta(days=1)})
        app = create_app(_settings(tmp_path, retention=retention))
        with TestClient(app) as client:
            status = client.get("/api/v1/device/status").json()
        assert status["cleanup_enabled"] is True
