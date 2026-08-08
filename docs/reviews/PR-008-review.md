# PR-008 Review: FastAPI Local API, SQLite Index, Runtime Hardening, and Test Coverage

> **Correction (AUDIT-001).** The "100% test coverage" claim in the PR
> description was not reproduced. Measured edge Python statement coverage on
> the merged result is approximately 99.5% (pytest-cov); the uncovered lines
> are viewer-session/no-token branches, derived-image and statistics
> fallbacks, the verify empty-work branch, and the unreachable IntegrityError
> handler. Treat coverage numbers as dated measurement artifacts, not
> guarantees, and record the exact command/output when making claims.

## Scope

Code review of `dev` -> `main` PR #8 (`feat(edge): FastAPI local API, SQLite
index, runtime hardening, and test coverage`). The PR wires the edge
dashboard to a real backend (`assemblyvision serve`, `/api/v1`), adds a SQLite
index with Alembic migration and idempotent CLI-output reconciliation, applies
PR-003 runtime hardening, and expands Python coverage.

This document records the findings, proposed solutions, and acceptance criteria
for the items that must be fixed before merge and for the non-blocking follow-up
work.

## Merge Decision

**Do not merge until F1-F14 below are resolved.**
GitHub CI, CodeQL, and the local quality gates all pass, but several critical
defects and contract violations are not covered by the current test suite.

C1-C4 are conditional production-persistence requirements, not blockers for
the explicitly bounded read-only M1 index. They become blockers if this PR is
described or used as the authoritative production persistence/upload subsystem.

## Resolution Status

All findings in this review have been fixed and validated on `dev`:

- **F1-F14** (blocking) resolved. Each commit carried its regression tests; the
  full suite passes and edge Python coverage is measured and recorded with
  pytest-cov (approximately 99.5% statement coverage on the merged result; see
  the correction note above).
- **C1-C4** (conditional production-persistence) addressed for M1: SQLite is
  documented as a rebuildable read projection with a rebuild-equivalence test,
  migration-head verification, duplicate-child rejection, and quarantine of
  crash-left staging bundles.
- **P2** items addressed: unknown `/api` paths return a problem 404, request
  IDs propagate, media streaming is bounded with a valid 416 problem,
  `verify --expected` disables filename fallback and rejects duplicate
  identities, inference metadata is typed with per-stage traceability, rule
  identities cannot be reactivated with different content, and the quickstart/
  context docs match the implemented M1 boundary.
- Remaining roadmap scope (upload queue scheduler, WebSocket channel, camera/
  barcode adapters, temporal aggregation, Docker packaging, authoritative
  SQLite persistence/outbox) is recorded as the next milestone and does not
  block this PR.

## Validation Performed

Executed on `dev` without modifying tracked files:

```text
make check
git diff --check origin/main...HEAD
gh pr status / gh pr view
```

Results:

- Ruff: pass
- Ruff format: pass
- MyPy: pass
- Pytest: `307 passed`
- TypeScript build / lint / test: pass
- Playwright e2e: `11 passed`
- GitHub CI + CodeQL checks: all green

The passing gates confirm the existing tests are stable but do not cover the
end-to-end, safety, and security scenarios below.

## Solution Validation Summary

| Findings | Validation | Notes |
|---|---|---|
| F1-F2 | Feasible as written | Fix at both persistence/import and serve boundaries; F1 must preserve pre-rename bundle atomicity. |
| F3 | Feasible after one security decision | The accepted contracts require backend authorization, but the exact offline edge-session mechanism remains an open design choice. Do not replace authentication with loopback binding or CORS. |
| F4 | Feasible with two valid scopes | Recommended for M1: remove/disable unsupported controls. Production alternative: add an inspection coordinator; do not put pause state in detector classes. |
| F5-F8 | Feasible as written | Explicit API mode, no mixed mock/real state, Ultralytics `[height, width]`, and subset compatibility checks are bounded changes. |
| F9 | Feasible but cross-workspace | This implements the already accepted OpenAPI-generation strategy and must update Python models, generated artifacts, TypeScript wrappers, and CI together. |
| F10 | Feasible as written | Separate persistent database configuration from per-connection PRAGMAs and hash only immutable inspection content. |
| F11-F14 | Feasible and required before merge | These close fail-safe, evidence-provenance, statistics, and evidence-presentation defects in behavior claimed by this PR. |
| C1-C4 | Feasible but conditional | Required when SQLite/upload becomes authoritative production persistence; not blockers for a clearly labelled rebuildable M1 read index. |

## Global Acceptance Rules

Every blocking finding is accepted only when:

- A regression test fails on the pre-fix implementation and passes with the
  fix; line coverage alone is not evidence of behavioral coverage.
- Tests exercise the public boundary involved (HTTP, persisted bundle/database,
  generated client, or inspection coordinator), not only a mocked private
  helper.
- Negative and fail-safe paths are asserted explicitly, including the returned
  problem code or NG reason code where applicable.
- `make check` and `git diff --check origin/main...HEAD` pass after all fixes.
- Quickstart/context claims are updated to match the implemented M1/production
  boundary; no unavailable feature is described as operational.

---

## Immediate Blocking Findings

### F1. Media records published under the staging path that is later renamed away

**Problem:** `OutputWriter.save` writes media into a random `.staging-...`
directory and then renames that directory to the inspection ID, but the
persisted `relative_path` is derived from the staging directory name and is
never updated after the rename. Every media record produced by the hardened
writer therefore points at a path that no longer exists.

**Location:**
- `apps/edge-service/src/assemblyvision_edge/output/writer.py:114` (staging dir)
- `apps/edge-service/src/assemblyvision_edge/output/writer.py:130` (rename)
- `apps/edge-service/src/assemblyvision_edge/output/writer.py:151` (`relative = f"{inspection_dir.name}/{name}"`)

**Impact:** After `assemblyvision inspect`, the final file exists at
`<output>/<inspection_id>/key_frame.jpg` while the record references
`<output>/.staging-.../key_frame.jpg`. Reconciliation imports the invalid path
and `GET /api/v1/media/{id}/content` returns 404 for every generated image.
Reproduced locally: the persisted path did not exist while the final file did.

**Test gap:** `apps/edge-service/tests/test_output_writer.py:60-78` and
`apps/edge-service/tests/test_output_writer_extended.py` assert the physical
file and checksum but never resolve `output_root / media.relative_path`.

**Proposed solution:** Build the final `relative_path` from the stable
inspection ID while files are still written under the staging directory. Pass
the final relative directory name separately to `_save_image`; do not rewrite
the record after publication because that would require rewriting
`inspection.json` after the atomic directory rename. Add a round-trip test that
saves media, reconciles, and serves the content through the repository and media
endpoint.

**Acceptance criteria:**
- `media.relative_path` resolves to an existing file under `output_root` for
  every kind of media produced by `writer.save`.
- A test verifies `output_root / media["relative_path"]` exists after save and
  after `reconcile_output_root`.
- An API test verifies `GET /api/v1/media/{id}/content` returns the bytes for a
  freshly produced inspection.

### F2. Media content endpoint allows directory traversal and absolute paths

**Problem:** `relative_path` is imported from `inspection.json` without
validation and served by joining `settings.output_root / media.relative_path`
without resolving and checking containment. An `inspection.json` containing
`../secret.txt` or an absolute path is accepted during reconciliation and its
content is served outside the media root. The caller-controlled MIME type can
also cause active browser content to be served.

**Location:**
- `packages/python/domain/src/assemblyvision_domain/models.py:136-145`
- `apps/edge-service/src/assemblyvision_edge/persistence/reconcile.py:30-40`
- `apps/edge-service/src/assemblyvision_edge/api/routers/media.py:49-60`

**Violation:** `docs/design/12-local-storage-and-retention.md:32` (paths are
generated by trusted code and cannot contain caller-supplied traversal
segments), `docs/design/14-data-model-and-database.md:429,511-515` (paths must
be relative to the configured media root), `docs/contracts/05-data-api-and-versioning-contracts.md:75-82` (API must not expose filesystem data).

**Proposed solution:**
- Reject absolute and traversal paths at import time (reconciliation and any
  future ingestion path).
- Resolve every served path and require
  `candidate.is_relative_to(output_root.resolve())` before reading.
- Do not trust the persisted MIME type; use a serve-time allowlist.

**Acceptance criteria:**
- Reconciliation skips (and logs) any media record whose path is absolute or
  escapes `output_root`; the inspection record is not partially imported.
- `GET /api/v1/media/{id}/content` returns 404 for any non-contained path.
- Tests with crafted reconciled metadata prove `../`, absolute paths, and
  symlink escapes cannot be read.
- Response `Content-Type` is derived from a media-kind/extension allowlist, or a
  validated persisted value; arbitrary persisted MIME values are rejected.

### F3. Unauthenticated local API with wildcard CORS exposes privileged operations

**Problem:** No route has an authentication or authorization dependency, and the
app enables `allow_origins=["*"]` with all methods and headers. Any process or
browser able to reach the host can pause/resume inspection, reconnect the
camera, retry uploads, and read history, configuration, logs, and media. The
wildcard CORS lets arbitrary websites issue cross-origin requests to the local
API. `paused_by` is therefore hardcoded to `"operator"`, creating false
attribution.

**Location:**
- `apps/edge-service/src/assemblyvision_edge/api/app.py:81-90` (CORS)
- `apps/edge-service/src/assemblyvision_edge/api/app.py:95-107` (no auth deps)
- `apps/edge-service/src/assemblyvision_edge/api/routers/inspection.py:48-81`
- `apps/edge-service/src/assemblyvision_edge/api/routers/camera.py:23-29`
- `apps/edge-service/src/assemblyvision_edge/api/routers/uploads.py:53-64`
- `apps/edge-service/src/assemblyvision_edge/api/state.py:60-64`

**Violation:** `docs/design/15-rest-api-and-events.md:13-18` (mutating routes
require `operator`/`edge_admin`; read-only health is deliberately limited; do
not treat localhost as authentication), `docs/design/16-edge-dashboard.md:137-139`,
`docs/contracts/08-security-permissions-and-audit.md:11-16`.

**Proposed solution:**
- Adopt and document an offline-capable edge session/principal design defining
  credential issuance, validation, expiry, CSRF protection, and viewer/operator/
  edge-admin authorization. Enforce it on every route except `/health/live`.
- For read-only M1, remove unsupported mutation routes and their UI controls
  rather than exposing unauthenticated placeholders. If mutations remain, they
  require the documented operator/admin role and actor attribution.
- Disable CORS by default (same-origin static deployment) and configure an
  explicit development-origin allowlist (or an anchored localhost regex) instead
  of `*`.
- Record the acting principal (real user or session) in `paused_by` and audit
  mutations.

**Acceptance criteria:**
- The selected edge-session contract is recorded in the relevant design/ADR;
  loopback binding and CORS are not treated as authentication.
- Every read route except the deliberately minimal `/health/live` returns
  401/403 without the defined viewer credential.
- Unsupported M1 mutations return 404/405 and have no corresponding UI control;
  any retained mutation returns 401/403 without its required role.
- A browser-origin test proves that an unapproved origin cannot read or mutate
  the API (preflight/actual request rejected).
- For retained mutations, actor fields reflect the authenticated principal and
  direct authorization tests cover every exposed command.

### F4. Pause changes presentation state but does not stop inspection work

**Problem:** `EdgeRuntime.pause` only sets booleans and metadata. Nothing in the
pipeline or any inspection entry point reads `runtime.paused`, so inspection
work can continue while the UI shows a prominent "No new product windows will be
opened" banner.

**Location:**
- `apps/edge-service/src/assemblyvision_edge/api/state.py:60-70`
- `apps/edge-service/src/assemblyvision_edge/api/routers/inspection.py:48-80`
- `apps/edge-web/src/pages/LiveInspection.vue:125-136`

**Violation:** `docs/design/16-edge-dashboard.md:112-116` (pause stops opening
new product windows; the API owns the active-window behavior).

**Proposed solution:** Route pause/resume through an inspection coordinator that
owns admission of new product windows; detector/pipeline classes should not own
operational pause state. The coordinator must finish or abort an active window
according to an explicit policy, and resume must evaluate a typed readiness
snapshot. For this read-only M1, the smaller valid alternative is to remove or
disable the mutation endpoints and hide the controls until such a coordinator
exists.

**Acceptance criteria:**
- For the M1 removal option, API tests assert pause/resume return 404/405 and UI
  tests assert that no control or effectiveness claim is rendered.
- For the coordinator option, integration tests prove paused admission
  rejection and the configured active-window finish/abort policy, including
  conservative NG persistence for an aborted window when applicable.
- For the coordinator option, resume returns `409 PRECONDITION_FAILED` unless
  camera, model, rule, database, and disk preconditions pass, and the UI does not
  optimistically render `READY` before confirmation.

### F5. The documented `serve` quickstart serves a mock-backed dashboard

**Problem:** `VITE_API_BASE_URL` is embedded at build time. The quickstart runs
`pnpm --filter edge-web build` without setting it, so the bundle selects
`MockApiClient` and the dashboard served by FastAPI shows seeded mock data
instead of the reconciled real inspections.

**Location:**
- `QUICKSTART.md:152-162`
- `apps/edge-web/src/services/client.ts:14-18`

**Contradicts:** `QUICKSTART.md:147-150` and `docs/ai/context.md:276-297`.

**Proposed solution:** Introduce an explicit build/runtime data mode such as
`VITE_API_MODE=mock|http`. In HTTP mode, an omitted base URL means same-origin
`/api/v1`; in mock mode the deterministic demo remains available. Build the
served production bundle in HTTP mode. Add a browser-to-FastAPI integration test
that proves real data renders when the built bundle is served by
`assemblyvision serve`.

**Acceptance criteria:**
- Following the quickstart end to end shows real inspections in history,
  detail, media, and statistics, and shows backend-derived configuration/logs.
- A separate HTTP integration fixture with a barcode value proves traceability
  rendering; the default static-MVP quickstart is not required to fabricate an
  SN that its CLI does not produce.
- A test asserts the served bundle talks to the same-origin API.
- The mock remains available only when an explicit mock mode is selected; an
  absent URL alone does not silently select mock in a production build.

---

## Additional Blocking Findings

### F6. Real mode mixes simulated inspection results with real device controls

**Problem:** The current inspection, confirm, next, and manual actions always
run against a private `MockApiClient`, while pause/resume, status, logs,
history, and runtime state use the configured real client. The mock inspection
ID is then used to request real media; on failure the UI silently substitutes a
synthetic camera frame.

**Location:**
- `apps/edge-web/src/services/inspectionService.ts:27-51`
- `apps/edge-web/src/pages/LiveInspection.vue:46-56`

**Violation:** `docs/design/16-edge-dashboard.md:63-73,128-130` (the
deterministic final decision is authoritative; simulated/stale data must not
look current), `docs/contracts/03-ai-rule-and-safety-contracts.md`.

**Proposed solution:** In real mode, hide or disable the mock workflow and never
render simulated decisions alongside real device state; surface missing evidence
as an explicit unavailable state instead of synthetic imagery.

**Acceptance criteria:**
- In real mode no mock inspection is shown as a current result.
- Missing media renders an unavailable/purged state, not a fabricated frame.
- A test covers the faulted-device scenario (synthetic data must not appear with
  real pause/status controls).

### F7. Non-square manifest inference size passed to Ultralytics in wrong order

**Problem:** The detectors pass `imgsz=(input_width, input_height)` but
Ultralytics interprets a two-element `imgsz` as `[height, width]`. For a
manifest declaring 1280x736 the runtime infers at 1280x736 swapped, so
preprocessing no longer matches the released model configuration.

**Location:**
- `apps/edge-service/src/assemblyvision_edge/detection/product_detector.py:84-90`
- `apps/edge-service/src/assemblyvision_edge/detection/component_detector.py:84-90`

**Test gap:** `apps/edge-service/tests/test_detectors.py` asserts the order
using square fixtures, which cannot expose the defect.

**Proposed solution:** Pass `(input_height, input_width)` to Ultralytics and add
a non-square manifest adapter test asserting the exact model invocation
arguments. Keep manifest dimensions named as width/height; serialize `imgsz`
explicitly as `[height, width]` to avoid ambiguity.

**Acceptance criteria:**
- Adapter tests with non-square manifests assert the correct `[height, width]`
  order.
- `effective_settings` and persisted `inference_metadata` reflect the same order.

### F8. Rule, component configuration, and manifest sets are not cross-validated at startup

**Problem:** Detector construction validates only `config.components ⊆
manifest.class_names`. If the rule requires a component that is present in the
manifest but missing from `config.components`, the pipeline is reported as
built and the detector later raises `KeyError` on every inspection.

**Location:**
- `apps/edge-service/src/assemblyvision_edge/api/state.py:210-230`
- `apps/edge-service/src/assemblyvision_edge/detection/component_detector.py:101-104`

**Status:** Unresolved PR-003 P1 (`docs/reviews/PR-003-review.md:43-57`).

**Proposed solution:** Validate the required subset relationships at startup:
`rule.required_components` must be a subset of `config.components`, and every
configured component must exist in the component manifest. Extra manifest
classes are allowed. Extra configured components may be allowed but are not
decision evidence unless required by the active rule. Also validate the rule's
declared compatible component-model version. Any invalid relationship prevents
`inspection_ready`.

**Acceptance criteria:**
- A missing rule-required component in `config.components` makes the pipeline
  fail to load; readiness returns `inspection_ready=false` and a stable
  `CONFIG_INVALID` reason category without exposing internal paths.
- CLI `inspect`/`verify` exit with configuration status 2 on the same mismatch
  and identify the missing component or incompatible version.
- Tests cover a rule component absent from config, a configured component absent
  from the manifest, an incompatible component-model version, and allowed extra
  manifest classes.

### F9. FastAPI/OpenAPI and TypeScript contracts are not synchronized

**Problem:** Most routes return `dict[str, object]` without typed response
models, so generated OpenAPI describes arbitrary objects
(`additionalProperties: true`). TypeScript types remain handwritten. Concrete
drift already exists: Python `AggregatedComponentEvidence` includes
`box_area_ratios` and `box_centers`, while
`packages/typescript/api-client/src/edge/types.ts:139-148` omits them.
`HttpApiClient` blindly casts JSON to `T`, so tests cannot detect incompatible
payloads.

**Location:**
- `apps/edge-service/src/assemblyvision_edge/api/routers/inspections.py:17-57`
- `apps/edge-service/src/assemblyvision_edge/api/routers/device.py:14-19`
- `packages/typescript/api-client/src/edge/types.ts:1-6`

**Violation:** ADR-006, `docs/contracts/02-code-and-interface-contracts.md:64-75`,
`docs/design/14-data-model-and-database.md:401-418,545-555`.

**Proposed solution:** Declare strict Pydantic request/response models and typed
route return annotations (using `response_model` where FastAPI cannot infer the
contract), commit deterministic OpenAPI, generate the TypeScript types/client
into the documented generated directory, and make CI fail on generated-file or
OpenAPI drift. Keep request models `extra="forbid"`.

**Acceptance criteria:**
- OpenAPI describes named `Page[T]`, `InspectionRecord`, `DeviceStatus`,
  `Problem`, etc., not arbitrary objects.
- A CI drift check fails when OpenAPI changes without updating generated TS.
- Unknown request-body fields are rejected whenever a body-bearing endpoint is
  present; this criterion is not applied to removed M1 mutation endpoints.
- Contract integration tests call a live TestClient endpoint and validate the
  returned JSON at the frontend boundary with generated schemas/runtime
  validation; TypeScript type-checking alone is not treated as JSON validation.

### F10. SQLite defaults and immutable inspection semantics do not meet the contract

**Problem:** The repository does not enable WAL or foreign keys, so `ON DELETE
CASCADE` is inert. `upsert_inspection` can overwrite `device_id`,
`completed_at`, and `decision` and deletes/replaces all evidence and media, while
the denormalized filter columns are not updated, leaving list filters
inconsistent with detail.

**Location:**
- `apps/edge-service/src/assemblyvision_edge/persistence/repository.py:122-131` (engine, no PRAGMAs)
- `apps/edge-service/src/assemblyvision_edge/persistence/repository.py:136-217`

**Violation:** `docs/design/14-data-model-and-database.md:420-430`,
`docs/design/12-local-storage-and-retention.md:47`,
`docs/contracts/05-data-api-and-versioning-contracts.md:3-18`.

**Proposed solution:** Set persistent database options such as WAL during
database initialization/migration, and configure connection-scoped PRAGMAs
(`foreign_keys`, `busy_timeout`, and the approved synchronous level) through
SQLAlchemy connection events. For the M1 read projection, make reconciliation
insert-only: identical existing content is a no-op, while different content for
the same inspection ID is an integrity conflict and is never applied. Move
mutable synchronization-state APIs to the authoritative persistence milestone.

**Acceptance criteria:**
- A reopened file-backed database reports `journal_mode=wal`; every checked-out
  connection reports `foreign_keys=1` and the configured `busy_timeout`.
- Re-importing an identical inspection is a no-op; conflicting content for the
  same inspection ID fails without partial mutation.
- No replay rewrites evidence/media, and list/filter projections remain
  consistent with detail.

### F11. Rule evaluation exceptions bypass the fail-safe persisted decision path

**Problem:** `RuleEngine.evaluate` can raise `RuleEvaluationError`, but the
pipeline does not convert it into a conservative terminal record. The CLI
reports an operational error and no auditable NG result is persisted.

**Location:**
- `apps/edge-service/src/assemblyvision_edge/rules/rule_engine.py:179-180`
- `apps/edge-service/src/assemblyvision_edge/pipeline.py:212-231`

**Proposed solution:** Catch `RuleEvaluationError` at the application/pipeline
boundary, create the canonical terminal internal NG decision, map the business
result to NG, add
`RULE_EVALUATION_ERROR`, and persist the available evidence. Do not catch broad
programming exceptions inside the rule engine itself.

**Acceptance criteria:**
- An injected `RuleEvaluationError` produces a persisted inspection with
  `business_result=NG` and `RULE_EVALUATION_ERROR`.
- The result cannot contain `internal_decision=OK`, and available model/rule/
  media provenance remains present.
- Persistence failure still returns a non-zero operational error and never
  reports an uncommitted NG/OK result as durable.

### F12. Component provenance does not validate the ROI/full-frame transform

**Problem:** Provenance validation checks frame/model IDs and image dimensions
but accepts mutually inconsistent `roi_bbox` and `full_frame_bbox` coordinates.
Contradictory evidence can therefore pass validation and contribute to OK.

**Location:**
- `apps/edge-service/src/assemblyvision_edge/pipeline.py:80-100`

**Proposed solution:** Map each ROI box to full-frame space (or vice versa) with
the recorded transform and compare it to the detector-provided counterpart
using a documented numeric tolerance that accounts only for floating-point
rounding (the current translation transform should use a small absolute
tolerance, not a broad pixel allowance). Reject non-invertible transforms and
inconsistent boxes as `INFERENCE_ERROR`.

**Acceptance criteria:**
- For M1, only the supported invertible translation transform is accepted;
  exact and floating-point-equivalent translated coordinate pairs pass.
- Pairs inconsistent with the recorded transform, unsupported/non-invertible
  transforms, and wrong-frame pairs fail closed to business NG with
  `INFERENCE_ERROR` and contribute no presence evidence.
- If general affine transforms are introduced later, valid non-unit scaling gets
  positive tests and only inconsistent mappings are rejected.

### F13. Statistics silently ignores documented filters

**Problem:** The client sends `from`, but the FastAPI route exposes `from_`
without an alias; `line` is accepted and ignored. Operators can receive totals
for the wrong time range or line.

**Location:**
- `apps/edge-service/src/assemblyvision_edge/api/routers/derived.py:44-60`
- `packages/typescript/api-client/src/edge/HttpApiClient.ts:185-191`

**Proposed solution:** Add `Query(alias="from")`, validate UTC timestamps, and
either implement line filtering against a persisted indexed line identity or
explicitly detect `line` and return `400 UNSUPPORTED_FILTER` until line identity
exists. Merely removing the declared parameter is insufficient because FastAPI
otherwise ignores unknown query parameters.

**Acceptance criteria:**
- End-to-end tests prove `from` and `to` change the returned population.
- Supplying `line` either filters correctly or returns a documented 400; it is
  never silently ignored.

### F14. Derived image endpoint mislabels or fabricates evidence

**Problem:** The endpoint maps `ANNOTATED_FRAME` to `detection` and prefers
`PRODUCT_ROI` for `annotated`; when media is absent the UI substitutes synthetic
imagery without an unavailable marker.

**Location:**
- `apps/edge-service/src/assemblyvision_edge/api/routers/derived.py:63-81`
- `apps/edge-web/src/pages/ImageViewer.vue:33-42`
- `apps/edge-web/src/pages/LiveInspection.vue:46-56`

**Proposed solution:** Define typed image slots whose names match canonical
media kinds, map each kind once, and represent unavailable/purged media
explicitly. Synthetic demo images must be possible only in explicit mock mode.

**Acceptance criteria:**
- KEY_FRAME, PRODUCT_ROI, and ANNOTATED_FRAME appear under correctly labelled
  slots in API and UI tests.
- Missing or purged evidence shows an explicit unavailable/purged state and no
  synthetic image in HTTP mode.

---

## Conditional Production-Persistence Findings

C1-C4 are valid requirements for the authoritative production persistence and
upload subsystem. They do not block a read-only M1 index if the API, quickstart,
and context documents clearly label SQLite as a rebuildable projection of CLI
bundles and do not claim transactional outbox/recovery readiness.

### C1. Completed inspections are not committed to the database as one durable unit

**Problem:** `assemblyvision inspect` publishes media/JSON and reports `OK`
immediately; SQLite is populated only when the API later starts and scans, and
reconciliation creates no upload tasks. A crash before startup leaves a completed
result outside the operational database and queue, and `/api/v1/uploads` remains
empty for normal inspections.

**Location:**
- `apps/edge-service/src/assemblyvision_edge/pipeline.py:235-278`
- `apps/edge-service/src/assemblyvision_edge/output/writer.py:96-135`
- `apps/edge-service/src/assemblyvision_edge/cli.py:150-164`
- `apps/edge-service/src/assemblyvision_edge/persistence/reconcile.py:30-42`

**Violation:** `docs/design/12-local-storage-and-retention.md:34-45`,
`docs/design/13-upload-and-synchronization.md:13-19`,
`docs/contracts/04-edge-storage-upload-contracts.md:30-43`, ADR-005.

**Proposed solution:** Keep the current CLI JSON bundle as the authoritative
static-MVP result and explicitly treat SQLite as a rebuildable read projection.
When authoritative SQLite persistence/upload enters scope, replace startup-only
reconciliation with an application service that, after durable media
publication and before completion is published, atomically inserts the
inspection, evidence, media metadata, and required upload outbox tasks in one
transaction.

**Acceptance criteria for M1:**
- Documentation identifies SQLite as a rebuildable read index, not the
  authoritative completion/outbox store.
- Deleting and rebuilding the index from valid CLI bundles yields equivalent
  read results without changing the bundles.

**Acceptance criteria before production persistence activation:**
- A completed inspection always has a matching database row and required upload
  task before `OK`/completion is published to operational consumers.
- Crash tests at each atomic-persistence step recover deterministically (no
  completed inspection without its required upload task).

### C2. Schema cannot enforce synchronization identity or recover upload leases

**Problem:** The schema permits duplicate `(device_id, device_sequence)`,
duplicate `(device_id, idempotency_key)`, duplicate media paths, and duplicate
component codes per inspection. `upload_tasks` and `UploadTask` have no lease
owner/expiry, so stale `IN_PROGRESS` work cannot be recovered after a crash.

**Location:**
- `apps/edge-service/src/assemblyvision_edge/persistence/schema.py:25-55,88-127`
- `apps/edge-service/migrations/versions/0001_initial.py:20-56,77-111`
- `packages/python/domain/src/assemblyvision_domain/models.py:148-167`

**Violation:** `docs/design/14-data-model-and-database.md:420-445`,
`docs/contracts/04-edge-storage-upload-contracts.md:45-66,90-99`.

**Proposed solution:** In the rebuildable M1 index, reject duplicate canonical
child identities during reconciliation and test that rejection. Before SQLite
becomes authoritative, add the documented database uniqueness constraints. If
revision `0001` has not been deployed outside disposable development data it may
be corrected directly; otherwise add a forward Alembic revision. Add upload
idempotency constraints and lease fields when the scheduler is implemented.

**Acceptance criteria for the M1 projection:**
- Reconciliation rejects duplicate component identities and conflicting media
  paths without partially importing the inspection.

**Acceptance criteria before persisted synchronization activation:**
- `UNIQUE(relative_path)` and
  `UNIQUE(inspection_id, component_code)` are enforced by the database.
- `UNIQUE(device_id, device_sequence)` is enforced after durable sequence
  allocation is implemented.

**Acceptance criteria before upload scheduler activation:**
- `UNIQUE(device_id, idempotency_key)` and lease owner/expiry fields are
  enforced.
- Stale `IN_PROGRESS` tasks are detectable and moved to a retryable state after
  lease expiry.

### C3. `device_sequence` is not durable and product-configuration version is not bound

**Problem:** `device_sequence` restarts at 1 after every process restart while an
omitted device ID is regenerated, producing duplicate sequence numbers that the
schema permits. The pipeline creates `ProductResolution` without
`product_version_id`, and the schema has no required product-configuration
version column, so central synchronization cannot deduplicate or replay an
inspection against its exact configuration.

**Location:**
- `apps/edge-service/src/assemblyvision_edge/pipeline.py:127-129,235-265`
- `apps/edge-service/src/assemblyvision_edge/api/state.py:40-45,230-240`
- `apps/edge-service/src/assemblyvision_edge/persistence/schema.py:28-55`

**Violation:** `docs/design/14-data-model-and-database.md:13-20,206-229,424-430`,
`docs/contracts/05-data-api-and-versioning-contracts.md:20-29,103-113`.

**Proposed solution:** For the static CLI MVP, document that its sequence is not
a synchronization identity. Before persisted/synchronized operation, require a
stable configured device identity, persist and transactionally allocate
per-device sequence numbers, and store the product-configuration version on
every inspection.

**Acceptance criteria before persisted/synchronized operation:**
- Sequence numbers are unique per device across restarts.
- Every persisted inspection records its product-configuration version.
- Duplicate device sequences are rejected by the database.

### C4. Startup reconciliation does not perform the required integrity or recovery work

**Problem:** Existing database rows are skipped, and their media existence, size,
checksum, and lifecycle are never checked. Stale `IN_PROGRESS` tasks,
interrupted inspections, orphan/staging files, and database integrity are not
recovered. Missing `AVAILABLE` media remains advertised until a request happens
to fail.

**Location:**
- `apps/edge-service/src/assemblyvision_edge/api/app.py:55-70`
- `apps/edge-service/src/assemblyvision_edge/persistence/reconcile.py:20-42`

**Violation:** `docs/design/12-local-storage-and-retention.md:108-112`,
`docs/design/14-data-model-and-database.md:539-543`,
`docs/contracts/04-edge-storage-upload-contracts.md:90-99`.

**Proposed solution:** For M1, validate migration success and rebuildability of
the read index, and do not claim full recovery. Before authoritative persistence
activation, implement explicit startup recovery phases (DB integrity,
interrupted inspections, staging/orphan files, referenced-media existence/size,
bounded checksum verification, expired upload leases) and enter a
storage-not-ready mode on unrecoverable corruption.

**Acceptance criteria before authoritative persistence activation:**
- Startup detects and reports missing or corrupt referenced media.
- Stale `IN_PROGRESS` tasks are recovered to a retryable state.
- Unrecoverable database corruption sets the service to storage-not-ready and
  never initializes a fresh database over corrupted evidence.

---

## Non-Blocking P2 Findings

The following items are not merge blockers but should be tracked for the next
milestone:

- **Unknown `/api/v1` routes return `index.html` with 200.**
  `apps/edge-service/src/assemblyvision_edge/api/app.py:130-143` applies the SPA
  fallback beneath `/api`; the test at `test_api_extended.py:111-116` codifies
  it. Return the standard API 404 problem there.
  *Solution:* Never apply SPA fallback under `/api`.

- **History cursors/filters do not implement the documented contract.**
  `apps/edge-service/src/assemblyvision_edge/api/routers/inspections.py:17-38`.
  Cursors are not bound to the normalized filter set, invalid cursors become 500,
  invalid decisions/timestamps are accepted as strings, and out-of-range limits
  silently reset.
  *Solution:* Validate typed enums/date-times/ranges at the boundary, bind the
  filter fingerprint in the opaque cursor, map failures to `400 INVALID_FILTER`.

- **Upload retry ignores eligibility, idempotency, reason, and state metadata.**
  `apps/edge-service/src/assemblyvision_edge/api/routers/uploads.py:53-64`;
  `repository.retry_upload` accepts any state, ignores `Idempotency-Key` and the
  reason, and does not update `updated_at`/`next_attempt_at`.
  *Solution:* Because the scheduler is out of M1 scope, remove/disable the
  mutation endpoint and UI action for now. When activated, persist key/reason,
  allow only eligible states, return `409 TASK_ACTIVE`, and update transition
  timestamps.

- **Media "streaming" loads the whole file and emits an invalid empty 416.**
  `apps/edge-service/src/assemblyvision_edge/api/routers/media.py:58-81`.
  *Solution:* Stream bounded chunks and raise a problem response with
  `Content-Range` retained.

- **Documented filters are omitted rather than rejected/implemented** for media
  kind, upload state/kind, and log level/component/time/cursor.
  *Solution:* Implement typed, indexed filters or stop claiming design 15.3
  conformance.

- **Unhandled 500 responses do not carry/propagate a request ID.**
  `apps/edge-service/src/assemblyvision_edge/api/app.py:41-49,121-127`.
  *Solution:* Generate/validate one request ID per request and include it in
  every problem and response header.

- **Inference provenance remains untyped and incomplete.**
  `packages/python/domain/src/assemblyvision_domain/models.py:263`,
  `pipeline.py:280-289`: `inference_metadata` is `dict[str, object]` and records
  settings only, not model name/version, per-inference timestamp, or stage
  latency. Required before claiming complete inference traceability
  (`docs/contracts/03-ai-rule-and-safety-contracts.md:30-43`).

- **Unresolved PR-003 verify gaps:** `verify --expected` still enables filename
  fallback (`cli.py:173-180`), and verification collapses identity to basename
  (`verify.py:191-212`). See `docs/reviews/PR-003-review.md:114-137`.

- **Rule version hashing does not enforce semantic immutability across releases.**
  Same `rule_id`/`rule_version` with different content is accepted
  (`rules/rule_engine.py:85-93`). Needs an installed-rule registry or collision
  rejection.

- **Crash-left staging bundles are ignored and never reconciled.**
  `output/writer.py:114-134`; in-process failures clean staging, but process
  termination bypasses the handler. Startup should quarantine/validate stale
  `.staging-*` directories.

- **Documentation overstates and contradicts the implementation:**
  `QUICKSTART.md:202-216` and `docs/ai/context.md:256-264,289-297,316-334`.
  Correction is required alongside the functional blockers (e.g. "switching to
  FastAPI requires no UI changes" is inaccurate; pause/resume described as
  implemented while it does not govern pipeline execution).

---

## Declared Out of Scope (tracked as next milestones, not blockers)

The following are explicitly listed in the PR description and `docs/ai/context.md`
as future work and were not treated as merge blockers:

- WebSocket runtime channel
- Upload queue scheduler with retry backoff and idempotency
- Camera and barcode hardware adapters
- Temporal aggregation
- Docker packaging
- PR-003 dataset staging and model-manifest full-content immutability
- Real-data baseline with X-AnyLabeling annotation and `adapt-xanylabeling.py`

## References

- `docs/contracts/01-architecture-boundaries.md`
- `docs/contracts/02-code-and-interface-contracts.md`
- `docs/contracts/03-ai-rule-and-safety-contracts.md`
- `docs/contracts/04-edge-storage-upload-contracts.md`
- `docs/contracts/05-data-api-and-versioning-contracts.md`
- `docs/contracts/08-security-permissions-and-audit.md`
- `docs/design/12-local-storage-and-retention.md`
- `docs/design/14-data-model-and-database.md`
- `docs/design/15-rest-api-and-events.md`
- `docs/design/16-edge-dashboard.md`
- `docs/design/decisions/ADR-006-rest-plus-websocket.md`
- `docs/reviews/PR-003-review.md`
