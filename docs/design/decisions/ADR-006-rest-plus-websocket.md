# ADR-006: REST Plus WebSocket

## 1. Status

Accepted

## 2. Context

Edge and central applications need queryable resources and commands as well as timely status updates. Inspection history, devices, rules, models, uploads, reviews, and configuration fit resource-oriented APIs. Camera/inspection/device/queue status benefits from push updates, but push delivery alone is not a reliable source of record.

## 3. Decision

Use versioned JSON REST APIs for authoritative queries, commands, ingestion, pagination, and media metadata. Use authenticated WebSocket channels for ephemeral inspection and device-status notifications to the dashboards. On connection or reconnection, clients retrieve authoritative state through REST; WebSocket messages carry identifiers, sequence/version information, and prompt clients to update state.

Generate the TypeScript API client/types from FastAPI OpenAPI. Upload endpoints use stable inspection identifiers and idempotency keys. Large media uses bounded multipart/resumable behavior when validated as necessary rather than WebSocket transfer.

## 4. Scope

This applies to browser-to-edge, browser-to-central, and edge-to-central application interfaces. Camera SDK callbacks and internal in-process events are not required to use REST or WebSocket.

## 5. Consequences

### 5.1 Positive

- Conventional, testable APIs with strong tooling and typed client generation.
- Dashboards receive timely status without aggressive polling.
- REST reconciliation handles missed or reordered push events.
- HTTP idempotency and proxy behavior are well understood.

### 5.2 Negative and Trade-offs

- Two communication modes require consistent authentication and versioning.
- WebSocket reconnect, backpressure, authorization expiry, and ordering need tests.
- REST is not ideal for every high-volume internal event stream.
- Generated clients must be updated as part of contract changes.

## 6. Alternatives

- **REST polling only:** simpler but less timely and more wasteful for live status.
- **WebSocket for all operations:** rejected because state recovery, commands, pagination, and idempotent uploads are clearer with REST.
- **GraphQL subscriptions:** rejected as unnecessary schema/runtime complexity for known API groups.
- **gRPC everywhere:** strong service contracts but adds browser/proxy complexity without an established need; may be reconsidered for a measured internal use case.
- **Message broker between edge and central:** not required for initial delayed upload; central background jobs may use a broker where specific asynchronous jobs justify it.

## 7. Open Questions and Validation Required

- Customer proxy/firewall support for WebSocket and idle timeout settings.
- API compatibility/support window and resumable media threshold.
- Local edge authentication/session behavior during prolonged offline use.

## 8. Links

- [Security and Source Distribution](../21-security-and-source-distribution.md)
- [Observability and Support](../23-observability-and-support.md)
- [ADR-003: Vue 3 and TypeScript frontend](ADR-003-vue-3-and-typescript-frontend.md)
