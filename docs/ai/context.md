# AssemblyVision - Full Project Context

> Context snapshot. Last updated: 2026-08-09
>
> Read this file first in a new session to reconstruct the project state quickly.

---

## 1. Project Overview

**AssemblyVision - Industrial Assembly Inspection System** is an edge-first industrial
computer-vision platform for conveyor-based production lines. It inspects completed products
and verifies that all required assembly components are present.

- **Business output**: `OK` (all required components reliably detected) or `NG` (missing,
  uncertain, or unverifiable). Quality priority is **minimizing false negatives** (high NG
  recall, extremely low false-negative rate). No 100% accuracy claims are ever made.
- **Architecture**: edge-client + central-server. All production-critical image processing and
  final decisions execute on the edge industrial computer; the central server is never required
  for real-time inspection.
- **Current repository state**: the static train-and-inspect MVP (ADR-011),
  the edge dashboard frontend, the M1 FastAPI + SQLite backend layer, the
  review-driven hardening, and the real-data baseline tooling are all merged
  to `main` (PRs #3, #6, #8, #9, #10, #11). The Python uv workspace ships
  shared `domain` and `vision-core` packages, a developer-only `av-train`
  training CLI, real two-stage Ultralytics YOLO inspection
  (`assemblyvision inspect`) and held-out verification, plus dataset adapters
  for Roboflow and X-AnyLabeling exports. The frontend pnpm workspace includes
  the Vue 3 + TypeScript operator dashboard (`apps/edge-web`), an Electron
  kiosk shell (`apps/edge-desktop`), a typed `api-client` contract layer, and
  shared UI primitives. PR #11 (dev -> main) added the real-data baseline
  tooling: the X-AnyLabeling dataset adapter, the single-product
  data-acquisition guidance (design §19.17, runbook 11), and README/QUICKSTART
  updates. Read-only dashboard views display real CLI results through the HTTP
  client, while the operator workflow actions remain on the mock client.
  PR #12 (dev -> main) closed the AUDIT-001 findings with acceptance tests
  (merged 2026-08-09); see section 8.4.

## 2. Repository State

- Remote: `https://github.com/dream-studio-china/assembly-vision`. PRs #3, #6,
  #8, #9, #10, #11, #12 are merged to `main`; PR #12 merged the completed
  AUDIT-001 closure on 2026-08-09. The next milestones are the upload
  scheduler + authoritative persistence (AUDIT-001 4.4) and collecting real
  customer data.
- `.obsidian/`, `.idea/`, and `.vscode/` are ignored local editor state.
- Runtime data, model weights, production media, datasets, and secrets must never be stored in
  Git. Build artifacts `docs-zh/`, `site/`, `mkdocs-en.yml`, `mkdocs-zh.yml` are gitignored.

## 3. Directory Structure

```
assembly-vision/
├── README.md               # Root README with docs map + bilingual site instructions
├── QUICKSTART.md           # Developer onboarding: setup, checks, CLI, end-to-end demo
├── AGENTS.md               # Coding rules: language, engineering, git workflow, security
├── LICENSE                 # MIT License (c) 2026 dream-studio-china
├── .gitignore              # Ignores site/, docs-zh/, generated configs, Python/OS artifacts
├── Makefile                # Quality gates: lint, format, typecheck, test, check
├── mkdocs.yml              # Master bilingual MkDocs config (Material, Mermaid rendering)
├── scripts/
│   ├── translate-docs.py            # docs/ -> docs-zh/ Chinese translation (deep-translator)
│   ├── generate-mkdocs-configs.py   # generates mkdocs-en.yml / mkdocs-zh.yml from mkdocs.yml
│   ├── build-docs.sh                # translate -> build site/ (EN) and site/zh/ (ZH)
│   ├── e2e-demo.sh                  # full train->prepare->train->inspect->verify smoke test
│   ├── generate-synthetic-dataset.py# procedural labeled assembly dataset (exact boxes)
│   ├── adapt-roboflow-dataset.py    # Roboflow YOLOv8 export -> two-stage layout
│   ├── adapt-xanylabeling.py        # X-AnyLabeling YOLO export -> two-stage layout
│   ├── generate-edge-openapi.py     # regenerate the committed edge OpenAPI doc
│   └── tests/                       # tests for the dataset adapters
├── .github/workflows/               # ci.yml (repo-wide quality gates) + docs.yml (Pages deploy)
├── apps/edge-service/                # inspection runtime (inspect/verify CLI, pipeline, rules, detectors)
├── apps/edge-web/                    # Vue 3 operator dashboard (Vite)
├── apps/edge-desktop/                # Electron kiosk/desktop shell
├── packages/
│   ├── python/
│   │   ├── domain/                   # canonical models, errors, reason codes
│   │   └── vision-core/              # ROI engine, image sources, manifest loading
│   └── typescript/
│       ├── api-client/               # edge API contract (types, Mock/HTTP client)
│       └── ui/                       # shared UI primitives (DetectionViewer, status, formatters)
├── training/                         # developer-only av-train CLI (product/prepare-components/component)
├── config/examples/                  # Example pipeline, rule, and manifest configuration
├── models/manifests/                 # Checked model metadata; weights remain outside Git
├── tests/fixtures/                   # Small non-sensitive test fixtures
├── pyproject.toml                    # Root uv workspace configuration (Python)
├── package.json                      # Root pnpm workspace (TypeScript)
├── pnpm-workspace.yaml               # pnpm workspace definition
├── pnpm-lock.yaml                    # locked frontend dependencies
└── docs/
    ├── index.md            # MkDocs home page
    ├── README.md           # Documentation index
    ├── source-brief.md     # Original architecture task brief (was doc-task.md)
    ├── contributing.md     # Contributor-facing repository rules and precedence
    ├── overrides/main.html # Theme override placeholder
    ├── ai/context.md       # THIS file
    ├── reviews/            # Reviews: PR-003, PR-008, AUDIT-001 system audit
    ├── contracts/          # 11 mandatory engineering contracts + index
    ├── runbooks/           # 11 operational recovery runbooks + index
    ├── design/             # 28 design documents + appendices + decisions/
    │   ├── 00-cover-and-status.md ... 27-risks-and-mitigations.md
    │   ├── appendices.md   # Terminology, decision checklist, open questions, reason codes
    │   └── decisions/      # ADR-001 ... ADR-012 + README
    └── research/           # 3 external-research reports
        ├── 01-industrial-inspection-success-rates.md
        ├── 02-yolo-capabilities-and-success-rates.md
        └── 03-imaging-workflow-and-training-cost.md
```

## 4. Architecture Summary (from docs/design/)

- **Edge client responsibilities**: camera integration, capture/trigger, product-window
  management, barcode recognition, product-type resolution, two-stage YOLO detection, ROI
  generation, optional OpenCV checks, per-component temporal aggregation, deterministic rule
  evaluation, local database/media, upload queue with retry, health monitoring, local FastAPI,
  local Vue dashboard. Inspection continues during central/network outages.
- **Central server responsibilities**: ingestion of selected results/media, history, governed
  metadata, manual review records, bounded pilot status, and later administration/reporting/audit.
  Remote package distribution is production scope. Central is not required for inspection.
- **Two-stage detection**: stage one detects the product in the full frame; the ROI engine
  expands/clips it; stage two detects required components (`component_a`, `component_b`,
  `component_c`, `manual`, ...) inside the ROI. Barcode decoding is separate from YOLO.
- **Temporal aggregation**: per-required-component evidence across frames (no whole-product
  majority voting). Aggregation improves system robustness, not single-frame model accuracy.
- **Rule engine**: deterministic, independent of the AI model, versioned. Only complete valid
  evidence may produce `OK`; internal `UNCERTAIN` always maps to business `NG`.
- **Deployment**: Python 3.12 / FastAPI / YOLO / OpenCV edge backend, Vue 3 + TypeScript
  frontends, Docker Compose (no Kubernetes at the edge), PostgreSQL central + SQLite edge (MVP).
- **Upload policy**: selective (OK: metadata + one key frame; NG: full metadata + multiple key
  frames + optional clip); persistent queue, retry with backoff, idempotency, checksums.

## 5. Documentation Set

- `docs/design/00` to `27` + [appendices.md](../design/appendices.md): cover/status, introduction, requirements,
  architecture overview, edge client, central server, AI detection pipeline, camera & image
  acquisition, product detection & ROI, component detection, temporal aggregation, rule engine,
  local storage & retention, upload & synchronization, data model & database, REST API & events,
  edge dashboard, central admin dashboard, monorepo & code organization, training & evaluation,
  deployment & operations, security & source distribution, testing & QA, observability & support,
  human-in-the-loop, roadmap, customer acceptance, risks & mitigations.
- `docs/design/decisions/`: ADR-001 edge-first inspection, ADR-002 Python backend, ADR-003 Vue 3
  + TypeScript frontend, ADR-004 two-stage detection, ADR-005 local-first storage & delayed
  upload, ADR-006 REST + WebSocket, ADR-007 monorepo, ADR-008 Docker deployment, ADR-009
   static-image-first MVP, ADR-010 per-component temporal aggregation, ADR-011 labeled
   train-and-inspect MVP, ADR-012 edge API M1 viewer auth, and ADR-013 camera frame
   sources and multi-instance edge.
- [docs/design/appendices.md](../design/appendices.md) holds the canonical terminology, decision consistency checklist,
  global open questions (OQ-001 ... OQ-025), reason-code glossary, and traceability conventions.
- `docs/research/`: industry success rates, YOLO capabilities, imaging/workflow/training cost.
- [docs/contracts/](../contracts/README.md): 11 enforceable architecture, safety, API, quality,
  operations, security, change-control, and acceptance contracts.
- [docs/runbooks/](../runbooks/README.md): executable recovery procedures for all contract-required
  operational scenarios, including model improvement (runbook 10) and data
  collection and annotation (runbook 11).

## 6. Bilingual MkDocs (English + Chinese)

- Master config `mkdocs.yml` is the single source of truth (Material theme, Mermaid rendering via
  `pymdownx.superfences` custom fence, `extra.alternate` language switcher).
- `scripts/build-docs.sh` pipeline: `translate-docs.py` (docs/ -> docs-zh/) ->
  `generate-mkdocs-configs.py` (produces mkdocs-en.yml + mkdocs-zh.yml) -> build site/ and site/zh/.
- Translation uses `deep-translator` GoogleTranslator (free, no API key). Rate-limited; a full
  translation takes ~15-30 minutes. Single-file mode:
  `python scripts/translate-docs.py design/03-architecture-overview.md`. On any API failure the
  original English chunk is kept.
- All content is translated, including `research/` and Mermaid diagram labels. Mermaid syntax is
  preserved; only node labels, edge text, subgraph titles, sequence messages, and state/ER labels
  are translated. `research/` no longer has a special copy step (removed from build-docs.sh).
- Translated headings keep their original English slug as an explicit `{#slug}` attribute so
  cross-document anchors (e.g. [appendices.md#3-global-open-questions](../design/appendices.md#3-global-open-questions)) work in Chinese too.
- Known machine-translation quality issues (not script bugs): `frames` -> 框架 (should be 帧),
  `volume` -> 音量 (should be 存储卷), `poll` -> 民意调查 (should be 轮询). Review before publishing.
- `docs-zh/`, `site/`, and the generated configs are build artifacts, not committed.

## 7. Conventions (AGENTS.md)

- English is the base language; all docs/comments/commits/READMEs MUST be English.
- Conventional Commits: `feat:`, `fix:`, `docs:`, `chore:`, `refactor:`.
- Branch naming: `feat/xxx`, `fix/xxx`, `docs/xxx`.
- Do NOT commit unless explicitly asked; do NOT push or force-push without explicit approval.
- No secrets committed. Use typed Pydantic models and TypeScript interfaces.
- Engineering rules: preserve edge-first architecture; keep AI inference / rule evaluation /
  persistence / Web APIs separated; do not put YOLO logic in FastAPI route handlers; do not put
  business rules in the AI model; edge must not depend on the central server; run tests + Ruff +
  MyPy; never claim tests passed without executing; never claim 100% accuracy.

## 8. Latest Session Decisions

- Generated the full architecture document set under `docs/design/` (28 docs + 12 ADRs +
  appendices) from [docs/source-brief.md](../source-brief.md) (formerly `docs/doc-task.md`).
- Created `docs/research/` (3 reports) via internet research.
- Built the bilingual MkDocs with automatic translation, adapted from the `crud-skeleton` project.
- Added Mermaid translation to `translate-docs.py` (labels/edge text only, syntax preserved).
- `UNCERTAIN` decision state is mandated to always map to business `NG` (not configurable).
- Edge deployment is a single `edge-service` process for the first production release (a separate
  edge worker/API split is deferred until measurements justify it).
- Inspections pin both product-detector and component-detector model versions separately.
- The one-month scope is a bounded controlled integration demonstrator, not complete production
  acceptance; generalized administration, remote distribution, and full resilience/soak work follow.
- ADR-011 supersedes ADR-009 only for the MVP training exclusion and two-day scope. The selected
  annotation tool is X-AnyLabeling; the MVP uses standard YOLO labels, a separate developer-only
  training CLI, real two-stage models, and held-out filename-ground-truth verification.
- Model encryption and `.pyc`-only runtime packaging are deferred. The MVP protection boundary is
  that training code, datasets, notebooks, and experiment configuration are not distributed.
- The MVP is implemented and validated end to end (M1-M5): shared `domain`/`vision-core`
  packages were extracted; the developer-only `training/` workspace and `av-train`
  (product / prepare-components / component) were added; detector stubs were replaced with real
  Ultralytics YOLO adapters that load manifest-referenced weights and map ROI boxes back to full
  frame; `assemblyvision verify` reports NG recall / false negatives / false positives; and
  `scripts/e2e-demo.sh` runs the full flow with a hard gate on false negatives.
- Datasets: `scripts/generate-synthetic-dataset.py` builds a labeled assembly dataset (exact
  boxes, missing-component NG variants) for framework testing; `scripts/adapt-roboflow-dataset.py`
  converts a Roboflow YOLOv8 export into the two-stage layout, drops generic `missing*` classes,
  and requires an independently annotated full-product class (the union of component boxes is
  rejected). The source `test` split becomes the held-out verification set only; it is never
  copied into training or validation, and split overlap is checked by SHA-256.
  `scripts/adapt-xanylabeling.py` does the same for X-AnyLabeling YOLO exports
  (classes.txt/data.yaml names; images-first or split-first layouts).
- Real-data tooling: the collection and annotation guidance lives in
  `docs/design/19-training-and-evaluation.md` §19.17 (single-product quantities,
  hard annotation rules) and `docs/runbooks/11-data-collection-and-annotation.md`
  (operational procedure). A local test drive downloaded the CC0 smdComponents
  set and the CC BY 4.0 PCBs-detection set under `data/test-training/`
  (gitignored) and trained a board-level missing-part detector (val mAP50 ~0.94;
  60-image held-out NG recall 0.848, all misses on multi-missing boards) - a
  demonstration, not an accuracy claim.
- A read-only system audit (recorded in
  `docs/reviews/AUDIT-001-system-audit.md`) ran 12 parallel sub-agent audits
  plus dynamic stress tests: no HIGH runtime vulnerability and no secrets;
  the HTTP read path handled 200 concurrent requests with zero errors. Four
  HIGH data-integrity/doc findings (adapter missing-label fabrication, stale
  staging paths in published data.yaml, av-train relative-path
  runs/detect-nesting, stale PR state) and three reproduced concurrency and
  robustness defects were recorded; all are now closed (PR #12, section 8.4).
- Model improvement is a developer-side loop (docs/runbooks/10-model-improvement.md):
  collect/correct data -> retrain -> verify no regression -> bump pipeline config and the rule's
  `compatible_component_model_versions` together (`av-train --rule` prints the suggested bump).
- Base YOLO weights are cached under `training/.cache/weights/` (gitignored); trained artifacts go
  to `models/weights/` (gitignored) with manifests under `models/manifests/`.

## 8.1 Review-Driven Hardening (PR-003 follow-up)

A code review of the `feat/mvp` runtime, training, and verification surfaces led
to a hardening pass that is committed and validated on `feat/mvp` (P0 items all
fixed; remaining P1/P2 items tracked in `docs/reviews/PR-003-review.md`):

- Rule engine: `expected_count` is enforced as an exact count, declared spatial
  constraints (`min_box_area_ratio`, `max_box_area_ratio`, `allowed_zone`) are
  evaluated against per-detection normalized ROI evidence, empty rules are
  rejected, and unsupported rule schema versions or empty model-compatibility
  lists fail closed.
- Verification: incomplete evidence (uncertain states, image-read/inference/ROI/
  rule failures) is no longer scored as a true positive, and skipped, failed,
  and unmatched expected samples make `verify` exit non-zero.
- Model integrity: runtime verifies artifact size and SHA-256, validates the
  loaded model class map against the manifest, rejects absolute artifact URIs,
  and binds the rule-facing model version to the verified manifest.
- Detector fail-safe: malformed output (invalid class IDs, non-finite confidence
  or coordinates, out-of-bounds boxes, bad tensor shapes) is converted to
  `INFERENCE_ERROR` at the adapter boundary instead of escaping or mis-indexing.
- Configuration: thresholds must be finite and in `[0, 1]`, booleans are strict,
  `min_area_pixels` must be a positive integer, and unknown keys are rejected in
  every section.
- Training data: malformed or out-of-range labels, zero-sized and out-of-frame
  boxes are fatal; missing label files fail validation unless the recorded
  `--allow-missing-labels` legacy opt-in is used; empty label files are valid
  negatives; component preparation keeps negative ROI crops; and published
  model versions refuse to be silently overwritten with different bytes.
- Quality gates: `ruff check .`, `ruff format --check .`, `mypy .`, and
  `pytest` now cover the whole repository (edge, packages, training, scripts
  tests) via the Makefile and a new `.github/workflows/ci.yml`.

## 8.2 Edge Dashboard and Operator Prototype (PR #6)

The frontend was built as a decoupled Vue 3 + TypeScript layer sharing a
pnpm workspace with the existing Python uv workspace, then merged to `main`:

- **Contract layer** (`@assemblyvision/api-client`): hand-synchronized TS types
  from the domain Pydantic models, an `ApiClient` interface, `MockApiClient`
  (deterministic in-memory data with an operator workflow state machine and mock
  SVG images), `HttpApiClient` (talks to the real `/api/v1` endpoints with
  runtime response validation at the fetch boundary), and a reconnecting
  WebSocket service.
- **Shared UI** (`@assemblyvision/ui`): `DetectionViewer` (contain-scaled
  preview with source-coordinate overlays, frame-ID reconciliation, stale-frame
  marker), color-independent `StatusBadge`, and display formatters.
- **Operator dashboard** (`apps/edge-web`): production inspection dashboard
  (Waiting/Processing/PASS/NG status, SN metadata, product image with overlay
  boxes, rule checks, confirm/continue/manual actions), live camera/detection
  view with runtime logs and inspection details, history (SN search + result
  filter), traceability per SN with reinspection attempts, statistics (ECharts
  with date/line filters), image management (original/detection/annotated),
  device status, and upload queue. All data flows through an API service layer
  that selects the mock or HTTP client explicitly via `VITE_API_MODE`; the
  operator workflow actions are mock-only and hidden in real mode.
- **Electron desktop** (`apps/edge-desktop`): hardened defaults (context
  isolation, sandbox, no node integration), kiosk mode, and production builds
  are loaded from the built edge-web output.
- **Tests and CI**: 63 Vitest unit tests across api-client/ui/edge-web/desktop
  (30 + 13 + 17 + 3), 12 Playwright e2e, a `web` CI job
  (build/lint/test/e2e), and `make check` now runs both Python and TypeScript
  gates.
- **Documentation**: QUICKSTART restructured per-app with extensible numbered
  sections; README updated with new features, project structure, and roadmap.

## 8.3 Edge Backend Layer (M1, PR #8)

The FastAPI + SQLite backend layer on `dev` gives read-only dashboard views real
CLI inspection results. PR #8 (dev -> main) carries this milestone; the
blocking findings (F1-F14) and M1 conditional items (C1-C4) in
`docs/reviews/PR-008-review.md` are resolved and validated on `dev`.

- **`assemblyvision serve`**: starts the local API on `/api/v1` (design 15.3),
  serves the built dashboard as static assets with SPA fallback, opens a SQLite
  index, and reconciles existing CLI `inspection.json` output idempotently on
  startup. Configuration/rule/manifest loading reuses the same verified
  pipeline build as `inspect`.
- **Persistence**: SQLAlchemy Core schema + Alembic migrations 0001/0002
  (`apps/edge-service/migrations/`); tables for inspections, component
  evidence, media, upload tasks, device events, active packages, and a durable
  `rule_identities` registry with contract-05 indexes. Denormalized filter
  columns (barcode, product, result) drive history queries. The SQLite index is
  a **rebuildable read projection** of the CLI `inspection.json` bundles (C1,
  ADR-012): it can be deleted and rebuilt from the same bundles without changing
  them, and it is not the authoritative completion/outbox store. The static-MVP
  `device_sequence` is per-process and is not a synchronization identity (C3).
  The `rule_identities` table makes rule identity immutable across restarts: a
  `(rule_id, rule_version)` reused with different content fails pipeline load
  with `CONFIG_INVALID`.
- **Endpoints**: health/device/camera, inspection state, inspections list
  (cursor pagination + filters) and detail, inspection media, media content
  with Range support, uploads (empty in M1), effective configuration, logs
  (in-memory ring buffer), and derived traceability/statistics/images.
  Statistics `from`/`to` filters are validated as timezone-aware UTC timestamps;
  the derived images endpoint reports per-slot AVAILABLE/PURGED/UNAVAILABLE
  status and returns 404 for unknown inspections. The M1 API is read-only
  (ADR-012): pause/resume, camera reconnect, and upload retry are not exposed.
- **Viewer authentication** (ADR-012): every route except `/health/live`
  requires the configured `AV_EDGE_API_TOKEN` bearer token or a short-lived
  HttpOnly, SameSite=strict, same-origin viewer session. `POST
  /api/v1/auth/session` exchanges a valid bearer token for the session cookie;
  the dashboard `/login` page provides the one-time entry so neither API JSON
  requests nor media `<img>` requests need the token in browser storage.
- **Media isolation (F2)**: media content is resolved only inside its
  inspection bundle directory; traversal, absolute, cross-bundle, and symlink
  escape paths are rejected at import and serve time, and duplicate media IDs
  are rejected so malformed bundles are skipped without aborting startup.
- **Contract boundary (F9)**: typed Pydantic response schemas with a committed
  OpenAPI document (`apps/edge-service/openapi/edge-openapi.json`) and CI drift
  checks, generated TypeScript types
  (`packages/typescript/api-client/src/edge/generated/api.ts`), plus runtime
  response validation in `HttpApiClient` (`validate.ts`) that rejects drifted
  or malformed payloads instead of blindly casting.
- **Frontend split**: read-only views route through the HTTP client when
  `VITE_API_MODE=http`; operator workflow actions (current/confirm/next/
  manual) stay on the deterministic mock because they are a demonstration
  queue, not a design 15.3 endpoint.
- **PR-003 hardening folded in**: rule version identity is bound to canonical
  rule content and registered durably; the output writer publishes inspection
  bundles atomically (staging + fsync + rename, rejects republish); detectors
  pass manifest `imgsz`/`iou`/`conf` explicitly and persist effective values in
  `InspectionRecord.inference_metadata`; the pipeline validates detection
  provenance (frame/model/coordinate space) with an absolute-only coordinate
  tolerance at the boundary.
- **Packaging**: `py.typed` markers added to `domain` and `vision-core` so MyPy
  strict passes repo-wide.
- **Test hardening**: the shared gate (ruff, format, mypy, pytest) passes with
  `472 passed` (2026-08-09); TypeScript is `34 passed` (api-client), `13 passed`
  (ui), `25 passed` (edge-web), `3 passed` (desktop), plus 12 Playwright e2e
  including a token-authenticated served dashboard that asserts real reconciled
  data and purged-media rendering. `uv run mkdocs build --strict` passes.

## 8.4 AUDIT-001 Closure and Review Fixes (PR #12)

The read-only system audit (`docs/reviews/AUDIT-001-system-audit.md`) was
verified and its findings closed with acceptance tests, merged via PR #12
(dev -> main, 16 commits; CI green):

- **H1-H3**: dataset adapters enforce image/label pairing (explicit empty
  labels, stem collisions, Roboflow `valid` -> `val`), publish
  dataset-relative `data.yaml` paths, and `av-train` resolves an absolute
  Ultralytics project dir and asserts `best.pt` exists.
- **M1-M3**: reconciliation skips NUL-byte media paths; rule-identity
  registration resolves concurrent races without leaking `IntegrityError`;
  first-open SQLite migration is serialized across threads and processes.
- **Rule/manifest fail-safe**: the rule engine rejects non-finite geometry and
  incomplete PRESENT evidence; manifest validation enforces runtime, artifact
  bundle containment, and class maps (`ConfigError`, never a leak).
- **API hardening**: non-loopback bind requires a token (or explicit dev
  override); log messages scrub absolute paths; failed-attempt throttling with
  `Retry-After`; bounded sessions; cursors bound to filter fingerprints
  (`400 INVALID_CURSOR`); PURGED media always `410`; non-ASCII bearer `401`;
  `/api` reserved before the SPA fallback; CSP/nosniff/referrer headers.
- **Frontend hardening**: production builds fail unless `VITE_API_MODE=http`;
  media blob URLs reject foreign origins; HTTP mode drops the unsupported line
  filter; WebSocket gaps are signalled; nested records are validated; the
  unrouted duplicate live view was removed.
- **Tooling/docs**: synthetic generator rotation geometry and scenario
  coverage corrected; training-run reproducibility metadata recorded beside
  manifests; design 14 M1 boundary, reason codes, adapters, runbooks, and
  QUICKSTART aligned.
- **PR review follow-up (`c634ca5`)**: preserved the documented sibling
  `models/manifests` + `models/weights` layout under bundle-root containment,
  requires independent product boxes in held-out test samples, re-verifies
  migrations on every database open, and adds `Retry-After` to auth
  throttling.
- **Deferred**: 4.4 authoritative persistence schema (product-configuration
  version, lease fields, concurrent equal-content upserts) is gated on the
  upload-scheduler milestone.

## 8.5 Camera Frame Sources and Multi-Instance Edge (ADR-013, in progress)

Documentation and ADR-013 are landed; implementation follows. The design:

- **`FrameSource` protocol in `vision-core`** (design 07 §7.3): `open /
  configure / frames(stop) / close` yielding `CapturedFrame` with monotonic +
  UTC timestamps, sequence, dimensions, pixel format, status, and PIL RGB
  image; decode failures raise a frame-stream error (fail-safe).
- **Pluggable sources**: `folder` (loopable), `video` (OpenCV), `opencv-device`
  (local/virtual camera, e.g. v4l2loopback or OBS), `rtsp` (PyAV + OpenCV
  fallback), `http-image` (httpx polling). Vendor SDKs are future protocol
  implementations.
- **Multi-instance `serve`**: `instances:` list in `pipeline.yaml`; each
  instance pairs a camera source with its own models/rule/product; flat
  single-config form stays backward compatible. `device_id` defaults to
  `uuid5(namespace, instance_id)` (explicit override wins).
- **Preview before WebSocket**: `GET /api/v1/camera/{instance_id}/preview`
  (rate-limited latest-frame JPEG; 404 unknown instance, 503 not ready); the
  WebSocket runtime channel later supersedes it.
- **Defaults**: `inspection.enabled: false` per instance (preview-only until
  the window/temporal milestone); dependencies `opencv-python-headless`, `av`,
  `httpx` in edge-service with vision-core optional extras.

## 9. Open Items / Next Steps

- The FastAPI + SQLite backend layer (`assemblyvision serve`, section 8.3) is
  merged; the **upload queue scheduler** (real `upload_tasks` rows, retry
  backoff, idempotency) and the **WebSocket runtime channel** are the next
  backend gaps. Read-only dashboard views already route through the HTTP
  client (`VITE_API_MODE=http`).
- AUDIT-001 (`docs/reviews/AUDIT-001-system-audit.md`) is **closed**: all
  findings fixed and committed on `dev` (section 8.4), merged to `main` via
  PR #12 on 2026-08-09. The only deferred item is 4.4 authoritative
  persistence, gated on the upload-scheduler milestone. Phase 3 still needs a
  decision on the multi-edge-per-host "shared" model before the upload
  scheduler, WebSocket, camera/barcode, and temporal aggregation work; ADR-013
  partially addresses it with per-instance pipelines (each instance loads its
  own models, so weight sharing remains an open optimization).
- Resilience documentation (2026-08-09, new docs PR): design 22 adds
  Accelerator/GPU failure and Repeated network disconnect to the resilience
  fault matrix, design 09 and contracts 06 are aligned, and README gained a
  Testing and Resilience section.
- PR-003 follow-up items are all resolved (see `docs/reviews/PR-003-review.md`):
  model-manifest publication now compares full decision-critical content
  (task, class order, input size, artifact, provenance), the Roboflow adapter
  validates every source label strictly and keeps explicit background
  negatives (component-only images without an independent product box are
  rejected), image/label pairing is required by default with a recorded
  `--allow-missing-labels` opt-in, verification uses source-relative sample
  identities, and dataset adaptation/component preparation reject stale output
  directories and write file manifests. Component preparation now loads a
  verified product manifest and mirrors the runtime exactly-one-product
  selection policy, recording ambiguous samples in `exclusions.json`.
- The two remaining M1 medium gaps are resolved:
  - **Token-protected Vite development across origins** now works. Loopback
    dev origins may use `GET`/`POST`/`OPTIONS` with `Authorization` and
    `Content-Type` headers, and the dashboard keeps the viewer token in memory
    (never persisted) when it runs cross-origin, attaching it to API and media
    requests; same-origin deployments keep the HttpOnly-cookie flow.
  - **CLI rule-identity registry is durable**: `assemblyvision inspect`/`verify`
    now register the loaded rule identity in the same SQLite `rule_identities`
    registry that `serve` uses (`<output>/edge.sqlite3`), so a published
    `(rule_id, rule_version)` stays immutable across CLI invocations and
    service restarts.
- Roadmap scope remaining after the merged M1 layer: upload queue scheduler,
  WebSocket channel, camera/barcode adapters, temporal aggregation, Docker
  packaging, and authoritative SQLite persistence/outbox.
- Real customer data is still required for the one-month baseline: collect and
  annotate with X-AnyLabeling per
  `docs/design/19-training-and-evaluation.md` §19.17 and
  `docs/runbooks/11-data-collection-and-annotation.md`, convert the export with
  `scripts/adapt-xanylabeling.py` (written; supports classes.txt/data.yaml,
  images-first and split-first layouts) into
  `dataset_product`/`dataset_components` + `test-expected.json`, then run
  `av-train` -> `assemblyvision inspect` -> `assemblyvision verify`.
- Camera acquisition milestone (ADR-013) is in progress: the `FrameSource`
  abstraction, simulated sources (folder/video/OpenCV-device/RTSP/HTTP-image),
  multi-instance `serve`, and the per-instance REST preview are being
  implemented with docs already landed; vendor SDK adapters and the
  window/temporal milestone remain hardware/design-gated.
- Camera/hardware integration (vendor SDK), barcode decoding, product-window
  management, temporal aggregation, authoritative SQLite persistence (the
  current index is a rebuildable read projection), the upload queue scheduler,
  and Docker deployment remain as the roadmap 25.5 one-month scope; only the
  vendor-SDK, barcode, and site-coupling parts are blocked on hardware and
  customer-site decisions.
- Hardware/conditions still unconfirmed (see [Appendices section 3](../design/appendices.md#3-global-open-questions)):
  camera vendor/SDK, barcode standard, conveyor speed, GPU/OS, retention periods, network
  reliability, central-server location, acceptance thresholds.
- `.obsidian/` remains untracked by choice; notify the user before changing that decision.
