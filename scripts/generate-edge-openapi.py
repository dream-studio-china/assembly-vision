"""Generate the deterministic edge API OpenAPI document.

Usage:
    python scripts/generate-edge-openapi.py

Writes ``apps/edge-service/openapi/edge-openapi.json``. CI regenerates the
document and fails when the committed artifact drifts from the current routers
(F9, design 14.13).
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

from assemblyvision_edge.api.app import create_app
from assemblyvision_edge.api.settings import ServerSettings

REPO_ROOT = Path(__file__).resolve().parents[1]
OUTPUT = REPO_ROOT / "apps/edge-service/openapi/edge-openapi.json"


def main() -> int:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        settings = ServerSettings(output_root=root / "out", db_path=root / "edge.sqlite3")
        app = create_app(settings)
        spec = app.openapi()
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(
        json.dumps(spec, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(f"wrote {OUTPUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
