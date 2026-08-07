"""Media content streaming with Range support (design 15.3.2)."""

from __future__ import annotations

from pathlib import Path

from assemblyvision_domain.models import MediaMetadata
from fastapi import APIRouter, Depends, Request
from fastapi.responses import Response

from assemblyvision_edge.api.deps import get_repository, get_settings
from assemblyvision_edge.api.problems import ApiProblem
from assemblyvision_edge.api.settings import ServerSettings
from assemblyvision_edge.persistence.repository import EdgeRepository

router = APIRouter(prefix="/media", tags=["media"])

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


def _resolve_media_path(output_root: Path, relative_path: str) -> Path | None:
    """Resolve a media path and return it only when it stays inside the root.

    Absolute paths and symlink escapes resolve outside ``output_root`` and are
    rejected here, so callers never read filesystem content outside the root.
    """
    root = output_root.resolve()
    try:
        candidate = (root / relative_path).resolve()
    except OSError:
        return None
    if not candidate.is_relative_to(root):
        return None
    return candidate


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
    media, _inspection_id = found
    path = _resolve_media_path(settings.output_root, media.relative_path)
    if path is None or not path.is_file():
        if media.lifecycle.value == "PURGED":
            raise ApiProblem(status_code=410, code="MEDIA_PURGED", detail="media has been purged")
        raise ApiProblem(status_code=404, code="MEDIA_NOT_FOUND", detail=f"no media {media_id}")
    size = path.stat().st_size
    range_header = request.headers.get("Range")
    body = path.read_bytes()
    if range_header:
        bounds = _parse_range(range_header, size)
        if bounds is None:
            return Response(
                status_code=416,
                headers={"Content-Range": f"bytes */{size}"},
                media_type="application/problem+json",
            )
        start, end = bounds
        body = body[start : end + 1]
        return Response(
            content=body,
            status_code=206,
            media_type=_content_type(media),
            headers={
                "Content-Range": f"bytes {start}-{end}/{size}",
                "Accept-Ranges": "bytes",
                "Content-Length": str(len(body)),
            },
        )
    return Response(
        content=body, media_type=_content_type(media), headers={"Accept-Ranges": "bytes"}
    )
