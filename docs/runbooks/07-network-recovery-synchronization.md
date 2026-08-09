# Runbook 07: Network Recovery Synchronization

## Trigger

Connectivity returns after an edge-to-central outage.

## Recovery

1. Keep inspection independent; verify protected local capacity and queue integrity.
2. Probe central authentication and health without releasing the entire backlog at once.
3. Drain due tasks with bounded concurrency, stable idempotency keys, backoff, and checksums.
4. Reconcile identical receipts, content conflicts, missing media, and out-of-order inspections.
5. Compare local queued/succeeded totals with central receipts and media availability.

## Exit Criteria

All eligible tasks are `SUCCEEDED`, remaining permanent failures are assigned,
no duplicates exist, and local cleanup becomes eligible only after verified
receipts and retention checks. Integrity-faulted or held media remains
protected; reconcile it through runbook 05 before any manual action.
