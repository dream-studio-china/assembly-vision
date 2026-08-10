"""Readiness probe unit tests (C1a)."""

from __future__ import annotations

import pytest
from assemblyvision_domain.errors import ConfigError
from central_service.api.readiness import (
    ReadinessCheck,
    ReadinessResult,
    probe_credentials,
    probe_object_store,
)
from central_service.api.settings import CentralSettings
from central_service.storage.object_store import ObjectStorage
from pydantic import ValidationError

_PILOT_TOKEN = "pilot-admin-token-0123456789abcdef"  # noqa: S105 - test fixture credential


def _make_settings(**overrides: object) -> CentralSettings:
    values: dict[str, object] = {
        "database_url": "postgresql+psycopg://u:p@h:1/db",
        "admin_token": _PILOT_TOKEN,
    }
    values.update(overrides)
    return CentralSettings(**values)  # type: ignore[arg-type]


class _FakeStorage(ObjectStorage):
    def __init__(self, ready: bool) -> None:
        self._ready = ready

    def ensure_bucket(self) -> None:
        return None

    def bucket_ready(self) -> bool:
        return self._ready


class _RaisingStorage(ObjectStorage):
    def ensure_bucket(self) -> None:
        return None

    def bucket_ready(self) -> bool:
        raise RuntimeError("storage unavailable")


def test_probe_credentials_ok() -> None:
    check = probe_credentials(_make_settings())
    assert check.ok
    assert check.name == "credentials"


def test_probe_credentials_fails_when_unset() -> None:
    check = probe_credentials(_make_settings(admin_token=None))
    assert not check.ok


def test_probe_credentials_fails_when_short() -> None:
    check = probe_credentials(
        _make_settings(admin_token="short")  # noqa: S106 - test fixture credential
    )
    assert not check.ok


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
        ("postgresql+psycopg://u:p@h:1/db", _PILOT_TOKEN, False),
        ("", _PILOT_TOKEN, True),
        ("postgresql+psycopg://u:p@h:1/db", None, False),
        ("postgresql+psycopg://u:p@h:1/db", "short", True),
        ("sqlite:///x.db", _PILOT_TOKEN, True),
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
