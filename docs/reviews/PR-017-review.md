# PR-017 Review: Durable Edge Upload Outbox and Scheduler

## Scope

Code review of PR #17 (`dev` against `main`, commit `7c0b9b9`) covering the
transactional outbox, SQLite lease handling, upload sinks, runtime wiring,
configuration, documentation, and contract-06 test coverage.

Relevant requirements reviewed:

- `docs/design/12-local-storage-and-retention.md`
- `docs/design/13-upload-and-synchronization.md`
- `docs/design/14-data-model-and-database.md`
- `docs/design/decisions/ADR-005-local-first-storage-and-delayed-upload.md`
- `docs/contracts/01-architecture-boundaries.md`
- `docs/contracts/04-edge-storage-upload-contracts.md`
- `docs/contracts/06-testing-quality-and-ci-contracts.md`

## Merge Decision

**Resolved — all findings fixed and validated on `dev` (PR #17 updated).**

The original review found that the PR could not safely transfer binary media,
did not make inspection persistence and task creation one recoverable unit,
permitted stale workers to overwrite a newer lease holder, and could report an
inspection as synchronized without a verified server receipt or its required
media. The normal `serve` path also provided no way to configure the
scheduler, while the programmatic HTTP path permitted plaintext credential and
evidence transmission. Each finding (F1-F8) below now has a fix commit with
regression tests, and the full quality gates pass.

## Resolution Status

Each finding was fixed on `dev` in its own commit with regression tests that
failed before the fix and pass after:

- **F1** - `HttpUploadSink` sends `base64.b64encode(payload)` with the byte
  size in the typed body; a mock-transport test round-trips non-ASCII bytes
  exactly and verifies size and checksum (`4f8b9b6`).
- **F2** - `EdgeRepository.persist_inspection_and_enqueue_uploads` commits the
  immutable projection, media, evidence, and all idempotent upload tasks in one
  SQLite transaction; runtime projection, dev import, and startup
  reconciliation use it for every bundle, so a stranded `LOCAL_ONLY` record is
  repaired rather than skipped, and interrupted `force_close` records are
  mirrored (`53a6385`).
- **F3** - `claim_upload_tasks` persists a unique per-task fencing token in
  `lease_owner` (migration 0004) and returns `ClaimedUploadTask`; every
  terminal or retry update requires `IN_PROGRESS` plus the matching token and
  returns the affected row count, so a late worker cannot overwrite a reclaimed
  task (`4c651b0`).
- **F4** - `MEDIA` tasks are claimable only after their `INSPECTION` task is
  `SUCCEEDED`, with inspection tasks ordered first; tests prove no media
  request is sent before the inspection receipt and that media blocked behind
  failed metadata stays `PENDING` (`6e4190d`).
- **F5** - `HttpUploadSink` parses a bounded typed receipt and accepts a 2xx
  only when it echoes the idempotency key, object, kind, byte size, and
  checksum; verified receipts and central object ids are persisted (migration
  0005); inspection synchronization is recomputed from every required task as
  `QUEUED`/`PARTIAL`/`SYNCED`/`FAILED` (`d956493`).
- **F6** - `UploadSettings` plus CLI/env wiring (`AV_EDGE_UPLOAD_*`) activate
  the scheduler through the supported `serve` path; a configured local sink
  drains end to end, an omitted configuration is an explicitly observable
  disabled state, and invalid numeric configuration fails startup (`ccdefc8`).
- **F7** - upload endpoints must be HTTPS with a non-empty host and no embedded
  credentials (plaintext only under an explicit dev flag); the sink uses the
  separate `AV_EDGE_UPLOAD_TOKEN` credential and never the viewer `api_token`,
  with tests proving the viewer credential is never sent (`406150e`).
- **F8** - an injected clock anchors every transition to the response/failure
  time, so a slow request cannot erode `Retry-After`; the deterministic test
  verifies `next_attempt_at = response_time + 60` (`81fc6f4`).
- **Post-resolution hardening** - final review closed four small gaps in the
  original fixes: receipts now require matching size/checksum and a media
  central-object ID before success; repository sync requires persisted verified
  receipt metadata; `create_app` revalidates programmatic upload settings and
  limits plaintext development HTTP to loopback; media size and explicit zero
  bandwidth configuration now fail closed (follow-up commit pending).

Validation executed after the fixes (all green):

```text
git diff --check
uv run ruff check .
uv run ruff format --check .
uv run mypy .
uv run pytest            # full repo suite, exit 0
uv run mkdocs build --strict
```

## Validation Performed

The review used the actual PR range and current GitHub PR status:

```text
git diff --check origin/main...dev
git diff --find-renames --find-copies origin/main...dev
gh pr view 17 --json state,mergeStateStatus,statusCheckRollup
```

Results:

- The diff whitespace check passes.
- PR #17 is open and mergeable; the two CI quality jobs, web jobs, and CodeQL
  checks report success.
- Passing CI does not exercise the data-loss, binary-payload, fencing,
  dependency-order, receipt-integrity, deployment-configuration, or transport
  security cases below.

## Blocking Findings

### F1. HTTP media uploads corrupt every non-ASCII payload

**Severity:** P1 / High

**Locations:**

- `apps/edge-service/src/assemblyvision_edge/upload/scheduler.py:103-110`
- `apps/edge-service/src/assemblyvision_edge/upload/scheduler.py:276-288`

`HttpUploadSink.upload()` labels the body field `payload_b64`, but produces it
with `payload.decode("ascii", errors="ignore")`. JPEG, PNG, clip, and video
bytes are not ASCII; this silently drops every invalid byte. The server thus
receives different data from the payload whose SHA-256 was recorded in the
task. A 2xx response subsequently marks the media task successful.

This violates the media checksum and completion requirements in contract 04
section 6 and design 13.3/13.4.

**Resolution:**

1. Define the central ingestion payload contract before sending bytes. For the
   current JSON transport, encode with
   `base64.b64encode(payload).decode("ascii")`; for production media, prefer
   the documented presigned/resumable binary upload path instead of embedding
   large media in JSON.
2. Include the media byte size and SHA-256 in the typed request model and have
   the central endpoint validate both after decoding or receiving the stream.
3. Apply a bounded request-body/media-size policy so Base64 expansion cannot
   exhaust worker memory.

**Acceptance criteria:**

- A test uploads a payload containing `b"\\x00\\xffJPEG\\x80"` through an
  `httpx.MockTransport`, Base64-decodes the received field, and asserts exact
  byte equality and matching SHA-256.
- A server-side contract test rejects malformed Base64, wrong byte size, and
  wrong checksum without creating/binding an object.
- A successful media task is impossible unless the received bytes and checksum
  match the task metadata.

### F2. Inspection projection and outbox creation are separate commits, and recovery skips stranded records

**Severity:** P1 / High

**Locations:**

- `apps/edge-service/src/assemblyvision_edge/api/state.py:299-302`
- `apps/edge-service/src/assemblyvision_edge/persistence/reconcile.py:107-122`
- `apps/edge-service/src/assemblyvision_edge/persistence/repository.py:194-398`
- `apps/edge-service/src/assemblyvision_edge/persistence/repository.py:715-804`

`upsert_inspection()` commits before `enqueue_inspection_uploads()` starts a
second transaction. If enqueue fails, or the process terminates in between,
the inspection remains `LOCAL_ONLY` without upload tasks. On the next startup,
`reconcile_output_root()` only calls enqueue when `upsert_inspection()` returns
`"inserted"`; an identical stranded record returns `"unchanged"` and is
permanently skipped. The same issue affects records persisted before this PR.

This breaks the recoverable atomic unit required by design 12.4, ADR-005, and
contract 04 section 3: a completed inspection can exist without its required
upload tasks.

**Resolution:**

1. Replace the public two-call workflow with one repository operation, for
   example `persist_inspection_and_enqueue_uploads(record)`, that validates,
   inserts the immutable projection/media/evidence, inserts all idempotent
   tasks, and transitions synchronization state in one SQLite transaction.
2. Make `reconcile_output_root()` call the idempotent operation for every valid
   bundle, not just records newly inserted on that pass. It must repair any
   `LOCAL_ONLY` record and report conflicts without partial mutation.
3. Preserve the current safe behavior for immutable content conflicts and
   duplicate task keys.

**Acceptance criteria:**

- Failure injection at every task insert rolls back the inspection, evidence,
  media, task rows, and state transition together.
- A database preseeded with a valid `LOCAL_ONLY` inspection but no tasks gains
  exactly one inspection task and one task per media item after reconciliation.
- Simulating a crash after the original projection commit and before enqueue,
  then restarting, repairs the outbox exactly once.
- Reconciliation of a fully queued record creates no duplicate tasks.

### F3. Lease expiry has no owner/token fencing, so a late worker can overwrite a newer worker

**Severity:** P1 / High

**Locations:**

- `apps/edge-service/migrations/versions/0003_upload_lease.py:19-24`
- `apps/edge-service/src/assemblyvision_edge/persistence/repository.py:806-944`
- `apps/edge-service/src/assemblyvision_edge/upload/scheduler.py:209-256`

The migration stores only `lease_expires_at`; it does not store the required
lease owner/token. After a task is reclaimed, the first worker can return from
a slow request and all three completion methods update solely by
`upload_task_id`. Its late `SUCCEEDED`, retry, or permanent-failure update can
overwrite the state produced by the second worker. This can falsely mark a task
successful, clear a new lease, or change a verified result into a failure.

Contract 04 section 4 and design 14.5 require both a lease owner and expiry
while a task is in progress.

**Resolution:**

1. Add `lease_owner` (a unique per-claim UUID/token) with an Alembic migration
   and expose the lease information only to the internal worker model as
   appropriate.
2. Have `claim_upload_tasks()` generate and atomically persist a unique token
   for each claimed task, returning that token with the claim.
3. Require `status = 'IN_PROGRESS' AND lease_owner = :token` in every terminal
   or retry update. Treat zero affected rows as a lost lease and do not mutate
   inspection synchronization state.
4. Consider lease renewal for uploads allowed to exceed the configured lease;
   otherwise bound request/upload duration below it.

**Acceptance criteria:**

- Two simulated workers claim the same task across lease expiry; a late first
  worker cannot modify the task or inspection state after the second claim.
- The current owner can still transition exactly once to success, retry, or
  permanent failure.
- Migration, repository, and schema tests prove both `lease_owner` and
  `lease_expires_at` are cleared only by the matching owner.

### F4. Media tasks can run before their inspection metadata task

**Severity:** P1 / High

**Locations:**

- `apps/edge-service/src/assemblyvision_edge/persistence/repository.py:725-743`
- `apps/edge-service/src/assemblyvision_edge/persistence/repository.py:829-866`
- `apps/edge-service/src/assemblyvision_edge/upload/scheduler.py:207-238`

The inspection and all media tasks receive the same `created_at`. Claiming then
orders ties by random `upload_task_id`, so a media task can be sent first. The
design sequence requires metadata ingestion before media binding (design
13.4/13.7). A central endpoint that correctly rejects unknown inspection media
with `404` will be classified as a permanent failure by `HttpUploadSink`, even
though the metadata would have succeeded later in the same batch.

**Resolution:**

1. Model the dependency explicitly: a media task is due only after its parent
   inspection task has a verified successful receipt, or use a single
   inspection-session state machine that uploads metadata before issuing media
   work.
2. Keep media in `PENDING` (with a dependency reason) rather than treating a
   pre-metadata server response as permanent evidence failure.
3. Use server-confirmed required-media information to determine which media
   tasks must run, rather than assuming every artifact can be accepted at once.

**Acceptance criteria:**

- A test with an endpoint that returns `404` before metadata proves no media
  request is made until the matching inspection receipt exists.
- Metadata succeeds first, required media drain afterward, and no task is
  marked permanent merely because its parent was not yet ingested.
- Restarting between metadata and media preserves the dependency and completes
  only the remaining media tasks without duplication.

### F5. Any 2xx response is treated as verified success, and inspection state becomes `SYNCED` while media remains pending or failed

**Severity:** P1 / High

**Locations:**

- `apps/edge-service/src/assemblyvision_edge/upload/scheduler.py:119-120`
- `apps/edge-service/src/assemblyvision_edge/upload/scheduler.py:234-257`
- `apps/edge-service/src/assemblyvision_edge/persistence/repository.py:869-903`
- `apps/edge-service/src/assemblyvision_edge/persistence/schema.py:112-132`

The HTTP sink accepts an empty or arbitrary 2xx body and substitutes the local
idempotency key as a receipt. No typed central receipt, central object ID,
server-confirmed byte size, or checksum is validated or persisted. Independently,
`mark_upload_succeeded()` sets the whole inspection to `SYNCED` as soon as its
metadata task succeeds, including when its required media is still pending or
has reached `PERMANENT_FAILURE`.

This violates contract 04 section 6 (validate completion, store central object
identifier, update only after confirmed success) and misuses the documented
`PARTIAL`/`SYNCED`/`FAILED` synchronization states in design 14. It also makes
future retention unable to prove that every required artifact received a
verified receipt.

**Resolution:**

1. Define typed request/receipt contracts owned by the central ingestion API.
   The receipt must identify the idempotency key, inspection/object, immutable
   content hash, byte size, checksum, and central object identifier where
   applicable.
2. Parse responses with a size limit; mark a task successful only when the
   receipt exactly matches its task and payload. Persist verified receipts and
   central object IDs in dedicated columns/tables.
3. Compute inspection synchronization state from all required tasks:
   `QUEUED` while work is outstanding, `PARTIAL` after metadata with remaining
   media, `SYNCED` only after all required tasks have verified receipts, and
   `FAILED` when a required task is permanently failed. Do not let this state
   authorize retention by itself without the stored verified receipts.

**Acceptance criteria:**

- Empty, malformed, oversized, wrong-idempotency-key, wrong-object-ID, wrong
  checksum, and wrong-size 2xx responses leave the task retryable or failed;
  none can mark it successful.
- A successful media task stores the central object identifier and verified
  receipt metadata.
- Metadata success with pending media reports `PARTIAL`; a required media
  permanent failure reports `FAILED`; only all-required-task verified success
  reports `SYNCED`.
- Retention tests prove pending, partial, failed, and receipt-less tasks cannot
  make media deletion eligible.

### F6. The deployed `serve` command cannot configure or enable uploads

**Severity:** P1 / High

**Locations:**

- `apps/edge-service/src/assemblyvision_edge/api/settings.py:9-26`
- `apps/edge-service/src/assemblyvision_edge/api/app.py:95-108`
- `apps/edge-service/src/assemblyvision_edge/cli.py:82-105`
- `apps/edge-service/src/assemblyvision_edge/cli.py:266-290`

`ServerSettings` contains `upload_base_url` and `upload_sink_dir`, but the
normal `assemblyvision-edge serve` command has no flags or environment mapping
for either setting, timeout, retry policy, lease duration, credentials, or
bandwidth. `_run_serve()` therefore always constructs settings with both
destinations unset, and the scheduler is always disabled in the supported
deployment entry point. Tasks accumulate indefinitely despite the PR's claim
that the worker is wired.

This also silently fails design 13.8's site configuration and observability
requirements rather than making an intentionally disabled synchronization
state explicit.

**Resolution:**

1. Add a typed upload configuration section to the edge configuration contract
   (endpoint, separate credential source, connect/request timeout, retry,
   lease, worker concurrency/batch, bandwidth, and explicit local development
   sink).
2. Parse and validate it in the production configuration loader, then wire it
   through the supported `serve` command/environment. Do not put credentials in
   CLI process arguments or committed configuration files.
3. Surface scheduler configuration/health and an explicit `sync_ready`/alert
   state so an operator can distinguish an intentionally disabled sink from a
   broken worker or growing queue.

**Acceptance criteria:**

- An end-to-end `serve` configuration test proves that a configured local sink
  starts the worker and drains an outbox task.
- An HTTPS central configuration starts `HttpUploadSink` with configured
  timeouts/retry/lease values; omitted configuration leaves it disabled and
  produces an explicit observable disabled state.
- Invalid endpoint, credential reference, timeout, retry, lease, and bandwidth
  values fail startup with an actionable configuration error.

### F7. HTTP endpoints and the edge viewer token are accepted for central uploads

**Severity:** P1 / High

**Locations:**

- `apps/edge-service/src/assemblyvision_edge/api/app.py:103-105`
- `apps/edge-service/src/assemblyvision_edge/api/settings.py:22-26`
- `apps/edge-service/src/assemblyvision_edge/upload/scheduler.py:82-116`
- `apps/edge-service/tests/test_upload_scheduler.py:347,363`

`HttpUploadSink` accepts any URL, including `http://`, and the application
passes the local viewer API token as the central bearer credential. A configured
plaintext endpoint consequently receives both inspection evidence and the
local-viewer token. This contradicts design 13.8's TLS, per-device credential,
least-privilege, and provisioning requirements. The existing unit tests encode
the insecure HTTP case as valid behavior.

**Resolution:**

1. Validate `upload_base_url` as HTTPS at configuration load, including a
   non-empty host and approved path. Permit HTTP only through an explicit,
   test-only/local-development mode that cannot run in a production build or
   non-loopback deployment.
2. Introduce a distinct least-privilege upload credential reference; never
   reuse `api_token`, which authenticates local dashboard clients.
3. Configure certificate validation and rotation outside the image, and ensure
   logs redact endpoint credentials and authorization headers.
4. Change HTTP tests to use `https://central.invalid` with mock transport and
   add validation tests for rejected plaintext URLs and token separation.

**Acceptance criteria:**

- Production configuration rejects `http://` and malformed URLs before the
  application starts the scheduler.
- A configured HTTPS sink receives a dedicated upload credential; the local
  viewer credential is never included in its `Authorization` header.
- Tests cover certificate-validation configuration and prove credentials do
  not appear in scheduler/application logs.

## Follow-up Finding

### F8. Retry deadlines are calculated from batch start, not from the failure response

**Severity:** P2 / Medium

**Locations:**

- `apps/edge-service/src/assemblyvision_edge/upload/scheduler.py:209-215`
- `apps/edge-service/src/assemblyvision_edge/upload/scheduler.py:244-256`

`run_once()` captures `now` before loading payloads and performing the HTTP
request. `_process()` uses that old time to create `next_attempt`. A slow read
or request can consume part or all of a server's `Retry-After` duration, so the
next request occurs too early. This defeats the documented throttling policy in
design 13.5.

**Resolution:**

1. Capture the retry base time immediately after the sink returns or raises.
2. Calculate both jitter and `Retry-After` from that response/failure time.
3. Keep the task's `updated_at` consistent with the same transition time.

**Acceptance criteria:**

- A sink delayed by more than one second and returning `Retry-After: 60`
  produces `next_attempt_at >= response_time + 60 seconds`.
- Transport errors and permanent payload failures retain their existing state
  classification.
- A deterministic clock/injected time source makes this behavior testable
  without timing-sensitive sleeps.

## Residual Notes

- Design 13.5/13.9 additionally calls for a circuit breaker, bounded bandwidth
  enforcement, queue-age/count/byte metrics, success/failure rate, latency,
  throughput, and last-contact observability. The configuration surface for
  bandwidth exists, but throttling and the circuit breaker remain in the
  connected-pilot completion scope before enabling site uploads.
- The central ingestion endpoint and its contract-verified media binding do
  not exist yet; the edge-side receipt contract implemented here defines what
  the endpoint must return, and the remaining `served` integration tests
  belong with that endpoint.
- `EdgeRuntime._run_instance_loop()` now persists interrupted `force_close`
  records through the atomic projection (`53a6385`), closing the earlier gap.
- Pre-existing latent issue observed during validation (not introduced by this
  PR and out of scope): `migrations/env.py` calls `fileConfig` on
  `alembic.ini`, whose default `disable_existing_loggers=True` marks every
  `assemblyvision.*` logger `disabled` after the first migration runs, so the
  application's own `LogBuffer` captures no application log records. A
  follow-up should pass `disable_existing_loggers=False` and add a log-endpoint
  content test.
