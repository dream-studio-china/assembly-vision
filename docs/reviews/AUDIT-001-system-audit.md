# AUDIT-001: System and Documentation Consistency Audit

## Scope

Read-only audit of the AssemblyVision repository (edge runtime, persistence,
API, frontend, training, scripts, and documentation), performed 2026-08-08.
This verification update was performed against the current worktree on
2026-08-09. No production code was changed by this update.

## Method

- Reviewed the governing safety, storage, data/API, security, and model-release
  contracts; design 11, 14, and 19; and ADR-011 and ADR-012.
- Inspected each cited current implementation and its related tests.
- A finding is retained only where the current code demonstrates the stated
  behavior or where the current documents demonstrably conflict. A struck item
  is not an open finding; its original evidence is stale, false, or based on an
  unsupported requirement.

## Resolution Status

The HIGH findings and reproduced MED findings remain open. Each retained item
below has a minimum implementation scope and strict acceptance criteria. The
shared closure gate for every behavioral change is:

```text
uv run ruff check .
uv run ruff format --check .
uv run mypy .
uv run pytest
```

Documentation-only changes must also pass `uv run mkdocs build --strict` when
the documentation environment is installed. A finding closes only when its
specific acceptance criteria and the applicable shared gate pass in CI.

## Overall Verdict

No evidence in this review contradicts the prior conclusion that the current
single-frame pipeline fails closed for ordinary invalid pipeline states. The
highest concrete risks are dataset-label fabrication, unusable published
training datasets, and a documented training command that can select the wrong
Ultralytics run directory. Several lower-severity robustness and contract gaps
remain. The M1 SQLite database is a rebuildable read projection, not the
contract-required authoritative inspection/outbox store; future scheduler and
authoritative-persistence work must not treat its current schema as fulfilling
that production contract.

---

## 3. HIGH Findings

### H1. Missing label files fabricate ground truth

- **Status:** OPEN, verified.
- **Evidence:** Both adapters use `[]` when `<image-stem>.txt` is absent
  (`adapt-roboflow-dataset.py:191`, `adapt-xanylabeling.py:231`). The result is
  interpreted as an explicit negative or an expected missing-component test
  sample. This contradicts design 19.17.3, which requires explicit empty label
  files and image/label pairing.
- **Required change:** Reject every missing label file in every supported split.
  Do not add an adapter opt-in unless its semantics, provenance, and downstream
  validation behavior are designed and documented; the minimal safe fix is
  rejection. Also reject duplicate image stems within a split before output
  writing, and normalize Roboflow's `valid` split to `val` if it is supported.
- **Acceptance:** Add parameterized tests for both adapters proving that a
  missing train, validation, or test label raises `ValueError`, leaves no output
  or staging directory, and does not write `test-expected.json`. Add tests for
  an explicit empty label (accepted), same-stem collision (rejected), and the
  documented `valid` layout (accepted only when normalized to `val`).

### H2. Published `data.yaml` references the removed staging directory

- **Status:** OPEN, verified.
- **Evidence:** The two adapters and `prepare_components.py:181-189` serialize
  absolute paths derived from their staging output, then atomically rename the
  staging directory. The published YAML therefore points to a non-existent
  directory.
- **Required change:** Write portable paths relative to the dataset YAML (for
  example `images/train` and `images/val`), or write final absolute paths only
  after publication. Use one documented convention in adapters, preparation,
  and the synthetic generator.
- **Acceptance:** For each adapter and component preparation, create a dataset,
  publish it, parse its `data.yaml`, resolve `train` and `val` according to the
  selected convention, and assert both directories exist under the final output
  root and contain the expected images. Assert no serialized value contains
  `.staging-`.

### H3. Relative `--out-weights` can select the wrong Ultralytics run path

- **Status:** OPEN, verified by current path construction.
- **Evidence:** `cli.py:226,313` passes a potentially relative
  `weights_path.parent / ".train-runs"`; `train.py:71-77` then assumes a
  fixed return path. This differs from the documented relative-path commands
  and can conflict with Ultralytics' handling of relative projects.
- **Required change:** Resolve the project directory before calling Ultralytics.
  Derive the returned weights path from the resolved project directory, verify
  it exists and is a regular file before `place_weights`, and raise a clear
  training error otherwise.
- **Acceptance:** Unit-test product and component CLI paths using a relative
  `--out-weights`, with `train_detector`/YOLO mocked, and assert the project is
  absolute and the expected `best.pt` is selected. Add a regression test for a
  missing returned artifact. Run one documented relative-path smoke command in
  CI only when its controlled training fixture is available.

### H4. `context.md` states PR #11 is open

- **Status:** ~~INVALID / STALE AUDIT EVIDENCE~~.
- **Reason:** `docs/ai/context.md:24,31,40` now states that PR #11 is merged,
  that there are no open PRs, and that `dev` is in sync with `main`. No change
  is required for this item.

---

## 4. MED Findings

### 4.1 Reproduced robustness and concurrency defects

| ID | Status and evidence | Required change | Strict acceptance |
|---|---|---|---|
| M1 | OPEN. `media_path_is_safe` catches `OSError` only (`reconcile.py:37-42`); `Path.resolve()` can raise `ValueError` for an embedded NUL. The startup scan therefore aborts instead of skipping the malformed bundle. | Treat `ValueError` raised during path construction/resolution as malformed media and skip that record. Keep errors from a single bundle isolated. | A reconciliation test containing a NUL-byte media path imports valid sibling bundles, skips the malformed bundle, returns the correct import count, and emits a warning without raising. |
| M2 | OPEN. `register_rule_identity` is a select-then-insert without an `IntegrityError` translation or retry (`repository.py:688-715`). | On a unique-race, re-read the stored hash in a new transaction: return successfully when equal and raise `RepositoryError` when different. Translate unexpected database errors. | A barrier-based multi-thread test registers the same identity/hash concurrently with no raw `IntegrityError`; a concurrent differing hash deterministically raises `RepositoryError` and leaves the original hash unchanged. |
| M3 | OPEN. `EdgeRepository.open()` always calls the process-unsafe Alembic runner for the same new path (`repository.py:155-167`, `migrate.py:17-29`). | Serialize first-open migration with an interprocess lock or explicitly reject concurrent first-open before creating the engine. Define the behavior in the M1 boundary documentation. | A multi-process test opening the same fresh database completes without Alembic `KeyError`, leaves exactly the head revision, enables the required SQLite pragmas, and both repositories can perform a read/write projection operation. |

### 4.2 Rule engine fail-safe gaps

- **Status:** OPEN, verified.
- **Evidence:** `_spatial_violation` does not reject non-finite ratios or
  centers (`rule_engine.py:110-123`); comparisons with `NaN` are false. Also,
  `PRESENT` evidence is accepted without a usable frame, confidence, or
  supporting frame (`147-168`). This violates contract 03.5's prohibition on
  `OK` from incomplete result data/no usable frames and design 11.2's evidence
  requirement.
- **Required change:** Explicitly reject non-finite geometry. Before a PRESENT
  component can satisfy a requirement, require `usable_frame_count >= 1`, a
  finite `best_confidence`, a non-empty supporting-frame list, and coherent
  detection/supporting-frame counts. Decide and document whether every
  detection needs geometry when no spatial constraint is declared.
- **Acceptance:** Table-driven tests inject `NaN`, `inf`, zero usable frames,
  absent/non-finite confidence, and empty supporting IDs into otherwise-valid
  evidence. Every case returns business `NG` with a stable reason code; no test
  may obtain `OK` from incomplete evidence. Existing valid evidence must still
  return `OK`.

### 4.3 Manifest validation gaps

- **Status:** OPEN, verified.
- **Evidence:** `runtime` is not constrained before detector construction;
  `verify_manifest_artifact` rejects only leading slash/backslash and permits
  traversal or URI-like artifact paths; `verify_model_class_map` assumes
  contiguous mapping keys and can leak `KeyError`.
- **Required change:** Require `runtime == "ultralytics"` at the manifest
  loading boundary, reject non-file URI schemes and `..` path parts, resolve
  the artifact and require containment below the manifest directory, and
  translate malformed/non-contiguous class maps to `ConfigError`.
- **Acceptance:** Tests reject `runtime="other"`, `../weights.pt`, encoded or
  scheme URI forms accepted by the path parser, symlink escape, and a
  non-contiguous `{1: "component"}` map with `ConfigError`. A valid relative
  artifact and contiguous mapping continue to load and checksum-verify.

### 4.4 Persistence and contract boundary

- **Status:** OPEN as documentation/roadmap debt; not a claim that M1 already
  implements the production outbox.
- **Evidence:** The current projection schema lacks the uniqueness constraints,
  product-configuration column, and upload leases specified by design 14 and
  contracts 04/05. `pipeline.py:303-305` creates a `ProductResolution` without
  `product_version_id`. `upsert_inspection` remains check-then-insert, although
  its outer `IntegrityError` translation prevents raw SQLAlchemy leakage.
- **Required change:** First update design 14 to distinguish the M1 rebuildable
  projection from the future authoritative store. Before any upload scheduler
  or multi-writer deployment, add an Alembic migration for the authoritative
  schema, persist a non-null governed product-configuration version, and make
  equal-content concurrent inspection upserts idempotently return `unchanged`.
- **Acceptance:** The boundary document names the projection's non-authoritative
  limitations. Authoritative-store tests verify all contract 04/05 constraints,
  lease fields, product version traceability, and concurrent equal-content
  upserts returning `unchanged`; differing content must fail without mutation.

### 4.5 API and frontend hardening

| Finding | Status | Required change and acceptance |
|---|---|---|
| Non-loopback service without token | OPEN hardening gap. ADR-012 permits explicit M1 development mode but says it is not production authentication. | Fail startup for non-loopback bind without a token, or require an explicit development override that logs a high-severity warning. Test loopback/dev, non-loopback/rejected, and non-loopback/explicit override paths. |
| Authenticated log endpoint exposes exception messages/paths | OPEN. `LogBuffer` stores `record.getMessage()` and the global handler captures `log.exception` output. | Exclude traceback/absolute paths from viewer records or restrict the endpoint to a later privileged role. Test that an induced exception produces no traceback or absolute path in `/logs`. |
| Session exchange lacks throttling and session storage has no sweep/cap | OPEN hardening gap. | Add bounded per-source failed-attempt throttling and bounded session storage with expiry sweeping; document M1 limits. Test repeated failures, successful exchange after cooldown, expiry cleanup, and capacity behavior. |
| Cursor errors and filter binding | OPEN. Invalid cursor becomes a generic repository failure, and cursors contain no filter fingerprint. | Map malformed cursors to `400 INVALID_CURSOR`; bind a cursor to a canonical filter hash. Tests must reject malformed/mismatched cursors without 500 and preserve stable pagination for matching filters. |
| PURGED media can be streamed if its file remains | OPEN. `media.py:110-114` checks the file before lifecycle. | Check `PURGED` first and always return `410 MEDIA_PURGED`. Add a test with a surviving file. |
| Non-ASCII bearer header can raise from `compare_digest` | OPEN. | Treat comparison type/encoding failure as an invalid credential and return `401`. Add an API test with non-ASCII authorization input. |
| `/api` may fall through to the SPA | OPEN. The guard only matches `api/`. | Reserve both `api` and `api/` before SPA fallback. Test `/api`, `/api/unknown`, and a normal client-side route. |
| Bearer token may be sent to arbitrary media URL | OPEN. `loadMediaBlobUrl` accepts any URL. | Require the media URL's origin to equal the configured HTTP API origin before attaching a token. Test same-origin/API-origin allowed and foreign origin rejected with no request. |
| Production bundle can silently select mock mode | OPEN. `VITE_API_MODE` defaults to mock and no build-time enforcement is present. | Make production builds fail unless the mode is exactly `http`; preserve explicit mock development mode. Add build/config tests for unset, invalid, mock-dev, and http-production modes. |
| Missing CSP | OPEN hardening gap. | Add a least-privilege CSP compatible with the locally served dashboard and test the response header. |
| Live view, WebSocket gap, line filter, shallow record validation | OPEN/PARTIAL. `LiveView.vue` exists but `/live` routes to `LiveInspection.vue`; the backend explicitly rejects line filtering; websocket code does not detect sequence gaps; record validation does not validate nested values read by UI. | Route the real live page or clearly remove/defer it; either remove the unsupported line control in HTTP mode or persist line identity; emit/refetch on `sequence > previous + 1`; validate nested consumed fields. Add component/API tests for each selected behavior. |
| ~~CRLF injection through reflected `X-Request-ID`~~ | ~~INVALID as stated.~~ HTTP servers reject CR/LF in request headers before this application receives the value; the audit did not establish an exploitable CRLF path. | No CRLF-specific fix is required. A separate correlation-ID format/length policy may still be adopted for observability. |
| ~~WebSocket sequence must reset on reconnect~~ | ~~INVALID.~~ Design 14.4.1 requires sequence reset only when source identity changes, not on reconnect. | Retain the separate missing-gap-signal finding above. |

---

## 5. Stress-Test Record

The original dynamic observations remain historical evidence, not proof that
the current worktree has been fixed:

| Test | Recorded result | Current audit status |
|---|---|---|
| Reconcile 3000 bundles | 7.6 s, 4.8 MB database | Informational; rerun after reconciliation changes. |
| 200 concurrent HTTP GETs | 200/200 success | Informational; does not exercise concurrent migration or write races. |
| NUL-byte media path | Startup crash | Retained as M1. |
| Concurrent rule registration | Raw `IntegrityError` | Retained as M2. |
| Concurrent first migration | Alembic `KeyError` | Retained as M3. |

---

## 6. Documentation and Tooling Consistency

| Finding | Status | Required change and acceptance |
|---|---|---|
| Design 14 describes an authoritative operational SQLite store rather than the M1 rebuildable projection | OPEN. | Update scope, tables, and recovery language; link the authoritative-store design as future work. Review against ADR-012 and context section 8.3. |
| Appendix reason-code glossary and design 11.5 omit/contradict emitted codes | OPEN. | Make `reason_codes.py` the explicit canonical list or generate the glossary from it. A test must compare all declared static codes and documented parameterized prefixes. |
| Coverage claims | PARTIAL. `context.md` currently says approximately 99.5%, so its claimed 99.6% discrepancy is ~~STALE~~; PR review claims still require source-based verification. | Replace numeric claims with a dated command/output reference or update all sources from one CI artifact. |
| Vitest count in `context.md` | ~~INVALID / STALE~~. `context.md:295-297` already records 63 tests (30 + 13 + 17 + 3). | No change required for this item. |
| README/QUICKSTART branch comments and SECURITY supported versions | OPEN. | Update merged-branch/release statements from current Git state. Validate all branch/PR assertions against `git branch -a` and GitHub before publication. |
| Runbook 10 requires `feat/mvp` | OPEN. | Replace with the supported `main`/current development workflow and test every documented command in a clean checkout. |
| Design 19.17.4/runbook 11/QUICKSTART claim strict pairing and usable adapter YAML | OPEN, dependent on H1/H2. | Update only after H1/H2 acceptance passes; documentation must describe the final behavior exactly. |
| Synthetic generator has rotated-drawing/label mismatch and unreachable chip/diode missing scenarios | OPEN. | Correct the rotation transform and scenario schedule. Add deterministic image/label geometry tests and assert every missing scenario occurs for a representative training count. |
| Documented pipeline keys are rejected by configuration loader | OPEN, verified by absence from current config implementation. | Either implement and test each documented key with fail-safe semantics, or remove/defer it from design 06/08/09. No documented accepted key may be rejected as unknown. |
| Manifest provenance omits reproducibility data required by design 19.8 | OPEN. | Extend manifest/run metadata with immutable dataset/split references, seed, epochs, augmentations, framework/environment versions, and checksums. Test a training invocation produces all required values. |
| Contract 10 example does not match `ModelManifest` | ~~INVALID as a schema violation.~~ Contract 10 says a manifest "similar to" the example; it is not an exact schema declaration. | Improve the example or link it to the canonical schema as documentation quality work, not a contract breach. |
| `--allow-missing-labels` marker is not read on later runs | ~~NOT AN ESTABLISHED DEFECT~~. The flag is a per-invocation legacy opt-in; recording it is provenance, not a documented persistent authorization. | If persistent authorization is desired, create a separate ADR/contract and validation design; otherwise clarify the help text. |
| QUICKSTART calls live configuration/log views placeholders and conflates derived endpoints with design 15.3 | OPEN. | Correct the endpoint descriptions and scope labels. Add a documentation link check and an API smoke test matching the published endpoint table. |

## 7. Closure Order

1. H1, H2, and H3: they block a trustworthy documented train-and-inspect loop.
2. M1, M2, M3, rule-engine evidence validation, and manifest containment:
   they are direct robustness or fail-safe defects.
3. Resolve the M1 projection versus authoritative-persistence boundary before
   implementing the upload scheduler, WebSocket runtime, or multi-edge hosting.
4. Complete documentation and tooling corrections only after the behavior they
   describe has passed its specific acceptance criteria.
