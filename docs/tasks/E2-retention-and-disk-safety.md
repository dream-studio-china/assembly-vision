# E2 Pipeline: Retention and Disk Safety

## 1. Purpose

Deliver the Edge retention and disk-safety milestone without weakening the
edge-first, fail-safe inspection contract. This pipeline makes local evidence
deletion controlled, auditable, receipt-gated, and safe under disk pressure.

The default production-safe configuration is **no deletion**. Cleanup can run
only after an approved retention policy is configured. Missing policy values,
unknown upload state, missing receipts, missing storage measurements, or
integrity faults must protect evidence rather than deleting it.

## 2. Scope and Non-Goals

### In scope

- Persistent media-retention state and cleanup audit fields.
- A receipt-gated retention cleanup worker with an inter-process lease and
  fencing token.
- Warning, critical, and stop storage-pressure states.
- Startup integrity scanning and quarantine/fault reporting.
- Typed Edge API, generated OpenAPI/TypeScript contracts, dashboard status,
  operational metrics, runbooks, and fault-injection tests for the above.

### Out of scope

- Central ingestion, central object storage, central manual review, and remote
  package distribution.
- Customer-specific retention durations, legal-hold policy, secure-erasure
  method, site disk sizing, and line-control integration. These are required
  inputs before deletion or stop-mode can be enabled in production.
- Bandwidth throttling, circuit breaking, and resumable media upload (E3).

## 3. Safety Invariants

The following invariants are mandatory in every E2 change and test:

1. The cleanup worker must never delete media if any required upload task is
   `PENDING`, `IN_PROGRESS`, `RETRY_WAIT`, `PERMANENT_FAILURE`, `CANCELLED`, or
   otherwise lacks a verified receipt.
2. A media receipt is verified only when it contains the expected idempotency
   key, object identity, checksum, byte size, and central object identifier.
3. Cleanup must never delete media subject to a configured hold, acceptance
   lock, human-review lock, integrity fault, unknown lifecycle, or unexpired
   retention deadline.
4. Cleanup must durably mark an artifact as deleting under a lease/fencing
   token before unlinking it. It may mark the artifact `PURGED` only after the
   intended file is absent; failed unlink must remain retryable and observable.
5. A stale cleanup worker must not overwrite the result of a newer lease
   holder. Lease expiry must make abandoned deletion claims recoverable.
6. Disk-pressure cleanup may prioritize eligible data, but must never delete
   pending-upload NG evidence to continue inspection silently.
7. At stop pressure, if a complete auditable inspection cannot be durably
   written, the runtime must stop accepting new products or make the outcome
   fail-safe. It must never return an unrecorded `OK`.
8. Integrity scan failures, read-only storage, disk-full writes, corrupt
   database state, and missing mandatory evidence must produce explicit fault
   state/alerts. They must not be represented as healthy storage.
9. SQLite metadata is not an authorization to remove an arbitrary filesystem
   path. Every unlink must be constrained to the configured output root and the
   artifact's trusted inspection bundle.
10. Retention is local-only and must not require central reachability at
    inspection time. Central unavailability protects evidence and may grow the
    queue; it must not block a locally durable inspection while reserve remains.

## 4. Required Decisions Before Production Enablement

E2 may be implemented with deletion disabled, but these decisions are release
blockers for enabling cleanup or storage stop behavior at a customer site:

- Retention duration and quota per `KEY_FRAME`, `ANNOTATED_FRAME`,
  `PRODUCT_ROI`, `NG_CLIP`, `ROLLING_VIDEO`, logs, and metadata.
- Disk volume capacity, inode capacity, daily media volume, maximum outage,
  required protected reserve, and warning/critical/stop thresholds.
- Whether NG media, rolling/full video, and selected OK media are mandatory.
- Legal, acceptance, and human-review hold behavior; purge audit retention;
  encryption-at-rest, backup, and secure-deletion obligations.
- Stop-mode line behavior: pause/trigger rejection, operator acknowledgement,
  recovery authority, and upstream equipment signal.
- Real central receipt deployment and media-binding guarantees. A test sink or
  undeployed central endpoint is not production authorization to delete data.

## 5. Delivery Pipeline

Each gate is independently reviewable. A later gate must not begin until all
acceptance criteria for its predecessor pass.

### E2a: Durable Retention State and Eligibility

**Implementation**

- Add a migration after `0006_upload_task_size` for retention and deletion
  coordination fields. At minimum this includes an effective
  `retention_eligible_at`, hold state, deletion claim/lease/fencing fields,
  deletion timestamp, purge timestamp/reason, and last deletion error.
- Extend typed domain/API media models only where externally visible metadata
  is required. Regenerate OpenAPI and TypeScript types for public changes.
- Add repository methods to compute receipt-gated eligibility, atomically claim
  a bounded cleanup batch, finalize a purge, and record a retryable deletion
  failure. All compare-and-set transitions require the current fencing token.
- Define the source of truth: the filesystem holds media bytes; SQLite holds
  metadata and deletion state. A `PURGED` row remains an audit tombstone; it is
  not removed with the file.

**Exit criteria**

- Fresh and migrated SQLite databases open successfully and preserve all
  existing outbox/media data.
- Eligibility returns no item without an unexpired receipt-verified `SYNCED`
  inspection, an elapsed retention deadline, and an allowed lifecycle.
- Eligibility excludes every pending, retrying, in-progress, failed, cancelled,
  held, locked, unknown, corrupted, or already-purged item.
- Two concurrent repository instances cannot claim the same media; a stale
  claim cannot mark a newer claim purged or failed.
- Public schema changes have committed OpenAPI and generated TypeScript
  artifacts, and contract-drift tests pass.

### E2b: Cleanup Worker and Audited Deletion

**Implementation**

- Add a supervised in-process cleanup worker, separate from the upload
  scheduler, with a process-level lifecycle and an inter-process SQLite lease.
- Claim first, then resolve and revalidate the trusted media path, unlink,
  verify absence, and finalize `PURGED` with timestamp/reason/reclaimed bytes.
- Treat missing files as integrity faults, not successful retention deletion.
- Record deletion failures, release/recover expired claims, expose worker
  health and cleanup metrics, and emit stable events/alerts without paths,
  credentials, or image bytes in logs.
- Keep cleanup disabled unless retention policy is explicitly valid and enabled.

**Exit criteria**

- An eligible uploaded artifact is deleted exactly once; its row becomes an
  auditable `PURGED` tombstone and media serving returns `410 MEDIA_PURGED`.
- A file missing before deletion causes an integrity alert/fault and does not
  falsely claim a successful purge.
- Permission error, read-only filesystem, unlink failure, process crash after
  claim, and crash after unlink/before finalization recover without deleting a
  second file or losing the audit trail.
- Concurrent workers and a worker restart demonstrate lease recovery and
  fencing; no test may rely only on in-process locks.
- Disabled or incomplete policy produces zero unlink calls, even under warning
  or critical disk pressure.

### E2c: Storage Pressure and Fail-Safe Runtime Behavior

**Implementation**

- Add typed configuration for storage volume, warning/critical/stop thresholds,
  cleanup interval/batch/lease, and enabled retention policy. Validate strict
  ordering: `stop < critical < warning`, valid percentage/byte/inode ranges,
  and no destructive default values.
- Measure free bytes and inodes on the actual persistent output volume. Publish
  a stable storage state with observed values, thresholds, timestamps, cleanup
  health, and stable alert codes through device status.
- At warning, request eligible cleanup and alert. At critical, suppress only
  explicitly optional capture; metadata and required NG evidence stay
  protected. At stop, pause/reject new product intake when mandatory durable
  persistence cannot be guaranteed.
- Convert mandatory output/persistence failures into a storage fault that gates
  inspection admission. A preflight check is not sufficient; write-time
  `ENOSPC`, `EROFS`, and I/O failure must also be fail-safe.
- Remove dashboard-owned fixed disk thresholds; render server-provided policy
  state and alerts instead.

**Exit criteria**

- Boundary tests prove exact transition behavior at warning, critical, and stop
  thresholds for both bytes and inodes, including recovery/hysteresis policy.
- Warning accelerates only eligible cleanup. Critical preserves required NG
  evidence and disables only configured optional capture. Stop prevents a new
  inspection from producing an unrecorded `OK`.
- Simulated `ENOSPC`, `EROFS`, write failure, and database write failure result
  in explicit storage/not-ready state or fail-safe inspection outcome; no
  exception path emits business `OK`.
- A full or read-only disk cannot make the service advertise
  `inspection_ready=true` when mandatory persistence is unavailable.
- The API, dashboard, and logs show one consistent server-authoritative state.

### E2d: Startup Integrity, Recovery, and Operational Acceptance

**Implementation**

- Extend startup reconciliation to identify missing referenced files,
  wrong-size files, checksum mismatches (full scan or explicitly configured
  bounded sampling), unsafe paths, orphan final bundles/media, and abandoned
  deletion claims.
- Define and implement a durable integrity-fault/quarantine state. Do not
  silently re-import, overwrite, or delete ambiguous evidence.
- Run appropriate SQLite integrity checks before declaring storage ready.
  Database corruption must enter storage-not-ready mode and require documented
  restore rather than automatic replacement.
- Update low-disk, upload-backlog, database-recovery, and synchronization
  runbooks with E2 alert codes, triage, cleanup restrictions, safe resume
  checks, and evidence-preservation requirements.

**Exit criteria**

- Startup fault-injection tests cover stale staging, abandoned deletion claim,
  missing file, size mismatch, checksum mismatch, orphan bundle, unsafe path,
  database corruption signal, and restart during cleanup.
- No integrity fault permits `OK` when required evidence cannot be durably
  recorded; ambiguous media is quarantined/protected, never silently removed.
- A controlled offline soak test runs concurrent inspection persistence,
  upload retry, cleanup, API reads, and restarts without duplicate upload tasks,
  premature deletion, SQLite lock failure, or unauditable inspection result.
- Runbooks are executable using only documented status/alerts and do not tell
  operators to delete protected evidence manually.

## 6. Mandatory Test Matrix

The implementation is not accepted without automated tests for every row.

| Area | Required cases |
|---|---|
| Eligibility | no receipt; malformed receipt; media without central object ID; `PENDING`; `IN_PROGRESS`; `RETRY_WAIT`; permanent failure; cancelled; held; unexpired; expired verified receipt |
| Lease/fencing | concurrent workers; stale lease completion; crash after claim; lease expiry/reclaim; duplicate cleanup invocation |
| Filesystem | missing file; traversal/absolute/symlink escape; wrong size; checksum mismatch; permission denied; read-only filesystem; `ENOSPC`; unlink crash boundary |
| Pressure | warning/critical/stop transitions; byte and inode thresholds; recovery; optional-media suppression; mandatory NG preservation; new-product stop admission |
| Reconciliation | staging residue; orphan final bundle; database/media mismatch; stale deleting state; corrupt SQLite signal; restart recovery |
| Contract/UI | schema defaults; OpenAPI/TypeScript drift; authenticated status; `PURGED` media `410`; server-authoritative dashboard alerts |
| Soak | concurrent inspection, upload, cleanup, dashboard reads, restarts, and prolonged offline backlog |

All normal repository quality gates remain mandatory:

```bash
uv run ruff check .
uv run ruff format --check .
uv run mypy .
uv run pytest
pnpm -r build
pnpm -r lint
pnpm -r test
cd apps/edge-web && pnpm test:e2e
uv run mkdocs build --strict
```

## 7. Merge and Release Gates

### Code merge gate

Every E2 pull request must have:

- Focused migration with tested upgrade and downgrade behavior.
- Typed interfaces; no unstructured dictionary used as the retention domain
  interface.
- Regression tests for every changed safety invariant.
- Current OpenAPI/TypeScript artifacts when a public schema changes.
- Passing mandatory quality commands and relevant fault-injection tests.
- Review evidence that the change cannot delete pending, unverified, held, or
  unexpired evidence.

### E2 completion gate

E2 is complete only when all E2a-E2d exit criteria pass and all of the
following are true:

1. No automated test can cause protected evidence to be deleted.
2. Cleanup remains disabled and non-destructive without approved policy.
3. Receipt-gated deletion, deletion audit, lease fencing, and restart recovery
   are demonstrated against SQLite and the filesystem.
4. Disk pressure and actual write failures result in a visible fail-safe mode,
   never an unrecorded `OK`.
5. Startup integrity faults are visible, protected, and recoverable through
   documented procedures.
6. API/dashboard state, logs, metrics, and runbooks agree on the storage mode.
7. The customer/site decisions in section 4 are recorded and approved before
   enabling deletion or stop-mode in production.

## 8. References

- [Local Storage and Retention](../design/12-local-storage-and-retention.md):
  sections 12.3-12.9.
- [Upload and Synchronization](../design/13-upload-and-synchronization.md):
  sections 13.3-13.10.
- [Observability and Support](../design/23-observability-and-support.md):
  sections 23.4-23.11.
- [Deployment and Operations](../design/20-deployment-and-operations.md):
  persistent-volume and recovery requirements.
- [ADR-005: Local-First Storage and Delayed Upload](../design/decisions/ADR-005-local-first-storage-and-delayed-upload.md).
- [Contract 01: Architecture Boundaries](../contracts/01-architecture-boundaries.md).
- [Contract 03: AI, Rule Engine, and Fail-Safe Contracts](../contracts/03-ai-rule-and-safety-contracts.md): fail-safe `OK` prohibition.
- [Contract 04: Edge, Storage, and Upload Contracts](../contracts/04-edge-storage-upload-contracts.md): persistence order, verified uploads, restart recovery, and cleanup restrictions.
- [Contract 06: Testing, Quality, and CI Contracts](../contracts/06-testing-quality-and-ci-contracts.md): mandatory quality and disk-full/power-loss testing.
- [Contract 07: Deployment, Observability, and Operations](../contracts/07-deployment-observability-and-operations.md): health, metrics, and runbook requirements.
- [Runbook 03: Low Disk Space](../runbooks/03-low-disk-space.md).
- [Runbook 04: Upload Backlog](../runbooks/04-upload-backlog.md).
- [Runbook 05: Database Recovery](../runbooks/05-database-recovery.md).
