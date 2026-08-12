# AssemblyVision Quickstart

> **Short developer guide.** Get every component running locally with the fewest
> commands. For the exhaustive reference covering dev, production, and training
> deployment, see [DEPLOYMENT.md](DEPLOYMENT.md).

AssemblyVision inspects assembled products on a production line: the **edge**
computers make every inspection decision locally (two-stage YOLO + deterministic
rules), and the **central server** is a delayed management/evidence plane
(PostgreSQL history, MinIO evidence, review, governed metadata) that is never
in the real-time inspection path.

| Component | What it is | Fast path |
|---|---|---|
| Edge CLI | train / inspect / verify | `uv run assemblyvision inspect ...` |
| Edge service | local API + dashboard | `uv run assemblyvision serve ...` |
| Edge dashboard | operator UI (Vue 3) | `pnpm --filter edge-web dev` |
| Edge desktop | kiosk shell | `pnpm --filter edge-desktop start` |
| Central server | M1 pilot API (PostgreSQL + MinIO) | `uv run python -m central_service serve` |
| Central dashboard | admin UI (Vue 3) | `pnpm --filter admin-web dev` |

## 1. Prerequisites

- [uv](https://docs.astral.sh/uv/) — Python 3.12 toolchain
- [pnpm](https://pnpm.io/) + Node.js 20+ — TypeScript workspace
- PostgreSQL and an S3-compatible object store — only for the central server
- macOS / Linux / Windows for development; Linux is the primary production OS

## 2. One-time setup

```bash
git clone https://github.com/dream-studio-china/assembly-vision.git
cd assembly-vision
git checkout dev          # `dev` is the development branch, kept in sync with `main`
uv sync                   # Python workspace (edge-service, packages)
pnpm install              # TypeScript workspace (edge-web, admin-web, packages)
```

## 3. Verify the toolchain

```bash
make check                # ruff + mypy + pytest + pnpm build/lint/test + Playwright smoke
```

## 4. Training the models (developer-only)

Two-stage detection needs a **product detector** (finds the product) and a
**component detector** (verifies required parts inside the ROI).

### 4.1 Get a dataset

- **Synthetic demo (fastest):** `scripts/e2e-demo.sh /tmp/av-e2e` trains on a
  generated labeled dataset (~10 min on a laptop) and runs the full
  train → inspect → verify loop, gating on zero false negatives.
- **Real data:** annotate production images with X-AnyLabeling (product
  full-board box + required component boxes; a missing component is left
  unlabeled, never a generic `missing_*` class), export the YOLO layout, then:

  ```bash
  uv run python scripts/adapt-xanylabeling.py <xal-export> <out> \
    --product-class product --required 'chip,capacitor,boot'
  ```

  Roboflow exports use `scripts/adapt-roboflow-dataset.py`. See
  `docs/design/19-training-and-evaluation.md` §19.17 for annotation rules and
  `docs/runbooks/11-data-collection-and-annotation.md` for the full procedure.

### 4.2 Train both stages

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

### 4.3 Release the pair together

After training, update `pipeline.yaml` `model_version` and the rule's
`compatible_component_model_versions` **together** — never one without the
other (see `docs/runbooks/10-model-improvement.md`).

## 5. Edge inspection CLI

```bash
# Inspect a folder of images (requires trained models in the pipeline config):
uv run assemblyvision inspect /path/to/images \
  --config config/examples/pipeline.yaml \
  --rule config/examples/product-rule.yaml \
  --output out/

# Verify against expected labels (report NG recall / FN / FP; exit non-zero on FN):
uv run assemblyvision verify /path/to/test-images \
  --config config/examples/pipeline.yaml \
  --rule config/examples/product-rule.yaml \
  --expected test-expected.json \
  --output out/
```

## 6. Edge local API and dashboard (`serve`)

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

Open `http://127.0.0.1:8000` — sign in with the configured `AV_EDGE_API_TOKEN`
once (exchanged for an HttpOnly session cookie). Add `--enable-web-test` for
the browser-based dev test harness (`/dev` tab: photo / image / short video
analysis).

## 7. Edge dashboard (dev, decoupled)

```bash
pnpm --filter edge-web dev      # http://localhost:5173 (mock data by default)
# Real backend: VITE_API_MODE=http VITE_API_BASE_URL=http://edge-host:8000 pnpm --filter edge-web dev
```

## 8. Central server — the API (M1 pilot)

Run the API against your own PostgreSQL and an S3-compatible object store
(dev defaults below; override secrets in real use):

```bash
(
  export AV_CENTRAL_DATABASE_URL=postgresql+psycopg://central:secret@127.0.0.1:5432/assemblyvision
  export AV_CENTRAL_MINIO_ENDPOINT=127.0.0.1:9000
  export AV_CENTRAL_MINIO_ACCESS_KEY=minioadmin
  export AV_CENTRAL_MINIO_SECRET_KEY=minioadmin
  export AV_CENTRAL_ADMIN_TOKEN=pilot-admin-token-0123456789
  export AV_CENTRAL_DEVICE_UPLOAD_TOKEN=pilot-device-token-0123456789
  uv run python -m central_service migrate && \
  uv run python -m central_service bootstrap && \
  uv run python -m central_service serve --host 127.0.0.1 --port 8000
)
```

- Readiness `/health/ready` fails closed while PostgreSQL, MinIO, the schema,
  or the pilot credentials are not ready; migrate/bootstrap are controlled
  release steps — the API never auto-migrates.
- Point `AV_EDGE_UPLOAD_*` at the central endpoint to sync the edge outbox
  (see DEPLOYMENT.md).

## 9. Admin-web — the central UI (M1 pilot)

The Vue 3 administration UI runs as its own dev server and proxies `/api` to
the central API from section 8:

```bash
pnpm --filter admin-web dev      # http://127.0.0.1:5174
```

- Sign in with `AV_CENTRAL_ADMIN_TOKEN` (the same token from section 8).
- Pages: overview, inspection history/detail, review queue, and the read-only
  configuration pages (products, rules, models, desired configurations).
- In production the built admin-web is served by the central stack (nginx
  proxy) — see DEPLOYMENT.md.

## 10. Quality gates

```bash
make check
```

## 11. Full documentation

- **Every deployment scenario** (dev / production / training, env reference,
  troubleshooting): [DEPLOYMENT.md](DEPLOYMENT.md)
- Central M1 plan and exit criteria: `docs/tasks/C1-central-server-m1.md`
- Architecture / contracts / ADRs / runbooks: `docs/` (MkDocs site:
  `uv run mkdocs build --strict`)
