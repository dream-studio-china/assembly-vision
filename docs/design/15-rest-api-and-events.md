# 15. REST API and Events

## 15.1 Contract Principles

AssemblyVision exposes independent `/api/v1` edge and central APIs. REST handles commands, durable resources, historical queries, and reconnect snapshots. WebSocket carries low-latency transient notifications; it is never required for inspection execution or durable synchronization.

Schemas are defined in [Data Model and Database](14-data-model-and-database.md). UI consumers are described in [Edge Dashboard](16-edge-dashboard.md) and [Central Admin Dashboard](17-central-admin-dashboard.md).

All JSON uses UTF-8, snake_case fields, ISO 8601 UTC timestamps, UUID strings, and `application/problem+json` errors. A problem response includes `type`, `title`, `status`, `detail`, `code`, `request_id`, and optional field `errors`.

## 15.2 Common Behavior

### 15.2.1 Authentication and Authorization

- Edge UI requests originate on the local management network. MVP may use a local operator session, but mutating routes require `operator` or `edge_admin`; read-only health is deliberately limited. Do not treat localhost as authentication. The one exception is review submission (`POST /api/v1/inspections/{id}/reviews`), which is intentionally exposed through the existing viewer credential per ADR-016 until an edge role model exists.
- Device-to-central calls use mutually authenticated TLS or short-lived device credentials bound to `device_id`.
- Central users authenticate through OIDC Authorization Code with PKCE. API authorization uses organization-scoped roles: `viewer`, `reviewer`, `config_manager`, `fleet_admin`, and `org_admin`.
- Media authorization is checked before issuing a short-lived download URL.

### 15.2.2 Idempotency and Concurrency

`PUT` and `DELETE` are naturally idempotent. Retriable central `POST` ingestion requests require `Idempotency-Key`. The server stores `(device_id, key, request_hash, response)`; same key/same hash replays the result, while same key/different hash returns `409 IDEMPOTENCY_CONFLICT`. Administrative updates use `If-Match` with an ETag/revision and return `412 REVISION_MISMATCH` on stale writes.

### 15.2.3 Pagination and Filtering

History endpoints use keyset pagination with `limit` (default 50, maximum 200) and opaque `cursor`. Responses are `{items, next_cursor}`. Filters are explicit query parameters; the cursor binds the normalized filter set and is rejected if reused with different filters. Small configuration lists may use the same envelope without a cursor.

## 15.3 Edge API Groups

In the tables, `R` means authenticated edge viewer, `O` operator, and `A` edge administrator. `-` under pagination means not applicable.

### 15.3.1 Runtime, Camera, and Health

| Method and endpoint | Purpose | Request / response | Errors | Idempotency | Pagination | Authorization |
|---|---|---|---|---|---|---|
| `GET /api/v1/health/live` | Process liveness only. | None / `{status}` | `503` only during shutdown | Safe GET | - | Unauthenticated, no internals |
| `GET /api/v1/health/ready` | Camera/model/database readiness. | None / `DeviceStatus` summary | `503 NOT_READY` | Safe GET | - | R |
| `GET /api/v1/device/status` | Full device, disk, network, and queue status. | None / `DeviceStatus` | `503 STATUS_UNAVAILABLE` | Safe GET | - | R |
| `GET /api/v1/camera/state` | Camera connection and capture settings, excluding secrets. | None / `CameraState` | `503 CAMERA_ADAPTER_ERROR` | Safe GET | - | R |
| `GET /api/v1/camera/{instance_id}/preview` | Latest captured frame as a rate-limited JPEG for the configured instance (interim REST preview, ADR-013). | Path instance ID / JPEG bytes | `404 INSTANCE_NOT_FOUND`, `503 CAMERA_UNAVAILABLE` | Safe GET | - | R |
| `POST /api/v1/camera/reconnect` | Request a supervised camera reconnect. | `{reason}` / `OperationAccepted` | `409 INSPECTION_ACTIVE`, `503 CAMERA_ADAPTER_ERROR` | `Idempotency-Key` | - | A |
| `POST /api/v1/ws/runtime/ticket` | Issue a short-lived, single-use ticket so a cross-origin browser socket can authenticate without placing a credential in the URL. | None / `WsTicket` | `401 UNAUTHENTICATED`, `429 RATE_LIMITED` | Each call issues a new ticket | - | R |
| `GET /api/v1/ws/runtime/stats` | Runtime event channel counters: active connections, published events by type, slow-consumer disconnects, delivery failures. | None / `RuntimeEventStats` | `401 UNAUTHENTICATED` | Safe GET | - | R |
| `GET /api/v1/inspection/state` | Current window and pause/fault state. | None / `InspectionRuntimeState` | `503 STATE_UNAVAILABLE` | Safe GET | - | R |
| `POST /api/v1/inspection/pause` | Stop opening new windows; finish or abort current window per safety policy. | `{reason}` / `InspectionRuntimeState` | `409 ALREADY_PAUSED`, `503 CONTROL_ERROR` | Repeated desired state succeeds | - | O |
| `POST /api/v1/inspection/resume` | Resume after readiness checks. | `{reason}` / `InspectionRuntimeState` | `409 PRECONDITION_FAILED`, `503 CONTROL_ERROR` | Repeated desired state succeeds | - | O |

### 15.3.2 Local Inspections and Media

| Method and endpoint | Purpose | Request / response | Errors | Idempotency | Pagination | Authorization |
|---|---|---|---|---|---|---|
| `GET /api/v1/inspections` | Query recent local inspections. | Query: business_result, internal_decision, barcode, product, from/to, cursor, limit / `Page[InspectionSummary]` | `400 INVALID_FILTER` | Safe GET | Cursor | R |
| `GET /api/v1/inspections/{inspection_id}` | Return complete local result/evidence. | Path UUID / `InspectionRecord` | `404 INSPECTION_NOT_FOUND` | Safe GET | - | R |
| `GET /api/v1/inspections/{inspection_id}/media` | List available/purged media metadata. | Optional kind / `list[MediaMetadata]` | `404 INSPECTION_NOT_FOUND` | Safe GET | - | R |
| `GET /api/v1/media/{media_id}/content` | Stream local image or clip with range support. | `Range` optional / bytes | `404 MEDIA_NOT_FOUND`, `410 MEDIA_PURGED`, `416 INVALID_RANGE` | Safe GET | - | R |

### 15.3.3 Review Queue (design 24, ADR-016)

Human-in-the-loop review is optional and additive: any inspection may be
reviewed, and a disposition never rewrites the machine decision. Records are
append-only; a later review supersedes an earlier one by reference.

| Method and endpoint | Purpose | Request / response | Errors | Idempotency | Pagination | Authorization |
|---|---|---|---|---|---|---|
| `GET /api/v1/reviews` | List the review queue with each inspection's review state. | Query: business_result, internal_decision, reviewed, cursor, limit / `Page[ReviewQueueItem]` | `400 INVALID_CURSOR` | Safe GET | Cursor | R |
| `GET /api/v1/inspections/{inspection_id}/reviews` | Append-only review history of one inspection (oldest first). | Path UUID / `list[ReviewRecord]` | `404 INSPECTION_NOT_FOUND` | Safe GET | - | R |
| `POST /api/v1/inspections/{inspection_id}/reviews` | Append one human disposition. | `SubmitReviewRequest` / `ReviewRecord` | `404 INSPECTION_NOT_FOUND`, `409 REVIEW_CONFLICT`, `422 REVIEW_DISPOSITION_INVALID` / `REVIEW_VALIDATION_FAILED` | None: each call appends a new review | - | R |

`SubmitReviewRequest` requires `disposition` and a non-empty `reviewer`;
`INCONCLUSIVE` requires a `reason`. The disposition must be permitted for the
machine outcome (design 24.3): `UNCERTAIN` may be confirmed NG/OK, reinspected,
or inconclusive; plain `NG` may be confirmed NG/OK or inconclusive; sampled
`OK` may be confirmed OK, corrected to NG, or inconclusive. `409 REVIEW_CONFLICT`
also covers a `supersedes_review_id` that names no review of that inspection.

### 15.3.4 Upload Queue and Configuration

| Method and endpoint | Purpose | Request / response | Errors | Idempotency | Pagination | Authorization |
|---|---|---|---|---|---|---|
| `GET /api/v1/uploads` | Inspect queue by state/kind. | Query filters/cursor / `Page[UploadTask]` | `400 INVALID_FILTER` | Safe GET | Cursor | R |
| `POST /api/v1/uploads/{upload_task_id}/retry` | Move eligible retry-wait or permanent-failure work to due state after operator resolution. | `{reason}` / `UploadTask` | `404 TASK_NOT_FOUND`, `409 TASK_ACTIVE` | `Idempotency-Key`; duplicate returns same state | - | O |
| `GET /api/v1/configuration/effective` | Effective config plus source/revision/checksum. | None / `EffectiveConfiguration` | `503 CONFIG_UNAVAILABLE` | Safe GET | - | R |
| `PUT /api/v1/configuration/local-overrides` | Replace permitted site-local overrides. | `If-Match`, `LocalOverrides` / new revision | `400 INVALID_CONFIG`, `403 MANAGED_FIELD`, `412 REVISION_MISMATCH` | Idempotent replacement | - | A |
| `POST /api/v1/configuration/validate` | Validate without activation. | `ConfigurationCandidate` / `ValidationResult` | `422 VALIDATION_FAILED` | Deterministic | - | A |
| `GET /api/v1/logs` | Bounded structured service log query. | level/component/from/to/cursor / `Page[LogEvent]` | `400 INVALID_FILTER` | Safe GET | Cursor | A |

### 15.3.5 Web Dev Test Harness (ADR-014)

These file-based endpoints are **disabled by default** and return
`404 DEV_TOOLS_DISABLED` unless `serve` runs with `--enable-web-test`. They are
a developer test harness, not a production acquisition path; production
real-time inspection uses the native app / RTSP / camera sources.

| Method and endpoint | Purpose | Request / response | Errors | Idempotency | Pagination | Authorization |
|---|---|---|---|---|---|---|
| `POST /api/v1/dev/inspect-frame` | Analyze one uploaded image through an instance pipeline; writes an evidence bundle unless `persist=false`. | Query: optional `barcode` simulated keyboard input; raw image bytes / `InspectionRecord` | `400 INVALID_IMAGE`, `404 INSTANCE_NOT_FOUND`, `413 PAYLOAD_TOO_LARGE`, `503 PIPELINE_UNAVAILABLE` | Deterministic | - | R + dev flag |
| `POST /api/v1/dev/inspect-video` | Analyze an uploaded video frame by frame (≤30 sampled frames) and return a summary; nothing is persisted. | Raw video bytes / `VideoInspectResult` | `400 INVALID_VIDEO`, `404 INSTANCE_NOT_FOUND`, `413 PAYLOAD_TOO_LARGE`, `503 PIPELINE_UNAVAILABLE` | Deterministic | - | R + dev flag |

### 15.3.6 Confidence Drift (Environment-Change Diagnostics)

`GET /api/v1/statistics/confidence-drift` analyzes detection confidence over
time under the premise of **the same product and the same rule version on this
device**, so a change reflects the acquisition environment (conveyor, camera
focus/angle, lighting) rather than a product-rule switch.

| Aspect | Behavior |
|---|---|
| Confidence metric | Per-component `best_confidence` weighted by `detection_count` (equivalent to weighting whole inspections by their total detection count); the evidence-level `median` is reported as a robust reference. Only evidence rows with a recorded confidence contribute. |
| Periods | `today` = `[local-today 00:00, now)`, `yesterday` = `[local-yesterday 00:00, local-today 00:00)`, `previous_7d` = `[local-today 00:00 - 7 days, local-today 00:00)` (includes yesterday), `previous_30d` = `[local-today 00:00 - 30 days, local-today 00:00)` (includes the 7-day window). Day boundaries follow the operator-local timezone given by `tz_offset_minutes` (default UTC). Buckets are half-open `[from, to)`. |
| Comparison | `today_vs_yesterday`, `today_vs_previous_7d`, and `today_vs_previous_30d` report the weighted-mean delta, the relative percent change, and both evidence counts. |
| Components | Per-component weighted means for today versus the previous-7-day baseline, sorted with the largest drop first; a component absent from the baseline carries `baseline_weighted_mean = null` (insufficient baseline evidence, never a fabricated zero). |
| Assessment | Heuristic label from the relative change versus the previous-7-day mean: `< 2 %` stable, `2–5 %` minor, `> 5 %` noticeable, with drop/rise direction, or `insufficient_data` when either window has no confidence evidence. The label is decision-support only and never claims a root cause or an accuracy value; a persistent drop prompts operators to verify frame quality and media. |
| Filters | Optional `product_code`, `rule_version_id`, and `component_code`; `tz_offset_minutes` is bounded to `[-840, 840]` (`422` outside). |

## 15.4 Central API Groups

Roles are abbreviated `V` viewer, `R` reviewer, `C` configuration manager, `F` fleet administrator, `O` organization administrator, and `D` enrolled device.

### 15.4.1 Identity, Fleet, and Events

| Method and endpoint | Purpose | Request / response | Errors | Idempotency | Pagination | Authorization |
|---|---|---|---|---|---|---|
| `GET /api/v1/auth/me` | Return user, organization, and effective permissions. | Session/token / `CurrentUser` | `401 UNAUTHENTICATED` | Safe GET | - | Any user |
| `GET /api/v1/sites` | List authorized sites and lines. | Query cursor / `Page[Site]` | `403 FORBIDDEN` | Safe GET | Cursor | V |
| `GET /api/v1/lines` | List/filter production lines. | site/cursor / `Page[ProductionLine]` | `404 SITE_NOT_FOUND` | Safe GET | Cursor | V |
| `GET /api/v1/devices` | Fleet query by site/line/state/last-seen. | Filters/cursor / `Page[DeviceSummary]` | `400 INVALID_FILTER` | Safe GET | Cursor | V |
| `POST /api/v1/devices` | Enroll a device and issue one-time bootstrap material. | `DeviceCreate` / `DeviceEnrollment` | `409 DEVICE_CODE_EXISTS` | `Idempotency-Key` | - | F |
| `GET /api/v1/devices/{device_id}` | Device details, assignments, versions, and health. | Path UUID / `DeviceDetail` | `404 DEVICE_NOT_FOUND` | Safe GET | - | V |
| `PATCH /api/v1/devices/{device_id}` | Change line assignment, label, or desired state. | `If-Match`, `DevicePatch` / `DeviceDetail` | `409 INVALID_STATE`, `412 REVISION_MISMATCH` | Idempotent fields | - | F |
| `POST /api/v1/device-events:batch` | Ingest bounded ordered event batch. | `DeviceEventBatch` / per-item receipts | `400 BATCH_TOO_LARGE`, `409 ID_CONFLICT` | `Idempotency-Key` plus event IDs | - | D |
| `GET /api/v1/system-events` | Query central/device events. | device/severity/code/time/cursor / page | `400 INVALID_FILTER` | Safe GET | Cursor | V |

### 15.4.2 Inspection Ingestion and History

| Method and endpoint | Purpose | Request / response | Errors | Idempotency | Pagination | Authorization |
|---|---|---|---|---|---|---|
| `POST /api/v1/inspection-uploads` | Ingest one finalized inspection and component evidence. | `InspectionRecord` / `UploadReceipt` | `409 VERSION_UNKNOWN`, `409 PAYLOAD_CONFLICT`, `422 INVALID_EVIDENCE` | Required key; inspection ID and device sequence also unique | - | D |
| `POST /api/v1/media-uploads:initiate` | Validate metadata and create upload target/session. | `MediaUploadInitiate` / target or already-present receipt | `409 INSPECTION_UNKNOWN`, `413 MEDIA_TOO_LARGE`, `415 TYPE_NOT_ALLOWED` | Required key; source media ID unique | - | D |
| `POST /api/v1/media-uploads/{upload_id}/complete` | Verify uploaded object size/checksum and attach it. | `{sha256, size_bytes}` / `MediaMetadata` | `409 CHECKSUM_MISMATCH`, `410 UPLOAD_EXPIRED` | Repeated completion returns verified resource | - | D |
| `GET /api/v1/inspections` | Cross-device history search. | Filters: site, line, device, time, barcode, product, business_result, internal_decision, model, rule, reason, review state, cursor / `Page[InspectionSummary]` | `400 INVALID_FILTER` | Safe GET | Cursor | V |
| `GET /api/v1/inspections/{inspection_id}` | Result, components, versions, media, latest review. | Path UUID / `CentralInspectionDetail` | `404 INSPECTION_NOT_FOUND` | Safe GET | - | V |
| `GET /api/v1/inspections/{inspection_id}/media` | Authorized media metadata and short-lived URLs. | kind optional / list | `404`, `410 MEDIA_PURGED` | Safe GET | - | V |

### 15.4.3 Review, Products, Rules, and Models

| Method and endpoint | Purpose | Request / response | Errors | Idempotency | Pagination | Authorization |
|---|---|---|---|---|---|---|
| `GET /api/v1/reviews/queue` | Pending NG/uncertain review worklist. | product/device/reason/cursor / page | `400 INVALID_FILTER` | Safe GET | Cursor | R |
| `POST /api/v1/inspections/{id}/reviews` | Append a review revision. | `If-Match`, `ReviewCreate` / `ReviewRecord` | `409 REVIEW_CONFLICT`, `422 INVALID_CORRECTION` | `Idempotency-Key` | - | R |
| `GET /api/v1/products` | Product and active-version list. | status/search/cursor / page | `400 INVALID_FILTER` | Safe GET | Cursor | V |
| `POST /api/v1/products` | Create stable product identity. | `ProductCreate` / `Product` | `409 PRODUCT_CODE_EXISTS` | `Idempotency-Key` | - | C |
| `POST /api/v1/products/{id}/versions` | Create draft product version. | `ProductConfigurationDraft` / version | `409 VERSION_EXISTS`, `422 INVALID_COMPONENT` | `Idempotency-Key` | - | C |
| `POST /api/v1/product-versions/{id}/publish` | Validate and immutably publish. | `{reason}` / `ProductConfiguration` | `409 ALREADY_PUBLISHED`, `422 INVALID_CONFIG` | Repeated publish returns published resource | - | C |
| `GET /api/v1/rules` | List stable rules and versions. | product/status/cursor / page | `400 INVALID_FILTER` | Safe GET | Cursor | V |
| `POST /api/v1/rules/{id}/versions` | Create rule draft. | `RuleConfigurationDraft` / draft | `422 INVALID_POLICY` | `Idempotency-Key` | - | C |
| `POST /api/v1/rule-versions/{id}/publish` | Publish after model/product compatibility validation. | `{reason}` / `RuleConfiguration` | `409 INCOMPATIBLE_VERSION`, `422 INVALID_POLICY` | Repeated publish succeeds | - | C |
| `GET /api/v1/models` | List model packages/versions and lifecycle state. | task/status/cursor / page | `400 INVALID_FILTER` | Safe GET | Cursor | V |
| `POST /api/v1/models/{id}/versions` | Register manifest and staged artifact. | `ModelManifestCreate` / version/upload target | `409 VERSION_EXISTS`, `422 INVALID_MANIFEST` | `Idempotency-Key` | - | C |
| `POST /api/v1/model-versions/{id}/publish` | Verify artifact and publish version. | `{reason}` / `ModelManifest` | `409 CHECKSUM_MISMATCH`, `422 EVALUATION_REQUIRED` | Repeated publish succeeds | - | C |
| `PUT /api/v1/devices/{id}/desired-configuration` | Assign versioned configuration bundle. | `If-Match`, `DesiredConfiguration` / assignment | `409 INCOMPATIBLE_BUNDLE`, `412 REVISION_MISMATCH` | Idempotent replacement | - | F |

### 15.4.4 Device Configuration Distribution (Production Target)

Remote delivery is not required for the one-month demonstrator; it may use manually installed,
checksum-verified immutable packages. When remote delivery enters scope, the following device-facing
contract is mandatory:

| Method and endpoint | Purpose | Request / response | Errors | Authorization |
|---|---|---|---|---|
| `GET /api/v1/device/configuration-manifest` | Poll the assigned immutable release manifest. | Current version/checksum / manifest or `304` | `409 DEVICE_QUARANTINED` | D |
| `GET /api/v1/device/configuration-packages/{version_id}` | Download a package or pre-signed artifact URL. | Version UUID / artifact metadata | `404`, `409 INCOMPATIBLE_PACKAGE` | D |
| `POST /api/v1/device/configuration-validations` | Report checksum, signature, compatibility, and smoke-test results. | `ConfigurationValidationReport` / receipt | `409 ASSIGNMENT_STALE` | D, idempotency key |
| `POST /api/v1/device/configuration-activations` | Acknowledge activation between inspection windows. | `ConfigurationActivationReport` / assignment state | `409 VERSION_NOT_VALIDATED` | D, idempotency key |
| `POST /api/v1/device/configuration-rollbacks` | Report rollback and active last-known-good package. | `ConfigurationRollbackReport` / assignment state | `409 INVALID_ROLLBACK_TARGET` | D, idempotency key |

### 15.4.5 Dashboards, Reports, Users, and Audit

| Method and endpoint | Purpose | Request / response | Errors | Idempotency | Pagination | Authorization |
|---|---|---|---|---|---|---|
| `GET /api/v1/dashboard/summary` | Aggregated KPIs for explicit time/site filters. | from/to/site/line/product/model/rule / `DashboardSummary` | `400 INVALID_RANGE` | Safe GET | - | V |
| `GET /api/v1/dashboard/timeseries` | Bucketed outcomes, latency, and failures. | filters, interval / `TimeSeries` | `400 INVALID_INTERVAL` | Safe GET | - | V |
| `POST /api/v1/reports` | Start a large export/report job. | `ReportRequest` / `JobAccepted` | `413 RANGE_TOO_LARGE`, `422 INVALID_COLUMNS` | `Idempotency-Key` | - | V with export permission |
| `GET /api/v1/reports/{job_id}` | Poll job and obtain expiring download URL. | Path UUID / `ReportStatus` | `404 JOB_NOT_FOUND`, `410 EXPIRED` | Safe GET | - | Requester or O |
| `GET /api/v1/users` | Organization user/role list. | search/role/cursor / page | `403 FORBIDDEN` | Safe GET | Cursor | O |
| `PUT /api/v1/users/{id}/roles` | Replace organization role assignments. | `If-Match`, `{role_ids}` / user | `400 LAST_ADMIN`, `412 REVISION_MISMATCH` | Idempotent replacement | - | O |
| `GET /api/v1/audit-logs` | Immutable audit query and export source. | actor/action/resource/time/cursor / page | `400 INVALID_FILTER` | Safe GET | Cursor | O/auditor |

## 15.5 REST and WebSocket Boundary

REST is authoritative for inspection details, queue state, configuration, commands, uploads, review, and reports. WebSocket communicates that something changed. A reconnecting client always refreshes REST state; it must not assume the WebSocket stream is complete.

| Channel | Events | Delivery semantics | Client action |
|---|---|---|---|
| Edge `WS /api/v1/ws/runtime` | `device.status_changed`, `inspection.started`, `inspection.updated`, `inspection.completed`, `upload.changed`, `alert.raised`, `alert.cleared` | Best effort, ordered per connection, bounded buffer; slow clients disconnected | Apply transient preview updates; refetch resource on sequence gap |
| Central `WS /api/v1/ws/organization` | `device.changed`, `inspection.received`, `review.changed`, `job.changed`, `configuration.assignment_changed` | Best effort after authorization filtering; no durable replay in MVP | Invalidate/refetch affected REST query |

WebSocket authentication uses the existing secure session cookie or a short-lived, single-purpose ticket obtained over REST. Tokens must not appear in URL query logs. Browser WebSocket cannot set an `Authorization` header, so a cross-origin dashboard exchanges its viewer credential for a one-time ticket at `POST /api/v1/ws/runtime/ticket` and sends it as the negotiated `Sec-WebSocket-Protocol` value; the ticket is consumed atomically during acceptance, expires within seconds, and is never logged.

## 15.6 Event Envelope and Evolution

```json
{
  "event_id": "01989...",
  "type": "inspection.completed",
  "schema_version": 1,
  "occurred_at": "2026-08-04T10:12:31.442Z",
  "source_id": "01988...",
  "sequence": 1842,
  "correlation_id": "01989...",
  "data": {"inspection_id": "01989...", "business_result": "NG", "internal_decision": "UNCERTAIN"}
}
```

Event payloads are intentionally small. Additive fields are allowed within a schema version; removal, meaning changes, or type changes require a new version. Event consumers allow unknown additive payload fields while request bodies remain strict. `sequence` is monotonic per `(source_id, channel)`; clients refetch REST state on gaps. Unknown event types are ignored and logged. Heartbeat ping/pong is transport-level; `DeviceStatus` snapshots remain REST resources.

## 15.7 Failure Handling and Limits

- Return `429` with `Retry-After` for rate limits and `503` with bounded retry guidance for temporary dependency failures.
- Cap request bodies, event batches, media size, filter ranges, and WebSocket message/buffer sizes.
- A central ingestion `202` means accepted for asynchronous verification, not fully persisted, only where the response explicitly includes a receipt state. Normal inspection metadata ingestion should commit before `201`.
- Never retry non-idempotent calls automatically without an idempotency key.
- Propagate `X-Request-ID`; edge upload attempts also carry inspection and task correlation IDs.
- Use presigned object upload for large media; do not proxy video through API workers unless storage constraints require it.

## 15.8 Open Questions and Validation Required

- Select the central identity provider and device certificate enrollment/rotation process.
- Confirm edge local-user requirements, session timeout, and emergency pause authorization.
- Confirm maximum media sizes, batch sizes, report ranges, and API rate limits from measured load.
- Decide whether central WebSocket scale requires Redis pub/sub after the single-instance MVP.
- Confirm whether external MES/PLC integrations require separate credentials, endpoints, or event delivery guarantees.
- Validate browser and reverse-proxy support for WebSockets in the customer network.
