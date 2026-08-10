# 07 — Database and Persistence

How the SQLite store, migrations, repository, upload outbox, and retention
worker work, and how to extend them.

## Schema (SQLite, WAL mode, foreign keys on)

Tables defined in `apps/edge-service/src/assemblyvision_edge/persistence/
schema.py`:

| Table | Purpose | Key columns |
|---|---|---|
| `inspections` | Immutable projection of each inspection | `inspection_id`, `device_id`, `device_sequence`, lifecycle, timestamps, barcode/product resolution, internal/business decision, model/rule versions + checksums, reason JSON, latency, `synchronization_status` |
| `component_evidence` | Per-component aggregated evidence | `inspection_id` FK, `component_code`, state, confidence/counts, reason JSON |
| `media` | Media metadata (bytes live on disk) | `media_id`, `inspection_id` FK, `kind`, `relative_path`, mime, `size_bytes`, `checksum_sha256`, lifecycle + retention fields (E2), hold/claim/lease/fencing/purge columns, `integrity_status` |
| `upload_tasks` | Durable outbox | `upload_task_id`, `device_id`, `inspection_id`, `kind`, `object_id`, `payload_hash`, `idempotency_key`, `status`, `checksum_sha256`, `attempt_count`, `next_attempt_at`, `last_error_code`, timestamps, `lease_owner`, `lease_expires_at` |
| `device_events` | Append-only events | occurred time, severity, code, details JSON, upload state |
| `active_packages` | Installed/activated model/rule packages | version IDs, manifest JSON, paths, checksums, state |
| `rule_identities` | Durable rule identity registry | `(rule_id, rule_version)` unique, `content_sha256` — reusing an identity with different content fails load (`CONFIG_INVALID`) |
| `review_records` | Append-only human reviews (migration 0008) | `review_id`, `inspection_id` FK, disposition, reason/note/reviewer, original decision snapshot, component-corrections JSON, `supersedes_review_id` |

Indexes (minimum, contract 05 §4): barcode, inspection timestamp, decision,
product type, device ID, model version, upload status — plus the
operational indexes in design 14.5 (e.g. `upload_tasks(state,
next_attempt_at)`).

## Migrations (Alembic)

- Migrations live in `apps/edge-service/migrations/`; the head revision chain
  ends at the `review_records` migration (0008).
- `persistence/migrate.py` runs migrations on every database open with
  process + inter-process (`flock`) serialization and revision verification;
  honors `AV_EDGE_ROOT`.

### Adding a migration — template

```bash
cd apps/edge-service
uv run alembic revision -m "add your_table"   # or write it manually following the chain
```

The migration file (skeleton following the existing ones):

```python
"""add your_table

Revision ID: <head+1>
Revises: <current head>
Create Date: ...
"""
from alembic import op
import sqlalchemy as sa

revision = "<head+1>"
down_revision = "<current head>"


def upgrade() -> None:
    op.create_table(
        "your_table",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("inspection_id", sa.String(length=36), nullable=False),
        # ... define all columns; text CHECKs for enum-like strings where used
        sa.ForeignKeyConstraint(["inspection_id"], ["inspections.inspection_id"]),
    )
    op.create_index("ix_your_table_inspection_id", "your_table", ["inspection_id"])


def downgrade() -> None:
    op.drop_index("ix_your_table_inspection_id", table_name="your_table")
    op.drop_table("your_table")
```

Rules:
- Every schema change is a migration; production schemas are never edited
  manually. Write a tested up/downgrade (the suite has migration tests that
  open fresh + migrated DBs).
- Update `persistence/schema.py` table definitions to match.
- If the new data is exposed via the API, update schemas/OpenAPI/TS and the
  `contract.test.ts` schema assertions.
- Required indexes for new query paths (contract 05 §4 + design 14.5).

## Repository patterns (`persistence/repository.py`, `EdgeRepository`)

- Open via `EdgeRepository.open(path)` (runs migrations + `PRAGMA
  quick_check`, fails closed on corruption).
- **Atomic projection + outbox**: `persist_inspection_and_enqueue_uploads(record,
  retention=...)` upserts the inspection, evidence, media rows, and enqueues
  one `INSPECTION` task + one `MEDIA` task per artifact **in a single
  transaction** (SQLite `BEGIN`; short writer transactions).
- **CAS state transitions + fencing**: terminal/retry updates require the
  matching `lease_owner` token and an expected current state, e.g.
  `mark_upload_succeeded(task_id, lease_owner, receipt)` returns the number
  of rows changed (0 = stale owner → rejected); a success additionally
  requires a persisted **verified receipt** matching the task's immutable
  fields (idempotency key, object, kind, size, checksum).
- **Immediate-transaction serialization**: `submit_review` resolves
  `supersedes_review_id` chaining under `BEGIN IMMEDIATE` so concurrent
  submissions chain linearly (no lost updates).
- Startup reconciliation (`persistence/reconcile.py`): imports CLI
  `inspection.json` bundles idempotently, quarantines stale staging and
  malformed/unsafe bundles, runs `scan_storage_integrity`
  (existence/size/checksums with bounded sampling), and `media_path_is_safe`
  rejects traversal/symlink escapes.

## Upload outbox + scheduler (`upload/scheduler.py`)

- `UploadScheduler` drains the outbox: claims due tasks in an immediate
  transaction under a per-task lease + fencing token; `MEDIA` tasks become
  due only after their inspection task holds a verified success receipt
  (metadata always precedes media).
- Failure classification: transport errors and `408/429/5xx` → full-jitter
  exponential backoff honoring `Retry-After`; missing/corrupt local evidence
  and server `409` conflicts → `PERMANENT_FAILURE` with local evidence
  preserved.
- Verified receipts: a 2xx is success only when the bounded typed receipt
  echoes the idempotency key, object, kind, size, and checksum of the payload
  sent; media receipts additionally require a central object ID.
- Sinks: `HttpUploadSink` (HTTPS POST to `{base_url}/inspection-uploads`;
  dev HTTP loopback-only) and `DirectoryUploadSink` (local/dev, idempotent by
  key). No configured destination → the worker stays disabled and tasks
  remain visible in `/api/v1/uploads`.
- E3 extras in the same module: token-bucket bandwidth limiter, circuit
  breaker (consecutive retryable failures → open → half-open probe), and the
  manual-retry path behind `POST /api/v1/uploads/{id}/retry`.

## Retention worker (`retention/worker.py`, `policy.py`, `storage.py`)

- Eligibility: inspection `SYNCED` (every task receipt-verified) + media
  receipt with central object ID + retention deadline elapsed + no
  hold/fault/purge/deleting state.
- `RetentionCleanupWorker`: claims candidates under an inter-process SQLite
  lease with per-artifact fencing; re-validates the full predicate
  immediately before destructive I/O; unlinks via `O_NOFOLLOW` directory
  file descriptors (a concurrent symlink swap cannot remove files outside
  the inspection bundle); missing files → integrity faults, never false
  purges; failed unlinks retryable and observable.
- Without an approved, enabled policy (`AV_EDGE_RETENTION_ENABLED=true` +
  `AV_EDGE_RETENTION_DURATIONS`), the worker performs **zero** filesystem
  mutation.
- `observe_storage` computes `PressureMode` (`NORMAL/WARNING/CRITICAL/STOP`)
  from free bytes + inodes against strictly ordered thresholds
  (`stop < critical < warning`); `storage_write_fault` latches and only
  clears via `probe_persistence` (probe file + fsync + `BEGIN IMMEDIATE`
  write).

## Extending persistence — checklist

- [ ] Migration with tested up/downgrade (revision chain follows the head)
- [ ] `schema.py` table/index updated
- [ ] Repository method with CAS transitions + fencing where applicable
- [ ] Tests: fresh + migrated DB, concurrent claims, lease fencing,
  restart-recovery, checksum mismatch
- [ ] OpenAPI/TS + contract tests if exposed via the API
