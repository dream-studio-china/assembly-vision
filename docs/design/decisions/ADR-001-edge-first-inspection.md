# ADR-001: Edge-First Inspection

## 1. Status

Accepted

## 2. Context

AssemblyVision inspects moving products in a factory where the network and central server may be unavailable. Camera capture, barcode resolution, two-stage detection, temporal aggregation, deterministic rules, and durable evidence form one production-critical decision path. A network round trip would add an uncontrolled dependency and could stop inspection or leave products without a timely result.

The central system remains necessary for fleet history, configuration and model management, review, reporting, users, audit, and synchronization.

## 3. Decision

All production-critical image processing and final per-product `OK`/`NG` decisions execute on the edge industrial computer. The edge stores decisions and required evidence locally and continues inspecting while disconnected. Central services receive delayed, idempotent uploads and are never required for the real-time decision.

The edge owns camera and trigger integration, product windows, barcode recognition, product-type mapping, inference, ROI, aggregation, rule evaluation, local database/media, upload queue, and local operational UI. The central server owns cross-device and administrative functions.

## 4. Scope

This decision applies to the one-month target and production architecture. The static-image MVP exercises the same decision core without camera, offline synchronization, or central services. It does not require every administrative feature to run at the edge.

## 5. Consequences

### 5.1 Positive

- Inspection availability and latency are independent of WAN and central availability.
- Decisions and evidence can be correlated at their source.
- Network use is bounded by selected evidence rather than every video frame.
- Central maintenance cannot directly interrupt line decisions.

### 5.2 Negative and Trade-offs

- Edge hardware must support inference, storage, monitoring, and upgrades.
- Fleet deployments duplicate runtime components and require version governance.
- Delayed uploads mean central dashboards and review can be stale.
- Offline capacity and queue reconciliation become production concerns.

## 6. Alternatives

- **Central-only inference:** rejected because it makes network/server availability and latency part of every decision.
- **Cloud inference with edge fallback:** rejected initially because two decision paths complicate validation and consistency.
- **Camera appliance decides, server records:** rejected because required barcode, rules, aggregation, traceability, and configurable models exceed an unspecified camera appliance capability.

## 7. Open Questions and Validation Required

- Candidate edge CPU/GPU capacity and production-resolution latency.
- Maximum expected disconnection and required local storage capacity.
- Physical line behavior when the edge is unavailable.

These questions affect sizing and operations, not the accepted edge-first boundary.

## 8. Links

- [Deployment and Operations](../20-deployment-and-operations.md)
- [Observability and Support](../23-observability-and-support.md)
- [ADR-005: Local-first storage and delayed upload](ADR-005-local-first-storage-and-delayed-upload.md)
