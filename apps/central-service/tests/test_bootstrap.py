"""Pilot bootstrap unit tests (C1b)."""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from central_service.api.settings import CentralSettings
from central_service.persistence.bootstrap import (
    BootstrapError,
    resolve_plan,
    run_bootstrap,
)
from central_service.persistence.repository import CentralRepository
from central_service.persistence.schema import metadata
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

# Test fixtures carry their own credential strings; these are never real.
_ADMIN_TOKEN = "test-admin-token-0123456789abcdef"  # noqa: S105
_DEVICE_TOKEN = "test-device-token-0123456789abcdef"  # noqa: S105


@pytest.fixture
def repository() -> Iterator[CentralRepository]:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    metadata.create_all(engine)
    try:
        yield CentralRepository(engine)
    finally:
        engine.dispose()


def _settings(**overrides: object) -> CentralSettings:
    values: dict[str, object] = {"database_url": "postgresql+psycopg://u:p@h:1/db"}
    values.update(overrides)
    return CentralSettings(**values)  # type: ignore[arg-type]


def test_plan_uses_settings_tokens_when_provided() -> None:
    plan = resolve_plan(_settings(admin_token=_ADMIN_TOKEN, device_upload_token=_DEVICE_TOKEN))
    assert plan.admin_token == _ADMIN_TOKEN
    assert plan.device_upload_token == _DEVICE_TOKEN


def test_plan_requires_explicit_tokens() -> None:
    with pytest.raises(BootstrapError):
        resolve_plan(_settings(), admin_token=_ADMIN_TOKEN)
    with pytest.raises(BootstrapError):
        resolve_plan(_settings(), device_upload_token=_DEVICE_TOKEN)
    with pytest.raises(BootstrapError):
        resolve_plan(_settings())


def test_plan_rejects_short_tokens() -> None:
    with pytest.raises(BootstrapError):
        resolve_plan(
            _settings(),
            admin_token="short",  # noqa: S106 - test credential
            device_upload_token=_DEVICE_TOKEN,
        )
    with pytest.raises(BootstrapError):
        resolve_plan(
            _settings(),
            device_upload_token="short",  # noqa: S106 - test credential
            admin_token=_ADMIN_TOKEN,
        )


def test_plan_rejects_empty_names() -> None:
    with pytest.raises(BootstrapError):
        resolve_plan(
            _settings(),
            organization_name="  ",
            admin_token=_ADMIN_TOKEN,
            device_upload_token=_DEVICE_TOKEN,
        )
    with pytest.raises(BootstrapError):
        resolve_plan(
            _settings(),
            device_id="",
            admin_token=_ADMIN_TOKEN,
            device_upload_token=_DEVICE_TOKEN,
        )


def test_run_bootstrap_is_idempotent(repository: CentralRepository) -> None:
    plan = resolve_plan(_settings(), admin_token=_ADMIN_TOKEN, device_upload_token=_DEVICE_TOKEN)
    outcome = run_bootstrap(repository, plan)
    assert outcome.result.bootstrapped
    second = run_bootstrap(repository, plan)
    assert second.result.created == ()
    assert not second.result.bootstrapped
