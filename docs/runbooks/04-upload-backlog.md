# Runbook 04: Upload Backlog

## Trigger

Queue count/bytes, oldest pending age, retry rate, or permanent failures exceed approved thresholds.

## Immediate Safety Action

1. Confirm local inspection remains ready and protected capacity is sufficient
   (see runbook 03: retention cleanup only deletes receipt-verified,
   hold-elapsed media; it never deletes pending-upload evidence).
2. Do not delete queued evidence or increase worker concurrency enough to starve inference.
3. Classify failures: connectivity, authentication, server capacity, schema, checksum, or content conflict.

## Recovery

1. Fix the dependency or credential fault; retain original idempotency keys and payload hashes.
2. Resume with bounded concurrency, backoff, jitter, and bandwidth limits.
3. Quarantine permanent content conflicts; do not overwrite immutable records.
4. Reconcile central receipts before marking tasks `SUCCEEDED`.
5. Watch `UPLOAD_FAILING`/`UPLOAD_BLOCKED` alerts and `upload_failure_rate` in
   device status; a `PERMANENT_FAILURE` upload keeps local evidence protected
   from retention deletion (`SYNCED` is required before media is eligible).

## Exit Criteria

Backlog drains without duplicates, oldest age returns below threshold, and permanent failures have owners.
