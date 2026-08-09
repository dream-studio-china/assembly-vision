# Runbook 12: Backup and Recovery

## Trigger

Scheduled backup, hardware replacement, disk failure, database corruption, or
pre-change snapshot before an upgrade or configuration change.

## Before You Begin

- Record site/device, start/end time, actor, affected inspections, evidence
  bundle, actions, result, and escalation reference.
- Confirm the service is stopped or quiesced only if required by the backup
  destination; `assemblyvision backup` uses the SQLite online backup API and is
  safe against a running service.
- Confirm the destination has enough space for the database, governed files,
  and pending (not yet uploaded) evidence.

## Backup Procedure

1. Create a consistent, checksummed bundle:

   ```text
   assemblyvision backup \
     --output /var/lib/assemblyvision/media \
     --db /var/lib/assemblyvision/db/edge.sqlite3 \
     --config /etc/assemblyvision/pipeline.yaml \
     --rule /etc/assemblyvision/rule.yaml \
     --dest /backup/edge-2026-08-10.tar.gz
   ```

2. Verify the reported SHA-256 and that governed files and pending evidence
   counts match expectations. A missing or changed pending-evidence file makes
   the backup fail closed instead of producing an incomplete bundle.
3. Copy the bundle off the device (encrypted destination agreed with the
   customer). Backups of edge configuration, rules, and manifests are taken on
   change and on the scheduled copy.
4. A backup is operational only after a representative restore has succeeded;
   do not rely on a backup that has never been restored.

## Recovery Procedure

1. Stop the edge service. Preserve the current database and media; recovery
   never deletes pending uploads or evidence.
2. Restore from the verified bundle:

   ```text
   assemblyvision restore \
     --backup /backup/edge-2026-08-10.tar.gz \
     --output /var/lib/assemblyvision/media \
     --db /var/lib/assemblyvision/db/edge.sqlite3
   ```

   Restore verifies every bundle checksum before applying anything, keeps a
   `.pre-restore` copy of the current database, restores pending media without
   overwriting conflicting files, and reconciles the store against the output
   root so pending upload tasks survive.
3. Start the service and confirm `/api/v1/health/ready` reports ready, history
   is visible, and the upload queue resumes.
4. Run a smoke inspection against a known sample and verify NG behavior before
   returning to production.

## Exit Criteria

Integrity checks pass, history and pending upload tasks are present, media
references resolve, and a smoke inspection succeeds.

## Related

- [Database Recovery](05-database-recovery.md)
- [Upload Backlog](04-upload-backlog.md)
