# Runbook 04: Upload Backlog

## Trigger

Queue count/bytes, oldest pending age, retry rate, or permanent failures exceed approved thresholds. The
`UPLOAD_CIRCUIT_OPEN` alert also fires while the scheduler stops attempting uploads during an outage.

## Immediate Safety Action

1. Confirm local inspection remains ready and protected capacity is sufficient
   (see runbook 03: retention cleanup only deletes receipt-verified,
   hold-elapsed media; it never deletes pending-upload evidence).
2. Do not delete queued evidence or increase worker concurrency enough to starve inference.
3. Classify failures: connectivity, authentication, server capacity, schema, checksum, or content conflict.

## Circuit-Open Diagnosis

1. `UPLOAD_CIRCUIT_OPEN` plus `upload_circuit_state=OPEN` in device status means the worker hit
   `AV_EDGE_UPLOAD_CIRCUIT_FAILURE_THRESHOLD` consecutive retryable failures (transport or
   `408/429/5xx`); permanent local/content failures never open the circuit.
2. The circuit is process-local liveness: it pauses new attempts, never mutates the queue, and the
   durable queue truth remains in `/api/v1/uploads`. After `AV_EDGE_UPLOAD_CIRCUIT_OPEN_SECONDS` the
   worker half-opens and probes one task; success closes it, failure reopens it.
3. Fix the dependency or credential fault first; while the circuit is open, no retry traffic is
   sent, so inspection capacity and queue growth are unaffected by the outage itself.

## Recovery

1. Fix the dependency or credential fault; retain original idempotency keys and payload hashes.
2. Resume with bounded concurrency, backoff, jitter, and bandwidth limits
   (`AV_EDGE_UPLOAD_MAXIMUM_BANDWIDTH_MBPS` bounds the serialized request body the HTTP sink sends).
3. Quarantine permanent content conflicts; do not overwrite immutable records.
4. Reconcile central receipts before marking tasks `SUCCEEDED`.
5. Use `POST /api/v1/uploads/{upload_task_id}/retry` only for `RETRY_WAIT` or `PERMANENT_FAILURE`
   tasks after the underlying cause is corrected. The transition is atomic (concurrent retries yield
   one success and one conflict), increments `attempt_count`, and never authorizes retention cleanup:
   media stays protected until a new verified central receipt makes the inspection `SYNCED`.
6. Watch `UPLOAD_FAILING`/`UPLOAD_BLOCKED`/`UPLOAD_CIRCUIT_OPEN` alerts, `upload_failure_rate`, and
   `upload_bytes_sent`/`upload_bandwidth_mbps`; a `PERMANENT_FAILURE` upload keeps local evidence
   protected from retention deletion (`SYNCED` is required before media is eligible).

## Exit Criteria

Backlog drains without duplicates, oldest age returns below threshold, the circuit closes and stays
closed, and permanent failures have owners.
