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

## Quickstart

```bash
git clone https://github.com/dream-studio-china/assembly-vision.git
cd assembly-vision
git checkout feat/mvp
uv sync
```

Verify everything:

```bash
uv run ruff check apps                                   # lint
uv run mypy apps/edge-service/src \
  packages/python/domain/src \
  packages/python/vision-core/src                          # type check
uv run pytest                                              # 42 tests
```

Run the inspection CLI:

```bash
uv run assemblyvision inspect /path/to/images \
  --config config/examples/pipeline.yaml \
  --rule  config/examples/product-rule.yaml \
  --output out/
```

See [QUICKSTART.md](QUICKSTART.md) for a detailed walkthrough.

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
path. The MVP runs as a CLI; production adds a local FastAPI/Vue dashboard.

## Project Structure

```text
apps/edge-service/       # inspection runtime (CLI, pipeline, rules, detectors)
packages/python/
  domain/                # canonical Pydantic models, errors, reason codes
  vision-core/           # ROI geometry, image sources, manifest loading
config/examples/         # pipeline, rule, and manifest examples
models/manifests/        # model metadata (weights outside Git)
docs/                    # architecture, contracts, ADRs, runbooks
```

## Documentation

| Document | Purpose |
|---|---|
| [Cover and status](docs/design/00-cover-and-status.md) | Scope horizons and decisions in force |
| [Roadmap](docs/design/25-roadmap.md) | Implementation sequence by phase |
| [Architecture overview](docs/design/03-architecture-overview.md) | System context, deployment, data flow |
| [Edge client](docs/design/04-edge-client-architecture.md) | Offline runtime and ingestion |
| [Requirements](docs/design/02-requirements.md) | Functional and quality requirements |
| [Decisions (ADRs)](docs/design/decisions/README.md) | Why major architecture choices were made |
| [Contracts](docs/contracts/README.md) | Mandatory implementation constraints |
| [Runbooks](docs/runbooks/README.md) | Operational recovery procedures |

## Safety

Only complete, valid evidence for every required component may produce `OK`.
Missing, uncertain, or unverifiable evidence always yields `NG`. No claim of
100 % accuracy is made. Production acceptance requires measured data excluded
from training.

## Roadmap

| Phase | Status |
|---|---|
| **Static train-and-inspect MVP** | In progress (`feat/mvp`) |
| One-month camera integration + persistence + dashboard | Planned |
| Production hardening + acceptance | Planned |

## License

MIT © 2026 dream-studio-china
