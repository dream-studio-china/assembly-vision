"""Sad-path tests for the edge API: media ranges, health, derived endpoints,
problem responses, and control rejection."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest
from assemblyvision_domain.models import (
    BusinessResult,
    InspectionRecord,
    MediaLifecycle,
    MediaMetadata,
)
from assemblyvision_edge.api.app import create_app
from assemblyvision_edge.api.routers.media import _parse_range
from assemblyvision_edge.api.settings import ServerSettings
from fastapi.testclient import TestClient

from tests.test_api import _record


def _pipeline_record() -> InspectionRecord:
    now = datetime.now(UTC)
    return _record(now, business=BusinessResult.OK, barcode="SN-0001")


@pytest.fixture
def seeded_root(tmp_path: Path) -> Path:
    """Output root with one inspection record and a key-frame file."""
    root = tmp_path / "out"
    root.mkdir()
    record = _pipeline_record()
    directory = root / str(record.inspection_id)
    directory.mkdir()
    directory.joinpath("inspection.json").write_text(record.model_dump_json(indent=2))
    directory.joinpath("key_frame.jpg").write_bytes(b"fake-jpeg-0000")
    return root


@pytest.fixture
def client(seeded_root: Path, tmp_path: Path) -> Iterator[TestClient]:
    settings = ServerSettings(output_root=seeded_root, db_path=tmp_path / "edge.sqlite3")
    app = create_app(settings)
    with TestClient(app) as test_client:
        yield test_client


def test_parse_range_unit_cases() -> None:
    # Open-ended start
    assert _parse_range("bytes=0-", 100) == (0, 99)
    # Explicit end
    assert _parse_range("bytes=10-19", 100) == (10, 19)
    # Suffix
    assert _parse_range("bytes=-10", 100) == (90, 99)
    # Suffix larger than size
    assert _parse_range("bytes=-500", 100) == (0, 99)
    # Non-bytes unit
    assert _parse_range("items=0-10", 100) is None
    # Empty spec
    assert _parse_range("bytes=-", 100) is None
    # Suffix zero
    assert _parse_range("bytes=-0", 100) is None
    # Non-integer
    assert _parse_range("bytes=abc-", 100) is None
    # Start beyond size
    assert _parse_range("bytes=200-", 100) is None
    # End before start
    assert _parse_range("bytes=50-10", 100) is None
    # Negative start
    assert _parse_range("bytes=-5-", 100) is None


def test_media_range_open_ended_and_suffix(client: TestClient) -> None:
    page = client.get("/api/v1/inspections").json()
    inspection_id = page["items"][0]["inspection_id"]
    media_id = client.get(f"/api/v1/inspections/{inspection_id}/media").json()[0]["media_id"]
    base = client.get(f"/api/v1/media/{media_id}/content").content
    open_ended = client.get(f"/api/v1/media/{media_id}/content", headers={"Range": "bytes=2-"})
    assert open_ended.status_code == 206
    assert open_ended.content == base[2:]
    suffix = client.get(f"/api/v1/media/{media_id}/content", headers={"Range": "bytes=-4"})
    assert suffix.status_code == 206
    assert suffix.content == base[-4:]


def test_media_not_found_and_purged(tmp_path: Path) -> None:
    root = tmp_path / "out"
    root.mkdir()
    record = _pipeline_record()
    directory = root / str(record.inspection_id)
    directory.mkdir()
    directory.joinpath("inspection.json").write_text(record.model_dump_json(indent=2))
    # Purged media: metadata row exists but the file is gone.
    purged_id = uuid4()
    record.media = [
        MediaMetadata(
            media_id=purged_id,
            kind="KEY_FRAME",
            lifecycle=MediaLifecycle.PURGED,
            relative_path=f"{record.inspection_id}/purged.jpg",
            mime_type="image/jpeg",
            size_bytes=10,
            checksum_sha256="0" * 64,
        )
    ]
    directory.joinpath("inspection.json").write_text(record.model_dump_json(indent=2))

    settings = ServerSettings(output_root=root, db_path=tmp_path / "edge.sqlite3")
    app = create_app(settings)
    with TestClient(app) as c:
        missing = c.get("/api/v1/media/does-not-exist/content")
        assert missing.status_code == 404
        assert missing.json()["code"] == "MEDIA_NOT_FOUND"
        purged = c.get(f"/api/v1/media/{purged_id}/content")
        assert purged.status_code == 410
        assert purged.json()["code"] == "MEDIA_PURGED"


def test_media_404_when_file_missing_but_not_purged(tmp_path: Path) -> None:
    root = tmp_path / "out"
    root.mkdir()
    record = _pipeline_record()
    directory = root / str(record.inspection_id)
    directory.mkdir()
    record.media = [
        MediaMetadata(
            media_id=uuid4(),
            kind="KEY_FRAME",
            lifecycle=MediaLifecycle.AVAILABLE,
            relative_path=f"{record.inspection_id}/gone.jpg",
            mime_type="image/jpeg",
            size_bytes=10,
            checksum_sha256="0" * 64,
        )
    ]
    directory.joinpath("inspection.json").write_text(record.model_dump_json(indent=2))
    settings = ServerSettings(output_root=root, db_path=tmp_path / "edge.sqlite3")
    app = create_app(settings)
    with TestClient(app) as c:
        media_id = record.media[0].media_id
        response = c.get(f"/api/v1/media/{media_id}/content")
        assert response.status_code == 404
        assert response.json()["code"] == "MEDIA_NOT_FOUND"


def test_health_ready_503_when_engine_not_ready(tmp_path: Path) -> None:
    settings = ServerSettings(output_root=tmp_path / "out", db_path=tmp_path / "edge.sqlite3")
    app = create_app(settings)
    with TestClient(app) as c:
        response = c.get("/api/v1/health/ready")
        assert response.status_code == 503
        assert response.json()["code"] == "NOT_READY"


def test_camera_state_and_removed_reconnect(client: TestClient) -> None:
    state = client.get("/api/v1/camera/state")
    assert state.status_code == 200
    assert state.json()["connected"] is True
    reconnect = client.post("/api/v1/camera/reconnect", json={"reason": "fault"})
    assert reconnect.status_code == 404


def test_upload_retry_404(client: TestClient) -> None:
    response = client.post("/api/v1/uploads/nope/retry", json={"reason": "why"})
    assert response.status_code == 404
    assert response.json()["code"] == "HTTP_404"


def test_validation_error_is_problem(client: TestClient) -> None:
    # Invalid query parameters trigger the 422 problem handler.
    response = client.get("/api/v1/inspections", params={"limit": "not-an-int"})
    assert response.status_code == 422
    assert response.json()["code"] == "VALIDATION_FAILED"
    assert response.headers["content-type"].startswith("application/problem+json")
    assert response.json()["errors"]


def test_inspection_media_404_for_unknown_inspection(client: TestClient) -> None:
    response = client.get("/api/v1/inspections/nope/media")
    assert response.status_code == 404
    assert response.json()["code"] == "INSPECTION_NOT_FOUND"


def test_derived_images_empty_when_no_media(tmp_path: Path) -> None:
    root = tmp_path / "out"
    root.mkdir()
    record = _pipeline_record()
    record.media = []
    directory = root / str(record.inspection_id)
    directory.mkdir()
    directory.joinpath("inspection.json").write_text(record.model_dump_json(indent=2))
    settings = ServerSettings(output_root=root, db_path=tmp_path / "edge.sqlite3")
    app = create_app(settings)
    with TestClient(app) as c:
        response = c.get(f"/api/v1/inspections/{record.inspection_id}/images")
        assert response.status_code == 200
        body = response.json()
        assert body["original"] == ""
        assert body["detection"] == ""
        assert body["annotated"] == ""


def test_derived_images_maps_kinds(tmp_path: Path) -> None:
    root = tmp_path / "out"
    root.mkdir()
    record = _pipeline_record()
    key_id = uuid4()
    annotated_id = uuid4()
    roi_id = uuid4()
    record.media = [
        MediaMetadata(
            media_id=key_id,
            kind="KEY_FRAME",
            lifecycle=MediaLifecycle.AVAILABLE,
            relative_path="key.jpg",
            mime_type="image/jpeg",
            size_bytes=1,
            checksum_sha256="0" * 64,
        ),
        MediaMetadata(
            media_id=annotated_id,
            kind="ANNOTATED_FRAME",
            lifecycle=MediaLifecycle.AVAILABLE,
            relative_path="ann.jpg",
            mime_type="image/jpeg",
            size_bytes=1,
            checksum_sha256="0" * 64,
        ),
        MediaMetadata(
            media_id=roi_id,
            kind="PRODUCT_ROI",
            lifecycle=MediaLifecycle.AVAILABLE,
            relative_path="roi.jpg",
            mime_type="image/jpeg",
            size_bytes=1,
            checksum_sha256="0" * 64,
        ),
    ]
    directory = root / str(record.inspection_id)
    directory.mkdir()
    directory.joinpath("inspection.json").write_text(record.model_dump_json(indent=2))
    settings = ServerSettings(output_root=root, db_path=tmp_path / "edge.sqlite3")
    app = create_app(settings)
    with TestClient(app) as c:
        body = c.get(f"/api/v1/inspections/{record.inspection_id}/images").json()
        assert f"/media/{key_id}/content" in body["original"]
        assert f"/media/{annotated_id}/content" in body["detection"]
        assert f"/media/{roi_id}/content" in body["annotated"]


def test_unhandled_exception_returns_problem(tmp_path: Path) -> None:
    root = tmp_path / "out"
    root.mkdir()
    settings = ServerSettings(output_root=root, db_path=tmp_path / "edge.sqlite3")
    app = create_app(settings)

    @app.get("/api/v1/_boom", include_in_schema=False)
    def boom() -> None:
        raise RuntimeError("kaboom")

    with TestClient(app, raise_server_exceptions=False) as c:
        response = c.get("/api/v1/_boom")
        assert response.status_code == 500
        assert response.json()["code"] == "INTERNAL_ERROR"
        assert response.headers["content-type"].startswith("application/problem+json")


def _crafted_record(relative_path: str, mime_type: str) -> InspectionRecord:
    record = _pipeline_record()
    payload = record.model_dump(mode="json")
    payload["media"] = [
        {
            "media_id": str(uuid4()),
            "kind": "KEY_FRAME",
            "lifecycle": "AVAILABLE",
            "relative_path": relative_path,
            "mime_type": mime_type,
            "size_bytes": 6,
            "checksum_sha256": "0" * 64,
        }
    ]
    return InspectionRecord.model_validate(payload)


def test_media_content_rejects_traversal_and_absolute(tmp_path: Path) -> None:
    from assemblyvision_edge.persistence.repository import EdgeRepository

    root = tmp_path / "out"
    root.mkdir()
    (root / "secret.txt").write_bytes(b"SECRET")
    db = tmp_path / "edge.sqlite3"

    for relative in ("../secret.txt", "/etc/hostname", "link/secret.txt"):
        outside = tmp_path / "outside"
        outside.mkdir(exist_ok=True)
        outside.joinpath("secret.txt").write_bytes(b"SECRET")
        link = root / "link"
        if not link.exists():
            link.symlink_to(outside, target_is_directory=True)
        record = _crafted_record(relative, "image/jpeg")
        repo = EdgeRepository.open(db)
        repo.upsert_inspection(record)
        repo.close()

        settings = ServerSettings(output_root=root, db_path=db)
        app = create_app(settings)
        with TestClient(app) as c:
            media_id = record.media[0].media_id
            response = c.get(f"/api/v1/media/{media_id}/content")
            assert response.status_code == 404
            assert response.json()["code"] == "MEDIA_NOT_FOUND"


def test_resolve_media_path_handles_oserror(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from assemblyvision_edge.api.routers import media as media_mod

    root = tmp_path / "out"
    real_resolve = Path.resolve

    def boom(self: Path, strict: bool = False) -> Path:
        if "key.jpg" in str(self):
            raise OSError("cannot resolve")
        return real_resolve(self, strict)

    monkeypatch.setattr(Path, "resolve", boom)
    assert media_mod._resolve_media_path(root, "key.jpg") is None


def test_media_content_uses_mime_allowlist_not_persisted_mime(tmp_path: Path) -> None:
    from assemblyvision_edge.persistence.repository import EdgeRepository

    root = tmp_path / "out"
    root.mkdir()
    record = _crafted_record("key.jpg", "text/html")
    (root / "key.jpg").write_bytes(b"fake-jpeg-0000")
    db = tmp_path / "edge.sqlite3"
    repo = EdgeRepository.open(db)
    repo.upsert_inspection(record)
    repo.close()

    settings = ServerSettings(output_root=root, db_path=db)
    app = create_app(settings)
    with TestClient(app) as c:
        media_id = record.media[0].media_id
        response = c.get(f"/api/v1/media/{media_id}/content")
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("image/jpeg")
