# PR-023 Review: Runtime and Live Event Channel (E4)

## 1. Review Decision

**Status: RESOLVED**

PR #23 has the intended E4 structure: transient server-side runtime events,
an explicit mock trigger seam, and a checksum/device-keyed shared-model
registry. The implementation correctly keeps inspection persistence ahead of
`inspection.completed` publication and serializes inference on a shared
Ultralytics predictor.

The initial review found three P1 issues that prevented the runtime channel
from working correctly in supported configurations and from satisfying its
bounded-buffer contract, plus two P2 gaps. All findings are now fixed and
covered by regression tests (see section 3.1).

## 2. Scope and Evidence

Reviewed PR: [#23](https://github.com/dream-studio-china/assembly-vision/pull/23)
(`feat/e4-runtime` into `main`).

Reviewed commits:

```text
503a0e2 docs: add E4 runtime delivery task
63b2e9a feat(edge): WebSocket runtime channel and event sources (E4a)
0aa74ad feat(edge): hardware-agnostic trigger/identity seam with mock source (E4b)
59a83c3 feat(edge): shared read-only model weight cache across instances (E4c)
ced8f9b style(edge): apply ruff multi-context with formatting in runtime event tests
```

Primary requirements:

- [E4 runtime task](../tasks/E4-runtime.md), especially sections 3, 5, 6,
  and 7.
- [REST API and Events](../design/15-rest-api-and-events.md), sections
  15.5-15.7.
- [Edge Dashboard](../design/16-edge-dashboard.md), sections 16.2, 16.10,
  and 16.13.
- [ADR-006: REST Plus WebSocket](../design/decisions/ADR-006-rest-plus-websocket.md).
- [ADR-013: Camera Frame Sources and Multi-Instance Edge](../design/decisions/ADR-013-camera-frame-sources-and-multi-instance.md).
- [Contract 01: Architecture Boundaries](../contracts/01-architecture-boundaries.md).
- [Contract 05: Data, API, and Versioning](../contracts/05-data-api-and-versioning-contracts.md).

The PR reports these local checks as passed: Ruff, MyPy, Pytest (`840 passed,
9 warnings`), pnpm build/lint/test, MkDocs strict, and 12 Playwright tests.
Those checks do not cover the cross-origin authenticated WebSocket path, the
cross-thread full-queue race, or the per-frame start-event transition below.

## 3. Required Findings

### PR23-F01 - P1: Cross-Origin Authenticated WebSocket Uses the Wrong Path and Cannot Carry the Viewer Credential

**References**

- `apps/edge-web/src/pages/LiveInspection.vue:95-115`
- `apps/edge-web/src/services/client.ts:20-24, 54-67`
- `apps/edge-web/tests/client.test.ts:69-103`
- `apps/edge-service/src/assemblyvision_edge/api/routers/ws.py:25-57`
- `docs/design/15-rest-api-and-events.md:157-160`

**Problem**

For the supported cross-origin development setup, `VITE_API_BASE_URL` is an
edge origin such as `http://edge-host:8000`. `runtimeWsUrl()` converts that to
`ws://edge-host:8000/ws/runtime`, but the server endpoint is
`/api/v1/ws/runtime`; the connection receives a 404 before authentication is
considered.

Even if the path is corrected, the dashboard cannot authenticate when
`api_token` is configured. The existing cross-origin flow intentionally keeps
the viewer bearer token in memory and adds it to `fetch` requests. Browser
`WebSocket` cannot set an `Authorization` header, cross-origin mode does not
receive the same-origin session cookie, and query-string tokens are forbidden.
The server therefore closes every such socket with `4401`.

This makes the E4 live-update path unavailable in the documented
token-protected Vite-to-edge development configuration. It also violates the
ADR-006/design-15 requirement for consistent authenticated browser event
delivery without URL tokens.

**Required solution**

1. Centralize API-to-WebSocket URL construction and always preserve the
   `/api/v1` prefix. The origin-only base URL used by the HTTP client must map
   to `ws(s)://<origin>/api/v1/ws/runtime`.
2. Add a short-lived, single-purpose, one-time WebSocket ticket obtained over
   an authenticated REST request. It must be scoped to the runtime channel,
   expire quickly, and be consumed atomically during socket acceptance.
3. Send the ticket outside the URL, for example as a dedicated negotiated
   `Sec-WebSocket-Protocol` value. Validate it before `accept()`, select only a
   fixed non-secret response subprotocol, and never log the ticket. Do not put
   the long-lived bearer token in a query parameter or in browser storage.
4. Retain cookie authentication for same-origin deployments and bearer
   authentication for non-browser clients that can set the header. Update the
   dashboard to select the ticket flow only when it is cross-origin and a
   bearer-backed viewer session exists.
5. Document the ticket lifetime, single-use behavior, failure close code, and
   reverse-proxy requirement. Add bounded cleanup for expired tickets.

**Acceptance criteria**

- With `VITE_API_BASE_URL=http://edge-host:8000`, the browser connects to
  `ws://edge-host:8000/api/v1/ws/runtime`; an HTTPS base uses `wss`.
- A same-origin authenticated session connects without placing any credential
  in the URL.
- A cross-origin token-protected dashboard obtains a ticket through REST and
  receives runtime events; its WebSocket handshake has no bearer token or
  ticket in the URL.
- Invalid, expired, replayed, wrong-channel, and unauthenticated tickets are
  rejected before any event is sent. One successful connection makes the same
  ticket unusable for a second connection.
- Tests cover the URL mapping, ticket issue/consume/replay/expiry paths, the
  existing bearer and session paths, and assert no secret appears in the URL or
  application logs.

### PR23-F02 - P1: Cross-Thread Queue Delivery Can Drop Events With `QueueFull` Instead of Disconnecting the Slow Consumer

**References**

- `apps/edge-service/src/assemblyvision_edge/api/events.py:86-119`
- `apps/edge-service/src/assemblyvision_edge/api/events.py:121-143`
- `apps/edge-service/src/assemblyvision_edge/api/state.py:411-425`
- `docs/tasks/E4-runtime.md:54-56, 91-103, 157-158`

**Problem**

Inspection and upload workers call `publish()` from non-asyncio threads. For a
non-loop publisher, the bus first calls `queue.full()` and then schedules
`queue.put_nowait(envelope)` separately through `call_soon_threadsafe`.

The queue can become full between those two operations. The scheduled
`put_nowait` then raises `asyncio.QueueFull` inside the event loop. It is not
caught, the socket is not sent `_Disconnect`, and the next event may be lost
silently apart from an event-loop exception. `asyncio.Queue` is not a
cross-thread synchronization primitive, so even the pre-scheduling capacity
check must not be used as the correctness decision.

This violates E4 invariant 2: a slow consumer must be disconnected rather than
causing an unbounded/error-prone delivery path. It also undermines sequence-gap
recovery because the failed callback does not guarantee a later message that
would reveal the gap.

**Required solution**

1. For every cross-thread publish, schedule one callback that invokes
   `_deliver(queue, envelope)` on the owning event loop. `_deliver()` must make
   the fullness decision and either enqueue the envelope or drain and enqueue
   exactly one `_Disconnect` sentinel.
2. Do not access or mutate an `asyncio.Queue` from the inspection/upload
   thread. Keep only subscription-map and sequence bookkeeping under the
   thread lock.
3. Make scheduled delivery tolerant of a closing event loop: event publication
   remains best-effort and must never raise into inspection, persistence, or
   the upload worker. Remove/unsubscribe dead subscriptions safely.
4. Preserve event order per subscribed connection and ensure a consumer marked
   for disconnect cannot receive later normal envelopes.

**Acceptance criteria**

- A deterministic worker-thread test fills a queue after the producer's
  scheduling point but before delivery runs. The result is one `_Disconnect`,
  no uncaught `QueueFull`, and no normal event after the sentinel.
- Repeated worker-thread publishes to a full queue remain non-blocking, leave
  the queue bounded, and do not produce event-loop exception-handler output.
- Publishing after a socket/event loop begins shutdown is a no-op for that
  subscription and does not interrupt the inspection loop or upload scheduler.
- Existing tests still prove monotonic sequence allocation and immediate
  same-loop delivery behavior.

### PR23-F03 - P1: Default Per-Frame Inspection Never Publishes `inspection.started`

**References**

- `apps/edge-service/src/assemblyvision_edge/api/state.py:358-392`
- `apps/edge-service/src/assemblyvision_edge/pipeline.py:239-258`
- `apps/edge-service/src/assemblyvision_edge/api/state.py:438-471`
- `docs/design/decisions/ADR-013-camera-frame-sources-and-multi-instance.md:53-61`
- `docs/tasks/E4-runtime.md:26-28, 98-114`

**Problem**

`inspection.started` is emitted only in the temporal-window branch after
`ProductWindowManager.feed()` opens a window. The default ADR-013 runtime mode
has no temporal policy and calls `pipeline.inspect_frame()` directly. That
path publishes `inspection.completed` after durable persistence but never
publishes `inspection.started`.

Per-frame inspection is the established default for enabled multi-instance
runtime, not a dead branch. As a result, dashboards and any other event
consumer receive an incomplete lifecycle for the default mode despite E4a
explicitly promising started and completed events from real inspection-loop
transitions.

**Required solution**

1. Define the lifecycle identity before inference for both modes. The
   per-frame pipeline must accept a caller-provided inspection ID (or expose a
   typed begin-inspection operation) so the runtime can publish one
   `inspection.started` before calling `inspect_frame()` and publish the same
   ID on completion.
2. Keep temporal-window IDs owned by `ProductWindowManager`; do not replace
   identity-sealed window behavior or generate a second ID for it.
3. Publish `inspection.completed` only after `_persist_projection()` succeeds,
   as the current code does. A failed inference/persistence path must not emit
   a false completion; if an explicit failure event is introduced, document its
   semantics and keep REST authoritative.
4. Include `instance_id` consistently in both started and completed payloads
   so a multi-instance dashboard can invalidate the correct resource.

**Acceptance criteria**

- An enabled, non-temporal instance emits exactly one `inspection.started` and
  one `inspection.completed` for one captured frame, in that order, with the
  same `inspection_id`, `instance_id`, and increasing event sequence.
- A temporal identity-window instance still emits one start per opened window
  and one completion per persisted finalized window, including gap and identity
  transition boundaries.
- Inference failure, projection failure, pause, storage stop, and no-frame
  paths do not manufacture a completed event. Their event behavior is tested
  and documented.
- The dashboard reconciliation test proves either mode refreshes the final
  REST record and never treats a start event as a completed decision.

## 3.1 Resolution Status

| Finding | Severity | Resolution | Tests |
|---|---|---|---|
| PR23-F01 | P1 | `POST /api/v1/ws/runtime/ticket` issues a 30-second, single-use ticket consumed atomically during socket acceptance; the dashboard sends it as the negotiated `Sec-WebSocket-Protocol` value; `getRuntimeWsUrl()` preserves the `/api/v1` prefix and the `ReconnectingWebSocket` accepts static subprotocols or a provider re-invoked on every reconnect; cookie and bearer paths unchanged | `test_runtime_ticket_requires_viewer`, `test_runtime_ticket_is_single_use`, `test_expired_runtime_ticket_is_rejected`, `test_bearer_authenticated_socket_streams`, `test_unauthenticated_socket_is_rejected`, api-client `passes static subprotocols` / `resolves protocol providers`, edge-web `maps an http origin base` / `requests a runtime ticket with the in-memory bearer credential` |
| PR23-F02 | P1 | Cross-thread publishes schedule one callback that performs the fullness decision on the owning loop; the producer never touches the queue, a dead-queue marker prevents any envelope after the disconnect sentinel, a closing loop drops the subscription without raising, and the registry lock is reentrant | `test_cross_thread_publish_disconnects_slow_consumer_without_queuefull`, `test_publish_after_loop_close_is_a_noop`, existing same-loop bounded-buffer test |
| PR23-F03 | P1 | `InspectionPipeline.inspect_frame` accepts a caller-provided `inspection_id`; the runtime emits one `inspection.started` before inference and the matching `inspection.completed` (same id and `instance_id`) only after durable persistence, for both per-frame and window modes | `test_per_frame_inspection_publishes_started_then_completed`, existing window/gap tests |
| PR23-F04 | P2 | `WSEventEnvelope` mirrors the full v1 envelope (`event_id`, `type`, `schema_version`, `occurred_at`, `source_id`, `sequence`, `correlation_id`, `data`) with structural validation before sequence handling | `exposes the full v1 envelope fields including data`, `drops malformed envelopes without corrupting the sequence baseline`, updated fixtures use real v1 envelopes |
| PR23-F05 | P2 | `RuntimeEventBus` tracks published events (total/by type), slow-consumer disconnects, and delivery failures; `GET /api/v1/ws/runtime/stats` exposes the authenticated snapshot | `test_stats_count_events_and_slow_consumers`, `test_delivery_failures_are_counted`, `test_runtime_stats_endpoint_requires_viewer` |

## 4. Non-Blocking Improvements

### PR23-F04 - P2: Shared TypeScript Event Contract Still Uses `payload` Rather Than the Server's `data` Envelope

**References**

- `packages/typescript/api-client/src/edge/websocket.ts:10-15`
- `packages/typescript/api-client/tests/websocket.test.ts:34-70`
- `apps/edge-service/src/assemblyvision_edge/api/events.py:27-41`
- `docs/design/15-rest-api-and-events.md:162-177`

`WSEventEnvelope` exposes only `type`, `sequence`, `source_id`, and `payload`,
while the server emits the design 15.6 fields and names the payload `data`.
`LiveInspection.vue` currently only checks `type`, so this does not block its
present refresh behavior. It does leave the shared client contract incorrect
and the sequence tests validate a synthetic legacy shape rather than a real
server envelope.

**Recommended solution**

Update the API-client type to exactly model the version-1 envelope:
`event_id`, `type`, `schema_version`, `occurred_at`, `source_id`, `sequence`,
`correlation_id`, and `data`. Add minimal runtime structural validation before
sequence handling, retain unknown event-type tolerance, and test with the
actual server field names.

**Acceptance criteria**

- A TypeScript consumer can access `event.data` and all mandatory envelope
  fields without casts.
- Valid server envelopes dispatch; malformed envelopes cannot corrupt the
  sequence baseline; unknown event types remain deliverable/ignorable.
- The package tests and at least one dashboard test use a real v1 envelope
  fixture rather than `payload`.

### PR23-F05 - P2: Required WebSocket Connection and Event Counts Are Not Observable

**References**

- `apps/edge-service/src/assemblyvision_edge/api/events.py:76-84`
- `apps/edge-service/src/assemblyvision_edge/api/app.py:87-93`
- `docs/tasks/E4-runtime.md:162, 169-172`
- `docs/contracts/07-deployment-observability-and-operations.md:84-98`

The bus retains `connection_count` and `last_sequence`, but neither is exposed
through an operational metric, structured status, or an authenticated support
endpoint. There is also no published/slow-consumer-disconnect counter. E4's
mandatory matrix explicitly requires observable connection and event counts,
so an operator cannot distinguish an idle dashboard from a failed event feed.

**Recommended solution**

Add a typed runtime-event health snapshot with active connections, events
published by type, slow-consumer disconnects, and delivery callback failures.
Expose it through the existing authenticated device/status or observability
surface, document units/reset semantics, and avoid putting unbounded
per-connection identifiers into metrics.

**Acceptance criteria**

- Connection open/close, published-event, slow-consumer, and failed-delivery
  counters change deterministically in tests.
- Operators can retrieve the current values through an authenticated existing
  status/metrics surface with documented fields.
- Counter collection remains non-blocking and does not expose credentials,
  identities, or payload contents.

## 5. Positive Findings

- `inspection.completed` is emitted only after projection/outbox persistence
  succeeds (`state.py:438-471`), preserving REST/SQLite as the authoritative
  source of truth.
- The runtime event path remains outside detector and rule-engine logic,
  preserving Contract 01 boundaries.
- Mock trigger configuration accepts only explicit `source: mock`; unsupported
  hardware sources reject configuration rather than silently substituting
  simulated identities (`config.py:499-534`).
- The trigger correlator leaves frames without a validated identity unchanged,
  allowing the identity-sealed window manager to fail closed instead of
  fabricating evidence (`trigger/source.py:104-118`).
- The review remediation correctly adds a per-artifact inference lock to the
  shared registry, avoiding concurrent access to mutable Ultralytics predictor
  state while keeping different artifacts/devices independent.

## 6. Resolution Checklist

| Finding | Severity | Required before merge | Resolution status |
|---|---:|---|---|
| PR23-F01 | P1 | Yes | Resolved |
| PR23-F02 | P1 | Yes | Resolved |
| PR23-F03 | P1 | Yes | Resolved |
| PR23-F04 | P2 | No, required before E4 production readiness | Resolved |
| PR23-F05 | P2 | No, required before E4 production readiness | Resolved |

## 7. Final Merge Gate

All findings are resolved with regression tests satisfying their acceptance
criteria, and the E4 task/documentation were updated for the authentication
and event-envelope behavior changes. The mandatory quality gates pass again:

```text
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
