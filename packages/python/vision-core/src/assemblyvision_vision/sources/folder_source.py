"""Folder image source with deterministic ordering."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

from PIL import Image

from assemblyvision_domain.errors import ImageReadError

SUPPORTED_EXTENSIONS = frozenset({".jpg", ".jpeg", ".png", ".bmp", ".tif", ".tiff", ".webp"})


class FolderSource:
    """Reads images from a directory in deterministic sorted order."""

    def __init__(self, folder: Path) -> None:
        if not folder.is_dir():
            raise ImageReadError(f"input folder does not exist: {folder}")
        self._folder = folder

    @property
    def folder(self) -> Path:
        return self._folder

    def iter_paths(self) -> Iterator[Path]:
        """Yield supported image paths in deterministic sorted order."""
        for path in sorted(self._folder.iterdir()):
            if path.is_file() and path.suffix.lower() in SUPPORTED_EXTENSIONS:
                yield path

    def read(self, path: Path) -> Image.Image:
        """Decode an image as RGB; raises ImageReadError on failure.

        Any decode failure maps to ImageReadError so the pipeline fails safe
        (NG); third-party PIL patches (e.g. Ultralytics HEIF) must not turn a
        corrupt image into an uncaught exception.
        """
        try:
            with Image.open(path) as handle:
                image: Image.Image = handle.convert("RGB")
                return image
        except Exception as exc:
            raise ImageReadError(f"cannot decode image: {path}") from exc
