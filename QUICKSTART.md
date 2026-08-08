# AssemblyVision Quickstart

AssemblyVision is organized as a monorepo of independently runnable **apps**
(`apps/`) sharing `packages/`. This guide is structured **per app**: install
once, then jump straight to the section for the app you are working on. New
apps get their own section instead of blurring this document.

| App | What it is |
|---|---|
| [Edge inspection CLI](#4-app-edge-inspection-cli-appsedge-service) | `assemblyvision` / `av-train`: train, inspect, verify |
| [Edge dashboard](#5-app-edge-dashboard-appsedge-web) | Vue 3 web UI for inspection history, live view, queue, health |
| [Edge desktop](#6-app-edge-desktop-appsedge-desktop) | Electron shell that runs the dashboard as a local kiosk app |

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
git checkout dev          # `dev` is the development branch, kept in sync with `main`
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

Expected JSON comes from `scripts/adapt-roboflow-dataset.py` (Roboflow) or
`scripts/adapt-xanylabeling.py` (X-AnyLabeling). Without `--expected`, the
filename fallback treats `ok_*` as OK and `ng_*`/`missing_*` as NG. The
command reports NG recall / FN / FP and exits non-zero on a false negative or
an incomplete report.

### 4.2.1 Prepare a real annotated dataset

Annotate production images with X-AnyLabeling (product full-board box +
required component boxes; a missing component is left unlabeled, never a
generic `missing_*` class), export the YOLO layout, then convert it into the
two-stage layout:

```bash
uv run python scripts/adapt-xanylabeling.py <xal-export> <out> \
  --product-class product --required 'chip,capacitor,boot'
```

This produces `dataset_product/`, `dataset_components/`, and
`test-expected.json` (plus a file manifest). Image/label pairing is enforced:
every image in every split must have a label file (an explicit empty label
file for background negatives), image stems must be unique per split, and
Roboflow's `valid` split is normalized to `val`. The published `data.yaml`
files use dataset-relative `images/train` and `images/val` paths so they stay
valid after the atomic publish. Roboflow exports use
`scripts/adapt-roboflow-dataset.py`. See
`docs/design/19-training-and-evaluation.md` §19.17 for the collection
quantities and hard annotation rules, and
`docs/runbooks/11-data-collection-and-annotation.md` for the full procedure.

### 4.3 Train the models (developer-only `av-train`)

```bash
uv run av-train product <dataset_product> --semver 0.1.0 --epochs 120 --no-augment \
  --out-weights models/weights/product-yolo-0.1.0.pt \
  --out-manifest models/manifests/product-manifest.json

uv run av-train prepare-components <dataset_components> \
  --product-manifest models/manifests/product-manifest.json \
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

### 4.6 Run the local API and dashboard (`serve`)

`assemblyvision serve` exposes the inspection pipeline and the local index over
`/api/v1` and serves the built dashboard. It opens a SQLite index, imports any
existing CLI inspection output, and (when configuration is supplied) loads the
same verified pipeline as `inspect`.

```bash
# Build the dashboard once (production mode talks to the same-origin API), then
# serve everything on one port:
pnpm --filter edge-web build
uv run assemblyvision serve \
  --output out/ \
  --db out/edge.sqlite3 \
  --config config/examples/pipeline.yaml \
  --rule config/examples/product-rule.yaml \
  --static apps/edge-web/dist \
  --host 127.0.0.1 --port 8000
```

Endpoints: the design 15.3 read routes `GET /api/v1/health/live`, `GET
/api/v1/inspections`, `GET /api/v1/inspections/{id}`, `GET
/api/v1/inspections/{id}/media`, `GET /api/v1/media/{id}/content` (Range
supported), `GET /api/v1/device/status`, `GET /api/v1/inspection/state`,
`GET /api/v1/uploads`, `GET
/api/v1/configuration/effective`, and `GET /api/v1/logs`, plus the M1 derived
endpoints `GET /api/v1/traceability/{sn}` and `GET /api/v1/statistics` (not
part of design 15.3).

The M1 API is **read-only** (ADR-012): mutation controls such as
`POST /api/v1/inspection/{pause,resume}`, camera reconnect, and upload retry
are not exposed. When `AV_EDGE_API_TOKEN` (or `--api-token`) is configured,
every route except `GET /api/v1/health/live` requires
`Authorization: Bearer <token>` or an authenticated same-origin viewer session.
Open `/login` in the served dashboard and enter the configured token once; it is
exchanged for an HttpOnly, same-origin session cookie and is never bundled or
stored by the dashboard.

### 4.7 Multi-camera serve (`instances`, ADR-013)

`serve` can open several independent camera instances from one config, each
with its own source (folder / video / OpenCV device / RTSP / HTTP-image) and
its own models/rule/product. `inspection.enabled` defaults to `false`, so
`serve` opens the sources and serves previews without writing inspections:

```bash
uv run assemblyvision serve \
  --output out/ \
  --db out/edge.sqlite3 \
  --config config/examples/pipeline.cameras.yaml \
  --static apps/edge-web/dist \
  --host 127.0.0.1 --port 8000
```

- Per-instance camera state: `GET /api/v1/camera/state` (aggregated) and the
  preview endpoint `GET /api/v1/camera/{instance_id}/preview` (latest frame as
  a rate-limited JPEG; `404` unknown instance, `503` not ready).
- Mock phase without hardware: use `source: folder` (loopable image
  directory), `source: video` (a local video file), or `source: rtsp` /
  `source: http-image` for remote TCP/IP inputs. A local camera or a virtual
  camera driver (Linux `v4l2loopback`, OBS Virtual Camera) plugs in as
  `source: opencv-device`.
- Each instance defaults to `device_id = uuid5(namespace, instance_id)` so
  records stay traceable per line across restarts; set `device_id` explicitly
  to override.

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
| `/` | **Operator dashboard** — current inspection status (Waiting/Processing/PASS/NG), product SN, rules, confirm/continue/manual actions |
| `/live` | Live inspection — camera image, detection result, detection regions, progress |
| `/history` | Inspection history — search by SN, filter by result, image links |
| `/traceability/:sn` | Product traceability — reinspection attempts and final status |
| `/images/:id` | Inspection images — original, detection result, annotations |
| `/statistics` | Production statistics — totals, PASS/NG, pass rate, date/line filters |
| `/device` | Device status — camera, vision engine, inspection service |
| `/uploads` | Upload queue — read-only in M1 (manual retry is not exposed) |
| `/health` | Disk/queue charts (ECharts) and device status |
| `/inspections` | Full record history (internal records) |
| `/configuration`, `/logs` | Read-only views of the effective configuration and the bounded log buffer |

The dashboard selects the mock or HTTP client explicitly via `VITE_API_MODE`
(see 5.3). The operator workflow (current/confirm/continue/manual) always runs
on the mock client; in real mode the operator dashboard hides it because it is
a demonstration queue, not a design 15.3 endpoint.

### 5.3 Mock vs real backend

Data mode is explicit (F5, ADR-012):

- `VITE_API_MODE=mock` (the dev default via `.env.development`) runs the
  deterministic in-memory mock client.
- `VITE_API_MODE=http` (the production default via `.env.production`) talks to
  the FastAPI backend. An omitted `VITE_API_BASE_URL` means **same-origin**
  `/api/v1`, so the bundle served by `assemblyvision serve` reads its own API.

```bash
# Dev against a remote edge host:
VITE_API_MODE=http VITE_API_BASE_URL=http://edge-host:8000 pnpm --filter edge-web dev
```

When the edge host is token-protected, sign in on `/login` as usual. The
viewer session cookie is same-origin, so a cross-origin dev client keeps the
entered token **in memory only** (never persisted) and attaches it to API and
media requests; same-origin deployments (the `assemblyvision serve` flow) keep
the HttpOnly-cookie exchange and never see the token.

The operator workflow actions (current inspection, confirm, next, manual) always
run on the deterministic mock client because they model a demonstration queue
rather than a design 15.3 contract endpoint.

### 5.4 Build and preview

```bash
pnpm --filter edge-web build      # bundle to apps/edge-web/dist (http mode)
pnpm --filter edge-web preview    # preview the build (default http://localhost:4173)
```

A production build selects the HTTP client by default, so the served dashboard
reads real data from the same-origin API with no extra flags.

### 5.5 Tests

```bash
pnpm --filter edge-web test                    # Vitest (stores, client)
cd apps/edge-web && pnpm test:e2e              # Playwright smoke tests
```

---

## 6. App: Edge desktop (`apps/edge-desktop`)

Electron shell that runs the edge dashboard as a local desktop/kiosk app on the
edge machine. It loads the **built** dashboard from disk in production, or the
Vite dev server in development, with hardened defaults (context isolation,
sandboxed renderer, no node integration).

Prerequisites: the dashboard must be built first (`pnpm --filter edge-web build`)
for production mode; development mode needs the Vite dev server running.

### 6.1 Production mode

```bash
pnpm --filter edge-web build
pnpm --filter edge-desktop start
```

Opens the bundled dashboard in a desktop window (default 1280×800, resizable).

### 6.2 Development mode (live reload)

```bash
pnpm --filter edge-web dev          # terminal 1: Vite dev server
pnpm --filter edge-desktop dev      # terminal 2: Electron loads http://localhost:5173
```

`ELECTRON_DEV=1` is set automatically; override the URL with
`VITE_DEV_SERVER_URL=http://127.0.0.1:5173`.

### 6.3 Kiosk mode

```bash
pnpm --filter edge-web build
pnpm --filter edge-desktop kiosk    # fullscreen, no application menu
```

### 6.4 Tests

```bash
pnpm --filter edge-desktop test     # Vitest (load-target resolution)
```

## 7. Shared packages (`packages/`)

Used by multiple apps; you normally consume them through the app sections
above, not run them directly.

| Package | Purpose |
|---|---|
| `packages/python/domain` | Canonical Pydantic models, errors, reason codes |
| `packages/python/vision-core` | ROI engine, image sources, manifest loading |
| `packages/typescript/api-client` | Edge API contract (types, Mock/HTTP client) |
| `packages/typescript/ui` | Shared UI primitives (detection viewer, status, formatters) |

## 8. Quality gates

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

See [SECURITY.md](SECURITY.md) for the security policy, the M1
authentication boundary, and how to report a vulnerability.

## 9. Project layout

```text
pyproject.toml                  # root uv workspace (Python)
package.json + pnpm-workspace.yaml  # root pnpm workspace (TypeScript)
apps/
  edge-service/                 # inspection runtime (CLI, pipeline, rules, detectors)
  edge-web/                     # Vue 3 edge dashboard (Vite)
  edge-desktop/                 # Electron shell for the dashboard (desktop/kiosk)
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

## 10. What's next

- **Real-data baseline** — collect and annotate production images with
  X-AnyLabeling per `docs/runbooks/11-data-collection-and-annotation.md`,
  convert the export with `scripts/adapt-xanylabeling.py`, then run `av-train`
  -> `assemblyvision inspect` -> `assemblyvision verify`.
- **Upload scheduler + WebSocket channel** — the next backend gaps after the
  merged M1 layer (PR #8): real `upload_tasks` rows with retry backoff and
  idempotency, and the runtime WebSocket channel.
