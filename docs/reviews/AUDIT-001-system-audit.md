# AUDIT-001: System and Documentation Consistency Audit

## Scope

Read-only audit of the AssemblyVision repository (edge runtime, persistence,
API, frontend, training, scripts, docs) for vulnerabilities and
documentation-vs-code inconsistencies, plus dynamic stress testing. Performed
2026-08-08 to prepare the next development milestone. No files were modified
during the audit; findings are recorded here for tracking.

## Method

- 12 parallel read-only sub-agent audits across: rule engine/config, edge API,
  persistence, output/media, pipeline/detectors, verify/CLI, training,
  scripts, frontend, doc-consistency sweep, security, and API contract chain.
- Dynamic stress tests executed locally (real HTTP load, concurrency, crafted
  inputs, large-volume reconciliation). Results in section 5.

## Resolution Status

Findings below are open. The next milestone should close the HIGH items
(section 3) and the reproduced MED items (section 4) first; DOC items
(section 6) should be aligned when their related code changes.

## Overall Verdict

No exploitable HIGH-severity runtime vulnerability was found: no path can
produce `OK` from incomplete or invalid evidence (the fail-safe decision
invariants hold), no secrets exist in tracked files or history, and SQL
injection, command injection, path traversal, and symlink escapes are clean.
The real HTTP read path is robust under load (200 concurrent requests, 2.8 s,
all 200). The main risks are data-integrity defects in the dataset adapters
and training CLI (HIGH), concurrency/robustness defects in persistence and
reconciliation (MED, reproduced), and broad documentation drift.

---

## 3. HIGH Findings (data integrity / broken documented flows)

### H1. Adapters treat a missing label file as an empty annotation (fabricated ground truth)

- **Location:** `scripts/adapt-roboflow-dataset.py:191`,
  `scripts/adapt-xanylabeling.py:231` (and downstream branches).
- **Finding:** A missing label file is parsed as `[]`, so the image becomes a
  background negative in `dataset_product` and an all-components-missing
  sample in `dataset_components` (and an expected-NG entry in
  `test-expected.json`). This is exactly the "fabricated missing-component
  ground truth" the scripts' own docstrings warn about.
- **Doc conflict:** design 19.17.3 / runbook 11 step 8 / QUICKSTART 4.2.1 claim
  the adapters enforce image/label pairing ("missing label files fail
  validation unless the recorded `--allow-missing-labels` legacy opt-in is
  used").
- **Fix (proposal):** raise `ValueError` on a missing label file, or require
  an explicit `--allow-missing-labels` opt-in mirrored from
  `validate_dataset`; add tests for both adapters.

### H2. Published `data.yaml` files contain stale staging-directory paths

- **Location:** `training/src/assemblyvision_training/prepare_components.py:181-189`
  (with staging rename at 56-63); `scripts/adapt-roboflow-dataset.py` and
  `scripts/adapt-xanylabeling.py` `_data()` writers.
- **Finding:** `train`/`val` paths are written as absolute paths into the
  sibling `.staging-<uuid>/` directory; after `staging_dir.rename(output_dir)`
  the published `data.yaml` points at a directory that no longer exists.
  `validate_dataset` passes (it uses the directory layout), so the defect is
  silent until training (`av-train component` / `av-train product` on the
  adapter output fails). Not covered by tests.
- **Fix (proposal):** write relative paths (`images/train`) or rewrite
  `data.yaml` with the final paths after the rename; add a test that reloads
  the published `data.yaml`.

### H3. `av-train` relative `--out-weights` triggers Ultralytics `runs/detect/` nesting

- **Location:** `training/src/assemblyvision_training/cli.py:226,313` +
  `training/src/assemblyvision_training/train.py:55-78`.
- **Finding:** `project_dir = weights_path.parent / ".train-runs"` is relative
  when `--out-weights` is relative (every documented command in runbook 10 /
  QUICKSTART 4.3). Ultralytics 8.4.115 prepends `<runs_dir>/detect/` to
  relative projects, so `train_detector` looks in the wrong path and raises
  `FileNotFoundError` (reproduced during the audit session). `e2e-demo.sh`
  uses absolute paths, so CI/demo passes while documented user commands fail.
- **Fix (proposal):** resolve `project_dir` to an absolute path in
  `cli.py` and assert the returned best path exists before placing it.

### H4. `docs/ai/context.md` states PR #11 is open; it is merged

- **Location:** `docs/ai/context.md:41` (and section 1).
- **Finding:** PR #11 (dev -> main) is MERGED; there are no open PRs. The
  context snapshot is stale.
- **Fix (proposal):** rewrite in past tense and list PRs #3-#11 as merged.

---

## 4. MED Findings

### 4.1 Reproduced dynamically

| # | Finding | Location | Evidence |
|---|---|---|---|
| M1 | Reconciliation crashes on a media path containing a NUL byte (`ValueError: lstat: embedded null character`), aborting the whole startup scan despite the "corrupt files are skipped" contract. | `persistence/reconcile.py:42,95` | Reproduced: `ValueError` uncaught. |
| M2 | Concurrent `register_rule_identity` with the same `(rule_id, rule_version)` raises a raw SQLAlchemy `IntegrityError` (not `ConfigError`/`RepositoryError`), crashing parallel `inspect` runs. | `persistence/repository.py:681-715` | Reproduced: 2 `IntegrityError` across 8 threads. |
| M3 | Concurrent first-open/migration of the same new SQLite file races in Alembic (`KeyError: 'config'`). Relevant to multi-instance per-host or parallel CLI runs on one output root. | `persistence/repository.py:164`, `persistence/migrate.py:17-29` | Reproduced during API concurrency test noise. |

### 4.2 Rule engine (crafted-input defense in depth)

- **NaN spatial evasion:** `rule_engine.py:113-117` - `NaN` in
  `box_area_ratios` makes both `ratio < min` and `ratio > max` false, so
  `_spatial_violation` returns False and a crafted PRESENT component passes,
  yielding `OK`. Contradicts the function docstring. Fix: reject non-finite
  ratios/centers.
- **Incomplete PRESENT evidence:** `rule_engine.py:147-167` - `PRESENT`
  evidence with `usable_frame_count=0`, `best_confidence=None`, or empty
  `supporting_frame_ids` yields `OK`. Not reachable from the current
  single-frame pipeline, but the engine is the documented decision authority.
  Fix: require `usable_frame_count >= 1` (and confidence present) in the
  PRESENT branch.

### 4.3 Manifest loading (`packages/python/vision-core/src/assemblyvision_vision/manifests.py`)

- `runtime` field never validated (`product_detector.py:45-51`,
  `component_detector.py:31-37`); any runtime string loads through
  Ultralytics. Fix: assert `runtime == "ultralytics"`.
- `verify_manifest_artifact` rejects only leading `/`/`\`; `../` segments and
  scheme URIs resolve outside the manifest directory. Fix: reject `..` and
  schemes; resolve + containment check.
- `verify_model_class_map` assumes contiguous keys; a non-contiguous
  `model.names` raises an uncaught `KeyError` at startup. Fix: wrap and raise
  `ConfigError`.

### 4.4 Persistence / contracts

- Schema has no `UNIQUE` constraints (C2): `UNIQUE(device_id, device_sequence)`,
  `UNIQUE(inspection_id, component_code)`, `UNIQUE(relative_path)`,
  `UNIQUE(device_id, idempotency_key)` all absent; `upload_tasks` lacks lease
  fields. Application-level checks partially cover single-writer M1.
- Contract 05 requires a product-configuration version on every inspection;
  the pipeline builds `ProductResolution` without `product_version_id` and the
  schema has no such column (silently unmet, C3).
- `upsert_inspection` idempotency is check-then-insert (TOCTOU); concurrent
  writers of the same new ID get `RepositoryError` instead of `unchanged`.

### 4.5 Security / API

- `serve --host 0.0.0.0` without `--api-token` disables auth entirely
  (loopback-only is the default, but non-loopback bind is a misconfiguration
  hazard). Fix: fail startup when host is non-loopback and no token is set.
- `GET /api/v1/logs` serves INFO logs including `log.exception` stack traces
  and filesystem paths to any authenticated viewer (violates SECURITY.md).
- `POST /auth/session` has no rate limiting / lockout; distinguishable
  204/401 responses enable brute force if exposed beyond loopback.
- `X-Request-ID` is reflected verbatim (CRLF injection risk); validate and
  fall back to a generated UUID.
- Cursor not bound to the filter set (`repository.py:462-468`); malformed
  cursor raises `RepositoryError` -> generic 500 instead of `400
  INVALID_CURSOR`.
- `410 MEDIA_PURGED` only triggers when the file is already gone; a PURGED
  record whose file still exists streams 200 (`media.py:110-115`).
- `viewer_sessions` dict grows unbounded (no cap/sweep).
- Auth `compare_digest` raises `TypeError` on non-ASCII `Authorization`
  header -> 500 instead of 401.
- SPA fallback check `startswith("api/")` lets `GET /api` serve `index.html`.
- Frontend: `loadMediaBlobUrl` attaches the bearer token to any supplied URL
  (origin not validated); `VITE_API_MODE` is fail-open in production (mock
  default); no CSP; `/live` routed to a component that never loads real data
  while the working `LiveView.vue` is unrouted; WebSocket sequence not reset
  on reconnect and no gap signal; statistics `line` filter always 400 in real
  mode; `validateInspectionRecord` validates only top-level fields.

---

## 5. Stress Test Results

Executed read-only (writes only under `/tmp/av-stress`):

| Test | Result |
|---|---|
| Reconcile 3000 inspection bundles | 7.6 s, DB 4.8 MB, no memory leak |
| 200 concurrent HTTP GETs (uvicorn + httpx, auth token) | 2.8 s, 200/200 OK, zero errors |
| Reconcile with NUL-byte media path | Crash reproduced (M1) |
| Concurrent `register_rule_identity` (8 threads) | `IntegrityError` reproduced (M2) |
| Concurrent first migration of one SQLite file | Alembic `KeyError: 'config'` reproduced (M3) |

---

## 6. Documentation Inconsistencies (LOW/DOC)

- **design 14** has not been updated to the M1 boundary: labels SQLite an
  "operational store" (14.1) and documents authoritative schema
  (`rule_installations` table, unique constraints, lease fields, `UploadTask`
  with `lease_owner`/`lease_expires_at`) that the implementation does not
  have; the implementation uses `rule_identities` and no unique constraints.
- **appendices.md section 4** reason-code glossary uses a different code set
  than `reason_codes.py`; design 11.5 omits codes the engine emits
  (`COMPONENT_SPATIAL_INVALID`, `PRODUCT_IDENTITY_UNVERIFIED`, `GATE_FAILED:*`,
  `RULE_EVALUATION_ERROR`).
- **Coverage claims:** PR-008-review "100% coverage" and context.md "99.6%"
  vs measured ~99.5% statement coverage (specific uncovered lines differ from
  the claimed two).
- **Vitest counts:** context.md says 56 (28+13+12+3); current is 63
  (30+13+17+3).
- **README/QUICKSTART** `git checkout dev` comments ("main = released MVP;
  dev = in-progress") are stale; dev is fully merged into main.
- **SECURITY.md Supported Versions** table omits merged PRs #9-#11.
- **runbook 10** precondition says "checked-out `feat/mvp` workspace" - should
  be `dev`/`main`.
- **design 19.17.4 / runbook 11 / QUICKSTART 4.2.1** claim the adapters
  enforce pairing and produce usable `data.yaml` - not implemented (H1, H2).
- **generate-synthetic-dataset.py:** y-coordinate rotation bug displaces
  drawn components from their labels; chip/diode missing scenarios are
  unreachable in training (`i % 4 == 0` gate vs 16-entry schedule); rotated
  drawing vs unrotated axis-aligned label boxes.
- **config schema:** documented keys in design 06/08/09
  (`pipeline.max_inflight_inspections`, per-component
  `high_confidence`/`expected_count`/`allowed_zone`, product
  `allowed_classes`/`max_inspectable_products`) are rejected as unknown keys
  by `load_pipeline_config`.
- **manifest provenance:** `datasets=[]`, `source_revision="av-train"`,
  `training_config_revision=semver` - no epochs/seed/augmentation/dataset
  checksum recorded (design 19.8).
- **contract 10 example manifest** does not match the actual `ModelManifest`
  schema.
- **`--allow-missing-labels` opt-in** recorded in data.yaml is never read
  back; a later run without the flag fails again.
- **QUICKSTART:** `/configuration` `/logs` described as "placeholders" but
  they render real data; "endpoints follow design 15.3" list includes derived
  endpoints not in 15.3.

---

## 7. Next Steps

Phase 1 (close HIGH + reproduced MED, each with regression tests):

1. H1 - adapters: missing label file -> error (or recorded opt-in); Roboflow
   `valid` -> `val` alias; same-stem collision detection.
2. H2 - rewrite `data.yaml` paths relative after atomic rename in both
   adapters and `prepare_components`.
3. H3 - absolute `project_dir` in `av-train` + best.pt existence assertion.
4. M1/M2/M3 - reconcile error handling (`OSError, ValueError, RuntimeError`);
   `register_rule_identity` `IntegrityError` handling; serialize first-open
   migration (or document single-writer).
5. Rule engine - non-finite spatial values; PRESENT evidence completeness.
6. Manifest - runtime validation; `..`/scheme URI rejection; class-map
   tolerance.

Phase 2 (documentation alignment): design 14 M1 boundary, appendices reason
codes, coverage/test-count claims, PR state in context.md, SECURITY.md
versions, runbook 10 precondition, QUICKSTART corrections.

Phase 3 (architecture): decide the multi-edge-per-host "shared" model
(container-per-line vs shared inference) before building the upload
scheduler, WebSocket channel, camera/barcode adapters, and temporal
aggregation.
