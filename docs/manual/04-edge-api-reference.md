# 04 — Edge API Reference

How the edge API is **really called**: base URL, auth flow, every endpoint
with real request/response JSON and curl examples, WebSocket protocol, error
conventions, and the code inventory. The authoritative contract is the
committed OpenAPI document (`apps/edge-service/openapi/edge-openapi.json`,
regenerate with `uv run python scripts/generate-edge-openapi.py`).

## Base URL and conventions

- Server: `uv run assemblyvision serve --output out/ --db out/edge.sqlite3
  --config ... --rule ... --static apps/edge-web/dist --host 127.0.0.1
  --port 8000`. Base URL `http://127.0.0.1:8000`, all routes under
  `/api/v1`.
- JSON everywhere; `snake_case` fields; ISO-8601 UTC timestamps; UUID
  strings.
- Every response carries security headers (`Content-Security-Policy`,
  `X-Content-Type-Options: nosniff`, `Referrer-Policy: same-origin`).
- `GET` under `/api/*` that is not a real route returns a JSON 404, never the
  dashboard HTML.

## Authentication

When an API token is configured (`--api-token` or `AV_EDGE_API_TOKEN`),
**every route except `GET /api/v1/health/live` requires a credential**.
Two credentials are accepted:

1. `Authorization: Bearer <token>` header (constant-time comparison).
2. The `av_edge_viewer_session` HttpOnly cookie (created by
   `POST /api/v1/auth/session`).

With no token configured the service runs in open M1 development mode (all
routes unauthenticated). Failure policy: bad/missing credential → `401`
`code: "UNAUTHENTICATED"`; after 5 failed attempts per client IP per minute →
`429` `code: "RATE_LIMITED"` with `Retry-After: 60`.

### Bearer → session cookie flow (what the dashboard login does)

```bash
# exchange the token for an HttpOnly session cookie (204, Set-Cookie: av_edge_viewer_session=...)
curl -i -X POST http://127.0.0.1:8000/api/v1/auth/session \
  -H "Authorization: Bearer $TOKEN"
```

- 204 No Content; cookie `Max-Age=28800` (8 h), `HttpOnly`, `SameSite=strict`,
  `Secure` when HTTPS; max 500 sessions.
- Wrong token → 401; rate-limited → 429.

### WebSocket ticket flow

Browser sockets cannot set an `Authorization` header, so the dashboard
exchanges its viewer credential for a short-lived single-use ticket:

```bash
TICKET=$(curl -X POST http://127.0.0.1:8000/api/v1/ws/runtime/ticket \
  -H "Authorization: Bearer $TOKEN" | python3 -c 'import sys,json;print(json.load(sys.stdin)["ticket"])')
# response: {"ticket": "<urlsafe-base64>", "expires_at": "ISO-8601", "channel": "runtime"}
```

Then connect with the ticket as the negotiated subprotocol:

```js
const ws = new WebSocket("ws://127.0.0.1:8000/api/v1/ws/runtime", [ticket]);
```

Ticket TTL 30 s, single-use, never in the URL; expired/replayed tickets →
close 4401.

## Error convention — `application/problem+json`

All non-2xx errors are RFC 7807 problems:

```json
{
  "type": "https://assemblyvision.example/problems/task_not_retryable",
  "title": "Task Not Retryable",
  "status": 409,
  "detail": "upload task is SUCCEEDED and cannot be manually retried",
  "code": "TASK_NOT_RETRYABLE",
  "request_id": "<X-Request-ID or generated uuid4>",
  "errors": []
}
```

- 422 validation failures use `code: "VALIDATION_FAILED"` and populate
  `errors` with `{"field": "<loc>", "message": "<msg>"}` entries.
- Unhandled exceptions → `500` `code: "INTERNAL_ERROR"`.
- Unknown API routes → `code: "HTTP_404"`.

## Endpoints

### Health

**GET `/api/v1/health/live`** — unauthenticated liveness.

```bash
curl http://127.0.0.1:8000/api/v1/health/live
```

```json
{"status": "ok"}
```

**GET `/api/v1/health/ready`** — authenticated; returns the full
`DeviceStatus` (see below) or `503` `code: "NOT_READY"` when the pipeline is
not loaded or storage cannot guarantee mandatory persistence (write fault,
`storage_mode == "STOP"`, integrity fault, cleanup integrity fault).

```bash
curl http://127.0.0.1:8000/api/v1/health/ready -H "Authorization: Bearer $TOKEN"
```

### Device status

**GET `/api/v1/device/status`** — authenticated; the richest endpoint
(~70 fields). Real response shape:

```json
{
  "device_id": "66905f26-71ce-471a-b34b-f255e66c6867",
  "observed_at": "2026-08-10T09:30:05Z",
  "operational_state": "READY",
  "inspection_ready": true,
  "inspection_error_code": null,
  "sync_ready": true,
  "camera_connected": true,
  "model_loaded": true,
  "central_connected": false,
  "disk_free_bytes": 214748364800,
  "upload_pending_count": 0,
  "upload_pending_bytes": 0,
  "upload_oldest_pending_at": null,
  "upload_attempts": 0,
  "upload_successes": 0,
  "upload_failures": 0,
  "upload_failure_rate": 0.0,
  "upload_last_attempt_at": null,
  "upload_last_success_at": null,
  "upload_last_error_code": null,
  "upload_bytes_sent": 0,
  "upload_bandwidth_mbps": null,
  "upload_circuit_state": "CLOSED",
  "upload_circuit_last_change_at": null,
  "storage_mode": "NORMAL",
  "storage_free_bytes": 0,
  "storage_free_percent": 0.0,
  "storage_free_inodes": 0,
  "storage_inode_percent": 0.0,
  "storage_warning_free_percent": 0.0,
  "storage_critical_free_percent": 0.0,
  "storage_stop_free_percent": 0.0,
  "storage_observed_at": null,
  "storage_write_fault": false,
  "cleanup_enabled": false,
  "cleanup_eligible_count": 0,
  "cleanup_eligible_bytes": 0,
  "cleanup_deleting_count": 0,
  "cleanup_delete_error_count": 0,
  "cleanup_purged_count": 0,
  "cleanup_integrity_fault_count": 0,
  "cleanup_last_run_at": null,
  "cleanup_last_error_code": null,
  "integrity_scan_last_run_at": null,
  "integrity_scan_checked": 0,
  "integrity_scan_faults": 0,
  "integrity_scan_checksummed": 0,
  "integrity_scan_skipped": 0,
  "integrity_scan_skipped_reason": null,
  "integrity_verify_checksums": false,
  "current_product_model_version_id": null,
  "current_component_model_version_id": null,
  "current_rule_version_id": null,
  "alerts": []
}
```

- `operational_state`: `READY | PAUSED | INITIALIZING | FAULTED`.
- `alerts` tokens: `STORAGE_WRITE_FAULT`, `DISK_STOP`, `DISK_CRITICAL`,
  `DISK_WARNING`, `STORAGE_INTEGRITY_FAULT`, `CLEANUP_FAULT`,
  `UPLOAD_BLOCKED`, `UPLOAD_FAILING`, `UPLOAD_CIRCUIT_OPEN`.

```bash
curl http://127.0.0.1:8000/api/v1/device/status -H "Authorization: Bearer $TOKEN"
```

### Camera

**GET `/api/v1/camera/state`** — query `instance_id` optional; 404
`INSTANCE_NOT_FOUND` for an unknown instance. Aggregate (no `instance_id`)
always reports `connected: true` with configured dimensions.

```bash
curl "http://127.0.0.1:8000/api/v1/camera/state?instance_id=cam" -H "Authorization: Bearer $TOKEN"
```

```json
{
  "connected": true,
  "source_width": 800,
  "source_height": 600,
  "fps": null,
  "last_frame_at": null,
  "error_code": null,
  "camera_serial": null,
  "camera_model": null,
  "firmware_version": null,
  "gentl_producer": null,
  "transport_parent": null,
  "pixel_format": null,
  "trigger_mode": null,
  "exposure_us": null,
  "gain_db": null,
  "packet_size": null
}
```

**GET `/api/v1/camera/{instance_id}/preview`** — latest frame as JPEG
(quality 75, rate-limited); `404 INSTANCE_NOT_FOUND`, `503 CAMERA_UNAVAILABLE`
when no frame yet.

```bash
curl http://127.0.0.1:8000/api/v1/camera/cam/preview -H "Authorization: Bearer $TOKEN" -o frame.jpg
```

### Inspection runtime state

**GET `/api/v1/inspection/state`**

```bash
curl http://127.0.0.1:8000/api/v1/inspection/state -H "Authorization: Bearer $TOKEN"
```

```json
{
  "window_active": false,
  "paused": false,
  "faulted": false,
  "current_inspection_id": null,
  "last_result": "NG",
  "paused_reason": null,
  "paused_by": null,
  "paused_at": null
}
```

> Note: the M1 operator endpoints `POST /inspection/pause|resume` and
> `POST /camera/reconnect` do **not** exist on the server (removed by
> ADR-012; they 404). The frontend keeps mock-only stubs for the operator
> workflow.

### Inspections (history)

**GET `/api/v1/inspections`** — query params: `business_result`, 
`internal_decision`, `barcode` (case-insensitive `LIKE %v%`), `product`
(exact), `sn` (fuzzy), `from`/`to` (timezone-aware UTC), `cursor` (opaque,
bound to filters), `limit` (default 50).

```bash
curl "http://127.0.0.1:8000/api/v1/inspections?business_result=NG&limit=25" \
  -H "Authorization: Bearer $TOKEN"
curl "http://127.0.0.1:8000/api/v1/inspections?sn=SN-001&cursor=$CURSOR&limit=50" \
  -H "Authorization: Bearer $TOKEN"
```

```json
{
  "items": [
    {
      "inspection_id": "3f830cec-a02f-4c8f-b85f-b6395981e0a2",
      "completed_at": "2026-08-10T09:30:01Z",
      "business_result": "OK",
      "internal_decision": "OK",
      "barcode": "SN-001234",
      "product_code": "model_a",
      "sn": "SN-001234",
      "reason_summary": [],
      "latency_ms": 12,
      "upload_state": "LOCAL_ONLY",
      "model_rule_versions": {
        "product_model": "8a147d10-...",
        "component_model": "760db85a-...",
        "rule": "bda63d68-..."
      }
    }
  ],
  "next_cursor": "base64-string-or-null"
}
```

`upload_state` = `synchronization_status`: `LOCAL_ONLY | QUEUED | PARTIAL |
SYNCED | FAILED`. Malformed or filter-mismatched cursor → `400`
`code: "INVALID_CURSOR"`.

**GET `/api/v1/inspections/{inspection_id}`** — the full record. Real
response shape (domain `InspectionRecord`, UUIDs as strings):

```json
{
  "inspection_id": "3f830cec-a02f-4c8f-b85f-b6395981e0a2",
  "device_id": "66905f26-71ce-471a-b34b-f255e66c6867",
  "device_sequence": 7,
  "lifecycle_status": "COMPLETED",
  "started_at": "2026-08-10T09:30:00Z",
  "completed_at": "2026-08-10T09:30:01Z",
  "barcode_result": {"status": "READ", "value": "SN-001234", "symbology": "code128"},
  "product_resolution": {
    "status": "RESOLVED", "source": "BARCODE",
    "product_code": "model_a", "product_version_id": "c47be866-..."
  },
  "product_detection": null,
  "roi_result": null,
  "frame_quality_summary": {"total_frame_count": 3, "usable_frame_count": 3,
                            "rejected_frame_count": 0, "reasons": []},
  "application_version": "0.1.0",
  "product_model_version_id": "8a147d10-...",
  "product_model_checksum_sha256": "aaaa...",
  "component_model_version_id": "760db85a-...",
  "component_model_checksum_sha256": "bbbb...",
  "rule_version_id": "bda63d68-...",
  "aggregation_policy_version": "single-frame-mvp-1",
  "evidence": [
    {
      "component_code": "component_a",
      "state": "PRESENT",
      "best_confidence": 0.93,
      "usable_frame_count": 3,
      "detection_count": 3,
      "adjacent_detection_run": 3,
      "supporting_frame_ids": ["d2d6f855-..."],
      "policy_reason_codes": [],
      "box_area_ratios": [0.5],
      "box_centers": [[0.5, 0.5]]
    }
  ],
  "media": [
    {
      "media_id": "d23ca3c6-...",
      "kind": "KEY_FRAME",
      "lifecycle": "AVAILABLE",
      "relative_path": "inspection/key_frame.jpg",
      "mime_type": "image/jpeg",
      "size_bytes": 1024,
      "checksum_sha256": "cccc..."
    }
  ],
  "decision": {
    "internal_decision": "OK", "business_result": "OK",
    "missing_components": [], "low_confidence_components": [],
    "reason_codes": [], "decided_at": "2026-08-10T09:30:01Z"
  },
  "synchronization_status": "LOCAL_ONLY",
  "processing_ms": 120,
  "inference_metadata": null
}
```

Enums: `evidence[].state` = `PRESENT | MISSING | UNCERTAIN | UNVERIFIABLE`;
`media[].kind` = `KEY_FRAME | ANNOTATED_FRAME | PRODUCT_ROI | NG_CLIP |
ROLLING_VIDEO`; `media[].lifecycle` = `PENDING | AVAILABLE | FAILED | PURGED`;
`barcode_result.status` = `READ | NOT_READ | CONFLICT | NOT_REQUIRED`;
`decision.internal_decision` = `OK | NG | UNCERTAIN`. Unknown id → `404`
`code: "INSPECTION_NOT_FOUND"`.

```bash
curl http://127.0.0.1:8000/api/v1/inspections/$INSPECTION_ID -H "Authorization: Bearer $TOKEN"
```

**GET `/api/v1/inspections/{inspection_id}/media`** — plain array (no page
wrapper); `404 INSPECTION_NOT_FOUND`.

```bash
curl http://127.0.0.1:8000/api/v1/inspections/$INSPECTION_ID/media -H "Authorization: Bearer $TOKEN"
```

**GET `/api/v1/inspections/{inspection_id}/images`** — derived image slots:

```json
{
  "inspection_id": "uuid",
  "original": "http://127.0.0.1:8000/api/v1/media/<media_id>/content",
  "detection": "http://127.0.0.1:8000/api/v1/media/<media_id>/content",
  "annotated": "http://127.0.0.1:8000/api/v1/media/<media_id>/content",
  "original_status": "AVAILABLE",
  "detection_status": "AVAILABLE",
  "annotated_status": "UNAVAILABLE"
}
```

Slots: `original` ← `KEY_FRAME`, `detection` ← `PRODUCT_ROI`, `annotated` ←
`ANNOTATED_FRAME`; status per slot `AVAILABLE | PURGED | UNAVAILABLE`
(purged slots carry an empty URL).

### Media

**GET `/api/v1/media/{media_id}/content`** — byte streaming with optional
`Range`:

```bash
curl http://127.0.0.1:8000/api/v1/media/$MEDIA_ID/content \
  -H "Authorization: Bearer $TOKEN" -o media.bin
curl http://127.0.0.1:8000/api/v1/media/$MEDIA_ID/content \
  -H "Authorization: Bearer $TOKEN" -H "Range: bytes=0-1023" -o part.bin
```

- `Content-Type` derived from the kind allowlist (images → `image/jpeg`,
  clips → `video/mp4`), never from persisted mime.
- `206` with `Content-Range` for ranges; `416` `code: "INVALID_RANGE"` for
  unsatisfiable ranges; `404` `MEDIA_NOT_FOUND`; **`410` `code:
  "MEDIA_PURGED"`** for purged media (even if the file exists).

### Uploads

**GET `/api/v1/uploads`** — `Page<UploadTask>`; `limit` default 50:

```bash
curl "http://127.0.0.1:8000/api/v1/uploads?limit=50" -H "Authorization: Bearer $TOKEN"
```

```json
{
  "items": [
    {
      "upload_task_id": "uuid",
      "device_id": "uuid",
      "inspection_id": "uuid",
      "kind": "INSPECTION",
      "object_id": "uuid",
      "payload_hash": "sha256-hex",
      "status": "PENDING",
      "idempotency_key": "inspection:<device_id>:<inspection_id>",
      "checksum_sha256": null,
      "attempt_count": 0,
      "next_attempt_at": null,
      "last_error_code": null,
      "created_at": "2026-08-10T09:30:02Z",
      "updated_at": "2026-08-10T09:30:02Z",
      "completed_at": null
    }
  ],
  "next_cursor": null
}
```

`status` = `PENDING | IN_PROGRESS | RETRY_WAIT | SUCCEEDED |
PERMANENT_FAILURE | CANCELLED`; `kind` = `INSPECTION | MEDIA | DEVICE_EVENT`.

**POST `/api/v1/uploads/{upload_task_id}/retry`** — manual retry. Only
`RETRY_WAIT` and `PERMANENT_FAILURE` tasks are eligible. Body optional
(`{"reason": "..."}`, max 200 chars, or no body):

```bash
curl -X POST http://127.0.0.1:8000/api/v1/uploads/$TASK_ID/retry \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"reason": "conveyor jam cleared"}'
# legacy: no body at all
curl -X POST http://127.0.0.1:8000/api/v1/uploads/$TASK_ID/retry \
  -H "Authorization: Bearer $TOKEN"
```

- 200 → refreshed `UploadTask` with `status: "PENDING"` and `attempt_count`
  incremented; `completed_at`/`next_attempt_at`/`last_error_code` cleared.
- `404` `code: "NOT_FOUND"` unknown task; `409` `code: "TASK_NOT_RETRYABLE"`
  for `SUCCEEDED`/`PENDING`/`IN_PROGRESS`/`CANCELLED` and for a second retry
  (compare-and-set); `422` when the reason is too long (no mutation).

### Configuration

**GET `/api/v1/configuration/effective`**

```bash
curl http://127.0.0.1:8000/api/v1/configuration/effective -H "Authorization: Bearer $TOKEN"
```

```json
{
  "revision": "local",
  "checksum_sha256": "sha256-of-config-and-rule-files",
  "managed": {
    "application_version": "0.1.0",
    "product_detection": {
      "model_version": "product-yolo-1.0.0",
      "confidence_threshold": 0.5,
      "iou_threshold": 0.5
    },
    "component_detection": {
      "model_version": "component-yolo-1.0.0",
      "iou_threshold": 0.5,
      "components": {"component_a": 0.5, "component_b": 0.5}
    },
    "roi": {
      "margin_x_ratio": 0.1, "margin_y_ratio": 0.1,
      "min_area_pixels": 1000, "min_expanded_area_retained": 0.6,
      "normalize_perspective": false
    },
    "rule": {
      "rule_id": "model-a-presence", "rule_version": 3,
      "product_type": "model_a",
      "required_components": ["component_a", "component_b"]
    }
  },
  "local_overrides": {}
}
```

`revision` is always `"local"`; `checksum_sha256` is the SHA-256 of the
loaded config+rule bytes; sub-objects are `null` when the pipeline is not
loaded.

### Logs

**GET `/api/v1/logs`** — bounded structured log ring (capacity 500); `limit`
default 100; `next_cursor` always `null` (the TS client sends `cursor` but
the server ignores it).

```bash
curl "http://127.0.0.1:8000/api/v1/logs?limit=100" -H "Authorization: Bearer $TOKEN"
```

```json
{
  "items": [
    {"logged_at": "2026-08-10T09:30:03Z", "level": "INFO",
     "component": "assemblyvision.api", "message": "text", "trace_id": null}
  ],
  "next_cursor": null
}
```

### Reviews (edge-local human review, ADR-016)

**GET `/api/v1/reviews`** — review queue. Query params: `business_result`
(`OK`/`NG`), `internal_decision`, `reviewed` (boolean: `true` = reviewed,
`false` = open), `cursor`, `limit` (default 50). `400 INVALID_CURSOR` on
malformed/filter-mismatched cursor.

```bash
curl "http://127.0.0.1:8000/api/v1/reviews?business_result=NG&reviewed=false&limit=25" \
  -H "Authorization: Bearer $TOKEN"
```

```json
{
  "items": [
    {
      "inspection_id": "uuid",
      "completed_at": "2026-08-10T09:30:01Z",
      "business_result": "NG",
      "internal_decision": "UNCERTAIN",
      "barcode": "SN-001234",
      "reason_summary": ["COMPONENT_MISSING:component_a"],
      "has_review": false,
      "latest_disposition": null
    }
  ],
  "next_cursor": "opaque-or-null"
}
```

**GET `/api/v1/inspections/{inspection_id}/reviews`** — append-only history
(oldest first), plain array:

```json
[
  {
    "review_id": "uuid",
    "inspection_id": "uuid",
    "disposition": "CORRECTED_NG",
    "reason": "rework performed",
    "note": "operator confirmed",
    "reviewer": "operator-1",
    "created_at": "2026-08-10T10:00:00Z",
    "original_business_result": "OK",
    "original_internal_decision": "OK",
    "original_reason_codes": [],
    "component_corrections": [
      {"component_code": "component_a", "corrected_state": "MISSING", "note": "pad missing"}
    ],
    "supersedes_review_id": null
  }
]
```

**POST `/api/v1/inspections/{inspection_id}/reviews`** — append one review.
Request body (`extra="forbid"`):

```json
{
  "disposition": "CONFIRMED_NG",
  "reason": "defect visible",
  "note": "optional operator note",
  "reviewer": "operator-1",
  "supersedes_review_id": null,
  "component_corrections": [
    {"component_code": "component_a", "corrected_state": "PRESENT", "note": "optional"}
  ]
}
```

Constraints: `disposition` required; `reason` ≤200; `note` ≤2000; `reviewer`
required 1-128 chars; `component_corrections` ≤64, each `component_code`
1-64 (stripped), `corrected_state` ∈ `PRESENT|MISSING|UNCERTAIN`, `note`
≤500; `INCONCLUSIVE` requires a `reason`; duplicate component codes rejected.

Allowed dispositions per machine outcome (server enforces):
`UNCERTAIN` → `CONFIRMED_NG, CONFIRMED_OK, REINSPECT, INCONCLUSIVE`;
business `NG` → `CONFIRMED_NG, CONFIRMED_OK, INCONCLUSIVE`;
`OK` → `CONFIRMED_OK, CORRECTED_NG, INCONCLUSIVE`.

```bash
curl -X POST http://127.0.0.1:8000/api/v1/inspections/$INSPECTION_ID/reviews \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"disposition":"CONFIRMED_NG","reason":"defect visible","reviewer":"operator-1"}'
```

Response: the stored `ReviewRecord` (original machine fields snapshotted,
never rewritten). Errors: `404 INSPECTION_NOT_FOUND`; `409 REVIEW_CONFLICT`
(`supersedes_review_id` targets a different inspection); `422
REVIEW_DISPOSITION_INVALID` (disposition not allowed); `422
VALIDATION_FAILED` (schema/model validation).

### Statistics and traceability (derived)

**GET `/api/v1/statistics`** — query params `from`/`to` (timezone-aware UTC),
`line` (always rejected):

```bash
curl "http://127.0.0.1:8000/api/v1/statistics?from=2026-08-10T00:00:00%2B00:00&to=2026-08-10T23:59:59%2B00:00" \
  -H "Authorization: Bearer $TOKEN"
```

```json
{"total_inspections": 100, "pass_count": 82, "ng_count": 18, "pass_rate": 0.82}
```

Errors: `400 UNSUPPORTED_FILTER` (`line`), `400 INVALID_FILTER` (naive
timestamp), `400 INVALID_RANGE` (`from` after `to`).

**GET `/api/v1/traceability/{sn}`**:

```bash
curl http://127.0.0.1:8000/api/v1/traceability/SN-001234 -H "Authorization: Bearer $TOKEN"
```

```json
{
  "sn": "SN-001234",
  "final_status": "PASS",
  "attempts": [
    {"attempt": 1, "inspection_id": "uuid", "timestamp": "2026-08-10T09:30:01Z",
     "result": "PASS", "reason": "COMPONENT_MISSING:component_a", "operator": "-"}
  ]
}
```

Unknown SN → `404` `code: "SN_NOT_FOUND"`.

### WebSocket runtime channel

**GET `/api/v1/ws/runtime/stats`** — channel counters:

```json
{
  "active_connections": 0,
  "published_total": 0,
  "published_by_type": {},
  "slow_consumer_disconnects": 0,
  "delivery_failures": 0
}
```

**WS `/api/v1/ws/runtime`** — server-pushed envelopes (v1). Handshake
accepts bearer/session cookie or a single ticket as `Sec-WebSocket-Protocol`;
failure → close 4401; slow consumers disconnected with close code 1008.

```json
{
  "event_id": "uuid",
  "type": "inspection.completed",
  "schema_version": 1,
  "occurred_at": "2026-08-10T09:30:01Z",
  "source_id": "<device_id>",
  "sequence": 1,
  "correlation_id": null,
  "data": {"inspection_id": "i-9"}
}
```

Event types: `inspection.started`, `inspection.completed`,
`device.status_changed`, `upload.changed`. Sequence is strictly monotonic
per `(source_id, channel)`; a gap means events were lost — **clients must
refetch REST**. Events are transient; REST is authoritative.

### Dev test harness (ADR-014; 404 `DEV_TOOLS_DISABLED` unless `serve --enable-web-test`)

**POST `/api/v1/dev/inspect-frame`** — raw image bytes body; query params
`instance_id` (default first instance), `persist` (default true), `barcode`
(simulated keyboard input). Limits ≤20 MB, ≤12000 px/dim, ≤50 MP total.

```bash
curl -X POST "http://127.0.0.1:8000/api/v1/dev/inspect-frame?persist=true&barcode=ABC-001" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/octet-stream" \
  --data-binary @frame.jpg
```

200 → full `InspectionRecord`. Errors: `400 EMPTY_BODY`/`INVALID_IMAGE`,
`404 DEV_TOOLS_DISABLED`/`INSTANCE_NOT_FOUND`, `413 PAYLOAD_TOO_LARGE`,
`503 PIPELINE_UNAVAILABLE`.

**POST `/api/v1/dev/inspect-video`** — raw video bytes; `step` (default 1,
1-100); limits <100 MB, ≤30 sampled frames, ≤1000 decoded frames, ≤60 s
decode.

```bash
curl -X POST "http://127.0.0.1:8000/api/v1/dev/inspect-video?step=2" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/octet-stream" \
  --data-binary @sample.avi
```

```json
{
  "instance_id": "default",
  "analyzed_frames": 4,
  "ok_count": 2,
  "ng_count": 2,
  "frames": [
    {"index": 1, "business_result": "OK", "internal_decision": "OK", "reason_codes": []},
    {"index": 2, "business_result": "NG", "internal_decision": "NG", "reason_codes": ["TEST_REASON"]}
  ],
  "truncated": false
}
```

## Code inventory (where each endpoint lives)

| Router | File | Endpoints |
|---|---|---|
| auth | `api/routers/auth.py` | `POST /auth/session` |
| camera | `api/routers/camera.py` | `GET /camera/state`, `GET /camera/{instance_id}/preview` |
| configuration | `api/routers/configuration.py` | `GET /configuration/effective` |
| derived | `api/routers/derived.py` | `GET /traceability/{sn}`, `GET /statistics`, `GET /inspections/{id}/images` |
| dev | `api/routers/dev.py` | `POST /dev/inspect-frame`, `POST /dev/inspect-video` |
| device | `api/routers/device.py` | `GET /device/status` |
| health | `api/routers/health.py` | `GET /health/live`, `GET /health/ready` |
| inspection | `api/routers/inspection.py` | `GET /inspection/state` |
| inspections | `api/routers/inspections.py` | `GET /inspections`, `GET /inspections/{id}`, `GET /inspections/{id}/media` |
| logs | `api/routers/logs.py` | `GET /logs` |
| media | `api/routers/media.py` | `GET /media/{media_id}/content` |
| reviews | `api/routers/reviews.py` | `GET /reviews`, `GET/POST /inspections/{id}/reviews` |
| uploads | `api/routers/uploads.py` | `GET /uploads`, `POST /uploads/{task_id}/retry` |
| ws | `api/routers/ws.py` | `GET /ws/runtime/stats`, `POST /ws/runtime/ticket`, `WS /ws/runtime` |

The reference client that shows how the frontend really calls these is
`packages/typescript/api-client/src/edge/HttpApiClient.ts` (prefixes
`/api/v1`, attaches bearer, `credentials: "same-origin"`, parses
`Problem`). Response validation lives in
`packages/typescript/api-client/src/edge/validate.ts`.
