# 04. Edge, Storage, and Upload Contracts

## 1. Edge-First Principle

The edge client must continue inspecting when:

- The central server is unavailable
- The network is disconnected
- DNS resolution fails
- Upload attempts fail
- The central database is unavailable

The central server must never participate in the real-time release decision.

## 2. Edge Responsibilities

The edge client owns:

- Camera capture
- Barcode recognition
- Product detection
- ROI generation
- Component detection
- Temporal aggregation
- Rule evaluation
- Final inspection decision
- Local persistence
- Upload queue management

## 3. Local Persistence Order

```text
1. Complete inspection
2. Finalize required media files with size and checksum
3. Atomically commit inspection, media manifests, and upload outbox tasks
4. Publish/return the committed local result
5. Upload asynchronously
```

Steps 2 and 3 form one recoverable unit: a crash must not leave a completed inspection without its
required upload task. Temporary files and incomplete transactions are reconciled at startup.

Local media and records must not be deleted before confirmed upload and retention checks.

## 4. Upload Task Fields

Each upload task must contain at least:

- `upload_task_id`
- `device_id`
- `inspection_id` (nullable for device-event tasks)
- `object_id`
- `kind`
- `payload_hash`
- `checksum_sha256` when bytes are uploaded
- `status`
- `attempt_count`
- `next_attempt_at`
- `last_error_code`
- `created_at`
- `updated_at`
- `completed_at`
- Lease owner and expiry while in progress

Canonical states are `PENDING`, `IN_PROGRESS`, `RETRY_WAIT`, `SUCCEEDED`,
`PERMANENT_FAILURE`, and `CANCELLED`.

## 5. Idempotency

The central server must support idempotent uploads.

Recommended idempotency key:

```text
inspection:{device_id}:{inspection_id}
```

Duplicate upload attempts must not create duplicate inspection records.

## 6. File Integrity

Media uploads must:

- Compute a checksum
- Validate file size
- Validate upload completion
- Store the central object identifier
- Update local task state only after confirmed success

## 7. Restart Recovery

On startup, the edge application must:

- Recover `PENDING` tasks
- Recover `RETRY_WAIT` tasks
- Detect stale `IN_PROGRESS` tasks
- Move stale tasks back into a retryable state
- Verify referenced media still exists
- Validate database-to-file consistency where practical

## 8. Cleanup Rules

The local cleanup process must not delete:

- Data not yet uploaded
- Data with unknown upload state
- Media still referenced by local records
- Data locked for acceptance testing or human review

## 9. Central Review

The central server may append:

- `review_disposition`
- `review_comment`
- `reviewer`
- `reviewed_at`

It must not overwrite:

- `original_internal_decision`
- `original_business_result`
- Product-detector model version and checksum
- Component-detector model version and checksum
- `rule_version`
- Original media references

## Related Documents

- [Edge Client Architecture](../design/04-edge-client-architecture.md)
- [Local Storage and Retention](../design/12-local-storage-and-retention.md)
- [Upload and Synchronization](../design/13-upload-and-synchronization.md)
- [ADR-001: Edge-First Inspection](../design/decisions/ADR-001-edge-first-inspection.md)
- [ADR-005: Local-First Storage and Delayed Upload](../design/decisions/ADR-005-local-first-storage-and-delayed-upload.md)
