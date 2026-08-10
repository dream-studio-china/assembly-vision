"""S3-compatible object storage abstraction (design 05 section 3.2).

M1 stores inspection evidence bytes only in the object store; PostgreSQL holds
metadata and opaque, tenant-scoped object keys. The central server generates
every key and never accepts client-controlled filesystem paths.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from minio import Minio


@dataclass(frozen=True)
class ObjectStorageSettings:
    """Endpoint and credential configuration for the object store."""

    endpoint: str
    access_key: str
    secret_key: str
    bucket: str
    secure: bool = False


class ObjectStorage(Protocol):
    """Storage operations used by the central server."""

    def ensure_bucket(self) -> None: ...
    def bucket_ready(self) -> bool: ...


class MinioObjectStorage:
    """MinIO-backed storage implementation with bucket bootstrapping."""

    def __init__(self, settings: ObjectStorageSettings) -> None:
        self._settings = settings
        self._client = Minio(
            settings.endpoint,
            access_key=settings.access_key,
            secret_key=settings.secret_key,
            secure=settings.secure,
        )

    def ensure_bucket(self) -> None:
        """Create the configured bucket when missing (idempotent)."""
        if self._client.bucket_exists(self._settings.bucket):
            return
        self._client.make_bucket(self._settings.bucket)

    def bucket_ready(self) -> bool:
        """Return whether the configured bucket is reachable and exists."""
        return self._client.bucket_exists(self._settings.bucket)
