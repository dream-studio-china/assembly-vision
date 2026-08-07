# AssemblyVision Quickstart

## Prerequisites

- [uv](https://docs.astral.sh/uv/) (Python package manager; installs Python 3.12 automatically)
- [pnpm](https://pnpm.io/) and Node.js 20+ (frontend workspace)
- macOS / Linux (the edge runtime targets Linux; development works on both)

## Setup

```bash
git clone https://github.com/dream-studio-china/assembly-vision.git
cd assembly-vision
git checkout dev          # `main` = released MVP; `dev` = in-progress work
uv sync                   # Python workspace
pnpm install              # TypeScript workspace (frontend)
```

This creates both workspaces:

| Layer | Tool | Contents |
|---|---|---|
| Python | uv | `assemblyvision-domain`, `assemblyvision-vision`, `assemblyvision-edge` packages |
| TypeScript | pnpm | `@assemblyvision/api-client`, `@assemblyvision/ui`, `edge-web` app |

## Verify everything works

```bash
uv run ruff check .        # Python lint
uv run mypy .              # Python type check
uv run pytest              # Python tests (136)

pnpm -r build              # TypeScript build (type check + bundling)
pnpm -r lint               # ESLint
pnpm -r test               # unit tests (api-client, ui, edge-web)
cd apps/edge-web && pnpm test:e2e   # Playwright smoke tests
```

## Run the inspection CLI

```bash
# train the models first (see av-train), then inspect a folder of images
uv run assemblyvision inspect /path/to/images \
  --config config/examples/pipeline.yaml \
  --rule config/examples/product-rule.yaml \
  --output out/
```

## Verify against expected labels

```bash
# compare decisions with expected OK/NG and report NG recall / FN / FP
# (expected JSON comes from scripts/adapt-roboflow-dataset.py; without it the
#  filename fallback treats ok_* as OK and ng_*/missing_* as NG)
uv run assemblyvision verify /path/to/test-images \
  --config config/examples/pipeline.yaml \
  --rule config/examples/product-rule.yaml \
  --expected test-expected.json \
  --output out/
```

Each image gets its own output directory under `out/<inspection_id>/`:

```text
out/<inspection_id>/
├── inspection.json        # full versioned record
├── key_frame.jpg          # original frame
├── annotated_frame.jpg    # annotated frame (boxes when detectors succeed)
└── product_roi.jpg        # product ROI crop (when a product is detected)
```

### Example with synthetic images

```bash
uv run python -c "
from PIL import Image
d = 'demo-images'
import os; os.makedirs(d, exist_ok=True)
Image.new('RGB', (800, 600), (180, 180, 180)).save(f'{d}/sample.png')
Image.new('RGB', (400, 300), (200, 200, 200)).save(f'{d}/sample2.jpg')
"

uv run assemblyvision inspect demo-images \
  --config config/examples/pipeline.yaml \
  --rule config/examples/product-rule.yaml \
  --output out/
```

## Run the edge dashboard (frontend)

The web dashboard runs fully decoupled from the backend. By default it uses an
in-memory mock client with pre-seeded inspection data, so you can start it
without any trained models or a running service.

```bash
pnpm --filter edge-web dev        # start Vite dev server on http://localhost:5173
```

Open http://localhost:5173/. The routes are:

| Route | Screen |
|---|---|
| `/` | Live inspection: camera overlay, latest decision, component matrix, readiness/connectivity, recent results, pause/resume |
| `/inspections` | Inspection history (filter by OK/NG) |
| `/inspections/:id` | Detail: evidence, overlay toggles, versions, media |
| `/uploads` | Upload queue with manual retry |
| `/health` | Disk/queue charts (ECharts) and device status |
| `/configuration`, `/logs` | Read-only placeholders |

To point the dashboard at a real backend instead of the mock, set the API base
URL when starting (the HTTP client targets `/api/v1`; the UI does not change):

```bash
VITE_API_BASE_URL=http://edge-host:8000 pnpm --filter edge-web dev
```

Production build and local preview:

```bash
pnpm --filter edge-web build      # bundle to apps/edge-web/dist
pnpm --filter edge-web preview    # preview the build (default http://localhost:4173)
```

## Run tests

```bash
uv run pytest                           # all tests
uv run pytest apps/edge-service/tests/test_rule_engine.py -v  # rule engine only
```

## Project layout

```text
pyproject.toml                  # root uv workspace (Python)
package.json + pnpm-workspace.yaml  # root pnpm workspace (TypeScript)
apps/
  edge-service/                 # inspection runtime (CLI, pipeline, rules, detectors)
  edge-web/                     # Vue 3 edge dashboard (Vite)
packages/
  python/domain/                # shared domain models, errors, reason codes
  python/vision-core/           # shared ROI engine, image sources, manifests
  typescript/api-client/        # edge API contract (types, Mock/HTTP client)
  typescript/ui/                # shared UI primitives (detection viewer, status, formatters)
config/examples/                # example pipeline, rule, and manifest config
models/manifests/               # model metadata (weights outside Git)
tests/fixtures/                 # small non-sensitive test fixtures
docs/                           # architecture, contracts, ADRs, runbooks
```

## Full end-to-end demo (one command)

```bash
# synthetic data -> train product -> prepare ROI -> train component ->
# inspect held-out images -> verify (hard gate on false negatives)
scripts/e2e-demo.sh /tmp/av-e2e
```

Takes ~10 minutes on a laptop CPU (120 + 150 epochs, nano model, no
augmentation). Expected result: 6 OK + 6 NG with NG recall 1.000 and zero
false negatives; the script exits non-zero if any NG is predicted as OK.

For richer or Roboflow-sourced data:
```bash
uv run python scripts/generate-synthetic-dataset.py /tmp/data --n-train 30 --n-val 8
uv run python scripts/adapt-roboflow-dataset.py <roboflow-export> /tmp/data \
  --product-class product --required "chip,capacitor,boot"
```

The Roboflow adapter requires an independently annotated full-product class and
keeps the source `test` split as a disjoint held-out verification set.

## What's next

- **Real-data baseline** — annotate production images with X-AnyLabeling, then
  run `av-train` -> `assemblyvision inspect` -> `assemblyvision verify`.
- **Edge backend API** — expose the local inspection records over FastAPI so the
  dashboard runs against real data (`VITE_API_BASE_URL`).

> `assemblyvision inspect` and `verify` run real Ultralytics YOLO detectors.
> They load weights from the model manifests; if the trained weights are
> missing they exit with a configuration error before processing any image.
> To use them, first train the product and component detectors with
> `av-train`, then point the pipeline config at the resulting manifests.
