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

    # Bootstrap-only pilot credentials (C1b). They are consumed once by
    # `central-service bootstrap` / the Compose bootstrap service to create
    # salted hashes in the durable credential store; the API never uses them
    # at runtime and never persists the plaintext. When either is unset the
    # bootstrap generates a token and prints it exactly once.
    admin_token: str | None = None
    device_upload_token: str | None = None

    # Browser session lifetime for pilot administrators (design 05 auth).
    admin_session_ttl_minutes: int = 480

    # Mark the administrator session cookie Secure. Defaults to True; local
    # loopback development over plain HTTP must set
    # AV_CENTRAL_SECURE_COOKIES=false explicitly. The attribute is deployment-
    # controlled because the API sits behind the admin-web proxy and cannot
    # infer the externally terminated TLS scheme.
    secure_cookies: bool = True

    # Ingestion bounds (C2a, contract 05 section 7). The envelope body cap
    # bounds the raw JSON request; the inspection payload cap bounds the
    # Base64-decoded InspectionRecord payload. Oversized requests fail closed
    # with 413 before any persistence.
    max_envelope_body_bytes: int = 16 * 1024 * 1024
    max_inspection_payload_bytes: int = 1 * 1024 * 1024

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
        if self.device_upload_token is not None and len(self.device_upload_token) < 16:
            raise ConfigError("central: device_upload_token must be at least 16 characters")
        if not (1 <= self.admin_session_ttl_minutes <= 1440):
            raise ConfigError("central: admin_session_ttl_minutes must be in [1, 1440]")
        if self.minio_bucket.strip() == "":
            raise ConfigError("central: minio_bucket must not be empty")
        if self.max_envelope_body_bytes < 1024:
            raise ConfigError("central: max_envelope_body_bytes must be at least 1024")
        if not (1 <= self.max_inspection_payload_bytes <= self.max_envelope_body_bytes):
            raise ConfigError(
                "central: max_inspection_payload_bytes must be in [1, max_envelope_body_bytes]"
            )
