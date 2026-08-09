# PR-020 Review: Retention and Disk Safety (E2)

## 1. Review Decision

**Status: RESOLVED**

PR #20 establishes the right overall structure: durable retention metadata,
receipt-gated selection, cleanup worker, storage observability, and startup
integrity scanning. The initial review found one P0 and several P1 gaps; all
findings are now fixed and covered by regression tests
(`apps/edge-service/tests/test_pr020_review_fixes.py` and updated suites).
Customer/site decisions in the E2 task remain production-enablement blockers
even after code findings are resolved.

## 2. Scope and Evidence

Reviewed commits:

```text
f596832 feat(edge): durable retention state and receipt-gated eligibility (E2a)
00fb3e4 feat(edge): retention cleanup worker with fenced deletion (E2b)
88a506c feat(edge): storage pressure policy and fail-safe runtime (E2c)
12069ee feat(edge): startup integrity scan, quarantine, and fail-closed checks (E2d)
803e0ef docs: add E2 retention and disk-safety delivery task
```

Primary requirements:

- [E2 retention and disk-safety task](../tasks/E2-retention-and-disk-safety.md)
  sections 3, 5, 6, and 7.
- [Local Storage and Retention](../design/12-local-storage-and-retention.md)
  sections 12.4, 12.7, and 12.8.
- [Contract 04: Edge, Storage, and Upload](../contracts/04-edge-storage-upload-contracts.md)
  sections 3, 6, 7, and 8.
- [Contract 03: Fail-Safe](../contracts/03-ai-rule-and-safety-contracts.md)
  section 5.
- [Contract 06: Testing, Quality, and CI](../contracts/06-testing-quality-and-ci-contracts.md).

Local checks previously run by the PR author pass: Ruff, MyPy, Pytest (766),
MkDocs strict build, pnpm build/lint/test, and 12 Playwright tests. Those
checks do not exercise the race and crash boundaries described below. GitHub
CI was still running when this review was started.

## 3. Required Findings

### PR20-F01 - P0: Projection Failure Can Publish an Unrecorded `OK`

**References**

- `apps/edge-service/src/assemblyvision_edge/api/state.py:290-310`
- `apps/edge-service/src/assemblyvision_edge/api/state.py:337-359`

**Problem**

The inspection loop assigns `runtime.last_result` from the record before
calling `_persist_projection()`. `_persist_projection()` catches every
repository failure, logs it, and returns. Therefore an `OK` may be exposed to
runtime consumers even when the SQLite projection/outbox did not commit. A
database error can also be wrapped by SQLAlchemy and bypass the narrow
`isinstance(exc, OSError)` storage-fault check.

This violates E2 invariant 7 and Contract 03: a result must not become an
operational `OK` when complete auditable persistence is unavailable.

**Failure scenario**

1. `inspect_frame()` writes/returns an `OK` record.
2. `runtime.last_result` becomes `OK`.
3. SQLite commit fails because the volume is read-only, full, locked beyond
   recovery, or returns a wrapped database I/O error.
4. `_persist_projection()` logs the failure and returns; no durable outbox
   exists, while callers can still observe the `OK`.

**Required solution**

1. Make successful durable projection/outbox persistence a prerequisite for
   publishing `last_result` or any physical/business `OK` signal.
2. Let `_persist_projection()` return a typed success/failure outcome instead
   of swallowing the error. Preserve the original exception internally for
   logs/diagnostics without exposing a stack trace through the API.
3. Convert every persistence failure to a latched storage/admission fault.
   Handle SQLite/SQLAlchemy operational errors as well as raw `ENOSPC`,
   `EROFS`, and `EIO`.
4. Stop/drain product intake until an explicit successful mandatory-persistence
   recovery probe or governed operator recovery clears the fault.

**Acceptance criteria**

- A fault-injection test for raw `ENOSPC`, raw `EROFS`, SQLite/SQLAlchemy write
  error, and outbox transaction failure proves that `last_result` is not `OK`,
  no result is published as `OK`, and `inspection_ready` becomes false.
- A failing `persist_inspection_and_enqueue_uploads()` leaves no partial
  inspection/outbox rows and latches a stable storage fault alert.
- A successful mandatory write after the documented recovery procedure is the
  only supported path that restores admission.

### PR20-F02 - P1: Expired Cleanup Holder Can Unlink Before Fencing Is Checked

**References**

- `apps/edge-service/src/assemblyvision_edge/retention/worker.py:128-187`
- `apps/edge-service/src/assemblyvision_edge/persistence/repository.py`
  `claim_retention_batch()` and `finalize_media_purge()`.

**Problem**

The worker verifies the fencing token only in the terminal database transition,
after `path.unlink()`. If worker A stalls past its lease, worker B reclaims the
artifact, and A resumes, A can still delete the file. A then loses finalization;
B encounters a missing file and records an integrity fault. Evidence was
deleted without a matching `PURGED` audit transition.

This violates E2 invariants 4 and 5.

**Required solution**

1. Add a fenced `confirm_or_renew_retention_claim()` compare-and-set operation
   immediately before destructive I/O. It must require the current owner,
   `AVAILABLE` lifecycle, no hold/fault, and an unexpired lease.
2. Use the returned renewed deadline for finalization and failure transitions.
   Do not use the batch-start timestamp for all files in a batch.
3. Size/retry lease duration so the worker can renew before a slow filesystem
   operation, and stop processing when renewal fails.

**Acceptance criteria**

- Deterministic two-worker test: A claims and pauses past expiry; B reclaims;
  A resumes. Assert A never calls unlink and B alone performs the `PURGED`
  transition.
- A lease expired between path validation and destructive I/O is rejected
  without changing the file or row.
- Audit state remains either validly `PURGED` by the current owner or
  `AVAILABLE`/faulted with the original evidence intact; never missing with no
  corresponding authoritative transition.

### PR20-F03 - P1: Post-Claim Hold or Integrity Fault Does Not Cancel Deletion

**References**

- `apps/edge-service/src/assemblyvision_edge/retention/worker.py:144-187`
- `apps/edge-service/src/assemblyvision_edge/persistence/repository.py`
  `finalize_media_purge()`.

**Problem**

Eligibility is evaluated at claim time only. A hold, acceptance lock,
human-review lock, or integrity fault applied after the claim does not invalidate
the active claim. Finalization checks ownership/expiry only. The worker can
unlink and mark `PURGED` evidence that became protected between claim and
deletion.

This violates E2 invariant 3.

**Required solution**

1. Make every hold/fault update atomically clear or invalidate an active
deletion claim.
2. Revalidate the full eligibility predicate atomically as part of the
pre-unlink claim confirmation/renewal from F02: lifecycle, hold state,
integrity status, deadline, inspection synchronization, verified media receipt,
and current fencing token.
3. Repeat the fenced eligibility check in finalization so a concurrent hold or
fault cannot turn a deleted file into `PURGED` after protection was applied.

**Acceptance criteria**

- Claim an artifact, then apply a review/acceptance hold before processing;
  assert no unlink and no `PURGED` transition.
- Repeat with an integrity fault applied before processing; assert no unlink,
  durable `FAULT`, and no future eligibility.
- Race test proves a hold/fault and a worker terminal transition cannot both
  succeed for the same artifact.

### PR20-F04 - P1: Path Validation Has a Symlink TOCTOU Window

**References**

- `apps/edge-service/src/assemblyvision_edge/retention/worker.py:146-163`
- `apps/edge-service/src/assemblyvision_edge/retention/worker.py:201-220`

**Problem**

`_resolve_path()` checks a resolved path inside the output root, but returns the
original unresolved pathname. A concurrent process can replace an intermediate
bundle directory with a symlink after validation and before `path.unlink()`.
The later unlink is authorized by an earlier resolution and can remove a file
outside the trusted inspection bundle.

This violates E2 invariant 9.

**Required solution**

1. Perform traversal and unlink relative to trusted directory file descriptors
   using no-follow semantics, where the target platform supports it.
2. Open the output root/bundle directory as trusted descriptors and reject
   symlink components during traversal; unlink only the final basename through
   the trusted parent descriptor.
3. If the deployment platform lacks required no-follow primitives, disable
   cleanup rather than claim path safety from a race-prone pathname check.

**Acceptance criteria**

- Test replaces an intermediate bundle directory with a symlink between
  validation and deletion; no external file is removed and the media row is
  faulted/protected.
- Traversal, absolute path, final-file symlink, and intermediate-directory
  symlink cases all prove cleanup stays inside the intended bundle.

### PR20-F05 - P1: Storage Write Fault Is Cleared by a Successful Stat Call

**References**

- `apps/edge-service/src/assemblyvision_edge/api/state.py:327-335`
- `apps/edge-service/src/assemblyvision_edge/api/state.py:380-393`

**Problem**

`_note_storage_write_fault()` sets `storage_write_fault` on a qualifying I/O
error, but every later successful `refresh_storage()` unconditionally sets it
to false. A transient full/read-only/database write failure can therefore clear
when `statvfs` works, without proving that mandatory output and SQLite/outbox
persistence have recovered.

**Required solution**

1. Treat write faults as latched admission faults.
2. Clear the latch only through an explicit recovery path that performs a
mandatory-persistence probe (atomic media/bundle and SQLite/outbox write) and
records the recovery event, or through an audited operator action whose policy
requires the same probe.
3. Keep volume observation separate from write health; a readable filesystem is
not evidence that it is writable.

**Acceptance criteria**

- Inject a storage/database write failure, then simulate successful
  `disk_usage`/`statvfs`; assert `inspection_ready` remains false and
  `STORAGE_WRITE_FAULT` remains present.
- A successful storage observation alone cannot clear the latch.
- Only the documented persistence recovery probe clears the fault and resumes
  intake.

### PR20-F06 - P1: Exact Threshold Values Enter the Less Severe Mode

**References**

- `apps/edge-service/src/assemblyvision_edge/retention/storage.py:71-77`

**Problem**

The implementation uses `<` while the E2 task and design specify action “at
or below” the warning, critical, and stop thresholds. Exactly 5%, 10%, or 20%
free remains in the less severe mode. At exactly the configured stop reserve,
new product intake can continue.

**Required solution**

Use `<=` for byte and inode pressure comparisons. Document any hysteresis
separately; it cannot silently redefine threshold entry semantics.

**Acceptance criteria**

- Parameterized tests prove exact warning, critical, and stop boundaries for
  both free-byte and free-inode percentages.
- At exactly the stop threshold, status is `STOP`, `inspection_ready=false`,
  and the inspection loop rejects/drains new frames.

### PR20-F07 - P1: Critical Mode Does Not Suppress Optional Capture

**References**

- `apps/edge-service/src/assemblyvision_edge/api/state.py:254-313`
- `apps/edge-service/src/assemblyvision_edge/retention/storage.py:71-77`

**Problem**

Only `STOP` changes inspection-loop behavior. At `CRITICAL`, every pipeline
still receives the normal `OutputWriter`, so optional full-video/OK-media
capture keeps consuming the constrained volume. This does not meet design
12.7 or E2c’s required critical-mode degradation.

**Required solution**

1. Define typed capture-policy classes that label artifacts as mandatory or
   optional by outcome/media kind.
2. Pass the current storage mode to the output/capture boundary. At critical,
   suppress only explicitly optional output; preserve mandatory metadata and NG
   evidence.
3. Record the suppression decision and reason in the inspection evidence or
   device event without misrepresenting omitted optional media as captured.

**Acceptance criteria**

- At `CRITICAL`, test that configured optional OK/rolling-video artifacts are
  not written while mandatory metadata and NG evidence persist.
- At `WARNING`, behavior remains normal apart from eligible cleanup request.
- At `STOP`, no new product is inspected or emitted as `OK`.

### PR20-F08 - P1: Startup Integrity Faults Do Not Gate Readiness or Emit an Alert

**References**

- `apps/edge-service/src/assemblyvision_edge/api/app.py:86-104`
- `apps/edge-service/src/assemblyvision_edge/api/state.py:438-476`

**Problem**

Startup scanning persists `integrity_status='FAULT'` and logs a warning, but it
does not latch runtime storage-not-ready, add a stable integrity alert, or stop
new inspection admission. A pipeline can advertise `inspection_ready=true`

**Required solution**

1. Propagate a nonzero startup integrity report into a durable runtime storage
   fault with a stable `STORAGE_INTEGRITY_FAULT` alert and count/details safe
   for the authenticated device-status API.
2. Gate intake/readiness until documented reconciliation resolves the affected
   mandatory evidence, or establish an explicit policy distinguishing historic
   evidence faults from current mandatory-persistence readiness.
3. Persist a device event with stable error code and count; do not log paths or
   sensitive identifiers to public clients.

**Acceptance criteria**

- App-lifespan test with missing and wrong-size media asserts the fault is
  visible in device status, `/health/ready` is not ready, and the inspection
  loop cannot publish a subsequent `OK` until recovery.
- Repeated startup does not erase the integrity fault or silently restore
  readiness.

### PR20-F09 - P1: Production Startup Skips Same-Size Checksum Tampering

**References**

- `apps/edge-service/src/assemblyvision_edge/api/app.py:93-103`
- `apps/edge-service/src/assemblyvision_edge/persistence/reconcile.py:126-149`

**Problem**

`scan_storage_integrity()` defaults to `verify_checksums=False`, and startup
uses that default. Same-size tampering is therefore not detected in production.
The E2 task requires a full checksum scan or explicitly configured bounded
sampling; this implementation provides neither configuration, policy, coverage
telemetry, nor startup invocation.

**Required solution**

1. Add typed integrity-scan settings for either full verification or bounded
   deterministic sampling (sample size/rate, maximum bytes, scheduling).
2. Run the selected policy at startup and expose last-run time, coverage, and
   skipped reason through authenticated status/metrics.
3. Default production enablement to a safe documented policy; do not silently
   claim checksum verification from size-only scanning.

**Acceptance criteria**

- Lifespan test writes same-size, different-checksum media and verifies the
  configured policy detects it and gates/alerts according to F08.
- Sampling tests prove deterministic bounds and that every configured sample is
  checksum-checked.
- Status exposes scan coverage and the policy currently in effect.

### PR20-F10 - P1: Orphan Final Bundles/Media Are Not Detected or Quarantined

**References**

- `apps/edge-service/src/assemblyvision_edge/persistence/reconcile.py:152-198`

**Problem**

Reconciliation enumerates only `*/inspection.json`. A final inspection
directory containing media but no manifest, an empty final directory, or
orphan final media is ignored rather than moved to quarantine. This leaves
ambiguous evidence outside the durable integrity/quarantine workflow required
by E2d.

**Required solution**

1. Enumerate candidate final bundle directories under the output root while
   excluding known system roots (`quarantine`, staging, database/log roots).
2. Quarantine directories missing a valid manifest, and report the reason with
   a stable code. Do not delete their contents.
3. Establish an idempotent collision policy for duplicate quarantine directory
   names; preserve both artifacts rather than overwriting the first.

**Acceptance criteria**

- Tests cover orphan media-only directory, empty final bundle, invalid manifest,
  unsafe path, and repeated startup. Each is quarantined exactly once without
  data loss.
- Quarantined artifacts are never rediscovered as normal bundles on subsequent
  startup.

### PR20-F11 - P1: `/health/ready` Returns 200 While Storage Admission Is Closed

**References**

- `apps/edge-service/src/assemblyvision_edge/api/routers/health.py:24-54`

**Problem**

The endpoint returns 503 only when `runtime.pipeline is None`. It serializes a

**Required solution**

Build the full readiness snapshot first. Return `503 NOT_READY` whenever any

**Acceptance criteria**

- Tests for normal, warning, critical, stop, latched write fault, and integrity
  fault assert expected HTTP status and stable problem code.
- Warning/critical remain 200 only when mandatory persistence is still
  guaranteed by explicit policy; stop/fault are always 503.

### PR20-F12 - P1: Repository Transition Does Not Independently Verify Receipt Content

**References**

- `apps/edge-service/src/assemblyvision_edge/persistence/repository.py`
  `mark_upload_succeeded()` and `_has_verified_receipt()`.

**Problem**

`mark_upload_succeeded()` accepts any non-empty `receipt_json` and, for media,

**Required solution**

1. Validate a typed receipt against persisted task fields inside the repository
   transition, or persist an immutable `receipt_verified_at` flag that can only
   be written by a small validated repository operation.
2. Require a non-empty central object ID for media and reject malformed JSON,
   missing receipt fields, and mismatched immutable data.
3. Keep sink validation as a first boundary; repository validation is the
   durable safety boundary for retention authorization.

**Acceptance criteria**

- Direct repository tests submit empty, malformed, mismatched, or incomplete
  receipt data and prove no task becomes `SUCCEEDED`, no inspection becomes
  `SYNCED`, and no media is eligible.
- A matching typed receipt succeeds and preserves replay/idempotency behavior.

## 3.1 Resolution Status

| Finding | Severity | Resolution | Tests |
|---|---|---|---|
| PR20-F01 | P0 | `_persist_projection` returns success only after the outbox commit and never publishes `last_result` on failure; every persistence failure latches `storage_write_fault` (SQLAlchemy-wrapped included) | `test_pr020_review_fixes.py::test_persist_failure_latches_fault_and_does_not_publish` |
| PR20-F02 | P1 | fenced `confirm_retention_claim` CAS renews the lease and re-validates eligibility immediately before destructive I/O | `test_pr020_review_fixes.py::test_expired_or_superseded_claim_cannot_unlink` |
| PR20-F03 | P1 | `apply_media_hold`/`mark_media_integrity_fault_direct` atomically clear active claims; `confirm_retention_claim` and `finalize_media_purge` re-validate full eligibility | `test_pr020_review_fixes.py::test_hold_or_fault_after_claim_cancels_deletion`, `test_finalize_purge_rechecks_sync_and_receipt` |
| PR20-F04 | P1 | `unlink_media_safely` traverses and unlinks through `O_NOFOLLOW` directory fds; no-follow final stat | `test_pr020_review_fixes.py::test_symlink_swapped_bundle_dir_cannot_delete_external_file` |
| PR20-F05 | P1 | `refresh_storage` never clears the write-fault latch; `probe_persistence` (probe file + `BEGIN IMMEDIATE` write probe) is the only clear path | `test_pr020_review_fixes.py::test_persist_failure_latches_fault_and_does_not_publish` |
| PR20-F06 | P1 | threshold comparisons use `<=` (at-or-below) for bytes and inodes | `test_pr020_review_fixes.py::test_exact_threshold_boundaries_are_stop_critical_warning` |
| PR20-F07 | P1 | `OutputWriter.save(suppress_optional=...)` skips optional OK media at critical; NG evidence and metadata always persist | `test_pr020_review_fixes.py::test_writer_suppresses_optional_ok_media_but_preserves_ng` |
| PR20-F08 | P1 | startup scan faults latch `storage_integrity_fault`, gate intake/readiness, and emit `STORAGE_INTEGRITY_FAULT` | `test_pr020_review_fixes.py::test_startup_integrity_fault_gates_ready_and_alerts` |
| PR20-F09 | P1 | full checksum verification is the startup default; typed `IntegrityScanSettings` supports explicit bounded sampling and exposes coverage telemetry | `test_pr020_review_fixes.py::test_checksum_policy_detects_same_size_tampering`, `test_default_startup_integrity_policy_verifies_checksums` |
| PR20-F10 | P1 | orphan final bundles (no valid manifest) are quarantined with collision-safe names; system roots excluded | `test_pr020_review_fixes.py::test_orphan_media_bundle_is_quarantined` |
| PR20-F11 | P1 | `/health/ready` returns 503 for stop pressure, latched write fault, and integrity faults | `test_pr020_review_fixes.py::test_health_ready_503_on_write_fault_and_stop` |
| PR20-F12 | P1 | `mark_upload_succeeded` validates a typed receipt against the task's immutable fields; media requires a central object ID | `test_pr020_review_fixes.py::test_mark_upload_succeeded_rejects_mismatched_receipt` |
| PR20-F13 | P2 | device status exposes thresholds, observation time, and scan coverage; dashboard renders server alerts | `test_pr020_review_fixes.py::test_startup_integrity_fault_gates_ready_and_alerts` |

Additionally, the inspection payload serialization now excludes the mutable
`synchronization_status` in both the enqueue size record and the uploader so
recorded task sizes equal the bytes actually uploaded.

## 4. P2 Improvements

### PR20-F13 - P2: Status Does Not Expose Full Storage Policy or Render Alerts

**References**

- `apps/edge-service/src/assemblyvision_edge/api/state.py:438-476`
- `apps/edge-service/src/assemblyvision_edge/api/schemas.py`
- `apps/edge-web/src/pages/DeviceStatus.vue:71-76`

`StorageState` retains thresholds and observation timestamp, but the public

**Solution and acceptance**

- Add configured thresholds, storage observation timestamp, integrity-scan
  summary, and stable server alert codes to `DeviceStatus`; regenerate OpenAPI
  and TypeScript types; synchronize the mock/runtime validator.
- Render those server-provided alerts and policy values in the dashboard.
- Add API contract and frontend tests proving an integrity/stop/cleanup fault
  is visible without client-side threshold reimplementation.

## 5. Required Regression Matrix Before Re-review

The following tests are required in addition to normal Ruff/MyPy/Pytest/TS/
MkDocs gates:

| Area | Required evidence |
|---|---|
| Persistence fail-safe | Raw and SQLAlchemy-wrapped write failure cannot publish `OK`; fault stays latched until durable recovery probe. |
| Cleanup fencing | Expired/superseded worker cannot unlink; current worker alone finalizes. |
| Protection races | Hold/integrity update after claim prevents unlink and `PURGED`. |
| Path safety | Intermediate/final symlink replacement cannot remove an out-of-root file. |
| Thresholds | Exact byte/inode boundary behavior uses `<=`; stop drains/rejects frames. |
| Critical degradation | Only configured optional artifacts are suppressed; required metadata/NG evidence persists. |
| Startup integrity | Missing/size/checksum/unsafe/orphan cases gate readiness, alert, quarantine, and remain protected across restart. |
| Readiness HTTP | `/health/ready` is 503 for stop/write/integrity faults. |
| Receipt authority | Invalid persisted receipt cannot authorize `SYNCED` or retention eligibility. |
| Observability | API/OpenAPI/TS/dashboard show policy, scan coverage, storage mode, and alert codes consistently. |

## 6. Production Enablement Conditions

Even after code findings pass, do not enable deletion or stop-mode on a live

- retention durations and quotas by media class;
- capacity, inode reserve, maximum outage, and threshold values;
- mandatory versus optional media policy by outcome;
- legal/acceptance/review holds, audit retention, encryption, backup, and
  secure-erasure policy;
- stop-mode line-control and operator recovery behavior; and
- deployed central verified-receipt/media-binding guarantees.
