# Runbook C4: Central Backup and Restore (PostgreSQL + MinIO)

## Trigger

Scheduled backup, pre-change snapshot before a pilot upgrade, hardware
replacement, database corruption, or media loss.

## Before You Begin

- Record site/device scope, start/end time, actor, backup destination,
  checksums, and the verification result. The edge keeps operating through
  the whole procedure; central backup does not gate edge inspection.
- Confirm the destination has enough space for the PostgreSQL dump and the
  MinIO object volume copy.
- M1 limits: the procedure below is a controlled-pilot backup/restore with a
  verified restore. It does **not** claim production HA, final RPO/RTO,
  point-in-time recovery windows, or continuous replication.

## Backup Procedure

1. **PostgreSQL logical backup** (schema + governed data + receipts + audit):

   ```text
   docker compose exec postgres pg_dump -U central -d assemblyvision \
     --format=custom -f /tmp/assemblyvision.dump
   docker compose cp central-service-postgres-1:/tmp/assemblyvision.dump \
     ./backups/assemblyvision-<date>.dump
   ```

   Record the SHA-256 of the dump file.

2. **MinIO data alignment**: media evidence lives in the object store, so the
   database backup alone is not a full restore. Copy the bucket (or the
   persistent volume) with an S3-compatible tool, preserving object keys:

   ```text
   mc mirror --overwrite --remove \
     myminio/assemblyvision-central ./backups/minio-<date>/
   ```

   The DB and the object store are backed up at approximately the same point;
   restore both from the same dated bundle so bindings line up.

3. Verify the backup before storing it: `pg_restore --list` on the dump and a
   `mc ls`/checksum spot-check of the mirror.

## Restore Procedure

1. Stop the API so no writes race the restore (the edge outbox keeps its
   durable queue and resumes after).

   ```text
   docker compose stop central-service
   ```

2. **PostgreSQL**: create a fresh database (or restore into an empty one) and
   load the dump:

   ```text
   docker compose exec postgres createdb -U central assemblyvision_restored
   docker compose cp ./backups/assemblyvision-<date>.dump \
     central-service-postgres-1:/tmp/assemblyvision.dump
   docker compose exec postgres pg_restore -U central -d assemblyvision_restored \
     /tmp/assemblyvision.dump
   ```

3. **MinIO**: restore the object volume/bucket from the same dated mirror so
   every `AVAILABLE` binding's object exists.
4. Point the API at the restored database (or rename the restored database
   back) and start the API again.

## Verification

- `GET /api/v1/health/ready` reports all dependencies `ok`, and the schema is
  at head (`alembic_version` matches the committed migration head).
- Spot-check `GET /api/v1/inspections` for the restored window and confirm
  media items load authorized URLs (`AVAILABLE`, not `PENDING`/`FAILED`).
- Replay one accepted upload: identical replay returns the original receipt
  (duplicate-free), proving receipts and effectively-once state survived.

## Escalation

- Restore verification fails (missing objects, schema drift, receipt replay
  conflicts): restore again from the same bundle or the prior verified bundle,
  and do not resume the pilot until a representative restore succeeds.
- Restore into a production (non-pilot) environment is out of M1 scope and
  must follow the organization's DR policy.
