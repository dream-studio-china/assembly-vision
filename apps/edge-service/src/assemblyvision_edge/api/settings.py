"""Local edge API server settings."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


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
