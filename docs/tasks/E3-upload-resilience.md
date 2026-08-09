# E3 Pipeline: Upload Resilience

## 1. Purpose

Make the edge upload path resilient under degraded networks and long central
outages without weakening the edge-first, fail-safe inspection contract. E3
adds bandwidth throttling, a circuit breaker, controlled manual retry, long
outage drain tests, and a resumable large-media client contract on top of the
durable outbox and scheduler delivered by PR #17 (design 13, ADR-005).

Local inspection must never depend on upload health: throttling and circuit
open states preserve the queue and stop new traffic, but never block durable
inspection persistence while protected storage remains available.

## 2. Scope and Non-Goals

### In scope

- Bandwidth throttling of upload traffic against a configured ceiling.
- A circuit breaker that pauses attempts during an outage and periodically
  probes recovery, with observable circuit state.
- A controlled manual retry endpoint that resets only eligible tasks and
  preserves attempt history.
- Long-outage drain tests proving duplicate-free, ordered recovery.
- A resumable large-media client contract (edge side and protocol contract
  only; the central endpoint is not implemented).

### Out of scope

- The central ingestion API, PostgreSQL model, object storage, and manual
  review (central work starts after E1-E6 and contract freeze).
- Multi-path/parallel media upload beyond the single POST envelope.
- Pre-signed S3-compatible multipart upload implementation (decision deferred
  to design 13.11 until file-size measurement).
- Encryption-at-rest, backups, and secure-deletion obligations (site
  decisions, E2 production enablement).

## 3. Safety Invariants

The following invariants are mandatory in every E3 change and test:

1. Throttling and circuit-open states must never discard, delay-commit, or
   reorder durable task state; tasks remain `PENDING`/`RETRY_WAIT` with their
   attempts and backoff intact.
2. A circuit open must stop new network attempts (no hot-looping) while
   inspection persistence continues; the queue must drain completely and
   duplicate-free after recovery.
3. Manual retry resets only eligible tasks (`RETRY_WAIT` or
   `PERMANENT_FAILURE`), increments `attempt_count`, and never touches
   `SUCCEEDED`, `IN_PROGRESS` (leased elsewhere), or `CANCELLED` tasks.
4. Manual retry must preserve the verified-receipt gate: retrying a media
   task never re-authorizes deletion before a verified central receipt.
5. Large media completion is accepted only when the server confirms expected
   size and checksum and binds the object to the inspection; a chunked/resumable
   flow must remain idempotent per task.
6. Upload health observability must distinguish queue truth (persistent) from
   worker liveness and circuit state (process-local), and a circuit-open state
   must not be reported as healthy.

## 4. Required Decisions Before Production Enablement

E3 may be implemented with conservative defaults, but these inputs are release
blockers for enabling aggressive upload behavior at a customer site:

- Bandwidth ceiling and scheduling window for upload traffic.
- Circuit failure threshold and open duration consistent with expected outage
  patterns.
- Which media kinds are large enough to require resumable transfer.
- Central ingestion contract and media-binding guarantees (deployed central
  endpoint; a test sink is not production authorization).

## 5. Delivery Pipeline

Each gate is independently reviewable.

### E3a: Bandwidth Throttling

**Implementation**

- Implement a bounded rate limiter (token-bucket) in `UploadScheduler` driven
  by the existing `UploadSettings.maximum_bandwidth_mbps` placeholder; a
  `None` ceiling means no throttling.
- Apply the limiter only to network payload bytes (media and metadata), never
  to local persistence; the limiter must not hold task leases while sleeping
  longer than the lease duration without renewal.
- Expose cumulative bytes sent and current ceiling through scheduler health /
  device status so operators can confirm the ceiling is enforced.

**Exit criteria**

- Parameterized tests prove that with a configured ceiling the total upload
  time for known payload bytes is at least the theoretical minimum, and that
  without a ceiling no artificial delay is introduced.
- A long media upload under throttle cannot starve inspection: the scheduler
  stops sending while local inspection persistence keeps committing.

### E3b: Circuit Breaker

**Implementation**

- Add typed circuit settings (`failure_threshold`, `open_seconds`) to
  `UploadSettings`; default closed.
- Track consecutive failures (transport errors and retryable HTTP statuses).
  When the threshold is reached the circuit opens: the scheduler stops
  claiming/attempting tasks. After `open_seconds` it half-opens and allows a
  probe attempt; success closes the circuit, failure reopens it.
- Expose circuit state and last state change through scheduler health and
  device status with a stable `UPLOAD_CIRCUIT_OPEN` alert; circuit state is
  process-local liveness, not queue truth.

**Exit criteria**

- Fault-injection tests prove: threshold failures open the circuit and produce
  zero further attempts; a half-open probe success closes it and resumes drain;
  a half-open probe failure reopens it; an open circuit does not mutate task
  state and recovery drains the backlog duplicate-free.

### E3c: Controlled Manual Retry

**Implementation**

- Add `POST /api/v1/uploads/{upload_task_id}/retry` (viewer-authenticated)
  wrapping the repository retry transition: only `RETRY_WAIT` /
  `PERMANENT_FAILURE` tasks reset to `PENDING` with `attempt_count + 1`;
  unknown tasks return 404 and non-eligible tasks return 409 with the current
  state.
- Keep the endpoint out of the auto-retry loop: the scheduler never uses it.
- Regenerate OpenAPI/TypeScript artifacts for the new endpoint.

**Exit criteria**

- API tests prove: retry on an eligible task resets it to `PENDING` and
  increments attempts; retry on `SUCCEEDED`/`IN_PROGRESS`/`CANCELLED`/unknown
  returns 409/404 without mutation; a retried task re-drains idempotently;
  receipt-gated retention eligibility is unchanged by retry.

### E3d: Long-Outage Drain Tests

**Implementation**

- Add fault-injection tests that run a prolonged offline period (sink
  failures), continue inspection persistence, restart the edge, restore
  connectivity, and verify complete duplicate-free drain with ordered
  metadata-before-media semantics.

**Exit criteria**

- A test proves thousands of queued tasks across a restart drain without
  duplicates, without premature retention deletion, and with inspection
  synchronization reaching `SYNCED` for every record.

### E3e: Resumable Large-Media Client Contract

**Implementation**

- Document the resumable large-media contract (design 13.3/13.11): stable
  task identity, chunk idempotency, size/checksum completion confirmation,
  and object-to-inspection binding; define the edge-side boundary and the
  central protocol contract without implementing the central endpoint.

**Exit criteria**

- The contract is documented and reviewed; the edge side defines the
  `media_chunk_bytes` placeholder and states clearly that transfer starts only
  after the central contract freeze.

## 6. Mandatory Test Matrix

| Area | Required cases |
|---|---|
| Throttling | ceiling time bound; no-ceiling no-delay; long media cannot starve inspection |
| Circuit | threshold open; zero attempts while open; half-open success/failure; open does not mutate tasks; duplicate-free recovery |
| Manual retry | eligible reset + attempt increment; 404 unknown; 409 non-eligible; idempotent re-drain; retention gate unchanged |
| Long outage | prolonged offline + inspection continues; restart; restore; complete duplicate-free drain; ordered metadata-before-media |
| Observability | queue truth vs worker liveness vs circuit state; stable alert codes; OpenAPI/TS contract updated |

## 7. Merge and Release Gates

- Focused changes with typed interfaces and no unstructured dictionary at the
  public boundary.
- Regression tests for every changed safety invariant.
- Current OpenAPI/TypeScript artifacts when a public schema changes.
- Passing mandatory quality commands: `ruff check/format`, `mypy`, `pytest`,
  `mkdocs build --strict`, `pnpm -r build/lint/test`, edge-web e2e.
- Review evidence that throttling/circuit/manual-retry cannot lose or
  duplicate tasks, and cannot re-authorize deletion without a verified receipt.

## 8. References

- [Upload and Synchronization](../design/13-upload-and-synchronization.md):
  sections 13.3-13.11.
- [Local Storage and Retention](../design/12-local-storage-and-retention.md):
  retention gates on verified receipts.
- [ADR-005: Local-First Storage and Delayed Upload](../design/decisions/ADR-005-local-first-storage-and-delayed-upload.md).
- [Contract 04: Edge, Storage, and Upload Contracts](../contracts/04-edge-storage-upload-contracts.md).
- [Observability and Support](../design/23-observability-and-support.md):
  queue/circuit observability.
- [Runbook 04: Upload Backlog](../runbooks/04-upload-backlog.md).
