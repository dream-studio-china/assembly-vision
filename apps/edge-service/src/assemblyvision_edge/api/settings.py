"""Local edge API server settings."""

from __future__ import annotations

from dataclasses import dataclass
from ipaddress import ip_address
from pathlib import Path
from urllib.parse import urlsplit

from assemblyvision_domain.errors import ConfigError


@dataclass(frozen=True)
class UploadSettings:
    """Upload worker configuration (design 13.8, PR-017 F6/F7).

    Exactly one of ``base_url`` (HTTPS central endpoint) and ``sink_dir``
    (explicit local/development sink) should be configured; both unset means
    the scheduler stays disabled and tasks accumulate visibly in the API.
    ``token`` is a separate least-privilege upload credential and is never the
    local viewer ``api_token``.
    """

    base_url: str | None = None
    sink_dir: Path | None = None
    token: str | None = None
    connect_timeout_seconds: float = 5.0
    request_timeout_seconds: float = 30.0
    interval_seconds: float = 1.0
    batch_size: int = 4
    lease_seconds: int = 120
    base_retry_seconds: float = 2.0
    maximum_retry_seconds: float = 900.0
    exponent_cap: int = 8
    maximum_bandwidth_mbps: float | None = None
    allow_insecure_http: bool = False

    def validate(self) -> None:
        """Reject invalid upload configurations with actionable errors."""
        if self.base_url is not None and self.sink_dir is not None:
            raise ConfigError("upload configuration: base_url and sink_dir are mutually exclusive")
        if self.connect_timeout_seconds <= 0:
            raise ConfigError("upload configuration: connect_timeout_seconds must be positive")
        if self.request_timeout_seconds <= 0:
            raise ConfigError("upload configuration: request_timeout_seconds must be positive")
        if self.interval_seconds <= 0:
            raise ConfigError("upload configuration: interval_seconds must be positive")
        if self.batch_size < 1:
            raise ConfigError("upload configuration: batch_size must be at least 1")
        if self.lease_seconds <= 0:
            raise ConfigError("upload configuration: lease_seconds must be positive")
        if self.base_retry_seconds < 0:
            raise ConfigError("upload configuration: base_retry_seconds must not be negative")
        if self.maximum_retry_seconds < self.base_retry_seconds:
            raise ConfigError(
                "upload configuration: maximum_retry_seconds must be >= base_retry_seconds"
            )
        if self.exponent_cap < 0:
            raise ConfigError("upload configuration: exponent_cap must not be negative")
        if self.maximum_bandwidth_mbps is not None and self.maximum_bandwidth_mbps <= 0:
            raise ConfigError("upload configuration: maximum_bandwidth_mbps must be positive")
        if self.base_url is not None:
            self._validate_base_url()

    def _validate_base_url(self) -> None:
        """Reject non-HTTPS or malformed central endpoints (design 13.8, PR-017 F7).

        Inspection evidence and the upload credential must only travel over
        TLS; plaintext is permitted solely through an explicit, test-only
        ``allow_insecure_http`` development flag.
        """
        parts = urlsplit(self.base_url)
        host = parts.hostname
        if not isinstance(host, str) or not host:
            raise ConfigError("upload configuration: base_url must include a non-empty host")
        if parts.username is not None or parts.password is not None:
            raise ConfigError("upload configuration: base_url must not embed credentials")
        if parts.scheme == "https":
            return
        if parts.scheme == "http" and self.allow_insecure_http and _is_loopback_host(host):
            return
        if parts.scheme == "http" and self.allow_insecure_http:
            raise ConfigError(
                "upload configuration: plaintext http is only allowed for a loopback host"
            )
        raise ConfigError(
            "upload configuration: base_url must use https; plaintext http "
            "is only allowed with the explicit allow_insecure_http "
            "development flag on a loopback host"
        )


def _is_loopback_host(host: str) -> bool:
    """Return whether a development HTTP endpoint is confined to loopback."""
    if host.lower() == "localhost":
        return True
    try:
        return ip_address(host).is_loopback
    except ValueError:
        return False


@dataclass(frozen=True)
class ServerSettings:
    """Runtime configuration for the local edge API (design 15.3)."""

    output_root: Path
    db_path: Path
    config_path: Path | None = None
    rule_path: Path | None = None
    device_id: str | None = None
    static_dir: Path | None = None
    camera_width: int = 800
    camera_height: int = 600
    camera_fps: int | None = None
    api_token: str | None = None
    cors_allow_loopback: bool = True
    enable_web_test: bool = False
    upload: UploadSettings | None = None
