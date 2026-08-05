# AssemblyVision - Full Project Context

> Context snapshot. Last updated: 2026-08-06
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
- **Current repository state**: the labeled static train-and-inspect MVP (ADR-011) is
  implemented and validated on `feat/mvp`. The uv workspace ships shared `domain` and
  `vision-core` packages, a developer-only `av-train` training CLI, real two-stage
  Ultralytics YOLO inspection (`assemblyvision inspect`), and held-out verification
  (`assemblyvision verify`) reporting NG recall, false negatives, and false positives.

## 2. Repository State

- Remote: `https://github.com/dream-studio-china/assembly-vision`; current MVP work is on branch `feat/mvp`.
- `dev` includes engineering contracts, cross-references, expanded contributor rules, and editor ignores on top of `origin/main`.
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
│   └── tests/                       # tests for the Roboflow adapter
├── .github/workflows/               # ci.yml (repo-wide quality gates) + docs.yml (Pages deploy)
├── apps/edge-service/                # inspection runtime (inspect/verify CLI, pipeline, rules, detectors)
├── packages/python/
│   ├── domain/                       # canonical models, errors, reason codes
│   └── vision-core/                  # ROI engine, image sources, manifest loading
├── training/                         # developer-only av-train CLI (product/prepare-components/component)
├── config/examples/                  # Example pipeline, rule, and manifest configuration
├── models/manifests/                 # Checked model metadata; weights remain outside Git
├── tests/fixtures/                   # Small non-sensitive test fixtures
├── pyproject.toml                    # Root uv workspace configuration
└── docs/
    ├── index.md            # MkDocs home page
    ├── README.md           # Documentation index
    ├── source-brief.md     # Original architecture task brief (was doc-task.md)
    ├── contributing.md     # Contributor-facing repository rules and precedence
    ├── overrides/main.html # Theme override placeholder
    ├── ai/context.md       # THIS file
    ├── reviews/            # Code-review follow-up findings (PR-003-review.md)
    ├── contracts/          # 11 mandatory engineering contracts + index
    ├── runbooks/           # 10 operational recovery runbooks + index
    ├── design/             # 28 design documents + appendices + decisions/
    │   ├── 00-cover-and-status.md ... 27-risks-and-mitigations.md
    │   ├── appendices.md   # Terminology, decision checklist, open questions, reason codes
    │   └── decisions/      # ADR-001 ... ADR-011 + README
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
   static-image-first MVP, ADR-010 per-component temporal aggregation, and ADR-011 labeled
   train-and-inspect MVP.
- [docs/design/appendices.md](../design/appendices.md) holds the canonical terminology, decision consistency checklist,
  global open questions (OQ-001 ... OQ-025), reason-code glossary, and traceability conventions.
- `docs/research/`: industry success rates, YOLO capabilities, imaging/workflow/training cost.
- [docs/contracts/](../contracts/README.md): 11 enforceable architecture, safety, API, quality,
  operations, security, change-control, and acceptance contracts.
- [docs/runbooks/](../runbooks/README.md): executable recovery procedures for all contract-required
  operational scenarios, including model improvement (runbook 10).

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

- Generated the full architecture document set under `docs/design/` (28 docs + 11 ADRs +
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
  boxes are fatal; missing label files warn; empty label files are valid
  negatives; component preparation keeps negative ROI crops; and published
  model versions refuse to be silently overwritten with different bytes.
- Quality gates: `ruff check .`, `ruff format --check .`, `mypy .`, and
  `pytest` now cover the whole repository (edge, packages, training, scripts
  tests) via the Makefile and a new `.github/workflows/ci.yml`.

## 9. Open Items / Next Steps

- The static train-and-inspect MVP is complete and validated on synthetic data (NG recall 1.0,
  zero false negatives on the held-out set). The next milestone is the one-month target
  (roadmap 25.5): camera/barcode integration, product windows, local persistence, temporal
  aggregation, edge dashboard, upload queue, and one central ingestion/history/review path.
- Real customer data is still required: annotate with X-AnyLabeling (product + component boxes),
  then run `av-train` -> `assemblyvision inspect` -> `assemblyvision verify`. Public Roboflow
  datasets (e.g., BoardEye-Missing-Component) can validate the framework but not a specific line.
- Model improvement workflow is documented (runbook 10) with `av-train --rule` version hints.
- Hardware/conditions still unconfirmed (see [Appendices section 3](../design/appendices.md#3-global-open-questions)):
  camera vendor/SDK, barcode standard, conveyor speed, GPU/OS, retention periods, network
  reliability, central-server location, acceptance thresholds.
- `.obsidian/` remains untracked by choice; notify the user before changing that decision.
