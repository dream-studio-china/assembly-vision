"""Central server runtime settings (design 05).

Configuration is environment-driven through the ``AV_CENTRAL_`` prefix so the
pilot can be deployed with Compose env files and Docker secrets without
changing code. Values are typed and validated at the composition root; the
migration CLI only requires the database URL.
"""

from __future__ import annotations

from assemblyvision_domain.errors import ConfigError
from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class CentralSettings(BaseSettings):
    """Runtime configuration for the central server (C1a).

    ``database_url`` uses the SQLAlchemy PostgreSQL dialect. MinIO credentials
    are never logged and are accepted over plaintext only for loopback
    development (the Compose pilot uses an internal HTTP endpoint).
    """

    model_config = SettingsConfigDict(env_prefix="AV_CENTRAL_", env_file=".env", extra="ignore")

    database_url: str = ""
    host: str = "127.0.0.1"
    port: int = 8000
    cors_allow_loopback: bool = True

    minio_endpoint: str = "127.0.0.1:9000"
    minio_access_key: str = ""
    minio_secret_key: str = ""
    minio_bucket: str = "assemblyvision-central"
    minio_secure: bool = False

    # Single pilot administrator token path (C1b replaces this with the
    # durable credential store; readiness fails while it is unset).
    admin_token: str | None = None

    @field_validator("database_url")
    @classmethod
    def _validate_database_scheme(cls, value: str) -> str:
        if value and not value.startswith("postgresql+psycopg://"):
            raise ValueError("database_url must use the postgresql+psycopg:// dialect")
        return value

    def validate_settings(self) -> None:
        """Reject invalid central configurations with actionable errors."""
        if not self.database_url:
            raise ConfigError("central: database_url is required")
        if not (1 <= self.port <= 65535):
            raise ConfigError("central: port must be in [1, 65535]")
        if self.admin_token is not None and len(self.admin_token) < 16:
            raise ConfigError("central: admin_token must be at least 16 characters")
        if self.minio_bucket.strip() == "":
            raise ConfigError("central: minio_bucket must not be empty")
