# E4 Pipeline: Runtime and Live Event Channel

## 1. Purpose

E4 makes the edge runtime observable and product-window boundaries hardware
ready without requiring the physical camera, barcode, or trigger hardware:

- A WebSocket runtime channel pushes ephemeral inspection/device/upload
  notifications to the dashboard, replacing the polling REST preview as the
  live-update path while REST remains the source of truth (ADR-006, design
  15.5/15.6).
- A hardware-agnostic trigger/barcode/identity seam feeds the
  `window_strategy: identity` product-window boundary from a validated
  product-identity source, with a deterministic mock source for development
  and acceptance tests. The time-only fallback stays a development mode.
- Multiple inspection instances share read-only model weights by manifest
  identity so per-instance pipelines do not reload identical artifacts
  (ADR-013 Phase 3).

## 2. Scope and Non-Goals

### In scope

- In-memory runtime event bus with per-`(source_id, channel)` monotonic
  sequence, bounded buffering, and slow-consumer disconnection.
- `WS /api/v1/ws/runtime` authenticated endpoint emitting the design 15.6
  envelope for `inspection.started`, `inspection.completed`,
  `device.status_changed`, and `upload.changed`.
- Frontend wiring so the live view refreshes on events and reconciles from
  REST on reconnect/sequence gaps (design 16 rule 3).
- A `TriggerSource` protocol plus deterministic `MockTriggerSource` that
  injects validated product identity into the existing identity-sealed window
  path; mock sources are development/test-only.
- A model-weight cache keyed by manifest checksum shared across instances.

### Out of scope

- Vendor camera SDKs, real barcode decoding, and physical photo-eye/PLC
  triggers (hardware decisions, E6 acceptance).
- Central WebSocket (`/api/v1/ws/organization`) and Redis pub/sub.
- Durable event replay: the bus is ephemeral by design (REST is authoritative).
- WebRTC/MJPEG full-frame previews; the dashboard continues to use the
  bounded JPEG preview for pixels.
- Pause/resume or camera-reconnect commands over WebSocket (REST commands
  remain, design 15.5).

## 3. Safety Invariants

The following invariants are mandatory in every E4 change and test:

1. WebSocket events are transient notifications only; the API never relies on
   the bus for inspection execution, durability, or synchronization, and a
   reconnecting client must refresh REST state before trusting pushed data.
2. Event publishing never blocks inspection, persistence, or the upload
   worker: the bus is non-blocking, buffers are bounded, and a slow consumer
   is disconnected rather than throttling the publisher.
3. WebSocket authentication uses the same viewer credential/session model as
   REST; tokens never appear in URL query logs, and unauthenticated sockets
   are rejected before any event is sent.
4. The sequence is monotonic per `(source_id, channel)`; a gap always means
   events were lost and clients must refetch REST. Reconnects preserve
   continuity and do not signal a gap (design 14.4.1).
5. A product window may release `OK` only when every frame belongs to one
   validated identity; missing identity, identity transition, or a confirmed
   multi-product frame fails the window closed as `NG` (PR-015 F1, unchanged).
   The identity seam only supplies that validated identity; mock sources are
   development/test-only and never misrepresent hardware as production data.
6. Shared model weights are keyed by the immutable manifest checksum; only
   identical artifacts are reused, and the cache never shares mutable
   inference state between instances.
7. The time-only window fallback remains explicitly a development mode and is
   never claimed as a production product boundary.

## 4. Required Decisions Before Production Enablement

- WebSocket proxy/firewall support and idle-timeout configuration (design 15.8
  open question).
- Selected trigger/barcode hardware, signal timing, and identity correlation
  rules for `window_strategy: identity` at each site.
- Per-instance model sharing policy on the deployed hardware (memory budget,
  warm-up behavior).

## 5. Delivery Pipeline

Each gate is independently reviewable.

### E4a: WebSocket Runtime Channel

**Implementation**

- Add a `RuntimeEventBus` (in-memory) that assigns monotonic sequence numbers
  per `(source_id, channel)`, keeps a bounded per-connection buffer, and
  disconnects consumers that fall behind instead of blocking publishers.
- Add `WS /api/v1/ws/runtime` authenticated with the existing viewer bearer
  token or session cookie; emit the design 15.6 envelope (`event_id`, `type`,
  `schema_version`, `occurred_at`, `source_id`, `sequence`, `correlation_id`,
  `data`).
- Publish events from real runtime transitions: inspection started/completed
  from the inspection loop, device status changes from pause/resume and
  storage fault transitions, and upload changes from the scheduler worker.
- Wire the dashboard live view to the event feed; on reconnect or a sequence
  gap the UI refetches REST state (existing `ReconnectingWebSocket`
  contract).

**Exit criteria**

- Tests prove: unauthenticated sockets are rejected; envelopes carry the
  documented fields with monotonic per-source sequence; a bounded buffer
  disconnects a slow consumer without blocking the publisher; events are
  emitted from real inspection completion, pause/resume, and upload-scheduler
  transitions.
- The frontend test proves the live view updates from a typed event and
  refetches REST after a sequence gap, and the preview polling is not required
  for correctness.

### E4b: Trigger/Barcode/Identity Seam

**Implementation**

- Define a `TriggerSource` protocol emitting deterministic
  `TriggerEvent`s (product identity, optional barcode, timing on the
  monotonic clock) and a `MockTriggerSource` driven by configuration for
  development and tests.
- Correlate trigger identity with captured frames so the existing
  `window_strategy: identity` window manager receives `product_identity` per
  frame; identity-sealed windows keep their fail-closed semantics.
- Keep mock sources gated so they can never masquerade as production hardware.

**Exit criteria**

- Tests prove the mock trigger produces a deterministic identity/barcode
  sequence and that identity-sealed windows open, seal, transition, and fail
  closed exactly as the existing PR-015 window contract requires.
- A test proves a window fed by mock identities releases exactly one `OK` per
  identity and aborts as `NG` on missing/transitioning identity without any
  fabricated evidence.

### E4c: Shared Model Weight Cache

**Implementation**

- Add a process-wide cache for loaded YOLO weights keyed by the manifest
  checksum; multiple instances referencing the same artifact share one model.
- Ensure the cache is read-only (no mutable inference state) and that
  distinct artifacts are never merged.

**Exit criteria**

- A test proves two instances with the same manifest checksum load the model
  once and instances with different manifests load separately; a
  cache-miss/eviction path is covered and no mutable state is shared.

## 6. Mandatory Test Matrix

| Area | Required cases |
|---|---|
| WebSocket | auth reject; envelope fields; monotonic per-source sequence; bounded buffer + slow-consumer disconnect without publisher block; gap semantics |
| Event sources | inspection completed; pause/resume device status; upload change from the scheduler |
| Identity seam | mock trigger deterministic sequence; identity window open/seal/transition/fail-closed; one OK per identity; no fabricated evidence |
| Shared weights | same-manifest reuse (one load); distinct manifests separate; read-only sharing |
| Frontend | event-driven live refresh; REST refetch on gap/reconnect |
| Observability | WebSocket connection/event counts observable; no URL tokens |

## 7. Merge and Release Gates

- Focused changes with typed interfaces and no unstructured dictionary at the
  public boundary.
- Regression tests for every changed safety invariant.
- Passing mandatory quality commands: `ruff check/format`, `mypy`, `pytest`,
  `mkdocs build --strict`, `pnpm -r build/lint/test`, edge-web e2e.
- Review evidence that WebSocket events never block inspection or upload, and
  that mock trigger sources cannot masquerade as production hardware.

## 8. References

- [ADR-006: REST Plus WebSocket](../design/decisions/ADR-006-rest-plus-websocket.md).
- [REST API and Events](../design/15-rest-api-and-events.md): sections 15.5-15.7.
- [Edge Dashboard](../design/16-edge-dashboard.md): live view and WebSocket
  reconciliation rules.
- [Camera and Image Acquisition](../design/07-camera-and-image-acquisition.md):
  trigger and product-window strategy.
- [ADR-013: Camera Frame Sources and Multi-Instance Edge](../design/decisions/ADR-013-camera-frame-sources-and-multi-instance.md).
- [PR-015 review](../reviews/PR-015-review.md): identity-sealed window contract.
