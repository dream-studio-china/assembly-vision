"""Upload worker configuration and app wiring tests (PR-017 F6).

Covers the supported ``serve``-style path: a configured local sink starts the
scheduler and drains the outbox, an omitted configuration leaves the scheduler
explicitly disabled and observable, and invalid upload settings fail with
actionable configuration errors.
"""

from __future__ import annotations

import argparse
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from assemblyvision_domain.errors import ConfigError
from assemblyvision_domain.models import BusinessResult
from assemblyvision_edge.api.app import create_app
from assemblyvision_edge.api.settings import ServerSettings, UploadSettings
from assemblyvision_edge.cli import _build_upload_settings
from assemblyvision_edge.persistence.repository import EdgeRepository
from fastapi.testclient import TestClient

from tests.test_api import _record
from tests.test_upload_scheduler import _write_bundle, _write_media


def _state(app: Any, key: str) -> Any:
    """Read an attribute set on the FastAPI app state at lifespan startup."""
    return getattr(app.state, key)


def _settings(tmp_path: Path, *, upload: UploadSettings | None) -> ServerSettings:
    return ServerSettings(
        output_root=tmp_path,
        db_path=tmp_path / "edge.sqlite3",
        upload=upload,
    )


def _wait_drained(repository: EdgeRepository, timeout_seconds: float = 5.0) -> None:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        tasks = repository.list_uploads(limit=100).items
        if tasks and all(task.status == "SUCCEEDED" for task in tasks):
            return
        time.sleep(0.05)
    raise AssertionError("upload tasks were not drained within the timeout")


class TestServeWiring:
    def test_local_sink_app_starts_worker_and_drains(self, tmp_path: Path) -> None:
        """F6: a configured local sink drains a reconciled bundle end to end."""
        record = _record(datetime.now(UTC), business=BusinessResult.OK, barcode="SN-serve")
        _write_media(tmp_path, record)
        _write_bundle(tmp_path, record)
        upload = UploadSettings(
            sink_dir=tmp_path / "sink",
            interval_seconds=0.05,
            batch_size=4,
        )
        app = create_app(_settings(tmp_path, upload=upload))
        with TestClient(app):
            repository = _state(app, "repository")
            scheduler = _state(app, "upload_scheduler")
            assert scheduler is not None
            _wait_drained(repository)
            tasks = repository.list_uploads(limit=100).items
            assert len(tasks) == 2
            assert all(task.status == "SUCCEEDED" for task in tasks)
            inspection = repository.get_inspection(str(record.inspection_id))
            assert inspection is not None
            assert inspection.synchronization_status == "SYNCED"
        assert (tmp_path / "sink" / "inspection").is_dir()

    def test_omitted_config_leaves_scheduler_disabled_and_observable(self, tmp_path: Path) -> None:
        """F6: without a sink or endpoint the worker stays off and tasks queue."""
        record = _record(datetime.now(UTC), business=BusinessResult.OK, barcode="SN-off")
        _write_media(tmp_path, record)
        _write_bundle(tmp_path, record)
        app = create_app(_settings(tmp_path, upload=None))
        with TestClient(app):
            assert _state(app, "upload_scheduler") is None
            repository = _state(app, "repository")
            tasks = repository.list_uploads(limit=100).items
            assert len(tasks) == 2
            assert all(task.status == "PENDING" for task in tasks)

    def test_logs_endpoint_captures_application_records(self, tmp_path: Path) -> None:
        """E1: after a fresh migration the LogBuffer captures application logs.

        Alembic's fileConfig used to disable every assemblyvision.* logger, so
        the app's own warnings never reached /api/v1/logs on a new database.
        """
        record = _record(datetime.now(UTC), business=BusinessResult.OK, barcode="SN-log")
        _write_media(tmp_path, record)
        _write_bundle(tmp_path, record)
        app = create_app(_settings(tmp_path, upload=None))
        with TestClient(app) as client:
            logs = client.get("/api/v1/logs").json()
            messages = [item["message"] for item in logs["items"]]
        assert any("upload scheduler is disabled" in message for message in messages)

    def test_device_status_exposes_upload_observability(self, tmp_path: Path) -> None:
        """E1: device status carries queue bytes/age and worker liveness."""
        record = _record(datetime.now(UTC), business=BusinessResult.OK, barcode="SN-metric")
        _write_media(tmp_path, record)
        _write_bundle(tmp_path, record)
        app = create_app(_settings(tmp_path, upload=None))
        with TestClient(app) as client:
            status = client.get("/api/v1/device/status").json()
        assert status["upload_pending_count"] == 2
        assert status["upload_pending_bytes"] > 0
        assert status["upload_oldest_pending_at"] is not None
        assert status["upload_attempts"] == 0
        assert status["upload_successes"] == 0
        assert status["upload_failure_rate"] == 0.0
        assert status["upload_last_error_code"] is None
        # Queued tasks with no worker are an explicit alert, not silent backlog.
        assert "UPLOAD_BLOCKED" in status["alerts"]

    def test_invalid_upload_settings_fail_fast(self) -> None:
        """F6/F7: invalid configuration is rejected with actionable errors."""
        with pytest.raises(ConfigError, match="mutually exclusive"):
            UploadSettings(
                base_url="https://central.invalid", sink_dir=Path("local-sink")
            ).validate()
        with pytest.raises(ConfigError, match="connect_timeout_seconds"):
            UploadSettings(connect_timeout_seconds=0).validate()
        with pytest.raises(ConfigError, match="request_timeout_seconds"):
            UploadSettings(request_timeout_seconds=-1).validate()
        with pytest.raises(ConfigError, match="batch_size"):
            UploadSettings(batch_size=0).validate()
        with pytest.raises(ConfigError, match="lease_seconds"):
            UploadSettings(lease_seconds=0).validate()
        with pytest.raises(ConfigError, match="maximum_retry_seconds"):
            UploadSettings(base_retry_seconds=10.0, maximum_retry_seconds=5.0).validate()
        with pytest.raises(ConfigError, match="maximum_bandwidth_mbps"):
            UploadSettings(maximum_bandwidth_mbps=-1.0).validate()
        with pytest.raises(ConfigError, match="circuit_failure_threshold"):
            UploadSettings(circuit_failure_threshold=0).validate()
        with pytest.raises(ConfigError, match="circuit_open_seconds"):
            UploadSettings(circuit_open_seconds=0).validate()
        with pytest.raises(ConfigError, match="media_chunk_bytes"):
            UploadSettings(media_chunk_bytes=0).validate()
        # All-unset is a valid, explicitly disabled configuration.
        UploadSettings().validate()

    def test_plaintext_upload_url_rejected_without_dev_flag(self) -> None:
        """F7: inspection evidence must not travel over plaintext http."""
        with pytest.raises(ConfigError, match="https"):
            UploadSettings(base_url="http://central.invalid").validate()
        # The explicit development flag permits HTTP for loopback testing only.
        with pytest.raises(ConfigError, match="loopback"):
            UploadSettings(base_url="http://central.invalid", allow_insecure_http=True).validate()
        UploadSettings(base_url="http://localhost:9000", allow_insecure_http=True).validate()
        # HTTPS is the supported production form.
        UploadSettings(base_url="https://central.invalid").validate()

    def test_malformed_upload_url_rejected(self) -> None:
        """F7: endpoints without a host or with embedded credentials fail."""
        with pytest.raises(ConfigError, match="non-empty host"):
            UploadSettings(base_url="https:///missing-host").validate()
        with pytest.raises(ConfigError, match="must not embed credentials"):
            UploadSettings(base_url="https://user:pass@central.invalid").validate()

    def test_composition_root_revalidates_programmatic_upload_settings(
        self, tmp_path: Path
    ) -> None:
        """F7 follow-up: direct create_app callers cannot bypass the TLS policy."""
        insecure = UploadSettings(base_url="http://central.invalid", allow_insecure_http=True)
        with pytest.raises(ConfigError, match="loopback"):
            create_app(_settings(tmp_path, upload=insecure))

    def test_zero_bandwidth_environment_value_is_rejected(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """F6 follow-up: an explicit zero is invalid, not an omitted bound."""
        monkeypatch.setenv("AV_EDGE_UPLOAD_MAXIMUM_BANDWIDTH_MBPS", "0")
        args = argparse.Namespace(
            upload_base_url="https://central.invalid",
            upload_sink_dir=None,
            upload_insecure_http=False,
        )
        with pytest.raises(ConfigError, match="maximum_bandwidth_mbps"):
            _build_upload_settings(args)

    def test_circuit_and_chunk_environment_values_are_parsed(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """PR-022 F03/P2: E3b/E3e environment values reach the settings."""
        monkeypatch.setenv("AV_EDGE_UPLOAD_CIRCUIT_FAILURE_THRESHOLD", "3")
        monkeypatch.setenv("AV_EDGE_UPLOAD_CIRCUIT_OPEN_SECONDS", "15")
        monkeypatch.setenv("AV_EDGE_UPLOAD_MEDIA_CHUNK_BYTES", "1048576")
        args = argparse.Namespace(
            upload_base_url="https://central.invalid",
            upload_sink_dir=None,
            upload_insecure_http=False,
        )
        settings = _build_upload_settings(args)
        assert settings is not None
        assert settings.circuit_failure_threshold == 3
        assert settings.circuit_open_seconds == 15.0
        assert settings.media_chunk_bytes == 1_048_576

    def test_invalid_circuit_environment_values_are_rejected(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("AV_EDGE_UPLOAD_CIRCUIT_OPEN_SECONDS", "0")
        args = argparse.Namespace(
            upload_base_url="https://central.invalid",
            upload_sink_dir=None,
            upload_insecure_http=False,
        )
        with pytest.raises(ConfigError, match="circuit_open_seconds"):
            _build_upload_settings(args)
