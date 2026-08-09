# Runbook 03: Low Disk Space

## Trigger

Warning/critical/stop storage pressure (free bytes or free inodes below the
configured `AV_EDGE_STORAGE_*` thresholds), a failed mandatory write, a
`STORAGE_WRITE_FAULT` alert, or abnormal storage growth.

## Alert Codes

| Alert | Meaning |
|---|---|
| `DISK_WARNING` | Free bytes or inodes below the warning threshold; eligible cleanup accelerates. |
| `DISK_CRITICAL` | Free bytes or inodes below the critical threshold; optional capture (rolling video, OK samples) is suppressed; mandatory NG evidence stays protected. |
| `DISK_STOP` | Free bytes or inodes below the stop threshold; new product intake stops because durable mandatory persistence cannot be guaranteed. |
| `STORAGE_WRITE_FAULT` | The volume could not be measured or a mandatory write failed (`ENOSPC`/`EROFS`/I/O); inspection readiness is forced false. |
| `CLEANUP_FAULT` | Retention cleanup hit a delete error (e.g. `EACCES`, read-only volume); cleanup retries are failing. |

## Immediate Safety Action

1. Preserve pending-upload, held-review, and mandatory inspection evidence.
   Cleanup only deletes receipt-verified, hold-elapsed media under an approved
   retention policy; it never deletes protected evidence to free space.
2. At `DISK_STOP` or `STORAGE_WRITE_FAULT`, the edge reports
   `inspection_ready=false` and stops accepting new products; do not force a
   resume before reserve is restored.
3. Do not delete evidence manually; remove only quarantined/staging files or
   data explicitly identified by the retention policy.

## Recovery

1. Identify growth by media class, logs, database, temporary files, upload
   backlog, and `quarantine/` contents.
2. Restore connectivity/credentials so the upload backlog drains and verified
   receipts accumulate; retention cleanup then deletes only eligible media.
3. Verify cleanup state in device status: `cleanup_eligible_count`,
   `cleanup_purged_count`, `cleanup_delete_error_count`, and
   `cleanup_integrity_fault_count`.
4. If `CLEANUP_FAULT` persists, check volume permissions/read-only state and
   the filesystem; a faulted artifact (`integrity_status=FAULT`) is protected
   until an operator reconciles it.
5. When space is restored, confirm `storage_mode` returns to `NORMAL`/`WARNING`
   and run an integrity scan check before resuming the line.

## Exit Criteria

Reserve capacity is restored, mandatory writes pass, `inspection_ready=true`,
no protected evidence was removed, and cleanup/integrity state is auditable
through device status and logs.
