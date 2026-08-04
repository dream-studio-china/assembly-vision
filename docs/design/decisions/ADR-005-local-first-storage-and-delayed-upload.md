# ADR-005: Local-First Storage and Delayed Upload

## 1. Status

Accepted

## 2. Context

Edge inspection must continue through network and central outages. Decisions require durable local traceability, while uploading every video frame would consume unnecessary bandwidth and storage. Retries can occur after the central server has committed a request but before the edge receives its response.

## 3. Decision

Persist inspection metadata, versions, evidence paths, final outcomes, and upload tasks locally before treating an inspection as complete. Store key media and configured rolling/full video locally under retention policy. Upload selected evidence asynchronously through a persistent queue with retry/backoff, idempotency keys, duplicate prevention, status tracking, checksums, and durable central receipts.

OK uploads normally include metadata and one representative key frame. NG uploads include richer metadata, missing/low-confidence components, multiple and annotated frames, product ROI, optional short clip, and relevant errors. System exceptions include state, evidence, logs, and time.

## 4. Scope

SQLite is the initial edge store; PostgreSQL may be used for larger edge installations only when justified. The central server uses PostgreSQL and filesystem/object-storage abstraction. Exact retention periods and media selection are deployment configuration.

## 5. Consequences

### 5.1 Positive

- Network and central outages do not block decisions.
- Durable queueing supports eventual synchronization and traceability.
- Selective uploads control network and central storage demand.
- Idempotent receipts resolve ambiguous retry outcomes.

### 5.2 Negative and Trade-offs

- Edge disk sizing, cleanup, database recovery, and queue monitoring are mandatory.
- Central state is eventually consistent and can be stale.
- Media/database reconciliation is needed after failures.
- Long outages can exceed local capacity and require safe degradation or pause.

## 6. Alternatives

- **Write directly to the central database:** rejected due to network coupling and security boundary violations.
- **In-memory upload queue:** rejected because restart/power loss would lose tasks.
- **Upload every frame:** rejected due to bandwidth/storage cost and unnecessary data exposure.
- **Metadata only:** rejected because review, support, and acceptance require image evidence.

## 7. Open Questions and Validation Required

- Retention periods and local disk capacity by media class.
- Expected maximum outage and upload bandwidth/clip size.
- Safe line behavior if durable storage reaches its critical reserve.

## 8. Links

- [Deployment and Operations](../20-deployment-and-operations.md)
- [Observability and Support](../23-observability-and-support.md)
- [ADR-001: Edge-first inspection](ADR-001-edge-first-inspection.md)
