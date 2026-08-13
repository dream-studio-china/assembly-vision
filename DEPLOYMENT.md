# AssemblyVision Deployment Guide

> **Exhaustive deployment reference** — the full companion to
> [QUICKSTART.md](QUICKSTART.md). Covers **development**, **production**, and
> **training** deployment of every component, over both the **CLI** and
> **Docker**. For the short developer fast path use QUICKSTART.md first.

**How this guide is organized**

| Section | What it covers |
|---|---|
| [1. Overview](#1-overview) | What is deployable, dev vs production boundaries, configuration model |
| [2. Developer setup](#2-developer-setup) | Prerequisites, one-time setup, toolchain verification |
| [3. Edge deployment](#3-edge-deployment) | CLI (inspect/verify), training, `serve`, Docker, dashboard, desktop |
| [4. Central deployment](#4-central-deployment) | API (Compose / CLI / production), admin-web, tests |
| [5. Quality gates and acceptance](#5-quality-gates-and-acceptance) | All repo gates + E6 evidence runner |
| [6. Environment variable reference](#6-environment-variable-reference) | `AV_EDGE_*`, `AV_CENTRAL_*`, Compose, `VITE_*` |
| [7. Troubleshooting](#7-troubleshooting) | Symptom → cause/fix table |
| [8. Project layout](#8-project-layout) | Repository map |
| [9. Operational status](#9-operational-status) | What is shipped, what remains |

---

## 1. Overview

### 1.1 Components

| Component | Role | CLI | Docker |
|---|---|---|---|
| Edge inspection CLI (`apps/edge-service`) | train / inspect / verify | `assemblyvision`, `av-train` | `apps/edge-service/Dockerfile` |
| Edge service (`serve`) | local API + dashboard | `assemblyvision serve` | same image |
| Edge dashboard (`apps/edge-web`) | operator UI (Vue 3) | Vite dev / static build | served by edge-service or any static host |
| Edge desktop (`apps/edge-desktop`) | kiosk shell | Electron | — |
| Central API (`apps/central-service`) | M1 management plane | `python -m central_service {migrate,bootstrap,serve}` | `apps/central-service/Dockerfile` |
| Central admin UI (`apps/admin-web`) | pilot administration UI | Vite dev / static + nginx | `apps/admin-web/Dockerfile` |
| PostgreSQL / MinIO | central persistence | external services | Compose (`postgres:16-alpine`, MinIO) |

### 1.2 Dev vs production boundary

- **Edge** runs all production-critical inference and decisions locally and
  never depends on the central server. Edge deployment is E1–E5-gated and
  Docker-packaged; on-site acceptance (E6) is hardware/data-gated.
- **Central** is a delayed management/evidence plane (PostgreSQL history, MinIO
  evidence, review, governed metadata). The M1 pilot is **feature-complete**
  and a **controlled pilot**: production hardening (OIDC/RBAC, remote rollout,
  resumable uploads, retention enforcement, DR/RPO-RTO) is deferred
  (`docs/tasks/C1-central-server-m1.md` §13–14).

### 1.3 Configuration model

- Runtime settings are **environment variables** with an `AV_EDGE_*` /
  `AV_CENTRAL_*` prefix (Pydantic settings), validated at startup (see
  [§6](#6-environment-variable-reference)).
- The Compose stack reads a `.env` file (see `compose.env.example`); secrets
  have no dev defaults and the bootstrap fails closed when unset.
- Docker secrets: the edge viewer/upload tokens fall back to files under
  `/run/secrets/` when the environment variables are absent (E5).
- Frontends use `VITE_*` build-time variables (`VITE_API_MODE`,
  `VITE_API_BASE_URL`, `VITE_DEFAULT_LOCALE`).

---

## 2. Developer Setup

### 2.1 Prerequisites

- [uv](https://docs.astral.sh/uv/) — Python package manager (installs Python 3.12 automatically)
- [pnpm](https://pnpm.io/) and Node.js 20+ — frontend workspace
- [Docker](https://www.docker.com/) — central Compose stack and image builds
- macOS / Linux / Windows for development; Linux is the primary production
  runtime. Windows production support requires the selected UVC driver or
  GigE Vision / GenICam producer to pass the camera conformance suite.

### 2.2 One-time setup

```bash
git clone https://github.com/dream-studio-china/assembly-vision.git
cd assembly-vision
git checkout dev          # `dev` is the development branch, kept in sync with `main`
uv sync                   # Python workspace (edge-service, packages)
pnpm install              # TypeScript workspace (edge-web, admin-web, packages)
```

| Layer | Tool | Contents |
|---|---|---|
| Python | uv | `assemblyvision-domain`, `assemblyvision-vision`, `assemblyvision-edge`, `assemblyvision-central` |
| TypeScript | pnpm | `@assemblyvision/api-client`, `@assemblyvision/api-client-central`, `@assemblyvision/ui`, `edge-web`, `admin-web` |

### 2.3 Verify the toolchain

```bash
uv run ruff check . && uv run mypy . && uv run pytest   # Python toolchain
pnpm -r build && pnpm -r lint && pnpm -r test           # TypeScript toolchain
uv run mkdocs build --strict                            # documentation site
```

---

## 3. Edge Deployment

### 3.1 Inspect a folder of images (CLI)

The CLI runs the real two-stage Ultralytics YOLO pipeline and writes evidence.
It requires trained models referenced by the pipeline config; otherwise it
exits with a configuration error before processing any image.

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

### 3.2 Verify against expected labels (CLI)

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

### 3.3 Training (developer-only `av-train`)

**Dataset preparation.** Annotate production images with X-AnyLabeling (product
full-board box + required component boxes; a missing component is left
unlabeled, never a generic `missing_*` class), export the YOLO layout, then
convert it into the two-stage layout:

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
`scripts/adapt-roboflow-dataset.py`.

A fully synthetic train → inspect → verify loop runs in one command:

```bash
scripts/e2e-demo.sh /tmp/av-e2e
```

Takes ~10 minutes on a laptop CPU. Expected result: 6 OK + 6 NG with NG recall
1.000 and zero false negatives; exits non-zero if any NG is predicted as OK.

**Training commands.**

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

**Release rule.** After training, update `pipeline.yaml` `model_version` and
the rule's `compatible_component_model_versions` **together** — a model release
is only valid when both move in lockstep. Base weights are cached under
`training/.cache/weights/` (gitignored); trained artifacts go to
`models/weights/` (gitignored) with manifests under `models/manifests/`. See
`docs/runbooks/10-model-improvement.md` for the collect → retrain → verify →
bump loop and `docs/runbooks/08-model-rollback.md` / `09-rule-rollback.md` for
rollback. Collection quantities and annotation rules:
`docs/design/19-training-and-evaluation.md` §19.17 and
`docs/runbooks/11-data-collection-and-annotation.md`.

### 3.4 Edge service (`serve`) — local API + dashboard

Build the dashboard once, then serve the API + dashboard on one port:

```bash
pnpm --filter edge-web build
uv run assemblyvision serve \
  --output out/ --db out/edge.sqlite3 \
  --config config/examples/pipeline.yaml \
  --rule config/examples/product-rule.yaml \
  --static apps/edge-web/dist \
  --host 127.0.0.1 --port 8000
```

**Endpoints.** The design 15.3 read routes `GET /api/v1/health/live`, `GET
/api/v1/health/ready`, `GET /api/v1/inspections`, `GET /api/v1/inspections/{id}`,
`GET /api/v1/inspections/{id}/media`, `GET /api/v1/media/{id}/content` (Range
supported), `GET /api/v1/device/status`, `GET /api/v1/inspection/state`, `GET
/api/v1/uploads`, `GET /api/v1/configuration/effective`, and `GET /api/v1/logs`,
plus the derived endpoints `GET /api/v1/traceability/{sn}` and `GET
/api/v1/statistics`. The live event channel (E4) streams inspection and device
events over `WS /api/v1/ws/runtime` (ticket at `POST /api/v1/ws/runtime/ticket`,
counters at `GET /api/v1/ws/runtime/stats`).

The API is **read-only for inspection control** (ADR-012): operator commands
such as `POST /api/v1/inspection/{pause,resume}` and camera reconnect are not
exposed. The only mutating routes are the controlled upload retry
`POST /api/v1/uploads/{id}/retry` (E3) and review submission
`POST /api/v1/inspections/{id}/reviews` (ADR-016) — both use the viewer
credential, a documented trade-off until an edge role model exists.

**Authentication, TLS, and secrets (E5).** When `AV_EDGE_API_TOKEN` (or
`--api-token`) is configured, every route except `GET /api/v1/health/live`
requires `Authorization: Bearer <token>` or an authenticated same-origin viewer
session. Open `/login` in the served dashboard and enter the configured token
once; it is exchanged for an HttpOnly, same-origin session cookie and is never
bundled or stored by the dashboard.

`serve` can expose local HTTPS with `--tls-cert`/`--tls-key` (or
`AV_EDGE_TLS_CERT`/`AV_EDGE_TLS_KEY`; the private key must not be readable by
group or others). The viewer and upload tokens also fall back to Docker secret
files under `/run/secrets/` when the environment variables are absent. Uploads
always use a separate credential (`AV_EDGE_UPLOAD_TOKEN`), never the viewer
token.

**Upload, storage, and retention configuration (E1/E2).** The upload scheduler
drains the transactional outbox only when a destination is configured — a local
development sink or an HTTPS central endpoint. Without one, tasks accumulate
visibly in the API and the queue stays intact:

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

**Multi-camera serve (`instances`, ADR-013).** `serve` can open several
independent camera instances from one config, each with its own source (folder
/ video / OpenCV device / RTSP / HTTP-image) and its own models/rule/product.
`inspection.enabled` defaults to `false`, so `serve` opens the sources and
serves previews without writing inspections:

```bash
uv run assemblyvision serve \
  --output out/ --db out/edge.sqlite3 \
  --config config/examples/pipeline.cameras.yaml \
  --static apps/edge-web/dist \
  --host 127.0.0.1 --port 8000
```

- Per-instance camera state: `GET /api/v1/camera/state` (aggregated) and the
  preview endpoint `GET /api/v1/camera/{instance_id}/preview` (latest frame as
  a rate-limited JPEG; `404` unknown instance, `503` not ready).
- Mock phase without hardware: `source: folder` (loopable image directory),
  `source: video`, or `source: rtsp` / `source: http-image` for remote
  TCP/IP inputs. A local or virtual camera driver (Linux `v4l2loopback`, OBS
  Virtual Camera) plugs in as `source: opencv-device`.
- Industrial cameras: `source: gige-vision` uses the hardened GigE Vision /
  GenICam source (PR #26) and requires `serial` and `gentl_producer` in the
  instance config plus a vendor GenICam producer at runtime; live validation
  on the target camera is still pending.
- Trigger/identity seam (E4b, ADR-015): an instance `trigger:` block enables
  the deterministic mock trigger source for development; the opt-in Modbus TCP
  FIFO trigger contract is the production path once a site-validated register
  profile exists.
- Each instance defaults to `device_id = uuid5(namespace, instance_id)` so
  records stay traceable per line across restarts; set `device_id` explicitly
  to override.

**Web dev test harness (`--enable-web-test`, ADR-014).** Start `serve` with
`--enable-web-test` to expose gated file-based test endpoints (disabled by
default):

```bash
uv run assemblyvision serve \
  --output out/ --db out/edge.sqlite3 \
  --config config/examples/pipeline.cameras.yaml \
  --static apps/edge-web/dist \
  --enable-web-test --host 127.0.0.1 --port 8000
```

Open the served dashboard at `/dev` (Test tab): take a photo with a phone
camera, upload an image, or upload a short video. Image tests write an evidence
bundle that appears in History (disable with the *persist* checkbox); video
tests return a per-frame summary without persisting. Endpoints: `POST
/api/v1/dev/inspect-frame` (optional `barcode` query simulates a keyboard
scanner) and `POST /api/v1/dev/inspect-video` (≤ 30 frames, < 100 MB). This is
a developer test harness, not a production acquisition path; it must not be
enabled on production hosts.

**Backup and restore (E5).**

```bash
uv run assemblyvision backup --output out/ --db out/edge.sqlite3 \
  --config config/examples/pipeline.yaml --rule config/examples/product-rule.yaml \
  --dest /backups/edge-$(date +%Y%m%d).tar.gz

uv run assemblyvision restore --backup /backups/edge-YYYYMMDD.tar.gz \
  --output out/ --db out/edge.sqlite3
```

The backup is a consistent SQLite online snapshot plus the governed
config/rule/manifest files and pending evidence with SHA-256 checksums into a
`.tar.gz` bundle; restore verifies every checksum before applying, keeps a
`.pre-restore` copy, never overwrites conflicting media, and reconciles the
store so pending upload tasks survive. See runbook 12 for the full procedure.

### 3.5 Edge service — Docker

The multi-stage `apps/edge-service/Dockerfile` resolves the pinned uv workspace
and installs dependencies non-editable, then ships only the virtualenv in a
slim runtime image running as the `av` (10001:10001) user with a read-only
root filesystem; data mount points are pre-created and owned by `av` so named
volumes inherit the right owner. The Docker `HEALTHCHECK` gates on
`python -m assemblyvision.healthcheck`.

```bash
docker build -f apps/edge-service/Dockerfile -t assemblyvision-edge .
docker run -d --name edge \
  -v edge-media:/data/media -v edge-db:/data/db \
  -p 127.0.0.1:8000:8000 \
  -e AV_EDGE_API_TOKEN=... -e AV_EDGE_UPLOAD_TOKEN=... \
  assemblyvision-edge
```

A `compose.yaml` template in `apps/edge-service/` provides persistent volumes,
restart policy, loopback binding, and no central-DNS dependency at startup.
Production runbooks: runbook 13 (TLS rotation), runbook 14 (deployment
upgrade and rollback), runbooks 04/05 (upload backlog / database recovery),
and the E2 retention policy enablement (cleanup stays disabled until an
approved policy exists).

### 3.6 Edge dashboard (`apps/edge-web`)

The dashboard runs **fully decoupled** from the backend. By default it uses an
in-memory mock client with pre-seeded data, so it starts with no trained models
or running service.

**Dev server.**

```bash
pnpm --filter edge-web dev        # http://localhost:5173
```

**Routes.**

| Route | Screen |
|---|---|
| `/` | **Operator dashboard** — current inspection status, product SN, rules, confirm/continue/manual actions |
| `/live` | Live inspection — camera image, detection result, regions, progress |
| `/history` | Inspection history — search by SN, filter by result, image links |
| `/traceability/:sn` | Product traceability — reinspection attempts and final status |
| `/images/:id` | Inspection images — original, detection result, annotations |
| `/statistics` | Production statistics — totals, PASS/NG, pass rate, date/line filters |
| `/device` | Device status — camera, vision engine, inspection service |
| `/uploads` | Upload queue — persistent outbox state with controlled manual retry (E3) |
| `/health` | Disk/queue charts, server-authoritative storage mode and alerts, device status |
| `/inspections` | Full record history (internal records) |
| `/configuration`, `/logs` | Read-only effective configuration and bounded log buffer |

**Mock vs real backend.**

- `VITE_API_MODE=mock` (dev default) runs the deterministic in-memory mock
  client.
- `VITE_API_MODE=http` (production default) talks to the FastAPI backend. An
  omitted `VITE_API_BASE_URL` means **same-origin** `/api/v1`, so the bundle
  served by `assemblyvision serve` reads its own API.

```bash
# Dev against a remote edge host:
VITE_API_MODE=http VITE_API_BASE_URL=http://edge-host:8000 pnpm --filter edge-web dev
```

When the edge host is token-protected, sign in on `/login` as usual. The
viewer session cookie is same-origin, so a cross-origin dev client keeps the
entered token **in memory only** and attaches it to API and media requests;
same-origin deployments keep the HttpOnly-cookie exchange and never see the
token. The operator workflow actions always run on the deterministic mock
client because they model a demonstration queue, not a design 15.3 contract
endpoint.

**Build and preview.**

```bash
pnpm --filter edge-web build      # bundle to apps/edge-web/dist (http mode)
pnpm --filter edge-web preview    # preview the build (default http://localhost:4173)
```

A production build selects the HTTP client by default, so the served dashboard
reads real data from the same-origin API with no extra flags.

**Tests.**

```bash
pnpm --filter edge-web test                    # Vitest (stores, client)
cd apps/edge-web && pnpm test:e2e              # Playwright smoke tests
```

### 3.7 Edge desktop (`apps/edge-desktop`)

Electron shell that runs the edge dashboard as a local desktop/kiosk app on the
edge machine, with hardened defaults (context isolation, sandboxed renderer, no
node integration). The dashboard must be built first for production mode;
development mode needs the Vite dev server running.

```bash
# Production mode
pnpm --filter edge-web build
pnpm --filter edge-desktop start

# Development mode (live reload) — terminal 1 Vite, terminal 2 Electron
pnpm --filter edge-web dev
ELECTRON_DEV=1 pnpm --filter edge-desktop dev   # or VITE_DEV_SERVER_URL=http://127.0.0.1:5173

# Kiosk mode
pnpm --filter edge-web build
pnpm --filter edge-desktop kiosk                # fullscreen, no application menu
```

---

## 4. Central Deployment

### 4.1 Overview and pilot status

The central M1 pilot is a management and evidence plane: it receives delayed
edge inspection and media uploads, stores history in PostgreSQL and evidence
in MinIO, and hosts the pilot administration UI. It is **never** required for
edge inspection decisions, and it preserves the current edge upload envelope
and verified-receipt semantics. The pilot is **feature-complete** (C1a–C6 plus
the E6-A16 edge-to-central integration fixture) and is a **controlled pilot**
(`docs/tasks/C1-central-server-m1.md` §13–14).

### 4.2 Docker Compose (the standard dev stack)

PostgreSQL, MinIO, the API (`central-service`), the one-shot migration step
(`central-migrate`), and the built admin UI (`admin-web`) start together. The
example environment file intentionally contains no usable credentials, so
populate every required value in a private `.env` before starting:

```bash
cp apps/central-service/compose.env.example apps/central-service/.env
# Edit .env: set POSTGRES_*, MINIO_*, CENTRAL_ADMIN_TOKEN, and
# CENTRAL_DEVICE_UPLOAD_TOKEN to unique non-empty values.
docker compose -f apps/central-service/compose.yaml up -d --build
curl http://localhost:8080/api/v1/health/live     # admin-web proxies /api to the API
```

- The API container health check uses `/api/v1/health/ready`; readiness
  returns `503` while PostgreSQL is unreachable, the schema is behind head,
  the MinIO bucket is unavailable, or the pilot credential is not configured.
- Schema migrations are a **controlled release step** run by the one-shot
  `central-migrate` service (`python -m central_service migrate`); the API
  never migrates automatically.
- `central-bootstrap` (one-shot) provisions the pilot organization, site,
  line, device, and administrator. Compose fails closed when any PostgreSQL,
  MinIO, administrator, or device-upload secret is unset.

### 4.3 Without Docker (CLI)

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

### 4.4 Production (controlled pilot)

The go-live checklist is recorded in `docs/tasks/C1-central-server-m1.md`
§13.2; the operational runbooks are `docs/runbooks/central-*.md` (C1 ingestion
backlog, C2 object-store failure, C3 credential compromise, C4 backup/restore,
C5 pilot upgrade/rollback). Key steps:

1. **TLS termination** in front of the API (admin-web nginx or a reverse
   proxy). The edge `HttpUploadSink` must reach `https://...`; plain HTTP is
   loopback-development only (contract 04). Keep `CENTRAL_SECURE_COOKIES=true`
   outside plain-HTTP loopback dev.
2. **Credentials**: set unique secrets in `apps/central-service/.env`
   (`CENTRAL_ADMIN_TOKEN`, `CENTRAL_DEVICE_UPLOAD_TOKEN`, MinIO keys, PostgreSQL
   password). The tracked example contains placeholders only; Compose fails
   closed when any required secret is unset.
3. **Migrations**: run `central-migrate` to head (`0006`) as a controlled
   release step; verify `GET /api/v1/health/ready` reports all dependencies ok.
4. **Backup/restore** (runbook C4): `pg_dump --format=custom` for PostgreSQL
   plus an S3-compatible mirror of the MinIO bucket (same dated bundle);
   restore into a fresh database and verify receipts replay duplicate-free.
5. **Upgrade/rollback** (runbook C5): build new images, migrate, verify;
   rollback restores the pre-upgrade backup (never a reverse migration).
6. **Rate limiting**: `AV_CENTRAL_RATE_LIMIT_REQUESTS_PER_MINUTE` (default 600
   per client; 0 disables). Health endpoints are never limited.

### 4.5 Admin-web (`apps/admin-web`)

The Vue 3 pilot administration UI. **Dev server** (proxies `/api` to the
central API):

```bash
pnpm --filter admin-web dev        # http://127.0.0.1:5174
```

Pages: overview, inspection history/detail, review queue, and the read-only
configuration pages (products, rules, models, desired configurations). Sign in
with `CENTRAL_ADMIN_TOKEN`.

**Production:** the Compose `admin-web` service builds the bundle and serves it
behind nginx, which proxies `/api` to the central API (loopback-bound by
default). i18n is build-time configurable via `VITE_DEFAULT_LOCALE`
(`en` / `zh-CN` / `zh-HK` / `ja`).

### 4.6 Tests

```bash
uv run pytest apps/central-service/tests        # health, readiness, settings, ingest, review, metadata, hardening
uv run pytest scripts/tests/test_edge_central_e2e.py   # E6-A16: real edge scheduler vs central
cd apps/admin-web && pnpm test:e2e              # pilot UI smoke test (CENTRAL_E2E_TOKEN against Compose)
```

---

## 5. Quality Gates and Acceptance

Run all Python + TypeScript gates together:

```bash
make check
```

Individually:

```bash
uv run ruff check . && uv run ruff format --check .   # Python lint
uv run mypy .                                          # Python types
uv run pytest                                          # Python tests (edge, central, packages, training, scripts)
pnpm -r build && pnpm -r lint && pnpm -r test          # TypeScript
uv run mkdocs build --strict                           # documentation
```

CI enforces the OpenAPI drift checks
(`uv run python scripts/generate-central-openapi.py` and the edge equivalent)
and the generated client drift checks (`pnpm --filter @assemblyvision/api-client-central generate:types`,
edge equivalent included), so a schema change must be committed with its
regenerated artifacts.

### 5.1 E6 edge acceptance evidence

The E6-prep acceptance runner executes every supported locally automatable E6
acceptance item and emits a machine-readable evidence manifest. On-site items —
real camera/SDK, barcode decode, PLC/photo-eye trigger, GPU failure, power
loss, long soak, and unseen customer data — are recorded as `NOT_EXECUTED`
with their required environment, never as pass.

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
human-readable summary. Exit code `0` means all required local checks passed
with a complete artifact lock; `1` means a check failed; `2` means the result
is incomplete (missing artifact lock or a skipped/unsupported local check).
See [docs/tasks/E6-edge-acceptance.md](docs/tasks/E6-edge-acceptance.md) and
[docs/design/28-edge-acceptance-report.md](docs/design/28-edge-acceptance-report.md).

---

## 6. Environment Variable Reference

### 6.1 Edge (`AV_EDGE_*`)

| Variable | Default | Purpose |
|---|---|---|
| `AV_EDGE_API_TOKEN` | unset | Viewer bearer token; every route except `/health/live` requires it when set |
| `AV_EDGE_UPLOAD_TOKEN` | unset | Separate upload credential (never the viewer token) |
| `AV_EDGE_UPLOAD_BASE_URL` | unset | Central endpoint; scheduler drains only when set |
| `AV_EDGE_UPLOAD_SINK_DIR` | unset | Local dev sink directory (alternative destination) |
| `AV_EDGE_UPLOAD_INSECURE_HTTP` | false | Allow plaintext HTTP for loopback dev only |
| `AV_EDGE_UPLOAD_INTERVAL_SECONDS` / `_LEASE_SECONDS` | 1 / 120 | Scheduler cadence and claim lease |
| `AV_EDGE_UPLOAD_MAXIMUM_BANDWIDTH_MBPS` | unset | Token-bucket bandwidth cap (E3) |
| `AV_EDGE_UPLOAD_CIRCUIT_FAILURE_THRESHOLD` / `_OPEN_SECONDS` | 5 / 60 | Circuit breaker (E3) |
| `AV_EDGE_STORAGE_WARNING/CRITICAL/STOP_FREE_PERCENT` | 20 / 10 / 5 | Disk-pressure thresholds (E2) |
| `AV_EDGE_STORAGE_INTEGRITY_*` | verify on | Startup media integrity scanning (E2) |
| `AV_EDGE_RETENTION_ENABLED` / `_DURATIONS` / `_HOLD_*` | disabled | Receipt-gated cleanup policy (E2) |
| `AV_EDGE_TLS_CERT` / `AV_EDGE_TLS_KEY` | unset | Local HTTPS for `serve` (E5) |

### 6.2 Central (`AV_CENTRAL_*`)

| Variable | Default | Purpose |
|---|---|---|
| `AV_CENTRAL_DATABASE_URL` | required | `postgresql+psycopg://` SQLAlchemy URL |
| `AV_CENTRAL_MINIO_ENDPOINT` / `_ACCESS_KEY` / `_SECRET_KEY` / `_BUCKET` / `_SECURE` | localhost / empty / empty / `assemblyvision-central` / false | Object store |
| `AV_CENTRAL_ADMIN_TOKEN` | unset | Bootstrap-only admin credential (≥16 chars) |
| `AV_CENTRAL_DEVICE_UPLOAD_TOKEN` | unset | Bootstrap-only device upload credential |
| `AV_CENTRAL_SECURE_COOKIES` | true | `Secure` on the admin session cookie |
| `AV_CENTRAL_ADMIN_SESSION_TTL_MINUTES` | 480 | Browser session lifetime |
| `AV_CENTRAL_MAX_ENVELOPE_BODY_BYTES` | 32 MiB | Raw request body cap (413) |
| `AV_CENTRAL_MAX_INSPECTION_PAYLOAD_BYTES` | 1 MiB | Decoded inspection payload cap |
| `AV_CENTRAL_MAX_MEDIA_PAYLOAD_BYTES` | 16 MiB | Decoded media payload cap |
| `AV_CENTRAL_RATE_LIMIT_REQUESTS_PER_MINUTE` | 600 | Per-client request cap (0 disables; health exempt) |
| `AV_CENTRAL_CORS_ALLOW_LOOPBACK` | true | Loopback-only CORS for browser dev |

### 6.3 Compose (`.env` for `apps/central-service/compose.yaml`)

`POSTGRES_USER` / `POSTGRES_PASSWORD` / `POSTGRES_DB`, `MINIO_ROOT_USER` /
`MINIO_ROOT_PASSWORD` / `MINIO_BUCKET`, `CENTRAL_ADMIN_TOKEN` /
`CENTRAL_DEVICE_UPLOAD_TOKEN` (all required; the tracked example has no usable
defaults),
`CENTRAL_SECURE_COOKIES`, `CENTRAL_RATE_LIMIT_REQUESTS_PER_MINUTE`,
`ADMIN_WEB_PORT`. See `apps/central-service/compose.env.example`.

### 6.4 Frontend (`VITE_*`)

`VITE_API_MODE` (`mock` dev / `http` production), `VITE_API_BASE_URL`
(same-origin `/api/v1` when omitted), `VITE_DEFAULT_LOCALE`
(`en` default; `zh-CN` / `zh-HK` / `ja`), and the admin-web
`assemblyvision.admin.locale` / `assemblyvision.admin.theme` storage keys.

---

## 7. Troubleshooting

| Symptom | Cause / fix |
|---|---|
| Edge `/health/ready` → `503`, intake stops, `DISK_STOP` alert | Volume free space ≤ `AV_EDGE_STORAGE_STOP_FREE_PERCENT` (default 5). Free disk or raise thresholds; the fail-safe is by design (runbook 03). |
| Edge rejects a model/rule | Manifest checksum/class map mismatch or `(rule_id, rule_version)` reused with different content — `CONFIG_INVALID`; bump the pair together (§3.3, runbooks 08/09). |
| Edge never reaches `SYNCED` | Scheduler destination unset (`AV_EDGE_UPLOAD_BASE_URL`/`_SINK_DIR`), `429`/`5xx` backoff, or central dependency down — runbook 04 / central runbook C1. |
| Central `/health/ready` → `503` | PostgreSQL unreachable, schema behind head (`central-migrate`), MinIO bucket missing, or pilot not bootstrapped. |
| Central `503 DATABASE_UNAVAILABLE` + `Retry-After` | Transient DB dependency failure; retry (C6). `IntegrityError` conflicts keep their explicit `409`. |
| Central `429 RATE_LIMITED` + `Retry-After` | Per-client window exceeded; raise `AV_CENTRAL_RATE_LIMIT_REQUESTS_PER_MINUTE` or wait (health endpoints exempt). |
| Upload → `409 PAYLOAD_CONFLICT` | A retry reused an idempotency key/id/sequence with different content; never force-clear — investigate (runbook C1). |
| Media upload → `422 MEDIA_MANIFEST_MISMATCH` / `503 OBJECT_STORE_UNAVAILABLE` | Bytes do not match the parent inspection manifest, or MinIO is down (runbook C2). |
| Admin-web shows 404 for configuration pages | The deployed central API is older than the UI; rebuild + migrate the stack (runbook C5). |

---

## 8. Project Layout

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
scripts/                        # dataset adapters, OpenAPI generation, E6 runner, edge-central e2e
tests/fixtures/                 # small non-sensitive test fixtures
docs/                           # architecture, contracts, ADRs, runbooks, tasks
```

---

## 9. Operational Status

- **Edge**: E1–E5 production gates merged; E6-prep tooling delivered; **on-site
  acceptance** (real camera/SDK, barcode, PLC/photo-eye trigger, GPU, unseen
  customer data, resilience/soak) remains gated on hardware and customer data.
- **Central**: M1 pilot **feature-complete** (C1a–C6 + E6-A16 integration
  fixture + recorded exit-criteria evidence). Controlled-pilot deployment
  follows the §13.2 checklist on the pilot host; production scope (OIDC/RBAC,
  remote rollout, resumable uploads, retention enforcement, DR) is deferred.
- **Training**: the developer-only `av-train` loop is the current release path;
  governed training pipelines and remote package distribution are production
  scope.
- See [QUICKSTART.md](QUICKSTART.md) for the fast path and
  [SECURITY.md](SECURITY.md) for the security policy and vulnerability
  reporting.
