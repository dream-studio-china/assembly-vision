"""Readiness probe unit tests (C1a/C1b)."""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from assemblyvision_domain.errors import ConfigError
from central_service.api.readiness import (
    ReadinessCheck,
    ReadinessResult,
    probe_credentials,
    probe_object_store,
)
from central_service.api.settings import CentralSettings
from central_service.persistence.bootstrap import resolve_plan, run_bootstrap
from central_service.persistence.repository import CentralRepository
from central_service.persistence.schema import metadata
from central_service.storage.object_store import ObjectStorage
from pydantic import ValidationError
from sqlalchemy import Engine, create_engine
from sqlalchemy.pool import StaticPool

# Test fixtures carry their own credential strings; these are never real.
_ADMIN_TOKEN = "test-admin-token-0123456789abcdef"  # noqa: S105
_DEVICE_TOKEN = "test-device-token-0123456789abcdef"  # noqa: S105


def _make_settings(**overrides: object) -> CentralSettings:
    values: dict[str, object] = {"database_url": "postgresql+psycopg://u:p@h:1/db"}
    values.update(overrides)
    return CentralSettings(**values)  # type: ignore[arg-type]


def _sqlite_engine() -> Engine:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    metadata.create_all(engine)
    return engine


class _FakeStorage(ObjectStorage):
    def __init__(self, ready: bool) -> None:
        self._ready = ready

    def ensure_bucket(self) -> None:
        return None

    def bucket_ready(self) -> bool:
        return self._ready

    def put_object(self, key: str, data: bytes, content_type: str) -> None:
        return None

    def verify_object(self, key: str, size_bytes: int, checksum_sha256: str) -> None:
        return None

    def object_exists(self, key: str) -> bool:
        return False

    def remove_object(self, key: str) -> None:
        return None

    def list_objects(self, prefix: str) -> Iterator[str]:
        return iter(())

    def presigned_get_url(self, key: str, expires_seconds: int) -> str:
        return f"http://fake-store.test/{key}"

    def get_object(self, key: str) -> Iterator[bytes]:
        return iter(())


class _RaisingStorage(ObjectStorage):
    def ensure_bucket(self) -> None:
        return None

    def bucket_ready(self) -> bool:
        raise RuntimeError("storage unavailable")

    def put_object(self, key: str, data: bytes, content_type: str) -> None:
        raise RuntimeError("storage unavailable")

    def verify_object(self, key: str, size_bytes: int, checksum_sha256: str) -> None:
        raise RuntimeError("storage unavailable")

    def object_exists(self, key: str) -> bool:
        raise RuntimeError("storage unavailable")

    def remove_object(self, key: str) -> None:
        raise RuntimeError("storage unavailable")

    def list_objects(self, prefix: str) -> Iterator[str]:
        raise RuntimeError("storage unavailable")

    def presigned_get_url(self, key: str, expires_seconds: int) -> str:
        raise RuntimeError("storage unavailable")

    def get_object(self, key: str) -> Iterator[bytes]:
        raise RuntimeError("storage unavailable")


def test_probe_credentials_ok_after_bootstrap() -> None:
    engine = _sqlite_engine()
    try:
        repository = CentralRepository(engine)
        run_bootstrap(
            repository,
            resolve_plan(
                _make_settings(), admin_token=_ADMIN_TOKEN, device_upload_token=_DEVICE_TOKEN
            ),
        )
        check = probe_credentials(engine)
        assert check.ok
        assert check.name == "credentials"
    finally:
        engine.dispose()


def test_probe_credentials_fails_without_administrator() -> None:
    engine = _sqlite_engine()
    try:
        check = probe_credentials(engine)
        assert not check.ok
        assert "not bootstrapped" in check.detail
    finally:
        engine.dispose()


def test_probe_credentials_fails_when_database_unavailable() -> None:
    engine = create_engine("postgresql+psycopg://unused:unused@127.0.0.1:1/unused")
    try:
        check = probe_credentials(engine)
        assert not check.ok
        assert check.detail == "credential store unavailable"
    finally:
        engine.dispose()


def test_probe_object_store_ok() -> None:
    check = probe_object_store(_FakeStorage(ready=True))
    assert check.ok


def test_probe_object_store_fails_when_missing() -> None:
    check = probe_object_store(_FakeStorage(ready=False))
    assert not check.ok


def test_probe_object_store_fails_when_unreachable() -> None:
    check = probe_object_store(_RaisingStorage())
    assert not check.ok
    assert check.detail == "unreachable"


def test_readiness_result_requires_all_checks() -> None:
    mixed = ReadinessResult(
        checks=(
            ReadinessCheck(name="database", ok=True),
            ReadinessCheck(name="object_store", ok=False),
        )
    )
    assert not mixed.ok
    all_ok = ReadinessResult(
        checks=(
            ReadinessCheck(name="database", ok=True),
            ReadinessCheck(name="object_store", ok=True),
        )
    )
    assert all_ok.ok


@pytest.mark.parametrize(
    ("database_url", "token", "expect_error"),
    [
        ("postgresql+psycopg://u:p@h:1/db", None, False),
        ("", None, True),
        ("postgresql+psycopg://u:p@h:1/db", "short", True),
        ("sqlite:///x.db", None, True),
    ],
)
def test_settings_validation(database_url: str, token: str | None, expect_error: bool) -> None:
    if expect_error:
        with pytest.raises((ConfigError, ValidationError)):
            settings = _make_settings(database_url=database_url, admin_token=token)
            settings.validate_settings()
    else:
        settings = _make_settings(database_url=database_url, admin_token=token)
        settings.validate_settings()


def test_settings_requires_postgresql_dialect() -> None:
    with pytest.raises(ValidationError):
        _make_settings(database_url="sqlite:///x.db")


def test_settings_rejects_short_device_token() -> None:
    with pytest.raises(ConfigError):
        settings = _make_settings(device_upload_token="short")  # noqa: S106 - test credential
        settings.validate_settings()
