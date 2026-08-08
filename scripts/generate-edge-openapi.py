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
from typing import Any

from assemblyvision_edge.api.app import create_app
from assemblyvision_edge.api.settings import ServerSettings

REPO_ROOT = Path(__file__).resolve().parents[1]
OUTPUT = REPO_ROOT / "apps/edge-service/openapi/edge-openapi.json"

# FastAPI cannot derive a requestBody for routes that consume the raw stream
# (dev.py reads request.stream() to bound buffering, F5), and their runtime
# errors are raised as ApiProblem, not declared responses. This patch documents
# the actual contract so generated clients can call and handle the endpoints
# (F9). Match operations by path+method to stay stable across regenerations.
_DEV_OPERATIONS = {
    "/api/v1/dev/inspect-frame": "post",
    "/api/v1/dev/inspect-video": "post",
}
_DEV_PROBLEM_CODES = ("400", "404", "413", "503")


def _problem_response() -> dict[str, Any]:
    return {
        "description": "Problem response (RFC 7807)",
        "content": {
            "application/problem+json": {"schema": {"$ref": "#/components/schemas/Problem"}}
        },
    }


def finalize_openapi(spec: dict[str, Any]) -> dict[str, Any]:
    """Post-process the generated document for the two dev operations."""
    for path, method in _DEV_OPERATIONS.items():
        operation = spec["paths"].get(path, {}).get(method)
        if operation is None:
            continue
        operation["requestBody"] = {
            "required": True,
            "content": {
                "application/octet-stream": {"schema": {"type": "string", "format": "binary"}}
            },
        }
        for code in _DEV_PROBLEM_CODES:
            operation["responses"].setdefault(code, _problem_response())
    return spec


def main() -> int:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        settings = ServerSettings(output_root=root / "out", db_path=root / "edge.sqlite3")
        app = create_app(settings)
        spec = finalize_openapi(app.openapi())
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(
        json.dumps(spec, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(f"wrote {OUTPUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
