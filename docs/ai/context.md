# AssemblyVision - Full Project Context

> Context snapshot. Last updated: 2026-08-13
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
  review-driven hardening, the real-data baseline tooling, camera/multi-
  instance serve, temporal aggregation, the durable upload outbox, E1-E5
  production gates, and the barcode identity / PLC FIFO trigger contract are
  all merged to `main` (PRs #3-#30). The Python uv workspace ships
  shared `domain` and `vision-core` packages, a developer-only `av-train`
  training CLI, real two-stage Ultralytics YOLO inspection
  (`assemblyvision inspect`) and held-out verification, plus dataset adapters
  for Roboflow and X-AnyLabeling exports. The frontend pnpm workspace includes
  the Vue 3 + TypeScript operator dashboard (`apps/edge-web`), an Electron
  kiosk shell (`apps/edge-desktop`), a typed `api-client` contract layer, and
  shared UI primitives. PR #14 added camera frame sources, multi-instance
  `serve`, and the gated web dev test harness (ADR-013/014); PR #15/#16 merged
  the product-window/temporal aggregation milestone (ADR-010); PR #17 merged
  the durable upload outbox and scheduler (ADR-005); PRs #18/#19 (E1) and #20
  (E2 retention and disk safety) completed the storage/observability gates;
  PRs #22/#23/#24 merged E3 (upload resilience), E4 (runtime/WebSocket), and
  E5 (deployment and security); PR #25 delivered E6 acceptance-prep tooling;
  PRs #26/#27/#28 added the hardened GigE/GenICam source and the
  production-ready dashboard themes; PR #29 fixed persistence inference
  metadata; and PR #30 added exact-mapped barcode identity resolution with an
  opt-in Modbus TCP FIFO trigger contract (ADR-015). PR #31 merged the
  edge-local human review feature (ADR-016), including its review hardening
  and the documented PR31-T05 viewer-credential trade-off. PRs #32 and #33
  added issue templates and the industrial README/QUICKSTART/SECURITY refresh;
  PR #34 added the developer manual; PR #35 added edge-web i18n; PR #36
  fixed the MkDocs README-index exclusion; PR #37 merged the central server
  M1 foundation (C1a); PR #38 added the confidence-drift statistics
  (design 15.3.6) and its dashboard panel; and PR #39 added live network
  traffic and GPU metrics to the device health page. Edge coding is complete
  through the E6 preparation gate. The central server M1 pilot has started
  (C1a foundation merged via PR #37; C1b tenant/credential foundation merged
  via PR #40); its bounded implementation plan is in
  `docs/tasks/C1-central-server-m1.md`. PR #41 repaired the GitHub issue
  form templates: the `.md` forms were renamed to `.yml` (GitHub parses
  `.md` files as Markdown templates requiring an `about:` key, which made
  the editor report "About can't be blank"), the missing closing frontmatter
  delimiter was added to the security template, and `.env` deployment secrets
  are now gitignored. The central M1 pilot has since delivered inspection
  ingestion with verified receipts (C2a, PR #42), MinIO media binding (C2b,
  PR #43), history/detail/media access and the real admin-web UI (C3, PR
  #44), central append-only human review (C4, PR #45), admin-web
  i18n/theme/pagination/sign-out hardening (PR #46), C5 metadata governance
  (PR #47), and C6 M1 hardening and operational evidence (PR #48, merged) -
  completing the C1a-C6 M1 feature set, plus the E6-A16 real
  edge-to-central integration fixture and the M1 closure documentation
  (exit-criteria evidence table + go-live checklist, README/QUICKSTART/
  DEPLOYMENT split) via PR #49 (open at snapshot time). The M1 pilot is
  feature-complete; remaining work is on-site E6 acceptance and the §13.2
  controlled-pilot deployment (execution, hardware/data-gated).

## 2. Repository State

- Remote: `https://github.com/dream-studio-china/assembly-vision`. PRs #3-#30
  are merged to `main`, covering the MVP, dashboard, M1 backend, camera/
  multi-instance (ADR-013/014), temporal aggregation (ADR-010), durable upload
  outbox (ADR-005), E1-E5 gates, E6 acceptance prep, GigE/GenICam source,
  dashboard themes, persistence fixes, and barcode identity / PLC trigger
  contract (ADR-015). PRs #31 through #39 are also merged: edge-local human
  review, issue templates, documentation refresh, developer manual, edge-web
  i18n, the MkDocs manual-index fix, the central server M1 foundation
  (C1a, PR #37), the central pilot tenant/device/credential foundation
  (C1b, PR #40), the confidence-drift statistics (PR #38), and the device
  health observability layer (PR #39). PR #41 fixed the GitHub issue form
  templates (`.yml` rename, security closing delimiter, `.env` ignore).
  PR #42 merged central inspection ingestion with verified receipts (C2a),
  PR #43 merged MinIO media binding (C2b), PR #44 merged history/detail/
  media access and the real admin-web UI (C3), PR #45 merged central
  append-only human review (C4), PR #46 merged admin-web i18n/theme/
  pagination/sign-out hardening, and PR #47 merged C5 metadata governance.
  `docs/tasks/C1-central-server-m1.md`
  defines the central pilot scope. C6 M1 hardening is merged via PR #48,
  completing the C1a-C6 M1 feature set; PR #49 (dev -> main, open at
  snapshot time) carries the E6-A16 real edge-to-central integration fixture
  (`scripts/tests/test_edge_central_e2e.py`, section 8.23), the §13
  exit-criteria evidence table and go-live checklist, and the
  README/QUICKSTART/DEPLOYMENT documentation split.
- `.obsidian/`, `.idea/`, and `.vscode/` are ignored local editor state.
- Runtime data, model weights, production media, datasets, and secrets must never be stored in
  Git. Build artifacts `docs-zh/`, `site/`, `mkdocs-en.yml`, `mkdocs-zh.yml` are gitignored.

## 3. Directory Structure

```
assembly-vision/
├── README.md               # Root README with docs map + bilingual site instructions
├── QUICKSTART.md           # Short developer fast path (Docker-free) for all components + training
├── DEPLOYMENT.md           # Exhaustive deployment reference (dev/production/training, CLI + Docker)
├── AGENTS.md               # Coding rules: language, engineering, git workflow, security
├── LICENSE                 # MIT License (c) 2026 Dream Studio
├── SECURITY.md             # Security policy: position, edge auth, vulnerability reporting
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
│   └── tests/                       # dev harness tests: dataset adapters + edge-central e2e (E6-A16)
├── .github/
│   ├── ISSUE_TEMPLATE/              # bug_report / feature_request / security_vulnerability + config
│   └── workflows/                   # ci.yml (repo-wide quality gates) + docs.yml (Pages deploy)
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
    ├── images/             # README screenshots (inspection detail, live view)
    ├── manual/             # Developer manual
    ├── reviews/            # Reviews: PR-003/008/014/015/017/020/022/023/031, AUDIT-001
    ├── tasks/              # Delivery tasks, including the Central Server M1 plan
    ├── contracts/          # 11 mandatory engineering contracts + index
    ├── runbooks/           # 20 operational recovery runbooks (01-15 + central C1-C5) + index
    ├── design/             # 28 design documents + appendices + decisions/
    │   ├── 00-cover-and-status.md ... 27-risks-and-mitigations.md
    │   ├── appendices.md   # Terminology, decision checklist, open questions, reason codes
    │   └── decisions/      # ADR-001 ... ADR-016 + README
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
   train-and-inspect MVP, ADR-012 edge API M1 viewer auth, ADR-013 camera frame
   sources and multi-instance edge, ADR-014 web dev test harness, ADR-015
   barcode identity and PLC trigger correlation, and ADR-016 edge-local human
   review (optional, append-only).
- [docs/design/appendices.md](../design/appendices.md) holds the canonical terminology, decision consistency checklist,
  global open questions (OQ-001 ... OQ-025), reason-code glossary, and traceability conventions.
- `docs/research/`: industry success rates, YOLO capabilities, imaging/workflow/training cost.
- [docs/contracts/](../contracts/README.md): 11 enforceable architecture, safety, API, quality,
  operations, security, change-control, and acceptance contracts.
- [docs/runbooks/](../runbooks/README.md): 20 executable recovery procedures
  for all contract-required operational scenarios, including model improvement
  (runbook 10), data collection and annotation (runbook 11), backup and
  recovery (12), TLS certificate rotation (13), deployment upgrade and
  rollback (14), edge acceptance execution (15), and the central runbooks C1-C5
  (ingestion backlog, object-store failure, credential compromise,
  backup/restore, pilot upgrade/rollback).

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
- `exclude_docs` must use `/README.md` (anchored) so the root documentation
  README is excluded without excluding nested manual, design, contract, and
  runbook index pages. `uv run mkdocs build --strict` verifies the site.

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
  `557 passed` (2026-08-09); TypeScript is `37 passed` (api-client), `13 passed`
  (ui), `28 passed` (edge-web), `3 passed` (desktop), plus 12 Playwright e2e
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

## 8.5 Camera Frame Sources, Multi-Instance Edge, and Web Dev Test Harness (ADR-013/014, PR #14)

Merged via PR #14 (dev -> main). The review-driven hardening pass is recorded in
`docs/reviews/PR-014-review.md`; findings F1-F14 are resolved with regression
tests. The design:

- **`FrameSource` protocol in `vision-core`** (design 07 §7.3): `open /
  configure / frames(stop) / close` yielding `CapturedFrame` with monotonic +
  UTC timestamps, sequence, dimensions, pixel format, status, and PIL RGB
  image; decode failures raise a frame-stream error (fail-safe).
- **Five pluggable sources** (all implemented): `folder` (loopable), `video`
  (OpenCV), `opencv-device` (local/virtual camera, e.g. v4l2loopback or OBS),
  `rtsp` (PyAV + OpenCV fallback), `http-image` (httpx polling). Vendor SDKs
  are future protocol implementations. `opencv-python-headless`, `av`, `httpx`
  are vision-core optional extras pulled in by edge-service.
- **Multi-instance `serve`**: `instances:` list in `pipeline.yaml`; each
  instance pairs a camera source with its own models/rule/product; the flat
  single-config form stays backward compatible. `device_id` defaults to
  `uuid5(namespace, instance_id)` (explicit override wins). A
  `CameraSourceManager` runs one bounded capture thread per instance (latest
  frame retained for preview, non-fatal per-instance failures); enabled
  instances consume a bounded per-instance inspection queue with explicit
  overflow reporting (`FRAME_OVERFLOW`, PR-014 F1/F2), and
  `EdgeRuntime.load_instances` starts an independent single-frame inspection
  loop per instance when `inspection.enabled` (default false).
- **Preview before WebSocket**: `GET /api/v1/camera/{instance_id}/preview`
  (rate-limited latest-frame JPEG; 404 unknown instance, 503 not ready) and
  per-instance `camera_state`; the WebSocket runtime channel later supersedes
  the preview.
- **Web dev test harness (ADR-014)**: gated `/api/v1/dev/inspect-frame` and
  `/api/v1/dev/inspect-video` (404 unless `serve --enable-web-test`) let a
  browser take a photo (mobile OS camera), upload an image, or upload a short
  video and get the inspection decision; a `/dev` dashboard page groups the
  tools with a Logs tab and a client-side product-bbox overlay. Image tests
  write evidence bundles by default (`persist=false` to skip); video tests
  return a per-frame summary (≤30 frames, <100 MB) without persisting. It is a
  test harness, not production acquisition.
- **Product window and temporal aggregation (ADR-010)**: an instance with a
  `temporal:` block in its pipeline config groups captured frames into
  per-product windows and emits one `per-component-temporal-v1` inspection
  record per window via a deterministic per-component aggregator (design 10).
  The default single-frame mode is unchanged. `UNVERIFIABLE` was added as an
  aggregated evidence state; insufficient valid frames yield
  `UNVERIFIABLE`/`INSUFFICIENT_VALID_FRAMES`, an interrupted window is closed
  as NG with `INSPECTION_INTERRUPTED`, and the OpenAPI/TypeScript contract was
  regenerated for the new state. The PR-015 review hardening (F1-F7) is
  applied: windows group on the frame capture monotonic clock and idle windows
  expire normally; `window_strategy: identity` seals each window to one
  validated product identity and aborts on missing/transitioning identities or
  multi-product frames; quality-rejected frames contribute no evidence;
  per-frame reasons are diagnostics while only window-integrity violations
  force NG; temporal configs must cover every rule-required component with
  strict `medium < high` thresholds; and count evidence is limited to detections
  at or above the policy medium threshold.
- **Remaining in the milestone**: vendor SDK adapters, per-instance model
  weight sharing (Phase 3), folding the REST preview into the WebSocket
  channel, and hardware trigger / barcode correlation sources that feed the
  `window_strategy: identity` seam (the time-only fallback remains a
  development mode, not a production product boundary).
- **Review hardening (PR-014)**: findings F1-F14 are closed with regression
  tests: no silent frame loss (bounded queue + explicit overflow), pause
  stops inspection and device status reports `PAUSED`, corrupt sources fail
  closed while bad instances stay non-fatal, dev-harness uploads are
  byte/pixel/step bounded with immediate projection persistence, disabled dev
  endpoints return 404 before authentication, and dev video decisions use the
  canonical business/internal enums with binary bodies and problem responses
  documented in the regenerated OpenAPI/TypeScript contract.
  `assemblyvision_edge` now ships `py.typed` so the strict mypy gate passes
  repo-wide; the current suite is 635 Python tests, 91 TypeScript unit tests
  (api-client 45, ui 13, edge-web 30, desktop 3), and 12 Playwright e2e.

## 8.6 Durable Upload Outbox and Scheduler (PR #17, ADR-005)

Merged via PR #17 (dev -> main, 10 commits). Implements the persistent upload
queue required by ADR-005 and closes the deferred AUDIT-001 4.4 persistence
item. The review-driven hardening pass is recorded in
`docs/reviews/PR-017-review.md`; findings F1-F8 plus a post-resolution pass
are resolved with regression tests:

- **Atomic projection and outbox**: `persist_inspection_and_enqueue_uploads`
  commits the immutable inspection, media, evidence, and one `INSPECTION` task
  plus one `MEDIA` task per artifact in a single SQLite transaction; startup
  reconciliation repairs stranded `LOCAL_ONLY` records.
- **Ordered, leased worker**: `UploadScheduler` claims due tasks in an
  immediate transaction; `MEDIA` tasks become due only after their inspection
  task has a verified receipt; each claim carries a per-task fencing token
  (`lease_owner`), stale `IN_PROGRESS` tasks are reclaimed after lease expiry,
  and terminal updates require the matching token.
- **Failure classification**: transport errors and `408/429/5xx` schedule
  full-jitter backoff honoring `Retry-After` from the response time; missing/
  corrupt evidence, checksum/size mismatch, and server conflicts become
  permanent failures while local evidence is preserved.
- **Verified receipts**: a 2xx is success only when the bounded typed receipt
  echoes idempotency key, object, kind, size, and checksum; media receipts
  require a central object ID; receipts are persisted and inspection
  synchronization is `QUEUED`/`PARTIAL`/`SYNCED`/`FAILED` from all tasks.
- **Configuration and security**: `UploadSettings` + `AV_EDGE_UPLOAD_*` wiring
  through `serve` (endpoint or local sink, separate credential, tunables);
  central endpoints require HTTPS (development HTTP loopback-only), and the
  viewer `api_token` is never reused for uploads.

## 8.7 Observability (E1) and Retention and Disk Safety (E2) (PRs #18/#19, #20)

Observability merged via PRs #18 and #19 (dev -> main): the Alembic
`fileConfig` side effect that disabled `assemblyvision.*` loggers after
migration is fixed so `/api/v1/logs` captures application records, and device
status now exposes upload queue bytes, oldest pending age, attempt/success/
failure counters, failure rate, last contact, and `UPLOAD_BLOCKED`/
`UPLOAD_FAILING` alerts.

Retention and disk safety merged via PR #20 (dev -> main, E2a-E2d plus the
PR-020 review hardening). The delivery task and mandatory safety invariants are
in `docs/tasks/E2-retention-and-disk-safety.md`; the review and its per-finding
resolutions are recorded in `docs/reviews/PR-020-review.md` (RESOLVED):

- **Durable retention state (E2a)**: migration 0007 adds media `created_at`,
  `retention_eligible_at`, hold state, deletion claim/lease/fencing columns,
  purge timestamp/reason, delete error, and integrity status. A `PURGED` row
  remains an audit tombstone. Eligibility requires a receipt-verified `SYNCED`
  inspection with a media receipt containing the central object ID, an elapsed
  hold deadline, and no hold/fault/purge/deleting state.
- **Cleanup worker (E2b)**: `RetentionCleanupWorker` claims candidates under an
  inter-process SQLite lease with per-artifact fencing tokens. A fenced
  pre-unlink confirmation re-validates the full eligibility predicate and
  renews the lease immediately before destructive I/O; holds and integrity
  faults applied after a claim cancel it, and finalization re-checks the same
  predicate. Unlink runs through `O_NOFOLLOW` directory file descriptors so a
  concurrent symlink swap cannot remove a file outside the inspection bundle.
  Missing files are integrity faults, never false purges; unlink failures are
  retryable and observable. Without an approved, enabled policy the worker
  performs zero filesystem mutation.
- **Disk pressure and fail-safe runtime (E2c)**: `StorageSettings` /
  `RetentionSettings` (`AV_EDGE_STORAGE_*`/`AV_EDGE_RETENTION_*`, strictly
  ordered stop < critical < warning) drive free-byte/inode pressure modes with
  at-or-below threshold semantics. At critical pressure optional OK capture is
  suppressed while NG evidence and metadata persist; at stop pressure or on a
  latched write fault the runtime stops intake and reports
  `inspection_ready=false`. Inspection results publish only after the
  projection/outbox transaction commits; a write fault clears only through a
  mandatory persistence probe (probe file + fsync and a `BEGIN IMMEDIATE`
  write). Device status exposes server-authoritative thresholds and stable
  alerts (`DISK_WARNING`/`DISK_CRITICAL`/`DISK_STOP`/`STORAGE_WRITE_FAULT`/
  `STORAGE_INTEGRITY_FAULT`/`CLEANUP_FAULT`), and the dashboard renders them
  instead of fixed client thresholds.
- **Startup integrity (E2d)**: `scan_storage_integrity` verifies media
  existence, size, and checksums by default (bounded deterministic sampling is
  explicitly configurable), quarantines malformed/orphan bundles idempotently,
  and latches `STORAGE_INTEGRITY_FAULT`; existing faults remain latched across
  restart. `PRAGMA quick_check` fails closed on corruption. `mark_upload_succeeded`
  validates a typed receipt against the task's immutable fields inside the
  repository, and `/health/ready` returns 503 whenever storage admission is
  closed by stop pressure, a write fault, or an integrity fault.

Cleanup stays disabled without an approved retention policy; customer retention
periods, disk sizing, holds, and stop-mode line behavior remain release
blockers for production enablement (E2 task section 4). Current suite: 781
Python tests, 91 TypeScript unit tests (api-client 45, ui 13, edge-web 30,
desktop 3), and 12 Playwright e2e.

## 8.8 Upload Resilience (E3)

Implemented on `feat/e3-upload-resilience` (delivery task
`docs/tasks/E3-upload-resilience.md`, design 13.13/13.14):

- **Bandwidth throttling (E3a)**: a token-bucket limiter bounds network
  payload bytes per second from `AV_EDGE_UPLOAD_MAXIMUM_BANDWIDTH_MBPS`
  (`None` disables); burst is capped at one second of tokens and the limiter
  never gates local persistence. Bytes sent and the ceiling are exposed in
  device status.
- **Circuit breaker (E3b)**: consecutive retryable failures
  (`AV_EDGE_UPLOAD_CIRCUIT_FAILURE_THRESHOLD`/`_OPEN_SECONDS`) open the
  circuit; while open the scheduler claims nothing, and after the open window
  a single half-open probe judges recovery. Permanent failures never count.
  `UPLOAD_CIRCUIT_OPEN` alert; the durable queue is never mutated.
- **Controlled manual retry (E3c)**: `POST /api/v1/uploads/{id}/retry`
  resets only `RETRY_WAIT`/`PERMANENT_FAILURE` tasks with
  `attempt_count + 1`; 404 unknown, 409 non-eligible without mutation.
- **Long-outage drain (E3d)**: days of offline inspection, a restart, and a
  restore drain the queue duplicate-free with ordered metadata-before-media
  uploads and every inspection `SYNCED`.
- **Resumable large-media contract (E3e)**: design 13.14 defines chunked
  transfer (stable task identity, chunk idempotency, size/checksum completion
  confirmation, object binding); `media_chunk_bytes` is a clearly-marked
  reserved placeholder — the central endpoint is not implemented and chunked
  transfer starts only after the Edge-to-central contract freezes.

## 8.9 Runtime and Live Event Channel (E4)

Implemented on `feat/e4-runtime` (delivery task
`docs/tasks/E4-runtime.md`):

- **WebSocket runtime channel (E4a)**: an in-memory `RuntimeEventBus` assigns
  monotonic per-source sequence numbers and keeps bounded per-connection
  buffers that disconnect slow consumers instead of blocking publishers.
  `WS /api/v1/ws/runtime` authenticates with the same viewer bearer/session
  model as REST and streams design 15.6 envelopes (`inspection.started`,
  `inspection.completed`, `device.status_changed`, `upload.changed`). Events
  come from real transitions: the inspection loop (started on each new window
  or per-frame inspection, completed after the projection/outbox commit),
  pause/resume, and the upload scheduler worker. Cross-origin browser sockets
  cannot set an `Authorization` header, so the dashboard exchanges its viewer
  credential for a short-lived, single-use ticket over REST
  (`POST /api/v1/ws/runtime/ticket`) and sends it as the negotiated
  `Sec-WebSocket-Protocol` value, never in the URL (PR-023 F01). The dashboard
  live view consumes the feed and refetches REST on reconnect or sequence
  gaps, with the poll reduced to a slow fallback. Publishing never blocks
  inspection, persistence, or the worker: cross-thread deliveries perform the
  bounded-buffer decision on the owning event loop, so a slow consumer is
  disconnected rather than raising `QueueFull` (PR-023 F02), and the channel
  counters are exposed through the authenticated
  `GET /api/v1/ws/runtime/stats` endpoint (PR-023 F05).
- **Trigger/barcode/identity seam (E4b)**: a `TriggerSource` protocol plus a
  deterministic `MockTriggerSource` (frame-ordered identities with barcode
  correlation metadata and validity spans) feed an `IdentityCorrelator` that
  stamps captured frames, so the identity-sealed product-window boundary
  (PR-015 F1) groups by physical product; frames after a non-looping stream
  keep no identity and fail the window closed. The mock source is gated behind
  explicit instance `trigger:` configuration (development/test-only) and can
  never masquerade as production hardware.
- **Shared model weights (E4c)**: a process-wide `ModelRegistry` keyed by the
  immutable artifact SHA-256 plus inference device lets instances referencing
  the same manifest share one loaded handle; holders serialize inference on a
  per-artifact lock because ultralytics predictors keep mutable state, while
  distinct artifacts/devices stay separate and no mutable state is shared
  (ADR-013 Phase 3).

## 8.10 Deployment and Security (E5)

Implemented on `feat/e5-deployment-security` (delivery task
`docs/tasks/E5-deployment-and-security.md`):

- **Docker packaging (E5a)**: a multi-stage `apps/edge-service/Dockerfile`
  resolves the pinned uv workspace and installs dependencies non-editable, then
  ships only the virtualenv in a slim runtime image running as the `av`
  (10001:10001) user with a read-only root filesystem; data mount points are
  pre-created and owned by `av` so named volumes inherit the right owner.
  `python -m assemblyvision.healthcheck` gates the Docker HEALTHCHECK, and a
  `compose.yaml` template provides persistent volumes, restart policy,
  loopback binding, and no central-DNS dependency at startup. Verified end to
  end on Docker: `health=healthy`, `user=av`, read-only rootfs.
- **Secrets and TLS (E5b)**: `serve` falls back from `AV_EDGE_*` environment
  variables to Docker secret files under `/run/secrets/` for the viewer and
  upload tokens (failing closed on unreadable secret files); optional local
  HTTPS via `--tls-cert`/`--tls-key` (or `AV_EDGE_TLS_*`) with startup
  validation of existence, private-key permissions, and certificate/key
  match.
- **Backup and restore (E5c)**: `assemblyvision backup` takes a consistent
  SQLite online snapshot plus governed config/rule/manifest files and pending
  evidence with SHA-256 checksums into a `tar.gz` bundle; `assemblyvision
  restore` verifies every checksum before applying, keeps a `.pre-restore`
  copy, never overwrites conflicting media, and reconciles the store so
  pending upload tasks survive.
- **Runbooks (E5d)**: runbook 12 (backup and recovery), 13 (TLS certificate
  rotation), and 14 (deployment upgrade and rollback) added to the indexed
  runbook set.

## 8.11 Barcode Identity and Edge-Local Human Review (PRs #30/#31)

Merged via PR #30 (dev -> main): exact-mapped barcode identity resolution
(ADR-015). PR #31 merged optional edge-local human review (ADR-016), including
the review hardening recorded in `docs/reviews/PR-031-review.md`: serialized
supersede chaining under
`BEGIN IMMEDIATE`, unique normalized component corrections, problem+json
declarations in the regenerated OpenAPI/TS contract, the review-queue initial
load, and review-panel history-error gating.

- **Barcode identity (PR #30, ADR-015)**: typed `BarcodeObservation` models,
  an optional ZXing-cpp visual decoder (`zxing-cpp>=2.3,<3`), an explicitly
  simulated keyboard input adapter (dev-harness only), and a deterministic
  resolver mapping complete barcode values to product codes. Resolution fails
  closed on unreadable, conflicting, unsupported-symbology, unknown, or
  active-product-mismatched reads. Visual identity runs on the dev upload
  path and the production single-frame camera loop; unverified identity is
  always persisted as `NG`. A `barcode_required` rule requires enabled
  required `identity.barcode` config at load time, and barcode identity with
  temporal inspection is rejected until windowed correlation exists. The
  Modbus TCP FIFO trigger adapter (ENTRY/EXIT/ABORT, sequence/heartbeat/
  overflow/consistency) is delivered as an opt-in contract; live transport
  stays gated on a site-validated register profile.
- **Edge-local human review (PR #31, ADR-016)**: optional, additive,
  append-only review of any inspection (OK or NG) without mutating the
  machine decision. Domain `ReviewDisposition` (CONFIRMED_NG/CONFIRMED_OK/
  CORRECTED_NG/INCONCLUSIVE/REINSPECT) constrained per machine outcome,
  `ReviewRecord` snapshotting the original decision, a `review_records` table
  (migration 0008) with supersede-by-reference chaining, repository
  `submit_review`/`list_review_queue`, and endpoints `GET /api/v1/reviews`,
  `GET/POST /api/v1/inspections/{id}/reviews` (design 15.3.3). The web
  `ReviewView` queue page and an additive `ReviewPanel` on the inspection
  detail view surface the workflow; NG detail views prompt review while OK
  views offer an optional audit path. The four-aspect review (docs,
  security, decoupling, extensibility) is recorded in
  `docs/reviews/PR-031-review.md` (RESOLVED); findings fixed include
  bounded `component_corrections`, machine reason codes in the open-item
  queue, cursor 400 hardening, log-injection repr, mock/server validation
  parity, and doc/contract consistency (design 14/15/16/24). Review
  submission is intentionally exposed through the existing viewer credential
  (no edge role model yet); local review records do not yet sync to a
  central server.

## 8.12 Review Hardening, Documentation, i18n, and MkDocs (PRs #31-#36)

PRs #31 through #36 are merged to `main`.

- **PR #31 review hardening**: PR-031
  findings F01-F10 are resolved, and follow-up fixes address the residual
  review findings: `submit_review` acquires the SQLite write lock before the
  supersede read (`BEGIN IMMEDIATE`) so concurrent submissions chain linearly
  (regression test with two repositories); `component_corrections` are
  normalized (whitespace-stripped, non-empty) and duplicate/contradictory
  codes are rejected at the domain and API boundaries; the review endpoints
  declare their 404/409/422 RFC 7807 problem responses with the real
  `application/problem+json` media type (OpenAPI + TS regenerated); the
  `/review` page loads its default NG/open queue on first entry and ignores
  stale in-flight responses; and the review panel blocks submission until the
  append-only history loads successfully, surfacing load failures with a
  retry. The viewer-credential review exception is recorded as accepted
  trade-off PR31-T05 (deferred until an edge RBAC exists).
- **PR #32 issue templates**: completed
  `.github/ISSUE_TEMPLATE/` for the current project state - the bug report
  gained P0-P3 severity, E1-E6 production impact, a related-runbook field, and
  the camera/barcode/trigger component; the feature request gained the ADR
  requirement plus documentation-impact and change-control-impact checkboxes
  (contracts 05/07/09/10); a new security-vulnerability template follows
  SECURITY.md private reporting; and the chooser links the security policy.
  The `triage` and `security` labels were created.
- **PR #33 documentation refresh**: the README
  was rewritten for an industrial, open-source-presentable tone - badges, an
  OK/NG false-negative safety framing, side-by-side dashboard screenshots
  (`docs/images/`), a vertical Mermaid architecture diagram covering the full
  edge pipeline and the planned central server, a production status table, and
  a three-phase roadmap (MVP / Edge / Central) with an outlook toward a
  complete AI recognition platform. QUICKSTART and SECURITY were aligned with
  the current state (WebSocket runtime channel, TLS/Docker-secret options, the
  separate upload credential, `gige-vision` and the trigger/identity seam,
  backup/restore, and the PR31-T05 edge review exception).
- **PR #34 developer manual**: added an indexed codebase manual.
- **PR #35 edge-web i18n**: added `vue-i18n` catalogs for English,
  Simplified Chinese, Traditional Chinese, and Japanese. English text is used
  as the message key; `VITE_DEFAULT_LOCALE` controls the default; a globe SVG
  dropdown persists the selected locale; and Element Plus uses the active
  locale provider. The edge-web checks passed: typecheck, lint, unit tests,
  build, and 15 Playwright tests.
- **PR #36 MkDocs index fix**: changed `exclude_docs: README.md` to
  `exclude_docs: /README.md`, restoring nested `README.md` index pages such as
  `/manual/`, `/design/`, `/contracts/`, and `/runbooks/`.
- **Central Server M1 plan**: `docs/tasks/C1-central-server-m1.md` defines a
  pilot implementation that remains edge-independent: separate device-upload
  and admin credentials, PostgreSQL + MinIO, current edge-compatible
  idempotent uploads and verified receipts, history/media, and append-only
  central review. OIDC, full RBAC, WebSocket, remote package rollout, and
  resumable uploads remain deferred.

## 8.13 Central Server M1 Foundation (C1a)

The first central-server delivery (C1a of
`docs/tasks/C1-central-server-m1.md`) is implemented and validated:

- **`apps/central-service`** (uv workspace member `assemblyvision-central`):
  FastAPI application with typed `AV_CENTRAL_*` settings, RFC 7807 problem
  responses, request-ID correlation, a `MinioObjectStorage` abstraction with
  idempotent bucket bootstrap, and an Alembic migration runner. Migrations are
  a **controlled release step** (`python -m central_service migrate`); the API
  never migrates automatically. Baseline migration `0001` establishes the
  `central_meta` marker.
- **Health/readiness**: `GET /api/v1/health/live` (no dependencies) and `GET
  /api/v1/health/ready` (503 + problem while PostgreSQL is unreachable, the
  schema is behind head, the MinIO bucket is unavailable, or the pilot
  credential is not configured). Probe results are injectable for tests.
- **`apps/admin-web`** (pnpm workspace): minimal Vue 3 + TypeScript + Pinia +
  Element Plus pilot shell (overview page, router, Vitest, Playwright e2e)
  with a Dockerfile serving it behind nginx that proxies `/api` to the API.
- **`packages/typescript/api-client-central`**: generated OpenAPI types from
  the committed `apps/central-service/openapi/central-openapi.json` with CI
  drift checks on both sides.
- **Compose**: PostgreSQL + MinIO + `central-migrate` (one-shot) +
  `central-service` + `admin-web`, named volumes, non-root images, health
  checks, dev-only env defaults in `compose.env.example`. Verified cold start,
  readiness, proxied health via admin-web, and restart persistence; CI/Makefile
  now cover the central OpenAPI drift check and admin-web gates.

The edge runtime imports no central code; the current edge upload envelope is
unchanged.

## 8.14 Confidence Drift and Device Health Observability (PRs #38/#39)

PRs #38 and #39 are merged to `main`.

- **Confidence drift (PR #38, design 15.3.6)**: `GET
  /api/v1/statistics/confidence-drift` compares today's weighted-mean
  per-component `best_confidence` (weighted by positive `detection_count`)
  against yesterday, the previous 7 days, and the previous 30 days. The
  comparison scope is mandatory - `product_code`, `rule_version_id`,
  `product_model_version_id`, `component_model_version_id`, and
  `aggregation_policy_version` - so a release or policy switch is never
  misreported as an acquisition-environment change; incomplete scopes return
  `422 application/problem+json`. Day boundaries follow the operator-local
  timezone (`tz_offset_minutes`, bounded `[-840, 840]`), buckets are half-open
  `[from, to)`, and an aware injected clock is normalized to UTC.
  Zero-detection evidence rows are excluded from the weighted aggregate.
  Per-component today-vs-7-day deltas are reported largest drop first with
  `null` when baseline evidence is missing (never a fabricated zero). The
  heuristic assessment (`stable` / `minor_drop` / `noticeable_drop` /
  `minor_rise` / `noticeable_rise` / `insufficient_data`) anchors on the 7-day
  baseline and is decision support only, never a root-cause or accuracy claim.
  The statistics dashboard panel derives the scope from the latest completed
  inspection, passes the browser's local UTC offset, and renders the effective
  scope; api-client types, runtime validation, and mocks were extended and the
  OpenAPI/TS contract regenerated.
- **Device health page (system metrics via PR #38, network/GPU via PR #39)**:
  the health view shows load (as a share of the CPU cores), memory, and disk
  as percentage circular gauges, plus a live gradient stacked area chart of
  upload/download traffic (one sample per second, 60-point sliding window)
  and GPU load/power gauges. Backend metrics come from the dependency-free
  `assemblyvision_edge/system.py`: CPU count/load and memory via
  `/proc/meminfo` (sysconf fallback); network rates by differencing the
  cumulative `/proc/net/dev` counters (first poll `null` until a baseline);
  NVIDIA GPU utilization/power via `nvidia-smi` (PATH-resolved, 2s timeout,
  5s result cache). Every metric fails closed to `null` when the platform
  cannot provide it, and none affect decision paths. The gauge cards and both
  charts share one four-column grid template so rows stay strictly aligned
  and the ECharts canvases shrink with the window (grid items carry
  `min-width: 0` instead of inheriting the canvas intrinsic width). The
  served-api e2e scopes the no-camera assertion to the camera pane, which
  had been matching the detection-result pane's historical media frame.

## 8.15 Central Server M1 Tenant and Pilot Authentication Foundation (C1b)

The second central-server delivery (C1b of
`docs/tasks/C1-central-server-m1.md`) is implemented and merged via PR #40:

- **Tenant/device/credential schema (migration 0002)**: `organizations`,
  `sites`, `production_lines`, `devices` (edge identity unique per
  organization, `ACTIVE`/`DISABLED` status, hashed upload credential),
  `administrators` (hashed pilot token), `admin_sessions` (split
  lookup/hashed-secret session tokens, `organization_id` scoped), and a
  minimum `audit_logs` table. Production lines and devices carry composite
  foreign keys that bind `organization_id` to the organization of their
  referenced site/line, so a cross-tenant hierarchy row is rejected by the
  database. The same schema is defined as SQLAlchemy Core tables
  (`central_service/persistence/schema.py`) so repository tests create it on
  SQLite with foreign keys enforced; the Alembic migration mirrors it for
  PostgreSQL.
- **Idempotent bootstrap**: `central-service bootstrap` (CLI) and the new
  Compose one-shot `central-bootstrap` service create exactly one pilot
  organization/site/line/device/administrator; existing rows are reused by
  name/identity and a registered device or administrator is never re-keyed.
  Credentials are always supplied explicitly via
  `AV_CENTRAL_ADMIN_TOKEN` / `AV_CENTRAL_DEVICE_UPLOAD_TOKEN` (or CLI
  options) - the bootstrap never generates or prints secrets, so no
  credential can reach process/container logs - and the enrollment plus its
  mandatory `PILOT_BOOTSTRAP` audit event commit in one transaction. Upload
  requests can never create a device implicitly.
- **Dual-path authentication (strictly separated)**: `CentralRepository`
  resolves administrator credentials/sessions and device upload tokens through
  separate lookups, so a device token never authorizes admin routes and an
  admin token never authenticates a device upload. Disabled devices fail
  closed. Browser sessions are short-lived HttpOnly SameSite=strict cookies
  (`POST /api/v1/auth/session` exchange, `admin_session_ttl_minutes`, default
  8 h); the `Secure` attribute comes from `AV_CENTRAL_SECURE_COOKIES`
  (default true) rather than the request scheme, because TLS is terminated
  outside the API.
- **Admin endpoints**: `GET /api/v1/auth/me`, `GET /api/v1/sites`,
  `GET /api/v1/lines` (optional `site_id`), and
  `GET /api/v1/devices` / `GET /api/v1/devices/{id}`. Every query is scoped
  server-side to the authenticated administrator's organization; credentials
  are never exposed. OpenAPI declares the `PilotBearer` security scheme and
  the RFC 7807 `401`/`404` responses (Problem schema), and
  `api-client-central` types were regenerated.
- **Readiness**: the credentials probe now verifies the durable credential
  store is bootstrapped (≥1 administrator and ≥1 active registered device)
  instead of checking an environment token; readiness fails closed while the
  pilot is not bootstrapped or the store is unreachable.
- **Compose**: `central-bootstrap` runs after `central-migrate` and before
  `central-service`; the admin/device tokens have no defaults (Compose fails
  closed when unset), `admin-web` binds to loopback by default, and
  `CENTRAL_SECURE_COOKIES` is in `compose.env.example`. The edge runtime
  still imports no central code and the edge upload envelope is unchanged.

## 8.16 GitHub Issue Form Template Repair (PR #41)

Merged via PR #41 (dev -> main). The `.github/ISSUE_TEMPLATE/` issue forms
were broken on GitHub: the editor reported "About can't be blank" and marked
the templates "this template has some problems".

- **Root cause**: GitHub parses `.md` files in `ISSUE_TEMPLATE/` as Markdown
  templates, which require an `about:` frontmatter key; the forms were
  written with the issue-form schema (`name:`/`description:`/`body:`) but
  carried `.md` extensions, so GitHub could not find `about:`.
- **Fix**: `bug_report.md`, `feature_request.md`, and
  `security_vulnerability.md` were renamed to `.yml` (GitHub then parses them
  as issue forms), the missing closing `---` frontmatter delimiter was added
  to `security_vulnerability.yml` (its YAML frontmatter was unparsable
  regardless of extension), and `.gitignore` now excludes local `.env`
  deployment secrets (Compose reads `.env`; see `compose.env.example`).
- **Validation**: all three forms parse with both PyYAML and Ruby Psych
  (name/description/body present, exactly two `---` delimiters, valid body
  types and dropdown/checkbox options); referenced labels (`bug`, `triage`,
  `enhancement`, `security`) exist in the repository; no code or docs
  reference the old `.md` template filenames.

## 8.17 Central Server Inspection Ingestion and Verified Receipts (C2a, PR #42)

Merged via PR #42 (dev -> main). Implements the C2a milestone of
`docs/tasks/C1-central-server-m1.md`: device-scoped idempotent inspection
ingestion over the current edge upload envelope. The edge runtime is
untouched; the endpoint preserves the existing wire contract and receipt
semantics.

- **Schema (migration 0003)**: `upload_receipts`, `inspections`, and
  `inspection_components` with `UNIQUE(device_row_id, idempotency_key)`,
  `UNIQUE(device_row_id, inspection_id)`, and
  `UNIQUE(device_row_id, device_sequence)` plus the design 14 keyset
  pagination and partial barcode indexes.
- **`POST /api/v1/inspection-uploads`**: strict typed envelope parsing
  (bounded Base64, canonical SHA-256 request hash, size/checksum
  cross-validation, unknown-field rejection), device identity matching
  against the authenticated device credential (C1b seam), and one-transaction
  persistence of inspection + components + receipt + audit event.
- **Idempotency**: identical replay returns the original receipt (200) with
  exactly one inspection row; a reused idempotency key, inspection id, or
  device sequence with different content returns `409 PAYLOAD_CONFLICT` with
  an audit event and the accepted resource preserved. Concurrent
  unique-constraint races map to 409, never 500.
- **MEDIA envelopes** returned a retryable `503 MEDIA_INGESTION_UNAVAILABLE`
  until the C2b milestone so pending edge media tasks were never permanently
  failed.
- **Verified receipts** echo idempotency key, object id, kind, size, and
  checksum, satisfying the edge `HttpUploadSink` receipt validation (covered
  by an end-to-end test driving the real sink).
- Review fixes folded in: invalid UUID inputs fail closed with typed 4xx,
  `capture_at` (edge capture clock) added to the media row, object keys
  sanitize the registered device identity, and a concurrent unique-race maps
  to 409. The pilot device must be registered with the edge's real UUID
  `device_id` (the C1b default `edge-device-001` is a plain string).
- Verification: 80 central tests, ruff/mypy/pytest, migration 0003
  upgrade/downgrade, real edge sink e2e, and a Docker Compose e2e against
  PostgreSQL (first SUCCEEDED, replay SUCCEEDED, conflict 409).

## 8.18 Central Server MinIO Media Ingestion and Binding (C2b, PR #43)

Merged via PR #43 (dev -> main). Implements the C2b milestone: binds the
existing edge MEDIA envelope into MinIO with verified receipts, replacing the
C2a temporary 503 placeholder.

- **Migration 0004 `inspection_media`**: source media identity, media kind,
  MIME, size, SHA-256, opaque tenant-scoped object key, a stable
  independent-UUID `central_object_id`, lifecycle, and both edge capture and
  central receive times; `UNIQUE(device_row_id, source_media_id)`,
  `UNIQUE(object_key)`, `UNIQUE(central_object_id)`.
- **`ObjectStorage` protocol / `MinioObjectStorage`** gained
  put/stat/remove/list/presigned operations; the test `NoopObjectStorage`
  keeps an in-memory object map for assertions.
- **`ingest_media`**: parent-inspection lookup, manifest cross-check of size
  and checksum against the accepted inspection payload (strong tamper
  protection), idempotent replay and media-identity conflict detection
  before any object write (no staged orphans on the common retry path),
  staging under a generated `org/{org}/device/{device}/{yy}/{mm}/{media_id}`
  key, then one transaction persisting the AVAILABLE binding, MEDIA receipt
  (non-empty `central_object_id`), and audit event.
- **Failure semantics**: object-store failure is a retryable 503; a manifest
  mismatch creates no AVAILABLE row; concurrent races map to 409; replay
  yields one final object/binding.
- **`central-service reconcile-media`** maintenance command over an
  extracted, unit-tested `reconcile_media` function reporting missing/orphan
  objects.
- Settings gained `max_media_payload_bytes` (16 MiB decoded); the envelope
  body bound rose to 32 MiB. Review fixes: `capture_at` on the binding row,
  conflict detection before object writes, and design 13 delivery status
  updated.
- Verification: 96+ central tests including a real edge outbox drain reaching
  SYNCED only after the media receipt (C2b exit criterion), migration 0004
  upgrade/downgrade, and a Docker e2e with a real MinIO object.

## 8.19 Central Server History, Detail, Media Access, and Admin Dashboard (C3, PR #44)

Merged via PR #44 (dev -> main). Implements the C3 milestone: cross-device
inspection history, detail with evidence and media, dashboard aggregates, and
the first real admin-web pilot UI.

- **`GET /api/v1/inspections`**: twelve bounded filters (site, line, device,
  UTC time range, barcode, product, business/internal decision, reason,
  model/rule version) with keyset pagination; cursors are bound to the
  normalized filter fingerprint and malformed/mismatched cursors return
  `400 INVALID_CURSOR`.
- **`GET /api/v1/inspections/{id}`**: decision, component evidence, version
  traceability, inference metadata, receipt state, and media bindings.
- **Authorized media streaming** `GET /api/v1/media/{central_object_id}`
  (organization-scoped; 401/404/410). Replaced presigned URLs whose MinIO
  container host was unreachable from browsers and keeps MinIO off the
  network.
- **`GET /api/v1/dashboard/summary`**, `/timeseries` (daily OK/NG/Uncertain
  buckets), and `/devices` (per-device last-seen and volume); empty data
  stays empty and no accuracy claims are made.
- **admin-web**: `CentralApiClient` (session-cookie auth), login page,
  overview with site/line/time scope selector and ECharts, history with the
  full filter set and bidirectional keyset paging, and detail with evidence,
  versions, receipt state, inference traceability, and streamed media.
  Playwright e2e runs the login-page smoke without a backend (CI) and the
  full pilot flow against Compose when `CENTRAL_E2E_TOKEN` is set.
- Review fixes: malformed UUID inputs fail closed (400/404, never 500), and
  the frontend pagination previous-page cursor handling was corrected.
- Verification: 113+ central tests, migration 0004 remains head, TS gates,
  and browser-verified overview/history/detail with zero console errors.

## 8.20 Central Server Append-Only Human Review (C4, PR #45)

PR #45 (dev -> main) implements the C4 milestone:
central append-only review of ingested inspections with optimistic
concurrency and the admin-web review queue and panel.

- **Migration 0005 `review_records`**: per-inspection monotonic revisions,
  disposition/reason/note/reviewer, bounded component corrections, a snapshot
  of the original machine decision, and idempotency keys
  (`UNIQUE(inspection_row_id, revision)` and
  `UNIQUE(inspection_row_id, idempotency_key)`).
- **`submit_review`**: appends under `Idempotency-Key` + `If-Match`; a stale
  revision returns `409 REVIEW_CONFLICT`, an identical retry replays the
  original record, and the disposition must be permitted for the machine
  outcome (design 24.3). SQLite serializes with `BEGIN IMMEDIATE`;
  PostgreSQL unique-constraint races map to 409, never 500. Every append
  writes a `REVIEW_APPENDED` audit event.
- **`GET /api/v1/reviews/queue`** (NG/uncertain inspections without a
  review, keyset-paginated), **`POST /api/v1/inspections/{id}/reviews`**, and
  **`GET /api/v1/inspections/{id}/reviews`** (oldest first). Inspection
  detail carries `latest_review`; the original machine decision stays
  byte-for-byte unchanged.
- **admin-web**: review queue page and a detail review panel with append
  history and optimistic append; dispositions are dynamically restricted per
  machine outcome (CORRECTED_NG for sampled OK audits, REINSPECT for
  uncertain), and reviewed inspections carry a "reviewed rN" badge distinct
  from the automated outcome.
- Review fixes: concurrent PostgreSQL append races surfaced as 500 (uncaught
  IntegrityError) and now map to explicit `REVIEW_CONFLICT`; the disposition
  options and initial value now follow the domain policy; the client request
  headers merge fixed a missing Content-Type that caused 422 on review
  submission.
- Verification: 131+ central tests including a threaded parallel race (one
  append wins, the other 409), migration 0005 upgrade/downgrade, and a
  browser-verified review flow with zero console errors.

## 8.21 Central Server Metadata Governance (C5, PR #47)

Merged via PR #47 (dev -> main). Implements the C5 milestone: organization-
scoped product/component/rule/model governance with immutable draft/publish
versions, exact-barcode mappings, explicit rule/model compatibility,
single-device desired configuration recording, and read-only admin-web
configuration pages.

- **Migration 0006 `metadata_governance`**: `components`, `products`,
  `product_versions`, `product_version_components`, `product_version_barcodes`
  (partial unique index on PUBLISHED exact barcodes), `rules`, `rule_versions`,
  `rule_component_policies`, `rule_model_compatibilities`, `model_packages`,
  `model_versions`, and `desired_configurations`; `audit_logs` gains
  `request_id`/`reason`/`before_state`/`after_state` correlation columns.
- **Repository**: idempotent create/draft (same key + same hash replays; a
  reused key with different content returns `409 IDEMPOTENCY_CONFLICT`),
  immutable publish (repeat publish returns the published version), publish
  validation (component uniqueness, bounded policy values, threshold ordering,
  exact-barcode ambiguity, published product/model and class coverage), and
  declarative model registration (artifact bytes are never fetched or verified
  server-side in M1; the audit states this explicitly and the edge validates
  bytes/checksum/compatibility and last-known-good rollback locally during
  manual installation). Desired configuration is assigned under an `If-Match`
  revision guard; every publish/assignment writes an immutable audit event in
  the same transaction.
- **Routers**: `/api/v1/components`, `/products`, `/product-versions`,
  `/rules`, `/rule-versions`, `/models`, `/model-versions`
  (list/create/draft/publish/detail) and `/devices/{id}/desired-configuration`
  plus `/device-configurations`. Stable creates and drafts require
  `Idempotency-Key`; assignment requires `If-Match`.
- **admin-web**: read-only Configuration pages (products, rules, models,
  desired configurations) with the mandatory manual-install notice
  ("Assignment is not proof of download, validation, or activation") in
  en/zh-CN/zh-HK/ja; no edit/publish/assign controls ship in C5. Top
  navigation uses direct links after an `el-dropdown` teleport/z-index issue
  made menu clicks unreliable.
- Verification: 162 central tests (29 new C5), regenerated OpenAPI + TS
  client, admin-web lint/build and 30 unit tests, e2e smoke against Compose,
  and a live browser check of all four configuration pages.

## 8.22 Central Server M1 Hardening and Operational Evidence (C6, PR #48)

Merged via PR #48 (dev -> main). Implements the C6 milestone:
structured log correlation, bounded rate limiting, retryable dependency-
failure responses, restart/backup/restore fault evidence, and central
operational runbooks.

- **Structured log correlation**: per-request `request_id` bound through a
  context variable and appended to every log record; the request middleware
  logs `method path -> status (ms)`; ingestion logs carry
  device/inspection/object/receipt correlation tying to the
  `audit_logs.request_id` column.
- **Rate limiting**: per-client sliding-window middleware returns
  `429 RATE_LIMITED` with `Retry-After` (health endpoints exempt;
  `AV_CENTRAL_RATE_LIMIT_REQUESTS_PER_MINUTE`, 0 disables).
- **Retryable dependency failures**: SQLAlchemy `OperationalError` maps to
  `503 DATABASE_UNAVAILABLE` + `Retry-After` (IntegrityError keeps explicit
  conflict semantics); object-store outages already returned
  `503 OBJECT_STORE_UNAVAILABLE`. Request-body/payload caps (413) existed
  from C2a/C2b and stay covered.
- **Fault tests (5 new)**: object-store outage returns 503 with no receipt or
  binding persisted; database outage returns 503; controlled restart (engine
  disposed and reopened) preserves inspections, media bindings, receipts, and
  audit rows with replayable receipts; a consistent snapshot restored as a
  fresh database preserves the same invariants; a real PostgreSQL
  `pg_dump`/`pg_restore` round-trip to a fresh database was executed and
  verified (schema at head, rows intact) as the representative restore
  evidence.
- **Central runbooks C1-C5**: ingestion backlog, object-store failure,
  credential compromise, backup/restore, and pilot upgrade/rollback, indexed
  in `docs/runbooks/README.md` and the mkdocs nav
  (`uv run mkdocs build --strict` passes). M1 remains labeled a controlled
  pilot (no production HA / final RPO-RTO / full retention / OIDC / remote
  rollout claims).
- CI quality gate: an initial failure was a repo-wide `mypy .` unused
  `type: ignore` in two C6 tests (local `mypy src` missed it); fixed in a
  follow-up commit and all PR #48 checks pass. A local 7-test edge-service
  failure was traced to the machine's Data volume being ~94% full
  (free space fluctuating around the E2c `stop_free_percent` 5% threshold,
  which correctly blocks intake); it passes in CI and now locally after disk
  pressure eased - an environment issue, not a defect.

## 8.23 E6-A16 Real Edge-to-Central Integration Fixture

Delivered after PR #48 and carried by PR #49 (`scripts/tests/test_edge_central_e2e.py`).
Closes the mandatory test-matrix item "an
end-to-end edge outbox fixture that validates the actual central receipt"
(task C1 section 11) and provides exit criterion 3's executable evidence,
which the mocked `central.invalid` fixtures cannot:

- The **real edge `UploadScheduler` + `HttpUploadSink`** run against a
  **live in-process central FastAPI server** (uvicorn on a loopback port,
  SQLite repository, in-memory object store, bootstrapped device) - no
  mocked central and no stub sink.
- Test 1 asserts the outbox drains in metadata-before-media order to
  `QUEUED -> PARTIAL -> SYNCED` only after verified central receipts; both
  INSPECTION and MEDIA tasks end `SUCCEEDED` (a SUCCEEDED MEDIA task proves
  the receipt carried a central object id, since `mark_upload_succeeded`
  rejects one without it), and the central inspection detail holds an
  `AVAILABLE` media binding.
- Test 2 asserts duplicate replay is duplicate-free: re-sending the exact
  payload the sink sent returns the original receipt and the central
  database keeps exactly one INSPECTION and one MEDIA receipt row.
- Verification: full repo gates pass (`ruff check .`, `ruff format --check
  .`, `mypy .`, `pytest` - 1174 tests total, `mkdocs build --strict`).

## 9. Open Items / Next Steps

- The **upload queue scheduler** gap is closed (PR #17, section 8.6); **E1
  observability** (PRs #18/#19), **E2 retention and disk safety** (PR #20,
  PR-020 review resolved), **E3 upload resilience** (PR #22, section 8.8),
   **E4 runtime** (section 8.9), **E5 deployment and security** (section
   8.10, PR #24), and **E6 acceptance prep** (PR #25) are merged.
   The clock-drift harness remains explicitly `NOT_EXECUTED`; E6 remains open
   until it and the hardware/customer-data-gated acceptance phase execute:
   - **E6 on-site acceptance**: resilience and soak evidence on the selected
     hardware, held-out customer model validation, and signed Edge acceptance
     report with hardware prerequisites.
- The **WebSocket runtime channel** is implemented (section 8.9); the polling
  preview remains as a pixel-feed stopgap and is not required for correctness.
- AUDIT-001 is **closed** including the deferred 4.4 authoritative persistence
  item (now delivered by PR #17). Shared model weights are implemented (E4c);
  per-instance pipelines use one registry.
- **Barcode identity** (PR #30), **edge-local human review** (PR #31), issue
  templates (PR #32), the README/QUICKSTART/SECURITY refresh (PR #33), the
  developer manual (PR #34), edge-web i18n (PR #35), and the MkDocs index fix
  (PR #36) are merged (see sections 8.11/8.12); the central C1a foundation
  (PR #37), the C1b tenant/credential foundation (PR #40), confidence drift
  (PR #38), device health observability (PR #39), and the issue-form template
  repair (PR #41) are merged too (see sections 8.13/8.15/8.16).
- Real customer data is still required for the baseline: collect and annotate
  with X-AnyLabeling per
  `docs/design/19-training-and-evaluation.md` §19.17 and
  `docs/runbooks/11-data-collection-and-annotation.md`, convert the export with
  `scripts/adapt-xanylabeling.py` (written; supports classes.txt/data.yaml,
  images-first and split-first layouts) into
  `dataset_product`/`dataset_components` + `test-expected.json`, then run
  `av-train` -> `assemblyvision inspect` -> `assemblyvision verify`.
- Camera acquisition (ADR-013/014) is merged (PR #14) including temporal
  aggregation (PR #15/#16) and the trigger/identity seam (E4b). Remaining
  hardware-dependent items: vendor SDK camera adapters (GigE/GenICam source
  merged in PR #26; live validation still required), real barcode decode
  validation on production samples, and a physical photo-eye/PLC transport to
  replace the mock trigger source (the Modbus FIFO contract from PR #30 needs
  a site-validated register profile) and the time-only fallback (which is a
  development mode, not a production product boundary).
- The central server M1 pilot is **feature-complete** (`docs/tasks/C1-central-server-m1.md`).
  C1a (workspace, service, Compose, health/readiness, OpenAPI) is merged
  (PR #37), C1b (tenant/device/credential schema, idempotent bootstrap,
  separated device/admin authentication, admin endpoints) is merged (PR #40,
  section 8.15), C2a (inspection ingestion and verified receipts) is merged
  (PR #42, section 8.17), C2b (MinIO media ingestion and binding) is merged
  (PR #43, section 8.18), C3 (history/detail/media access and the real
  admin-web UI) is merged (PR #44, section 8.19), C4 (central append-only
  human review) is merged (PR #45, section 8.20), admin-web
  i18n/theme/pagination/sign-out hardening is merged (PR #46), C5 (metadata
  governance) is merged (PR #47, section 8.21), and C6 (M1 hardening and
  operational evidence) is merged via PR #48 (section 8.22): `apps/central-service` (FastAPI, PostgreSQL, MinIO,
  controlled schema migrations 0001-0006), `apps/admin-web` (login, overview,
  history, detail, review queue, read-only configuration pages), and
  `packages/typescript/api-client-central`. The E6-A16 real edge-to-central
  integration fixture is delivered
  (`scripts/tests/test_edge_central_e2e.py`): the actual edge
  `UploadScheduler` + `HttpUploadSink` run against a live in-process central
  FastAPI server, verifying metadata-before-media ordering to
  `QUEUED -> PARTIAL -> SYNCED` with real receipts and duplicate-free replay
  (closes the mandatory-matrix edge-outbox item and exit criterion 3).
  The section 13 exit-criteria evidence table (13.1) and the go-live
  deployment checklist (13.2) are recorded in the task doc, and the
  README/QUICKSTART/DEPLOYMENT documentation split is delivered; all of
  these ride on PR #49 (open at snapshot time). Remaining execution work:
  merge PR #49, apply the §13.2 deployment steps on the pilot host (TLS
  termination, real device registration, hardware validation), and execute
  E6 acceptance-prep evidence on-site.
  M1 is a controlled pilot: no production HA, final RPO/RTO, full retention
  enforcement, OIDC, or remote rollout claims. Resumable uploads remain
  deferred until the edge-to-central contract changes. Pilot admin/device/UI
  management operations (device registration/disable/credential rotation,
  user/RBAC, remote package distribution) are production scope driven by
  OQ-021/OQ-022 (roadmap 25.6), not part of C1a-C6.
- Hardware/conditions still unconfirmed (see [Appendices section 3](../design/appendices.md#3-global-open-questions)):
  camera vendor/SDK, barcode standard, conveyor speed, GPU/OS, retention periods, network
  reliability, central-server location, acceptance thresholds.
- `.obsidian/` remains untracked by choice; notify the user before changing that decision.
