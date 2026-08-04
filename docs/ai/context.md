# AssemblyVision - Full Project Context

> Context snapshot. Last updated: 2026-08-04
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
- **Current repository state**: documentation and architecture baseline only. No application
  code exists yet. The next concrete milestone is the two-day static-image MVP.

## 2. Repository State

- Remote: `https://github.com/dream-studio-china/assembly-vision` (branch `main`)
- Git history (all commits so far):
  - `75e2f2e` Add MIT License
  - `fc55b9e` docs: organize AGENTS.md with language, git workflow, and security rules
  - `5924580` Add AssemblyVision architecture documentation and bilingual MkDocs site
- Untracked on disk (intentionally not committed): `.obsidian/` (local Obsidian config).
- Runtime data, model weights, production media, datasets, and secrets must never be stored in
  Git. Build artifacts `docs-zh/`, `site/`, `mkdocs-en.yml`, `mkdocs-zh.yml` are gitignored.

## 3. Directory Structure

```
assembly-vision/
├── README.md               # Root README with docs map + bilingual site instructions
├── AGENTS.md               # Coding rules: language, engineering, git workflow, security
├── LICENSE                 # MIT License (c) 2026 dream-studio-china
├── .gitignore              # Ignores site/, docs-zh/, generated configs, Python/OS artifacts
├── mkdocs.yml              # Master bilingual MkDocs config (Material, Mermaid rendering)
├── scripts/
│   ├── translate-docs.py            # docs/ -> docs-zh/ Chinese translation (deep-translator)
│   ├── generate-mkdocs-configs.py   # generates mkdocs-en.yml / mkdocs-zh.yml from mkdocs.yml
│   └── build-docs.sh                # translate -> build site/ (EN) and site/zh/ (ZH)
├── .github/workflows/docs.yml       # GitHub Pages deploy on push to main
└── docs/
    ├── index.md            # MkDocs home page
    ├── README.md           # Documentation index
    ├── source-brief.md     # Original architecture task brief (was doc-task.md)
    ├── overrides/main.html # Theme override placeholder
    ├── ai/context.md       # THIS file
    ├── design/             # 28 design documents + appendices + decisions/
    │   ├── 00-cover-and-status.md ... 27-risks-and-mitigations.md
    │   ├── appendices.md   # Terminology, decision checklist, open questions, reason codes
    │   └── decisions/      # ADR-001 ... ADR-010 + README
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
- **Central server responsibilities**: ingestion of selected results/media, history, reporting,
  device/config/rule/model management, users/roles, manual NG review, audit, dashboards, remote
  distribution. Not required for inspection.
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
  static-image-first MVP, ADR-010 per-component temporal aggregation.
- [docs/design/appendices.md](../design/appendices.md) holds the canonical terminology, decision consistency checklist,
  global open questions (OQ-001 ... OQ-025), reason-code glossary, and traceability conventions.
- `docs/research/`: industry success rates, YOLO capabilities, imaging/workflow/training cost.

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

- Generated the full architecture document set under `docs/design/` (28 docs + 10 ADRs +
  appendices) from [docs/source-brief.md](../source-brief.md) (formerly `docs/doc-task.md`).
- Created `docs/research/` (3 reports) via internet research.
- Built the bilingual MkDocs with automatic translation, adapted from the `crud-skeleton` project.
- Added Mermaid translation to `translate-docs.py` (labels/edge text only, syntax preserved).
- `UNCERTAIN` decision state is mandated to always map to business `NG` (not configurable).
- Edge deployment is a single `edge-service` process for the first production release (a separate
  edge worker/API split is deferred until measurements justify it).
- Inspections pin both product-detector and component-detector model versions separately.

## 9. Open Items / Next Steps

- Two-day static-image MVP is the next engineering milestone (folder input, two-stage detection,
  ROI, rules, JSON + annotated images, CLI).
- Hardware/conditions still unconfirmed (see [Appendices section 3](../design/appendices.md#3-global-open-questions)):
  camera vendor/SDK, barcode standard, conveyor speed, GPU/OS, retention periods, network
  reliability, central-server location, acceptance thresholds.
- `.obsidian/` remains untracked by choice; notify the user before changing that decision.
