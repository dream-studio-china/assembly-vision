# Runbook 05: Database Recovery

## Trigger

SQLite/PostgreSQL integrity error, failed migration, `quick_check` failure,
unavailable database, or unrecoverable transaction failure.

## Immediate Safety Action

1. Mark inspection readiness false when local decisions cannot be durably
   recorded. The edge fails closed: `EdgeRepository.open` runs `PRAGMA
   quick_check` and refuses to serve a database that does not pass it.
2. Preserve database files, WAL/journals, media, temporary files, and logs; do
   not run destructive repair first.
3. Stop writers and record application/schema versions and the last known
   inspection sequence.

## Recovery

1. Run supported integrity diagnostics on a copy (never on the live database).
2. Restore the latest verified backup using the documented database procedure;
   the service must not automatically initialize a fresh database over
   corrupted evidence.
3. Apply approved Alembic migrations and verify schema revision and
   `quick_check`.
4. Reconcile media manifests, incomplete inspections, expired upload and
   retention cleanup leases, integrity-faulted media, and central upload
   receipts.
5. Quarantine unrecoverable evidence gaps and require reinspection where
   identity is known; protected (faulted) media is never deleted by retention.

## Exit Criteria

Integrity checks pass, sequence/idempotency invariants hold, reconciliation is
recorded, and smoke inspection succeeds.
