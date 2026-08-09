# PR-022 Review: Upload Resilience (E3)

## 1. Review Decision

**Status: RESOLVED**

PR #22 establishes the right E3 structure: a rate limiter, a process-local
circuit breaker, a controlled retry route, durable-outage coverage, and a
clearly deferred resumable-media protocol. The initial review found one P0
(the throttle could block every large upload forever) and two P1 gaps (the
limiter did not bound the bytes actually sent, and manual retry was not an
atomic transition). All findings are now fixed and covered by regression tests
(see section 3.1).

## 2. Scope and Evidence

Reviewed PR: [#22](https://github.com/dream-studio-china/assembly-vision/pull/22)
(`feat/e3-upload-resilience` into `dev`).

Reviewed commits:

```text
e443661 docs: add E3 upload resilience delivery task
bab38c2 feat(edge): bandwidth throttle upload traffic (E3a)
f91095f feat(edge): circuit breaker stops upload attempts during outages (E3b)
6f3c9c4 feat(edge): controlled manual upload retry endpoint (E3c)
d3473bc test(edge): prolonged offline outage drains duplicate-free after restart (E3d)
e5d6a87 docs(edge): resumable large-media client contract and chunk placeholder (E3e)
175352e test(edge): update retry-404 assertion for the E3c retry endpoint
f3e06f8 docs: record E3 upload resilience in project context
```

Primary requirements:

- [E3 upload resilience task](../tasks/E3-upload-resilience.md), especially
  sections 3, 5, 6, and 7.
- [Upload and Synchronization](../design/13-upload-and-synchronization.md),
  sections 13.3 through 13.10 and 13.13 through 13.14.
- [Contract 04: Edge, Storage, and Upload](../contracts/04-edge-storage-upload-contracts.md),
  sections 3 through 8.
- [Contract 05: Data, API, and Versioning](../contracts/05-data-api-and-versioning-contracts.md),
  sections 5 through 7.
- [Contract 06: Testing, Quality, and CI](../contracts/06-testing-quality-and-ci-contracts.md),
  sections 2 and 6.
- [Contract 07: Deployment, Observability, and Operations](../contracts/07-deployment-observability-and-operations.md),
  sections 4 through 7.
- [ADR-005: Local-First Storage and Delayed Upload](../design/decisions/ADR-005-local-first-storage-and-delayed-upload.md).

The PR description reports these completed local checks: Ruff, MyPy, Pytest
(`796 passed`), MkDocs strict, pnpm build/lint/test, and 12 Playwright tests.
They do not cover the payload-size, wire-byte, lease, and transition-race
boundaries below. GitHub checks were pending at review time.

## 3. Required Findings

### PR22-F01 - P0: A Payload Larger Than One Bucket Capacity Blocks Forever

**References**

- `apps/edge-service/src/assemblyvision_edge/upload/scheduler.py:50-71`
- `apps/edge-service/src/assemblyvision_edge/upload/scheduler.py:487-503`
- `docs/tasks/E3-upload-resilience.md:80-95`

**Problem**

`_TokenBucket.acquire()` caps tokens at one second of the configured rate, but
requires the bucket to contain the full `amount` before it returns. For any
payload larger than `rate_bytes_per_second * 1.0`, this predicate can never be
true:

```text
tokens <= rate * 1 second < amount
```

The scheduler has already leased the task before it calls `acquire()`. It then
loops indefinitely in 250 ms sleeps and never calls the sink or writes a task
transition. For example, an 8 MiB media task at 1 Mbps has a 125,000-byte bucket
capacity and is permanently stuck. The worker may retain the task lease past
its expiry, and `stop()` cannot promptly finish the blocked worker.

This is a production data-flow failure, not only a throughput issue: large
evidence never drains after recovery, while the durable queue reports it as
`IN_PROGRESS`. It violates E3 invariant 1 and E3a's requirement not to sleep
beyond a lease without renewal.

**Required solution**

1. Do not require one token reservation equal to a complete media object. Rate
   limit a bounded sequence of request-body segments instead.
2. Apply the segment limiter at the actual transport write boundary. The HTTP
   sink should stream the serialized request body in bounded chunks and acquire
   budget for each chunk before yielding it to `httpx`; do not wait once and
   then emit the entire media object in one burst.
3. Add a fenced upload-lease renewal operation in the repository, and renew the
   active lease before any wait that could cross the current expiry. Abort the
   request without a terminal transition if renewal fails, allowing the current
   owner to recover the task.
4. Make throttling cancellable through the scheduler stop event. A shutdown
   must not wait for an arbitrary media transfer duration.
5. Keep all throttling out of inspection persistence and the development
   directory sink. Only bytes being sent to a network destination are subject
   to this policy.

**Acceptance criteria**

- A deterministic test sends a payload larger than one second of capacity at a
  low configured rate. It completes rather than looping, calls the sink, and
  takes at least the configured theoretical minimum transfer time.
- The same test proves the active lease is renewed before expiry throughout the
  throttled transfer; a failed renewal prevents the stale owner from sending or
  updating the task.
- A stop/shutdown test interrupts a throttled wait promptly and leaves the
  leased task recoverable through the existing lease-reclaim path.
- A parallel local-inspection persistence test proves throttling neither blocks
  the SQLite/outbox commit nor changes its order.
- Existing no-ceiling behavior remains immediate, and a normal payload below
  the bucket capacity still honors the configured limit.

### PR22-F02 - P1: The Configured Ceiling Does Not Bound HTTP Network Payload Bytes

**References**

- `apps/edge-service/src/assemblyvision_edge/upload/scheduler.py:500-504`
- `apps/edge-service/src/assemblyvision_edge/upload/scheduler.py:174-191`
- `docs/tasks/E3-upload-resilience.md:80-86`

**Problem**

The scheduler reserves `len(payload)`, but `HttpUploadSink` sends a JSON
envelope containing Base64 data. A media request's body is therefore larger
than the raw media bytes by approximately one third plus JSON metadata. The
full envelope is then handed to `httpx` in one write after the raw-byte wait.
Consequently, a configured bandwidth maximum is exceeded on the actual network
payload and the `upload_bytes_sent` metric reports a smaller, different unit.

This contradicts E3a's requirement to apply the limiter to network payload
bytes and makes capacity planning/observability misleading during outages.

**Required solution**

1. Define one explicit metric: application request-body bytes written to the
   network. Use that same metric for rate limiting and `bytes_sent` telemetry.
2. Serialize the HTTP envelope once, measure its serialized bytes, and stream
   those bytes through the segment limiter described in PR22-F01. Count only
   body bytes that are actually yielded to the transport; document whether
   protocol headers are intentionally excluded.
3. Update the `UploadSink` boundary or introduce a typed prepared-request
   object so the scheduler does not guess the wire size of a sink-specific
   envelope. Directory/development sinks must report zero network bytes rather
   than pretending filesystem writes consumed WAN capacity.
4. Update design 13.13 and device-status field descriptions to name the chosen
   unit precisely.

**Acceptance criteria**

- A test with binary media verifies that the rate limiter budgets the serialized
  Base64 JSON body, not `len(raw_media)`.
- With a configured ceiling, measured request-body throughput stays at or below
  the ceiling after the documented bounded burst; with no ceiling, no limiter
  delay is introduced.
- `upload_bytes_sent` equals the request-body bytes yielded by the HTTP sink
  across successful and retryable attempts. It is zero for the directory sink.
- OpenAPI, generated TypeScript, and status documentation describe the same
  byte unit and preserve nullable/unthrottled behavior.

### PR22-F03 - P1: Manual Retry Is Not an Atomic State Transition and Leaves Aggregate Sync State Stale

**References**

- `apps/edge-service/src/assemblyvision_edge/api/routers/uploads.py:41-56`
- `apps/edge-service/src/assemblyvision_edge/persistence/repository.py:993-1026`
- `apps/edge-service/src/assemblyvision_edge/persistence/repository.py:1781-1816`
- `docs/tasks/E3-upload-resilience.md:48-50, 120-135`

**Problem**

The route checks eligibility in one repository call and executes the mutation
in another. Between them, the scheduler can claim the task, or a second manual
retry can reset it. `EdgeRepository.retry_upload()` then returns the current
non-eligible task rather than reporting a transition conflict, and the route
returns HTTP 200. The operator is told a retry succeeded although no retry was
performed and the task may be leased by another worker.

When the transition does succeed, the repository changes only `status`,
`attempt_count`, and `last_error_code`. It does not clear stale terminal fields
(`completed_at`), set `updated_at`, clear an old retry deadline, or recompute
the inspection's aggregate synchronization status. Thus a media task retried
from `PERMANENT_FAILURE` can remain reported as inspection `FAILED` while it is
again pending, until a later terminal worker transition happens to refresh it.

This violates the E3c promise that non-eligible tasks return 409 with the
current state, and it makes queue/inspection truth inconsistent during a retry.

**Required solution**

1. Replace the route's read-then-write flow with one repository operation that
   owns the complete decision in one immediate transaction.
2. Return a typed result that distinguishes `NOT_FOUND`, `NOT_RETRYABLE`
   (including the current task/state), and `RETRIED`. Map it to 404, 409, and
   200 in the route without a preliminary lookup.
3. Make the transition compare-and-set on both task ID and eligible state. On a
   successful transition set `status='PENDING'`, increment `attempt_count`,
   clear `last_error_code`, `next_attempt_at`, `completed_at`, and lease fields,
   and set `updated_at` from one injected/current UTC timestamp.
4. In the same transaction, call `_refresh_inspection_sync()` for a task with an
   inspection ID. The retry must not alter any verified receipt or authorize
   retention; it merely returns the aggregate state to `QUEUED` or `PARTIAL`.

**Acceptance criteria**

- A deterministic race test pauses after eligibility is observed, then has a
  worker claim the task (or another retry win). The delayed HTTP request returns
  409 `TASK_NOT_RETRYABLE` with the current state; it never returns false 200
  and never changes the worker's lease.
- Two simultaneous retry requests produce exactly one 200 transition and one
  409; `attempt_count` increases exactly once.
- Retrying both `RETRY_WAIT` and `PERMANENT_FAILURE` clears terminal/retry
  fields, sets a newer `updated_at`, and returns an immediately due `PENDING`
  task.
- Retrying a permanently failed media task moves its inspection state from
  `FAILED` to `QUEUED`/`PARTIAL` as dictated by the other verified tasks. It is
  not retention-eligible until the task succeeds with a new verified receipt.
- `SUCCEEDED`, `IN_PROGRESS`, `CANCELLED`, and unknown task cases retain their
  existing state and return 409/404 without mutation.

## 3.1 Resolution Status

| Finding | Severity | Resolution | Tests |
|---|---|---|---|
| PR22-F01 | P0 | `_TokenBucket.acquire` splits amounts above one burst into per-burst waits; `EdgeRepository.renew_upload_lease` CAS-renews the claim during the wait, and a stop or lease loss aborts without a terminal transition | `test_token_bucket_splits_large_amounts_across_bursts`, `test_token_bucket_on_wait_runs_and_can_abort`, `test_large_media_throttle_completes_and_renews_lease`, `test_throttle_aborts_on_stop_without_terminal_transition`, `test_renew_upload_lease_is_compare_and_set` |
| PR22-F02 | P1 | `HttpUploadSink` serializes the envelope once (`wire_size`), the scheduler throttles and meters those request-body bytes, and the directory sink reports zero network bytes; design 13.13 names the unit | `test_wire_size_counts_serialized_body_not_raw_bytes`, `test_payload_bytes_sent_matches_the_transport_body`, `test_directory_sink_reports_zero_network_bytes` |
| PR22-F03 | P1 | `retry_upload` is one compare-and-set transaction returning `NOT_FOUND`/`NOT_RETRYABLE`/`RETRIED`, clears terminal/retry/lease fields with a fresh `updated_at`, and refreshes inspection sync state; the route maps the typed outcome to 404/409/200 | `test_second_retry_of_same_task_is_409_not_false_200`, `test_concurrent_retries_have_single_winner`, `test_retry_clears_terminal_and_retry_fields`, `test_retried_permanent_media_refreshes_inspection_sync` |
| PR22-F04 | P2 | `ApiClient.retryUpload` with typed 404/409 mapping in HTTP and mock clients; `UploadsView` retry action only for eligible states; design 13.8 and runbook 04 document circuit/chunk settings and circuit-open diagnosis; upload config tests cover E3b/E3e validation and CLI parsing | `tests/client.test.ts` retry success/409/404 cases, `test_circuit_and_chunk_environment_values_are_parsed`, `test_invalid_circuit_environment_values_are_rejected` |

## 4. Non-Blocking Improvements

### PR22-F04 - P2: Operator Client and Runbook Do Not Expose the New E3 Controls

**References**

- `packages/typescript/api-client/src/edge/ApiClient.ts:46`
- `packages/typescript/api-client/src/edge/HttpApiClient.ts:162-167`
- `packages/typescript/api-client/src/edge/MockApiClient.ts:505-508`
- `docs/design/13-upload-and-synchronization.md:98-112`
- `docs/runbooks/04-upload-backlog.md:15-23`
- `docs/design/16-edge-dashboard.md:26, 162`

The generated OpenAPI type declares the retry operation, but the maintained
`ApiClient`, HTTP client, and mock client expose only `listUploads`. The
dashboard therefore has no typed path to perform the new controlled retry that
design 16 lists as an MVP queue operation. Design 13.8 also omits the new
circuit settings from its configuration example, and runbook 04 does not tell
operators how to interpret `UPLOAD_CIRCUIT_OPEN`, inspect the circuit state, or
safely use manual retry after correcting a permanent cause.

**Recommended solution**

1. Add `retryUpload(uploadTaskId: string): Promise<UploadTask>` to the typed
   API interface, HTTP client, and mock client. Validate the returned task and
   surface 404/409 as typed API errors rather than treating them as success.
2. Add a retry action to the upload queue UI only for `RETRY_WAIT` and
   `PERMANENT_FAILURE`; refresh status after completion and render conflict
   feedback without optimistic mutation.
3. Extend design 13.8 with the circuit threshold/open duration and explain the
   reserved `media_chunk_bytes` setting. Extend runbook 04 with circuit-open
   diagnosis, backoff/probe behavior, manual-retry eligibility, and the rule
   that a retry never authorizes cleanup.

**Acceptance criteria**

- TypeScript unit tests cover a successful retry and 404/409 error mapping for
  the HTTP client; mock and interface implementations stay type-complete.
- UI tests prove retry is visible only in eligible states, never mutates local
  state before server success, and displays a conflict response.
- The runbook names `UPLOAD_CIRCUIT_OPEN`, `upload_circuit_state`, bandwidth
  telemetry, and the post-repair retry procedure; it explicitly preserves
  idempotency keys and receipt-gated deletion.
- The configuration example documents all supported E3 environment/settings
  values and clearly labels chunking as deferred until central contract freeze.

## 5. Required Regression Matrix Before Re-review

| Area | Required evidence |
|---|---|
| Large media throttle | Payload larger than one bucket capacity completes, has bounded throughput, renews its lease, and remains recoverable on stop/failure. |
| Actual wire limit | Base64 JSON body, not raw source bytes, is rate-limited and counted in status telemetry. |
| Local-first safety | A throttled/backlogged upload cannot delay a separate inspection/outbox commit. |
| Circuit breaker | Threshold/open/half-open success/failure, no claims while open, permanent failures excluded, and duplicate-free recovery remain passing. |
| Retry CAS | Scheduler/operator race and two-operator race yield one authoritative transition; ineligible/unknown cases do not mutate. |
| Sync and retention | Retried permanent media immediately recomputes aggregate sync state and cannot become cleanup-eligible without a new verified receipt. |
| Public contracts | OpenAPI/generated types/client interfaces, status units, settings documentation, and runbook describe the implemented behavior consistently. |

## 6. Production Enablement Conditions

Even after the findings above are resolved, E3 does not authorize production
resumable media upload. The central ingestion endpoint, chunk receipt format,
object binding, size/checksum confirmation, and compatibility/version handling
remain explicitly deferred until the Edge-to-central protocol contract freezes.

Site-specific blockers also remain: approved bandwidth ceilings/scheduling
windows, circuit threshold/open-duration values, maximum outage/backlog sizing,
media classes requiring resumable transfer, retention policy, and the response
procedure when protected local capacity reaches its stop reserve.
