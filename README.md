# AssemblyVision

Industrial assembly inspection platform. Two-stage YOLO detection, deterministic
rules, edge-first decisions, delayed sync to a central server.

## Features

- **Two-stage detection** — product localization → ROI extraction → component presence check
- **Deterministic rule engine** — versioned, model-independent, always fail-safe
- **Edge-first architecture** — offline inspection; no central round-trip required
- **Full traceability** — every decision records model, rule, and configuration versions
- **Atomic evidence output** — JSON records + annotated images with SHA-256 checksums
- **Python monorepo** — uv workspace, strict typing (MyPy), Pydantic domain models
- **Edge dashboard** — Vue 3 + TypeScript operator UI (current inspection, live view, history, traceability, statistics, device status, images), decoupled from the backend via a typed API client
- **Edge desktop** — Electron shell that runs the dashboard as a local desktop/kiosk app
- **Frontend workspace** — pnpm workspace with a typed `api-client` (synchronized from the domain models) and shared UI primitives

## Quickstart

```bash
git clone https://github.com/dream-studio-china/assembly-vision.git
cd assembly-vision
git checkout dev            # `dev` is the development branch, kept in sync with `main`
uv sync                     # Python workspace
pnpm install                # TypeScript workspace (frontend)
```

Verify everything:

```bash
uv run ruff check .                                    # Python lint
uv run mypy .                                          # Python type check
uv run pytest                                          # Python tests

pnpm -r build && pnpm -r lint && pnpm -r test          # frontend build/lint/unit tests
```

Run the inspection CLI:

```bash
uv run assemblyvision inspect /path/to/images \
  --config config/examples/pipeline.yaml \
  --rule  config/examples/product-rule.yaml \
  --output out/
```

Run the edge dashboard (mock data, no backend required):

```bash
pnpm --filter edge-web dev        # http://localhost:5173
```

Run the dashboard as a local desktop/kiosk app:

```bash
pnpm --filter edge-web build && pnpm --filter edge-desktop start
```

See [QUICKSTART.md](QUICKSTART.md) for a detailed walkthrough, structured
per app: section 4 covers the edge inspection CLI, section 5 the edge
dashboard, section 6 the edge desktop shell.

## Usage

```bash
assemblyvision inspect images/ --config pipeline.yaml --rule rules.yaml --output out/
```

Each image gets an output directory with a versioned JSON record and annotated
media. Per-image machine-readable output:

```text
img/product_001.jpg  NG  INFERENCE_ERROR,GATE_FAILED:product_detected,...  <inspection_id>
```

## Architecture

```text
 Industrial Camera → Edge Client (inspection runtime)
                         ├── Product Detector (YOLO)
                         ├── ROI Engine
                         ├── Component Detector (YOLO)
                         ├── Rule Engine
                         └── Local Evidence + Upload Queue
                                │
                                ▼ (delayed, idempotent)
                         Central Server (history, review, admin)
```

The edge makes every inspection decision. Central is never in the real-time
path. The MVP runs as a CLI; a Vue dashboard (`apps/edge-web`) consumes the
edge API contract through a decoupled client backed by a local FastAPI service
(`assemblyvision serve`, read-only M1 API per ADR-012).

## Project Structure

```text
apps/
  edge-service/           # inspection runtime (CLI, pipeline, rules, detectors)
  edge-web/               # Vue 3 edge dashboard (Vite)
  edge-desktop/           # Electron shell for the dashboard (desktop/kiosk)
packages/
  python/
    domain/               # canonical Pydantic models, errors, reason codes
    vision-core/          # ROI geometry, image sources, manifest loading
  typescript/
    api-client/           # edge API contract (types, Mock/HTTP client)
    ui/                   # shared UI primitives (detection viewer, status)
config/examples/          # pipeline, rule, and manifest examples
models/manifests/         # model metadata (weights outside Git)
scripts/                  # dataset adapters (Roboflow / X-AnyLabeling), e2e demo
docs/                     # architecture, contracts, ADRs, runbooks
```

## Documentation

| Document | Purpose |
|---|---|
| [Cover and status](docs/design/00-cover-and-status.md) | Scope horizons and decisions in force |
| [Roadmap](docs/design/25-roadmap.md) | Implementation sequence by phase |
| [Architecture overview](docs/design/03-architecture-overview.md) | System context, deployment, data flow |
| [Edge client](docs/design/04-edge-client-architecture.md) | Offline runtime and ingestion |
| [Requirements](docs/design/02-requirements.md) | Functional and quality requirements |
| [Single-product data acquisition](docs/design/19-training-and-evaluation.md#1917-single-product-data-acquisition-and-annotation-checklist) | What to collect and how to annotate the real-data baseline |
| [Decisions (ADRs)](docs/design/decisions/README.md) | Why major architecture choices were made |
| [Contracts](docs/contracts/README.md) | Mandatory implementation constraints |
| [Runbooks](docs/runbooks/README.md) | Operational recovery procedures (incl. data collection and annotation) |
| [Security policy](SECURITY.md) | Vulnerability reporting and security position |

## Safety

Only complete, valid evidence for every required component may produce `OK`.
Missing, uncertain, or unverifiable evidence always yields `NG`. No claim of
100 % accuracy is made. Production acceptance requires measured data excluded
from training.

## Roadmap

| Phase | Status |
|---|---|
| **Static train-and-inspect MVP** | Done — merged to `main` (PR #3) |
| **Edge dashboard + desktop** | Done — merged to `main` (PR #6) |
| **Edge backend layer (M1)** | Done — merged to `main` (PR #8) — `assemblyvision serve`, SQLite index, read-only API |
| One-month camera integration + upload scheduler + WebSocket + persistence | Planned |
| Production hardening + acceptance | Planned |

## License

MIT © 2026 dream-studio-china
