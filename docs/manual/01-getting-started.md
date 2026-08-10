# 01 — Getting Started

## Prerequisites

- **uv** (manages Python 3.12 for the workspace)
- **pnpm** + **Node.js 20+**
- macOS / Linux / Windows for development; **Linux is the primary production
  runtime** (GigE Vision/GenICam is Linux/Windows-only; macOS resolves the
  gige extra to nothing).

## Setup

```bash
git clone https://github.com/dream-studio-china/assembly-vision
cd assembly-vision
git checkout dev            # dev = development branch, kept in sync with main
uv sync                     # Python workspace (domain, vision-core, edge-service, training)
pnpm install                # TypeScript workspace (api-client, ui, edge-web, edge-desktop)
```

## Verify the toolchain

```bash
uv run ruff check .
uv run ruff format --check .
uv run mypy .
uv run pytest

pnpm -r build && pnpm -r lint && pnpm -r test
```

Or run everything at once: `make check`.

## Run the pieces

```bash
# 1. CLI inspection (requires real model weights; placeholder manifests in
#    models/manifests/ fail closed without weights — use e2e-demo.sh for a
#    complete train->inspect loop)
scripts/e2e-demo.sh /tmp/av-e2e      # ~10 min CPU; expected 6 OK + 6 NG, NG recall 1.000

# 2. Manual CLI run
uv run assemblyvision inspect /path/to/images \
  --config config/examples/pipeline.yaml \
  --rule config/examples/product-rule.yaml \
  --output out/

# 3. Dashboard in mock mode (no backend needed)
pnpm --filter edge-web dev           # http://localhost:5173

# 4. Full local stack
pnpm --filter edge-web build
uv run assemblyvision serve --output out/ --db out/edge.sqlite3 \
  --config config/examples/pipeline.yaml --rule config/examples/product-rule.yaml \
  --static apps/edge-web/dist --host 127.0.0.1 --port 8000
# API at http://127.0.0.1:8000/api/v1 (see 04-edge-api-reference.md)

# 5. Desktop/kiosk
pnpm --filter edge-web build && pnpm --filter edge-desktop start
pnpm --filter edge-web build && pnpm --filter edge-desktop kiosk
```

## Day-to-day workflow

1. **Python changes**: `uv run ruff check .`, `uv run ruff format --check .`,
   `uv run mypy .`, `uv run pytest` (or the area-specific subsets in
   `11-testing-and-quality-gates.md`).
2. **TypeScript changes**: `pnpm -r build`, `pnpm -r lint`, `pnpm -r test`,
   and `cd apps/edge-web && pnpm test:e2e` for UI work.
3. **API contract changes**: after changing Pydantic schemas or routes, run
   `uv run python scripts/generate-edge-openapi.py` and
   `pnpm --filter @assemblyvision/api-client generate:types`, then commit the
   regenerated files (CI fails on drift otherwise).
4. **Database changes**: every schema change needs an Alembic migration
   (see `07-database-and-persistence.md`).
5. **Behavioral changes** require tests + all quality gates; documentation is
   part of the implementation (update design/contracts/runbooks when public
   behavior changes).
6. Commit with a Conventional Commit message. Never push without approval.

## Common pitfalls

- `assemblyvision inspect` exits `0` on NG results — only *errors* make it
  exit `1`. `verify` exits non-zero on any false negative or incomplete
  report.
- Production web builds fail unless `VITE_API_MODE=http` is set.
- `serve` without `--config`/`--rule` serves history/health but reports
  `inspection_ready=false`.
- Model weights are never in Git: `models/weights/` and
  `training/.cache/weights/` are gitignored; manifests under
  `models/manifests/` reference them.
- The operator workflow (confirm/continue/manual) in the dashboard is a mock
  demonstration; the real server has no such endpoints (they 404).
