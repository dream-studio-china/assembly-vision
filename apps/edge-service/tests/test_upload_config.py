"""Upload worker configuration and app wiring tests (PR-017 F6).

Covers the supported ``serve``-style path: a configured local sink starts the
scheduler and drains the outbox, an omitted configuration leaves the scheduler
explicitly disabled and observable, and invalid upload settings fail with
actionable configuration errors.
"""

from __future__ import annotations

import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from assemblyvision_domain.errors import ConfigError
from assemblyvision_domain.models import BusinessResult
from assemblyvision_edge.api.app import create_app
from assemblyvision_edge.api.settings import ServerSettings, UploadSettings
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

    def test_invalid_upload_settings_fail_fast(self) -> None:
        """F6: invalid configuration is rejected with actionable errors."""
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
        # All-unset is a valid, explicitly disabled configuration.
        UploadSettings().validate()
