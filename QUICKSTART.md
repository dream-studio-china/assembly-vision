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
| [Central server](#7-app-central-server-appscentral-service) | M1 pilot: delayed edge upload ingestion, PostgreSQL history, MinIO evidence, admin-web |

Future apps add a numbered section here.

---

## 1. Prerequisites

- [uv](https://docs.astral.sh/uv/) — Python package manager (installs Python 3.12 automatically)
- [pnpm](https://pnpm.io/) and Node.js 20+ — frontend workspace
- macOS / Linux / Windows for development; Linux is the primary production
  runtime. Windows production support requires the selected UVC driver or
  GigE Vision / GenICam producer to pass the camera conformance suite.

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
| Python | uv | `assemblyvision-domain`, `assemblyvision-vision`, `assemblyvision-edge`, `assemblyvision-central` |
| TypeScript | pnpm | `@assemblyvision/api-client`, `@assemblyvision/api-client-central`, `@assemblyvision/ui`, `edge-web`, `admin-web` |

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
/api/v1/health/ready`, `GET /api/v1/inspections`, `GET
/api/v1/inspections/{id}`, `GET /api/v1/inspections/{id}/media`, `GET
/api/v1/media/{id}/content` (Range supported), `GET /api/v1/device/status`,
`GET /api/v1/inspection/state`, `GET /api/v1/uploads`, `GET
/api/v1/configuration/effective`, and `GET /api/v1/logs`, plus the derived
endpoints `GET /api/v1/traceability/{sn}` and `GET /api/v1/statistics` (not
part of design 15.3). The live event channel (E4) streams inspection and
device events over `WS /api/v1/ws/runtime` (ticket at `POST
/api/v1/ws/runtime/ticket`, counters at `GET /api/v1/ws/runtime/stats`).

The API is **read-only for inspection control** (ADR-012): operator commands
such as `POST /api/v1/inspection/{pause,resume}` and camera reconnect are not
exposed. The only mutating route on `main` is the controlled upload retry
`POST /api/v1/uploads/{id}/retry` (E3; resets `RETRY_WAIT` and
`PERMANENT_FAILURE` tasks only). Review submission (`POST
/api/v1/inspections/{id}/reviews`, ADR-016) arrives with PR #31 and, like the
upload retry, uses the viewer credential — a documented trade-off until an
edge role model exists. When `AV_EDGE_API_TOKEN` (or `--api-token`) is
configured, every route except `GET /api/v1/health/live` requires
`Authorization: Bearer <token>` or an authenticated same-origin viewer session.
Open `/login` in the served dashboard and enter the configured token once; it
is exchanged for an HttpOnly, same-origin session cookie and is never bundled
or stored by the dashboard.

`serve` can expose local HTTPS with `--tls-cert`/`--tls-key` (or
`AV_EDGE_TLS_CERT`/`AV_EDGE_TLS_KEY`; the private key must not be readable by
group or others). The viewer and upload tokens also fall back to Docker secret
files under `/run/secrets/` when the environment variables are absent (E5).
Uploads always use a separate credential (`AV_EDGE_UPLOAD_TOKEN`), never the
viewer token.

#### Upload, storage, and retention configuration (E1/E2)

The upload scheduler drains the transactional outbox only when a destination is
configured — a local development sink or an HTTPS central endpoint. Without
one, tasks accumulate visibly in the API and the queue stays intact:

```bash
# Local development sink (writes each payload to a directory):
AV_EDGE_UPLOAD_SINK_DIR=/tmp/av-uploads \
  AV_EDGE_UPLOAD_INTERVAL_SECONDS=1 \
  AV_EDGE_UPLOAD_LEASE_SECONDS=120 \
  uv run assemblyvision serve --output out/ --db out/edge.sqlite3 \
    --config config/examples/pipeline.yaml --rule config/examples/product-rule.yaml \
    --static apps/edge-web/dist --host 127.0.0.1 --port 8000

# Or an HTTPS central endpoint (AV_EDGE_UPLOAD_TOKEN is a separate credential;
# plaintext http is allowed only for a loopback host with
# AV_EDGE_UPLOAD_INSECURE_HTTP=true in development).
```

Disk-pressure thresholds and retention durations are environment-configured
(`AV_EDGE_STORAGE_WARNING/CRITICAL/STOP_FREE_PERCENT`, `AV_EDGE_RETENTION_*`)
and always fail closed:

- **Cleanup is disabled by default.** Deletion only runs with an explicitly
  approved, enabled policy, e.g.
  `AV_EDGE_RETENTION_ENABLED=true AV_EDGE_RETENTION_DURATIONS='{"KEY_FRAME":"30d"}'`;
  media kinds absent from the map are protected forever.
- At **critical** free space optional OK capture is suppressed while NG
  evidence and metadata persist; at **stop** pressure, on a write fault, or on
  a startup integrity fault the runtime stops intake, reports
  `inspection_ready=false` in `GET /api/v1/device/status`, and
  `GET /api/v1/health/ready` returns `503` — never an unrecorded `OK`.
- Startup integrity scanning verifies media existence/size/checksums by
  default (`AV_EDGE_STORAGE_INTEGRITY_VERIFY_CHECKSUMS=false` disables checksum
  verification; `AV_EDGE_STORAGE_INTEGRITY_SAMPLE_LIMIT` /
  `..._SAMPLE_MAX_BYTES` bound the checksum budget). Malformed or orphan
  bundles are quarantined, never deleted.

See [docs/contracts/04-edge-storage-upload-contracts.md](docs/contracts/04-edge-storage-upload-contracts.md)
and the E2 task ([docs/tasks/E2-retention-and-disk-safety.md](docs/tasks/E2-retention-and-disk-safety.md))
for the full policy and safety invariants.

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
- Industrial cameras: `source: gige-vision` uses the hardened GigE Vision /
  GenICam source (PR #26) and requires `serial` and `gentl_producer` in the
  instance config plus a vendor GenICam producer at runtime; live validation
  on the target camera is still pending.
- Trigger/identity seam (E4b, ADR-015): an instance `trigger:` block enables
  the deterministic mock trigger source for development; the opt-in Modbus TCP
  FIFO trigger contract is the production path once a site-validated register
  profile exists. Barcode identity resolution runs on the dev harness and the
  production single-frame camera loop (PR #30).
- Each instance defaults to `device_id = uuid5(namespace, instance_id)` so
  records stay traceable per line across restarts; set `device_id` explicitly
  to override.

### 4.8 Web dev test harness (`--enable-web-test`, ADR-014)

For quick testing from any browser (including a phone's camera), `serve` can
expose gated file-based test endpoints that analyze one image or a short video
and return the inspection decision. They are **disabled by default** — start
`serve` with `--enable-web-test` to turn them on:

```bash
uv run assemblyvision serve \
  --output out/ \
  --db out/edge.sqlite3 \
  --config config/examples/pipeline.cameras.yaml \
  --static apps/edge-web/dist \
  --enable-web-test \
  --host 127.0.0.1 --port 8000
```

Then open the served dashboard at `/dev` (Test tab): take a photo with the
phone camera, upload an image, or upload a short video. Image tests write an
evidence bundle that appears in History (disable with the *persist* checkbox);
video tests return a per-frame summary without persisting. The endpoints are:

- `POST /api/v1/dev/inspect-frame` — image bytes → `InspectionRecord`; an
  optional `barcode` query parameter simulates a keyboard scanner input for
  barcode identity resolution (ADR-015, PR #30)
- `POST /api/v1/dev/inspect-video` — video bytes → `VideoInspectResult`
  (≤ 30 analyzed frames, < 100 MB)

This is a developer test harness, not a production acquisition path: it never
streams video and must not be enabled on production hosts. Production
real-time inspection uses the native app / RTSP / camera sources (ADR-014).

### 4.9 Backup and restore (E5)

`assemblyvision backup` takes a consistent SQLite snapshot plus the governed
config/rule/manifest files and pending evidence with SHA-256 checksums into a
`.tar.gz` bundle; `assemblyvision restore` verifies every checksum before
applying, keeps a `.pre-restore` copy, never overwrites conflicting media, and
reconciles the store so pending upload tasks survive:

```bash
uv run assemblyvision backup --output out/ --db out/edge.sqlite3 \
  --config config/examples/pipeline.yaml --rule config/examples/product-rule.yaml \
  --dest /backups/edge-$(date +%Y%m%d).tar.gz

uv run assemblyvision restore --backup /backups/edge-YYYYMMDD.tar.gz \
  --output out/ --db out/edge.sqlite3
```

See runbook 12 (backup and recovery) for the full procedure.

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
| `/uploads` | Upload queue — persistent outbox state with controlled manual retry (E3) |
| `/health` | Disk/queue charts (ECharts), server-authoritative storage mode and alerts, device status |
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

---

## 7. App: Central server (`apps/central-service`)

The central M1 pilot is a management and evidence plane: it receives delayed
edge inspection and media uploads, stores history in PostgreSQL and evidence
in MinIO, and hosts the pilot administration UI. It is **never** required for
edge inspection decisions, and it preserves the current edge upload envelope
and verified-receipt semantics (`docs/tasks/C1-central-server-m1.md`). The
C1a foundation (workspace, service, Compose, health, OpenAPI) is delivered;
C1b–C6 are in progress.

### 7.1 Run the pilot stack (Docker Compose)

PostgreSQL, MinIO, the API (`central-service`), the one-shot migration step
(`central-migrate`), and the built admin UI (`admin-web`) start together:

```bash
cp apps/central-service/compose.env.example apps/central-service/.env   # dev defaults; override secrets for real use
docker compose -f apps/central-service/compose.yaml up -d --build
curl http://localhost:8080/api/v1/health/live     # admin-web proxies /api to the API
```

- The API container health check uses `/api/v1/health/ready`; readiness
  returns `503` while PostgreSQL is unreachable, the schema is behind head,
  the MinIO bucket is unavailable, or the pilot credential is not configured.
- Schema migrations are a **controlled release step** run by the one-shot
  `central-migrate` service (`python -m central_service migrate`); the API
  never migrates automatically.

### 7.2 Run without Docker

Requires a PostgreSQL database and an S3-compatible object store:

```bash
export AV_CENTRAL_DATABASE_URL=postgresql+psycopg://central:secret@127.0.0.1:5432/assemblyvision
export AV_CENTRAL_MINIO_ENDPOINT=127.0.0.1:9000
export AV_CENTRAL_MINIO_ACCESS_KEY=minioadmin
export AV_CENTRAL_MINIO_SECRET_KEY=minioadmin
export AV_CENTRAL_ADMIN_TOKEN='<pilot-admin-token>'   # at least 16 characters

uv run python -m central_service migrate        # controlled schema release step
uv run python -m central_service serve --host 127.0.0.1 --port 8000
```

Health endpoints: `GET /api/v1/health/live` (liveness, no dependencies) and
`GET /api/v1/health/ready` (dependency readiness naming each checked
dependency in the `checks` map).

### 7.3 Tests

```bash
uv run pytest apps/central-service/tests        # health, readiness, settings
cd apps/admin-web && pnpm test:e2e              # pilot UI smoke test
```

---

## 8. Shared packages (`packages/`)

Used by multiple apps; you normally consume them through the app sections
above, not run them directly.

| Package | Purpose |
|---|---|
| `packages/python/domain` | Canonical Pydantic models, errors, reason codes |
| `packages/python/vision-core` | ROI engine, image sources, manifest loading |
| `packages/typescript/api-client` | Edge API contract (types, Mock/HTTP client) |
| `packages/typescript/api-client-central` | Central API contract (generated types) |
| `packages/typescript/ui` | Shared UI primitives (detection viewer, status, formatters) |

## 9. Quality gates

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

`make check` additionally runs the Playwright smoke tests for both `edge-web`
and `admin-web`. CI enforces the OpenAPI drift checks
(`uv run python scripts/generate-central-openapi.py` and the edge equivalent)
and the generated client drift checks (`pnpm --filter @assemblyvision/api-client-central generate:types`,
edge equivalent included), so a schema change must be committed with its
regenerated artifacts.

See [SECURITY.md](SECURITY.md) for the security policy, the M1
authentication boundary, and how to report a vulnerability.

### 9.1 E6 edge acceptance evidence

The E6-prep acceptance runner executes every supported locally automatable E6
acceptance item (Python/frontend/docs gates, compose render, optional Docker image
healthcheck) and emits a machine-readable evidence manifest. On-site items —
real camera/SDK, barcode decode, PLC/photo-eye trigger, GPU failure, power
loss, long soak, and unseen customer data — are recorded as `NOT_EXECUTED`
with their required environment, never as pass. The 12 locally asserted
behavior items (no-product, offline, restart, backup/restore, checksum
failure, ...) execute explicit pytest nodes or a Docker restart check, so a
skipped or failed assertion can never yield `PASS`.

```bash
uv run python scripts/edge-acceptance-run.py --out evidence/ --label pre-release \
  --artifact application=/path/to/edge-service-image.tar \
  --artifact product-model=/path/to/product-model-manifest.json \
  --artifact component-model=/path/to/component-model-manifest.json \
  --artifact rule=/path/to/approved-rule.yaml \
  --artifact configuration=/path/to/approved-pipeline.yaml \
  --acceptance-manifest acceptance/manifest.json
# Skip individual gates: --no-pytest --no-pnpm --no-docker --no-mkdocs
# Opt-in slow Docker image build + container healthcheck: --docker
```

Outputs `evidence/edge-acceptance-evidence-<timestamp>.json` and a short
human-readable summary. The application, product model, component model, rule,
configuration, and acceptance manifest are required and locked with SHA-256
before execution. Exit code `0` means all required local
checks passed with a complete artifact lock; `1` means a check failed; `2` means
the result is incomplete (missing artifact lock or a skipped/unsupported local
check). `--no-*` flags therefore produce an evidence draft and exit `2`, never
a successful E6-prep result. See
[docs/tasks/E6-edge-acceptance.md](docs/tasks/E6-edge-acceptance.md) for the
acceptance matrix and
[docs/design/28-edge-acceptance-report.md](docs/design/28-edge-acceptance-report.md)
for the report template.

## 10. Project layout

```text
pyproject.toml                  # root uv workspace (Python)
package.json + pnpm-workspace.yaml  # root pnpm workspace (TypeScript)
apps/
  central-service/              # central M1 API (FastAPI · PostgreSQL · MinIO)
  admin-web/                    # central administration UI (Vue 3)
  edge-service/                 # inspection runtime (CLI, pipeline, rules, detectors)
  edge-web/                     # Vue 3 edge dashboard (Vite)
  edge-desktop/                 # Electron shell for the dashboard (desktop/kiosk)
packages/
  python/domain/                # shared domain models, errors, reason codes
  python/vision-core/           # shared ROI engine, image sources, manifests
  typescript/api-client/        # edge API contract (types, Mock/HTTP client)
  typescript/api-client-central/# central API contract (generated types)
  typescript/ui/                # shared UI primitives (detection viewer, status)
config/examples/                # example pipeline, rule, and manifest config
models/manifests/               # model metadata (weights outside Git)
tests/fixtures/                 # small non-sensitive test fixtures
docs/                           # architecture, contracts, ADRs, runbooks
```

## 11. What's next

Milestones E1-E5 are implemented: observability (PRs #18/#19), retention and
disk safety (PR #20), upload resilience (PR #22), runtime/WebSocket (PR #23),
and deployment and security (E5, PR #24). The remaining Edge gate is E6, split
into two phases:

- **E6-prep tooling (delivered)** — acceptance test matrix, the local runner
  (`scripts/edge-acceptance-run.py`, section 9.1), the acceptance report
  template, and the on-site execution plan. The clock-drift harness remains an
  explicit incomplete local item; the runner reports it as `NOT_EXECUTED`.
- **On-site acceptance (gated)** — requires customer-approved targets, real
  edge hardware (camera/SDK, barcode, PLC/photo-eye trigger, GPU), unseen
  customer data, and executed resilience/soak evidence before the acceptance
  report can be issued with measured metrics.

Next work items:

- **Run the E6 evidence runner** on every release candidate
  (`uv run python scripts/edge-acceptance-run.py --out evidence/`) and attach
  the manifest to the release record.
- **On-site acceptance** — once hardware and customer data are available,
  execute `docs/tasks/E6-edge-acceptance.md` §E6d and produce the report from
  `docs/design/28-edge-acceptance-report.md`.
- **Barcode identity / PLC trigger (ADR-015)** — merged (PR #30): ZXing-based
  barcode decoding on the dev harness and the production single-frame loop,
  plus the opt-in Modbus TCP FIFO trigger contract. Live decode validation on
  production samples and a site-validated register profile remain.
- **Edge-local human review (ADR-016)** — merged (PR #31): append-only review
  of any inspection through the viewer credential, with the `/review` queue
  page and review panel in the dashboard.
- **Central server M1 pilot** — in progress
  (`docs/tasks/C1-central-server-m1.md`). C1a (workspace, service, Compose,
  health/readiness, OpenAPI) is delivered: `apps/central-service`,
  `apps/admin-web`, and `packages/typescript/api-client-central`. Next steps:
  C1b tenant/device/pilot authentication, C2a inspection ingestion with
  verified receipts, C2b MinIO media binding, C3 history/detail/overview,
  C4 append-only review, C5 metadata governance, C6 hardening and operational
  evidence. The edge uploader already implements the outbox, idempotency
  keys, checksums, and verified-receipt semantics the central ingestion
  contract consumes.
