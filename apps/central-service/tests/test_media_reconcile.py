"""C2b media reconciliation unit tests.

``reconcile_media`` compares persisted bindings against the object store and
reports missing objects and orphan objects; the CLI maintenance command is a
thin wrapper over it.
"""

from __future__ import annotations

from collections.abc import Iterator

from central_service.storage.object_store import ReconcileReport, reconcile_media


class _Binding:
    def __init__(self, object_key: str) -> None:
        self.object_key = object_key


class _Storage:
    """Minimal object-store stub satisfying the ObjectStorage protocol."""

    def __init__(self, objects: dict[str, bytes] | None = None) -> None:
        self.objects = objects or {}

    def ensure_bucket(self) -> None:
        return None

    def bucket_ready(self) -> bool:
        return True

    def put_object(self, key: str, data: bytes, content_type: str) -> None:
        self.objects[key] = data

    def object_exists(self, key: str) -> bool:
        return key in self.objects

    def remove_object(self, key: str) -> None:
        self.objects.pop(key, None)

    def list_objects(self, prefix: str) -> Iterator[str]:
        yield from sorted(key for key in self.objects if key.startswith(prefix))

    def presigned_get_url(self, key: str, expires_seconds: int) -> str:
        return f"http://fake-store.test/{key}?expires={expires_seconds}"

    def get_object(self, key: str) -> Iterator[bytes]:
        yield self.objects.get(key, b"")


def test_reconcile_consistent_state_reports_nothing() -> None:
    storage = _Storage({"org/1/device/a/2026/08/m1": b"x"})
    report = reconcile_media([_Binding("org/1/device/a/2026/08/m1")], storage)
    assert report == ReconcileReport(binding_count=1, missing_objects=(), orphan_objects=())


def test_reconcile_reports_missing_and_orphan_objects() -> None:
    storage = _Storage({"org/1/device/a/2026/08/m1": b"x", "org/1/device/a/2026/08/orphan": b"y"})
    report = reconcile_media([_Binding("org/1/device/a/2026/08/m1")], storage)
    assert report.binding_count == 1
    assert report.missing_objects == ()
    assert report.orphan_objects == ("org/1/device/a/2026/08/orphan",)


def test_reconcile_reports_missing_when_object_absent() -> None:
    storage = _Storage({})
    report = reconcile_media([_Binding("org/1/device/a/2026/08/m1")], storage)
    assert report.missing_objects == ("org/1/device/a/2026/08/m1",)
    assert report.orphan_objects == ()


def test_reconcile_is_idempotent() -> None:
    storage = _Storage({"org/1/device/a/2026/08/m1": b"x"})
    first = reconcile_media([_Binding("org/1/device/a/2026/08/m1")], storage)
    second = reconcile_media([_Binding("org/1/device/a/2026/08/m1")], storage)
    assert first == second
