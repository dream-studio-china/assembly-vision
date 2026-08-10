"""Generate the deterministic central API OpenAPI document.

Usage:
    python scripts/generate-central-openapi.py

Writes ``apps/central-service/openapi/central-openapi.json``. CI regenerates
the document and fails when the committed artifact drifts from the current
routers (C1a, contract 05 section 9).
"""

from __future__ import annotations

import json
from pathlib import Path

from central_service.api.app import create_app
from central_service.api.settings import CentralSettings

REPO_ROOT = Path(__file__).resolve().parents[1]
OUTPUT = REPO_ROOT / "apps/central-service/openapi/central-openapi.json"


def main() -> int:
    # Placeholder values only; app.openapi() never runs the lifespan, so no
    # database or object-store connection is attempted during generation.
    settings = CentralSettings(
        database_url="postgresql+psycopg://unused:unused@127.0.0.1:1/unused",
        admin_token="unused-token-0123456789abcdef",  # noqa: S106 - placeholder, never used
    )
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
