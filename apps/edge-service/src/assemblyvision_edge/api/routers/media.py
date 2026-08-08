"""Media content streaming with Range support (design 15.3.2)."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

from assemblyvision_domain.models import MediaMetadata
from fastapi import APIRouter, Depends, Request
from fastapi.responses import Response, StreamingResponse

from assemblyvision_edge.api.deps import get_repository, get_settings
from assemblyvision_edge.api.problems import ApiProblem
from assemblyvision_edge.api.settings import ServerSettings
from assemblyvision_edge.persistence.repository import EdgeRepository

router = APIRouter(prefix="/media", tags=["media"])

_CHUNK_SIZE = 64 * 1024

_MIME_BY_KIND: dict[str, str] = {
    "KEY_FRAME": "image/jpeg",
    "ANNOTATED_FRAME": "image/jpeg",
    "PRODUCT_ROI": "image/jpeg",
    "NG_CLIP": "video/mp4",
    "ROLLING_VIDEO": "video/mp4",
}


def _content_type(media: MediaMetadata) -> str:
    """Derive a safe response type from the media kind, never the persisted MIME."""
    return _MIME_BY_KIND.get(media.kind, "application/octet-stream")


def _resolve_media_path(output_root: Path, inspection_id: str, relative_path: str) -> Path | None:
    """Resolve a media path and return it only when it stays inside the root.

    A media file must be a child of its inspection bundle. Absolute paths,
    cross-inspection paths, root files, and symlink escapes are rejected here,
    so callers never read unrelated filesystem content.
    """
    root = output_root.resolve()
    relative = Path(relative_path)
    inspection_dir = Path(inspection_id)
    if (
        relative.is_absolute()
        or ".." in relative.parts
        or len(relative.parts) < 2
        or relative.parts[0] != inspection_dir.name
    ):
        return None
    try:
        bundle_root = (root / inspection_dir).resolve()
        candidate = (root / relative).resolve()
    except OSError:
        return None
    if not bundle_root.is_relative_to(root) or not candidate.is_relative_to(bundle_root):
        return None
    return candidate


def _iter_chunks(path: Path, start: int, end: int) -> Iterator[bytes]:
    """Stream a bounded byte range without loading the whole file (P2)."""
    with path.open("rb") as handle:
        handle.seek(start)
        remaining = end - start + 1
        while remaining > 0:
            chunk = handle.read(min(_CHUNK_SIZE, remaining))
            if not chunk:
                break
            remaining -= len(chunk)
            yield chunk


def _parse_range(header: str, size: int) -> tuple[int, int] | None:
    if not header.startswith("bytes="):
        return None
    spec = header[len("bytes=") :].split(",", 1)[0]
    start_s, _, end_s = spec.partition("-")
    if not start_s and not end_s:
        return None
    try:
        if start_s:
            start = int(start_s)
            end = int(end_s) if end_s else size - 1
        else:
            suffix = int(end_s)
            if suffix == 0:
                return None
            start = max(size - suffix, 0)
            end = size - 1
    except ValueError:
        return None
    if start < 0 or end < start or start >= size:
        return None
    return start, min(end, size - 1)


@router.get("/{media_id}/content")
def media_content(
    media_id: str,
    request: Request,
    repository: EdgeRepository = Depends(get_repository),
    settings: ServerSettings = Depends(get_settings),
) -> Response:
    found = repository.get_media(media_id)
    if found is None:
        raise ApiProblem(status_code=404, code="MEDIA_NOT_FOUND", detail=f"no media {media_id}")
    media, inspection_id = found
    path = _resolve_media_path(settings.output_root, str(inspection_id), media.relative_path)
    if path is None or not path.is_file():
        if media.lifecycle.value == "PURGED":
            raise ApiProblem(status_code=410, code="MEDIA_PURGED", detail="media has been purged")
        raise ApiProblem(status_code=404, code="MEDIA_NOT_FOUND", detail=f"no media {media_id}")
    size = path.stat().st_size
    range_header = request.headers.get("Range")
    if range_header:
        bounds = _parse_range(range_header, size)
        if bounds is None:
            raise ApiProblem(
                status_code=416,
                code="INVALID_RANGE",
                detail=f"invalid byte range {range_header!r}",
                headers={"Content-Range": f"bytes */{size}"},
            )
        start, end = bounds
        return StreamingResponse(
            _iter_chunks(path, start, end),
            status_code=206,
            media_type=_content_type(media),
            headers={
                "Content-Range": f"bytes {start}-{end}/{size}",
                "Accept-Ranges": "bytes",
                "Content-Length": str(end - start + 1),
            },
        )
    return StreamingResponse(
        _iter_chunks(path, 0, size - 1),
        media_type=_content_type(media),
        headers={"Accept-Ranges": "bytes", "Content-Length": str(size)},
    )
