# Runbook C2: Central Object-Store Failure (MinIO)

## Trigger

`GET /api/v1/health/ready` reports `object_store: unreachable` or
`bucket missing`; media uploads fail with `503 OBJECT_STORE_UNAVAILABLE` and
`Retry-After`; readiness degrades while PostgreSQL stays healthy.

## Immediate Safety Action

1. The API never reports media `AVAILABLE` until the final MinIO object is
   present and checksum-verified (C1 invariant 8). Missing bindings stay
   `PENDING`; this is correct, do not force them to `AVAILABLE`.
2. Inspection metadata ingestion must keep working: it commits to PostgreSQL
   only. A healthy database means history and receipts keep flowing while the
   object store is down; the edge reaches `PARTIAL`, not `SYNCED`.
3. Do not delete `PENDING` bindings or object keys; they are the recovery
   plan after the store returns.

## Diagnosis

1. Confirm the failure is the store, not the network path:

   ```text
   docker compose ps minio
   docker compose logs --tail=200 minio
   ```

2. Verify bucket credentials and bucket existence from the API container
   settings (`AV_CENTRAL_MINIO_*`); the API only needs an internal endpoint
   in Compose.
3. Check readiness from inside the API container to confirm the probe fails
   for object_store only:
   `GET /api/v1/health/ready` must name the failing dependency without
   exposing credentials or internal paths.

## Recovery

1. Restart MinIO and confirm the volume mounts intact; the object keys are
   central-generated opaque keys under `org/{id}/device/{device}/...` and
   survive container restart because they live in the persistent volume.
2. Re-run the reconciliation path so `PENDING` bindings whose objects exist
   are finalized and `AVAILABLE`; bindings whose objects are genuinely gone
   are reported `FAILED` for operator review (never silently dropped).
3. Resume edge retries; media re-uploads are duplicate-free (same
   idempotency key + same bytes replay the original receipt).

## Verification

- `GET /api/v1/health/ready` returns all `ok` again.
- No binding reports `AVAILABLE` without its object; every `FAILED` binding
  has a recorded reconciliation reason and an owner.

## Escalation

- Objects lost from the volume (binding `FAILED` with no object): do not
  re-run production with missing evidence; engage storage/backup owner and
  confirm runbook C4 (backup/restore) coverage before accepting new media.
- Store outage overlaps a critical backlog: engage the platform owner for
  disk/network and schedule the catch-up outside peak windows.
