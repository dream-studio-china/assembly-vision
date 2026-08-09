# syntax=docker/dockerfile:1
# AssemblyVision edge-service image (design 20.3/20.4, E5a).
#
# Multi-stage build:
#   - builder: resolves the pinned uv workspace (uv.lock) and installs the
#     edge service plus its workspace dependencies non-editable into the
#     workspace virtualenv (uv places it at the workspace root), so the
#     runtime stage ships only that virtualenv;
#   - runtime: slim base, dedicated non-root user, read-only root filesystem
#     (all runtime writes go to /var/lib/assemblyvision volumes), a health
#     check against /api/v1/health/live, and no source tree, tests, training
#     code, Git metadata, or package-manager caches.

FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim AS builder

WORKDIR /app
COPY . .

RUN uv sync --frozen --no-dev --no-editable --project apps/edge-service

FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PATH=/opt/assemblyvision/venv/bin:$PATH

RUN groupadd --gid 10001 av \
    && useradd --uid 10001 --gid 10001 --no-create-home --home-dir /opt/assemblyvision av \
    && mkdir -p /opt/assemblyvision /var/lib/assemblyvision \
    && chown -R av:av /opt/assemblyvision /var/lib/assemblyvision

COPY --from=builder --chown=av:av /app/.venv /opt/assemblyvision/venv

USER av
WORKDIR /opt/assemblyvision

EXPOSE 8000

HEALTHCHECK --interval=15s --timeout=3s --start-period=30s --retries=4 \
  CMD python -m assemblyvision.healthcheck http://127.0.0.1:8000/api/v1/health/live

ENTRYPOINT ["assemblyvision"]
CMD ["serve", "--output", "/var/lib/assemblyvision/media", "--db", "/var/lib/assemblyvision/db/edge.sqlite3", "--host", "0.0.0.0"]
