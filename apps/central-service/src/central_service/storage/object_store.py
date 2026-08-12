"""S3-compatible object storage abstraction (design 05 section 3.2).

M1 stores inspection evidence bytes only in the object store; PostgreSQL holds
metadata and opaque, tenant-scoped object keys. The central server generates
every key and never accepts client-controlled filesystem paths. Objects are
staged and verified before a binding row may report ``AVAILABLE``; the
reconciliation command (``central-service reconcile-media``) repairs staged or
orphan objects.
"""

from __future__ import annotations

import io
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from datetime import timedelta
from typing import Protocol

from minio import Minio
from minio.error import S3Error


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
    def put_object(self, key: str, data: bytes, content_type: str) -> None: ...
    def object_exists(self, key: str) -> bool: ...
    def remove_object(self, key: str) -> None: ...
    def list_objects(self, prefix: str) -> Iterator[str]: ...
    def presigned_get_url(self, key: str, expires_seconds: int) -> str: ...
    def get_object(self, key: str) -> Iterator[bytes]: ...


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

    def put_object(self, key: str, data: bytes, content_type: str) -> None:
        """Write one object atomically; S3 single-PUT semantics."""
        self._client.put_object(
            self._settings.bucket,
            key,
            io.BytesIO(data),
            length=len(data),
            content_type=content_type,
        )

    def object_exists(self, key: str) -> bool:
        """Return whether the object exists in the configured bucket."""
        try:
            self._client.stat_object(self._settings.bucket, key)
            return True
        except S3Error as exc:
            if exc.code == "NoSuchKey":
                return False
            raise

    def remove_object(self, key: str) -> None:
        """Remove one object; a missing object is a no-op (idempotent)."""
        try:
            self._client.remove_object(self._settings.bucket, key)
        except S3Error as exc:
            if exc.code == "NoSuchKey":
                return
            raise

    def list_objects(self, prefix: str) -> Iterator[str]:
        """Yield object names under ``prefix`` (recursive)."""
        for item in self._client.list_objects(self._settings.bucket, prefix=prefix, recursive=True):
            yield str(item.object_name)

    def presigned_get_url(self, key: str, expires_seconds: int) -> str:
        """Return a short-lived authorized GET URL (design 05 section 3.2).

        The URL is scoped to one object and expires; bucket credentials and
        raw keys are never returned to browsers.
        """
        return self._client.presigned_get_object(
            self._settings.bucket, key, expires=timedelta(seconds=expires_seconds)
        )

    def get_object(self, key: str) -> Iterator[bytes]:
        """Yield the object bytes in chunks (authorized streaming, C3)."""
        response = self._client.get_object(self._settings.bucket, key)
        try:
            yield from response.stream(amt=64 * 1024)
        finally:
            response.close()
            response.release_conn()


@dataclass(frozen=True)
class ReconcileReport:
    """Outcome of one media reconciliation pass (C2b maintenance command)."""

    binding_count: int
    missing_objects: tuple[str, ...]
    orphan_objects: tuple[str, ...]


class _HasObjectKey(Protocol):
    """Minimal shape of a persisted media binding for reconciliation."""

    @property
    def object_key(self) -> str: ...


def reconcile_media(bindings: Iterable[_HasObjectKey], storage: ObjectStorage) -> ReconcileReport:
    """Compare persisted bindings against the object store (idempotent).

    Bindings whose object is absent are reported as missing; objects under the
    tenant prefix without a binding are reported as orphans for the
    maintenance command. Pure and injectable so the CLI stays a thin wrapper.
    """
    binding_list = list(bindings)
    bound_keys = {binding.object_key for binding in binding_list}
    missing = tuple(
        binding.object_key
        for binding in binding_list
        if not storage.object_exists(binding.object_key)
    )
    stored_keys = list(storage.list_objects("org/"))
    orphans = tuple(key for key in stored_keys if key not in bound_keys)
    return ReconcileReport(
        binding_count=len(binding_list),
        missing_objects=missing,
        orphan_objects=orphans,
    )
