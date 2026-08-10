# AssemblyVision central-service image (design 05 section 10, C1a).
#
# Multi-stage build mirrors apps/edge-service: the builder resolves the pinned
# uv workspace and installs the central service non-editable into the workspace
# virtualenv; the runtime stage ships only that virtualenv, runs as a dedicated
# non-root user with a read-only root filesystem, and never auto-migrates the
# schema (migrations are a controlled release step).

FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim AS builder

WORKDIR /app
COPY . .

RUN uv sync --frozen --no-dev --no-editable --project apps/central-service

FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PATH=/opt/central/venv/bin:$PATH

RUN groupadd --gid 10002 central \
    && useradd --uid 10002 --gid 10002 --no-create-home --home-dir /opt/central central \
    && mkdir -p /opt/central

COPY --from=builder --chown=central:central /app/.venv /opt/central/venv
# Alembic migrations and config are outside the Python package; point the
# packaged runtime at their copied location.
ENV AV_CENTRAL_ROOT=/opt/central
COPY --from=builder --chown=central:central /app/apps/central-service/alembic.ini /opt/central/alembic.ini
COPY --from=builder --chown=central:central /app/apps/central-service/migrations /opt/central/migrations

USER central
WORKDIR /opt/central

EXPOSE 8000

HEALTHCHECK --interval=15s --timeout=3s --start-period=30s --retries=4 \
  CMD python -m central_service.healthcheck http://127.0.0.1:8000/api/v1/health/live

# The virtualenv is moved from the builder path, so console-script shebangs
# are stale; invoke the package module instead.
ENTRYPOINT ["python", "-m", "central_service"]
CMD ["serve", "--host", "0.0.0.0"]
