# Runbook C5: Central Pilot Upgrade and Rollback

## Trigger

Planned pilot upgrade (new central-service/admin-web image, schema migration,
or configuration change) or rollback after a failed upgrade.

## Before You Begin

- Record start/end time, actor, source and target image tags, migration
  revisions, affected device scope, and the verification result.
- Take a backup first (runbook C4): PostgreSQL dump + MinIO mirror, and record
  the current `alembic_version` and image digests.
- Confirm the edge contract boundary: the M1 wire envelope is frozen; an
  upgrade must keep accepting the existing envelope or it must be treated as a
  contract-breaking change (out of pilot scope).

## Upgrade Procedure

1. Build and pull the new images, then apply schema migrations as a
   **controlled release step**, never concurrently from API replicas:

   ```text
   docker compose build central-service admin-web
   docker compose run --rm central-migrate
   ```

2. Verify the migrated schema before starting the API:
   `alembic_version` equals the new head, and
   `GET /api/v1/health/ready` reports `database: ok`.
3. Start the new API and admin-web, then verify:
   - `GET /api/v1/health/ready` all `ok`;
   - a sample inspection upload still returns a verified compatible receipt
     and replay is duplicate-free;
   - admin login, history/detail, review, and the configuration pages load
     without error alerts.

## Rollback Procedure

1. If the upgrade fails verification, stop the API and restore the previous
   image tag and the **pre-upgrade backup** (runbook C4). Schema rollback is a
   database restore, not a reverse migration: downgrade migrations are not a
   substitute for a verified restore.
2. Confirm `alembic_version` matches the pre-upgrade head and that
   `GET /api/v1/inspections` returns the pre-upgrade windows with media
   `AVAILABLE`.
3. Resume the edge scheduler and verify `QUEUED → PARTIAL → SYNCED` reaches
   `SYNCED` for a sample device; the durable outbox replays anything accepted
   by neither side.

## Verification

- Post-upgrade and post-rollback, readiness is all-`ok`, receipts replay
  duplicate-free, and no `409` conflict cluster or `503` dependency storm
  appears in the API logs.
- The admin UI shows the expected version and no regression alerts.

## Escalation

- Migration fails mid-way: do not force the API up; restore the pre-upgrade
  backup and engage the migration owner (contract 05 section 3: migrations
  remain auditable and risky migrations require migration notes).
- Edge outbox disagreement after upgrade/rollback (a payload accepted on one
  side only): keep the edge outbox as authority and re-upload with original
  idempotency keys rather than force-clearing any side.
