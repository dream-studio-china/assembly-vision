# Runbook C1: Central Ingestion Backlog

## Trigger

The central `upload_receipts`/`inspections` tables grow without the edge
reaching `SYNCED`, or the `central ingestion backlog` operational signal (oldest
un-receipted edge task age, receipt rate, or retry rate) exceeds approved
thresholds. This is the central half of runbook 04: the edge outbox remains
authoritative and continues local inspection while the central catch-up is in
progress.

## Immediate Safety Action

1. Confirm the edge scheduler is not being blocked: central backlog never
   affects edge inspection decisions (C1 invariant 1). Only the edge's own
   upload circuit (runbook 04) pauses retry traffic.
2. Do not delete `upload_receipts`, `inspections`, `inspection_media`, or
   `audit_logs` rows to make the backlog disappear. Receipts are replayable
   evidence; deletion breaks effectively-once persistence.
3. Classify the cause before acting: connectivity/TLS, device credential,
   API capacity/rate limit (`429`), dependency outage (`503` +
   `Retry-After`), or payload conflict (`409`).

## Diagnosis

1. Inspect recent receipts and their response codes:

   ```sql
   SELECT response_code, status, COUNT(*) FROM upload_receipts
   GROUP BY response_code, status ORDER BY 3 DESC;
   ```

2. Confirm accepted inspections exist without media bindings (partial uploads):

   ```sql
   SELECT i.inspection_id, i.received_at FROM inspections i
   LEFT JOIN inspection_media m ON m.inspection_row_id = i.id
   WHERE m.id IS NULL;
   ```

3. Check API capacity and dependency health via
   `GET /api/v1/health/ready`; a `503 DATABASE_UNAVAILABLE` or
   `503 OBJECT_STORE_UNAVAILABLE` during the backlog window points at a
   dependency fault (runbook C2) rather than a device issue.

## Recovery

1. Resolve the underlying dependency or credential fault first; receipts are
   only issued after durable commits, so retrying accepted work is
   duplicate-free (identical replay returns the original receipt).
2. Let the edge scheduler retry with its own backoff; do not raise edge
   concurrency enough to starve inference.
3. If replayable media is missing, confirm the object store is reachable and
   run the reconciliation path; bindings report `PENDING` until the final
   MinIO object is present and checksum-verified (C1 invariant 8).
4. When the backlog drains, record start/end time, actor, affected device
   scope, cause, and the evidence the edge reached `QUEUED → PARTIAL → SYNCED`.

## Verification

- `GET /api/v1/inspections` shows the expected received windows and the oldest
  pending-upload age returns to baseline.
- No `409 PAYLOAD_CONFLICT` storms appear (conflicts mean a retry reused a key
  with different content and must be investigated, never force-cleared).

## Escalation

- Backlog persists after dependency recovery, or any `409` conflict cluster
  appears: pause the affected device's retries and engage the operator owning
  the credential/contract boundary before allowing further uploads.
