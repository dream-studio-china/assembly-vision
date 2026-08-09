# AssemblyVision

Edge-first industrial AI vision inspection platform powered by YOLO detection and configurable rule engines. Supports automated assembly verification, quality inspection, offline edge inference, and traceable inspection workflows.

## Features

- **Two-stage detection** — product localization → ROI extraction → component presence check
- **Deterministic rule engine** — versioned, model-independent, always fail-safe
- **Edge-first architecture** — offline inspection; no central round-trip required
- **Full traceability** — every decision records model, rule, and configuration versions
- **Atomic evidence output** — JSON records + annotated images with SHA-256 checksums
- **Durable upload outbox** — transactional queue with retry/backoff, idempotency keys, and verified receipts (ADR-005)
- **Retention and disk safety** — receipt-gated cleanup with lease fencing, startup integrity scanning/quarantine, and a fail-safe stop gate that never returns an unrecorded `OK`
- **Python monorepo** — uv workspace, strict typing (MyPy), Pydantic domain models
- **Edge dashboard** — Vue 3 + TypeScript operator UI (current inspection, live view, history, traceability, statistics, device status, images, upload queue, health), decoupled from the backend via a typed API client
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
path. The edge runs as a CLI (`assemblyvision inspect`/`verify`) and as a local
FastAPI service (`assemblyvision serve`) that serves the Vue dashboard
(`apps/edge-web`) through a decoupled typed client. The service persists every
inspection and its upload tasks atomically, retries uploads from a durable
queue with idempotency and verified receipts, enforces receipt-gated retention
cleanup, and fails closed under disk pressure or integrity faults — an
unrecorded `OK` is never possible.

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

## Testing and Resilience

The resilience test matrix (design 22.8) and the testing contracts (contracts 06)
grade fault cases by delivery horizon: design cases → targeted pilot subset →
full approved suite. Covered faults include camera disconnect/reconnect, sudden
power loss, disk-full recovery, accelerator/GPU failure with validated CPU
fallback, repeated network disconnects with persistent queue drain, and
long-running soak stability (duration agreed from operating patterns). Recovery
procedures live in the runbooks (camera disconnection, low disk space, database
recovery, network recovery synchronization).

## Developer Tools (web test harness)

A gated `/api/v1/dev/` endpoint group and a `/dev` dashboard page let you test
the inspection pipeline from any browser: take a photo with a phone camera,
upload an image, or upload a short video, and get the decision immediately
(ADR-014). These endpoints are **disabled by default** — start `serve` with
`--enable-web-test` to enable them. This is a test harness, not a production
acquisition path: it never streams video. Production real-time inspection uses
the native app / RTSP / camera sources. See [QUICKSTART](QUICKSTART.md) §4.8.

## Roadmap

| Phase | Status |
|---|---|
| **Static train-and-inspect MVP** | Done — merged to `main` (PR #3) |
| **Edge dashboard + desktop** | Done — merged to `main` (PR #6) |
| **Edge backend layer (M1)** | Done — merged to `main` (PR #8) — `assemblyvision serve`, SQLite index, read-only API |
| **Camera frame sources + multi-instance serve** | Done — merged to `main` (PR #14) — folder/video/OpenCV/RTSP/HTTP sources, web dev test harness |
| **Temporal aggregation (product windows)** | Done — merged to `main` (PRs #15/#16) — per-component aggregation, identity-sealed windows |
| **Durable upload outbox + scheduler** | Done — merged to `main` (PR #17) — transactional outbox, leased worker, verified receipts |
| **Observability (E1)** | Done — merged to `main` (PRs #18/#19) — log capture, upload-queue device status |
| **Retention and disk safety (E2)** | Done — merged to `main` (PR #20) — receipt-gated cleanup, storage-pressure fail-safe, startup integrity scan |
| **Upload resilience (E3)** | Planned — bandwidth throttling, circuit breaker, manual retry, resumable large media |
| **Runtime/WebSocket (E4)** | Planned — WebSocket channel, hardware trigger/barcode/identity seams |
| **Deployment and security (E5)** | Planned — Docker packaging, secret/TLS provisioning, backup/restore |
| **Acceptance (E6)** | Planned — resilience matrix, soak, held-out model validation, Edge acceptance report |

## License

MIT © 2026 dream-studio-china
