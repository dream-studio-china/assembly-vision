# central-service

AssemblyVision central server (M1 pilot). Receives delayed edge inspection and
media uploads, stores history in PostgreSQL and evidence in an S3-compatible
object store (MinIO), and provides the pilot administration surface.

M1 is a management and evidence plane. It is never required for edge
inspection decisions; the edge durable outbox remains authoritative for
pending uploads (see `docs/tasks/C1-central-server-m1.md`).

## Layout

```text
src/central_service/
  api/             # FastAPI app, routers, auth dependencies, problems, OpenAPI
  persistence/     # SQLAlchemy engine, Alembic migrations, schema metadata
  storage/         # MinIO/S3 object storage abstraction
  observability/   # structured logging, request correlation, readiness
```

## Commands

```text
python -m central_service migrate   # controlled schema release step (Alembic)
python -m central_service serve     # run the FastAPI application
```

Migrations are a controlled release step and are never run automatically by
the API process.

## Configuration

All settings are read from `AV_CENTRAL_*` environment variables (see
`central_service/api/settings.py`). `compose.env.example` contains empty
required placeholders only; every Compose secret must be supplied in a private
`.env` or a deployment secret store before startup.
