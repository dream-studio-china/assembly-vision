# AssemblyVision Quickstart

AssemblyVision is organized as a monorepo of independently runnable **apps**
(`apps/`) sharing `packages/`. This guide is structured **per app**: install
once, then jump straight to the section for the app you are working on. New
apps get their own section instead of blurring this document.

| App | What it is |
|---|---|
| [Edge inspection CLI](#4-app-edge-inspection-cli-appsedge-service) | `assemblyvision` / `av-train`: train, inspect, verify |
| [Edge dashboard](#5-app-edge-dashboard-appsedge-web) | Vue 3 web UI for inspection history, live view, queue, health |

Future apps (e.g. a central API or worker) add a numbered section here.

---

## 1. Prerequisites

- [uv](https://docs.astral.sh/uv/) — Python package manager (installs Python 3.12 automatically)
- [pnpm](https://pnpm.io/) and Node.js 20+ — frontend workspace
- macOS / Linux (the edge runtime targets Linux; development works on both)

## 2. One-time setup

```bash
git clone https://github.com/dream-studio-china/assembly-vision.git
cd assembly-vision
git checkout dev          # `main` = released MVP; `dev` = in-progress work
uv sync                   # Python workspace (edge-service, packages)
pnpm install              # TypeScript workspace (edge-web, packages)
```

This prepares both workspaces:

| Layer | Tool | Contents |
|---|---|---|
| Python | uv | `assemblyvision-domain`, `assemblyvision-vision`, `assemblyvision-edge` |
| TypeScript | pnpm | `@assemblyvision/api-client`, `@assemblyvision/ui`, `edge-web` |

## 3. Verify the toolchain

```bash
uv run ruff check . && uv run mypy . && uv run pytest   # Python toolchain
pnpm -r build && pnpm -r lint && pnpm -r test           # TypeScript toolchain
```

If this passes, skip to the section for the app you want to run.

---

## 4. App: Edge inspection CLI (`apps/edge-service`)

The CLI runs the real two-stage Ultralytics YOLO pipeline and writes evidence.
It requires trained models referenced by the pipeline config; otherwise it
exits with a configuration error before processing any image.

### 4.1 Inspect a folder of images

```bash
uv run assemblyvision inspect /path/to/images \
  --config config/examples/pipeline.yaml \
  --rule config/examples/product-rule.yaml \
  --output out/
```

Each image gets an output directory:

```text
out/<inspection_id>/
├── inspection.json        # full versioned record
├── key_frame.jpg          # original frame
├── annotated_frame.jpg    # annotated frame (boxes when detectors succeed)
└── product_roi.jpg        # product ROI crop (when a product is detected)
```

### 4.2 Verify against expected labels

```bash
uv run assemblyvision verify /path/to/test-images \
  --config config/examples/pipeline.yaml \
  --rule config/examples/product-rule.yaml \
  --expected test-expected.json \
  --output out/
```

Expected JSON comes from `scripts/adapt-roboflow-dataset.py`. Without
`--expected`, the filename fallback treats `ok_*` as OK and `ng_*`/`missing_*`
as NG. The command reports NG recall / FN / FP and exits non-zero on a false
negative or an incomplete report.

### 4.3 Train the models (developer-only `av-train`)

```bash
uv run av-train product <dataset_product> --semver 0.1.0 --epochs 120 --no-augment \
  --out-weights models/weights/product-yolo-0.1.0.pt \
  --out-manifest models/manifests/product-manifest.json

uv run av-train prepare-components <dataset_components> \
  --product-weights models/weights/product-yolo-0.1.0.pt \
  --min-area 10000 --min-retention 0.80 --out-dir <roi-dataset>

uv run av-train component <roi-dataset> --semver 0.1.0 --epochs 150 --no-augment \
  --out-weights models/weights/component-yolo-0.1.0.pt \
  --out-manifest models/manifests/component-manifest.json
```

After training, update `pipeline.yaml` `model_version` and the rule's
`compatible_component_model_versions` together (see
`docs/runbooks/10-model-improvement.md`).

### 4.4 Demo with synthetic images

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

Full synthetic train -> inspect -> verify loop in one command:

```bash
scripts/e2e-demo.sh /tmp/av-e2e
```

Takes ~10 minutes on a laptop CPU. Expected result: 6 OK + 6 NG with NG recall
1.000 and zero false negatives; exits non-zero if any NG is predicted as OK.

### 4.5 Tests

```bash
uv run pytest apps/edge-service/tests               # runtime tests
uv run pytest training/tests                        # training tests
```

---

## 5. App: Edge dashboard (`apps/edge-web`)

The dashboard runs **fully decoupled** from the backend. By default it uses an
in-memory mock client with pre-seeded data, so it starts with no trained models
or running service.

### 5.1 Run the dev server

```bash
pnpm --filter edge-web dev        # http://localhost:5173
```

### 5.2 Routes

| Route | Screen |
|---|---|
| `/` | Live inspection: camera overlay, latest decision, component matrix, readiness/connectivity, recent results, pause/resume |
| `/inspections` | Inspection history (filter by OK/NG) |
| `/inspections/:id` | Detail: evidence, overlay toggles, versions, media |
| `/uploads` | Upload queue with manual retry |
| `/health` | Disk/queue charts (ECharts) and device status |
| `/configuration`, `/logs` | Read-only placeholders |

### 5.3 Mock vs real backend

Set `VITE_API_BASE_URL` to use the HTTP client (targets `/api/v1`) instead of
the mock. The UI does not change:

```bash
VITE_API_BASE_URL=http://edge-host:8000 pnpm --filter edge-web dev
```

### 5.4 Build and preview

```bash
pnpm --filter edge-web build      # bundle to apps/edge-web/dist
pnpm --filter edge-web preview    # preview the build (default http://localhost:4173)
```

### 5.5 Tests

```bash
pnpm --filter edge-web test                    # Vitest (stores, client)
cd apps/edge-web && pnpm test:e2e              # Playwright smoke tests
```

---

## 6. Shared packages (`packages/`)

Used by multiple apps; you normally consume them through the app sections
above, not run them directly.

| Package | Purpose |
|---|---|
| `packages/python/domain` | Canonical Pydantic models, errors, reason codes |
| `packages/python/vision-core` | ROI engine, image sources, manifest loading |
| `packages/typescript/api-client` | Edge API contract (types, Mock/HTTP client) |
| `packages/typescript/ui` | Shared UI primitives (detection viewer, status, formatters) |

## 7. Quality gates

Run all Python + TypeScript gates together:

```bash
make check
```

Individually:

```bash
uv run ruff check . && uv run ruff format --check .   # Python lint
uv run mypy .                                          # Python types
uv run pytest                                          # Python tests
pnpm -r build && pnpm -r lint && pnpm -r test          # TypeScript
```

## 8. Project layout

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
  typescript/ui/                # shared UI primitives (detection viewer, status)
config/examples/                # example pipeline, rule, and manifest config
models/manifests/               # model metadata (weights outside Git)
tests/fixtures/                 # small non-sensitive test fixtures
docs/                           # architecture, contracts, ADRs, runbooks
```

## 9. What's next

- **Real-data baseline** — annotate production images with X-AnyLabeling, then
  run `av-train` -> `assemblyvision inspect` -> `assemblyvision verify`.
- **Edge backend API** — expose local inspection records over FastAPI so the
  dashboard runs against real data (`VITE_API_BASE_URL`).
