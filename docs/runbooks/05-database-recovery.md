# Runbook 05: Database Recovery

## Trigger

SQLite/PostgreSQL integrity error, failed migration, unavailable database, or unrecoverable transaction failure.

## Immediate Safety Action

1. Mark inspection readiness false when local decisions cannot be durably recorded.
2. Preserve database files, WAL/journals, media, temporary files, and logs; do not run destructive repair first.
3. Stop writers and record application/schema versions and the last known inspection sequence.

## Recovery

1. Run supported integrity diagnostics on a copy.
2. Restore the latest verified backup using the documented database procedure.
3. Apply approved Alembic migrations and verify schema revision.
4. Reconcile media manifests, incomplete inspections, expired leases, and central upload receipts.
5. Quarantine unrecoverable evidence gaps and require reinspection where identity is known.

## Exit Criteria

Integrity checks pass, sequence/idempotency invariants hold, reconciliation is recorded, and smoke inspection succeeds.
