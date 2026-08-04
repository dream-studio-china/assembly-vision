# Runbook 03: Low Disk Space

## Trigger

Warning/critical byte or inode watermark, failed mandatory write, or abnormal storage growth.

## Immediate Safety Action

1. Preserve pending-upload, held-review, and mandatory inspection evidence.
2. At warning level, stop optional rolling/full-video retention and alert operations.
3. At critical level, stop new inspections if durable mandatory recording cannot be guaranteed.

## Recovery

1. Identify growth by media class, logs, database, temporary files, and upload backlog.
2. Delete only expired, uploaded, unreferenced data in the documented retention order.
3. Resolve the underlying upload/network fault or expand/replace storage.
4. Reconcile filesystem paths, media manifests, checksums, and database references.

## Exit Criteria

Reserve capacity is restored, mandatory writes pass, no protected evidence was removed, and cleanup is audited.
