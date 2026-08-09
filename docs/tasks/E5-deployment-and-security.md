# E5 Pipeline: Deployment and Security

## 1. Purpose

E5 turns the edge runtime into a deployable, recoverable production unit
without introducing the central server:

- **Docker packaging**: a multi-stage, non-root, read-only-root image for
  `edge-service` with health checks, restart policy, and explicit persistent
  volumes (design 20.3/20.4, contract 07 §1).
- **Secrets and TLS**: runtime-only secret injection (environment or Docker
  secrets), a local TLS option for the edge API, and production constraints so
  a non-loopback bind or a non-HTTPS central endpoint is rejected unless an
  explicit development flag is present (design 21.4/21.9, contract 08).
- **Backup and restore**: a consistent `assemblyvision backup` /
  `assemblyvision restore` workflow for the SQLite store, governed
  configuration, and pending evidence, with a restore that never drops
  un-uploaded media (design 20.10, contract 07 §7).
- **Deployment runbooks**: backup/restore, TLS certificate rotation, and
  upgrade/rollback procedures added to the indexed runbook set.

The central server remains out of scope; this milestone never makes inspection
depend on central reachability.

## 2. Scope and Non-Goals

### In scope

- Multi-stage Dockerfile for `edge-service` (uv build, non-root runtime UID,
  read-only root filesystem, explicit writable volumes), a healthcheck module,
  and a `compose.yaml` deployment template.
- Runtime secret injection via environment or Docker secrets
  (`/run/secrets/<name>`), including the viewer token and upload token.
- Optional local TLS termination for the edge API with certificate/key from
  secrets, plus validation that certificate and key exist, match, and are not
  world-readable.
- `assemblyvision backup` (online SQLite backup plus configuration, rule,
  manifest, and pending-evidence manifest with checksums) and
  `assemblyvision restore` (validated restore that leaves media intact and
  reconciles the store against the output root).
- Runbooks 12-14: backup and recovery, TLS certificate rotation, and
  deployment upgrade/rollback.

### Out of scope

- Central deployment (Compose profile, PostgreSQL, object storage) until the
  central milestone starts.
- Signed package distribution and fleet rollout (CENTRAL-007 production
  scope; the one-month demonstrator installs checksum-verified packages
  manually).
- Kubernetes, orchestrated secret stores (Vault), or hardware-backed key
  management.
- Strong code obfuscation: `.pyc`-only packaging is packaging hygiene, not a
  security boundary (design 21.8).

## 3. Safety Invariants

The following invariants are mandatory in every E5 change and test:

1. The container runs as a non-root user with a read-only root filesystem;
   application code and base files are never writable by the runtime user, and
   all runtime writes land in explicitly mounted volumes.
2. Secrets (viewer token, upload token, TLS private keys, central credentials)
   are injected only at runtime; they never appear in image layers, frontend
   bundles, configuration packages, logs, or API responses.
3. Production transport is TLS: a non-loopback bind without an API token and a
   non-HTTPS central upload endpoint are rejected unless an explicit
   development flag is set (unchanged, AUDIT-001 4.5).
4. A backup is a consistent point-in-time snapshot: the SQLite store is backed
   up with an online backup API, and the bundle records checksums for every
   configuration/rule/manifest artifact and for pending evidence paths.
5. Restore never destroys or re-uploads evidence: media on the output root is
   preserved, the restored store is reconciled against the root, and pending
   upload tasks survive restore.
6. A backup is not considered operational until a representative restore has
   succeeded (design 20.10); the restore command verifies bundle integrity
   before applying anything.
7. Upgrades and rollbacks preserve last-known-good configuration, inspection
   data, and pending evidence; a failed activation or health check retains the
   previous working release and reports the failure.

## 4. Required Decisions Before Production Enablement

- Customer TLS termination choice: edge-service local TLS vs. an existing
  factory reverse proxy, and certificate source/rotation owner.
- Backup destination, schedule, retention, and restore RPO/RTO agreed with the
  customer; exact frequencies are acceptance decisions (design 20.10).
- Docker registry and image immutability (digest pinning) for release
  promotion.
- Hardware device mapping (camera SDK, GPU) required inside the container at
  the customer site.

## 5. Delivery Pipeline

Each gate is independently reviewable.

### E5a: Docker Packaging and Health Checks

**Implementation**

- Add `apps/edge-service/Dockerfile`: a multi-stage build that resolves pinned
  dependencies with uv, compiles nothing unnecessary, and produces a runtime
  stage with a dedicated non-root UID/GID, read-only root filesystem, and
  explicit writable mount points.
- Add a `healthcheck` module usable as
  `python -m assemblyvision.healthcheck <url>` that returns non-zero when the
  liveness endpoint is not healthy.
- Add `compose.yaml` (deployment template): `edge-service` with
  `read_only: true`, `user: <non-root>`, `restart: unless-stopped`, health
  check, persistent volumes for database, media, config (ro), models (ro),
  and temp, and no dependency on central DNS.
- Verify the service writes only to configured paths when running with a
  read-only root filesystem.

**Exit criteria**

- The image builds and runs as a non-root user with a read-only root
  filesystem; the healthcheck passes against a running container.
- The compose template exposes `/api/v1/health/live` and serves the dashboard
  from the configured static volume; central absence does not prevent startup.
- Unit tests cover the healthcheck exit codes; a CI job builds the image and
  runs the container health check where Docker is available.

### E5b: Secrets and TLS

**Implementation**

- Support Docker secret files for runtime secrets: when `AV_EDGE_API_TOKEN` is
  unset but `/run/secrets/edge_api_token` exists, use the file content;
  likewise for the upload token.
- Add optional local TLS to `serve`: `--tls-cert` / `--tls-key` (or
  `AV_EDGE_TLS_CERT` / `AV_EDGE_TLS_KEY`), validated at startup (files exist,
  not world-readable, certificate/key match).
- Reject production-hostile combinations: TLS key/cert that are world-readable,
  or a non-loopback bind without a token, fail closed with actionable errors.
- Document the recommended deployment shape: either edge-service local TLS or
  an upstream factory proxy terminating TLS with a `wss:`/`https:` forwarding
  header contract.

**Exit criteria**

- Tests prove secret-file fallback precedence (environment over secret file),
  missing/unreadable key files fail closed, certificate/key mismatch is
  rejected, and TLS-enabled `serve` accepts HTTPS requests in an integration
  test.
- Design 20/21 and the compose template document both TLS shapes without
  claiming one is mandatory for the customer.

### E5c: Backup and Restore

**Implementation**

- Add `assemblyvision backup` that:
  - takes a consistent online snapshot of the SQLite store (SQLite online
    backup API);
  - copies governed configuration, rule, and manifest artifacts with SHA-256
    checksums;
  - records the set of pending evidence paths (media not yet uploaded) with
    sizes and checksums;
  - writes a single bundle (tar or directory) with a manifest and bundle
    checksum.
- Add `assemblyvision restore` that:
  - verifies the bundle manifest and checksums before applying anything;
  - restores the SQLite store without touching the output root;
  - reconciles the restored store against the output root so pending media
    and upload tasks survive.
- Add tests: backup/restore round-trip, checksum mismatch rejection, pending
  evidence survival, and restart-after-restore continuity.

**Exit criteria**

- A backup created while records are being written is consistent (no
  `database is locked` or torn state).
- Restore into a fresh directory reproduces history, media references, and
  pending upload tasks; a corrupt or tampered bundle is rejected before any
  file is written.
- The runbook procedure is executable from the CLI help text alone.

### E5d: Deployment Runbooks

**Implementation**

- Add runbook 12 (backup and recovery), runbook 13 (TLS certificate
  rotation), and runbook 14 (deployment upgrade and rollback) to the indexed
  runbook set, each with site-fill sections, verification steps, and the
  mandatory runbook record fields.
- Update the runbook index and any design/contract cross-references.

**Exit criteria**

- MkDocs strict passes with the new runbooks; each runbook has a concrete
  verification step (e.g. restore smoke, `/health/live`, certificate expiry
  check) and never implies evidence loss is acceptable.

## 6. Mandatory Test Matrix

| Area | Required cases |
|---|---|
| Packaging | image builds; non-root runtime; read-only rootfs; healthcheck exit codes; compose template renders; central-absent startup |
| Secrets/TLS | env-over-secret precedence; missing secret fails closed; cert/key existence, match, permissions; TLS serve accepts HTTPS; non-loopback-without-token rejected |
| Backup | consistent online backup; bundle checksums; tamper rejection; round-trip; pending evidence preserved; restart continuity |
| Runbooks | index links resolve; mkdocs strict; verification steps present |

## 7. Merge and Release Gates

- Focused changes with typed interfaces; no secrets or absolute paths in
  logs/APIs.
- Regression tests for every changed safety invariant.
- Passing mandatory quality commands: `ruff check/format`, `mypy`, `pytest`,
  `mkdocs build --strict`, `pnpm -r build/lint/test`, edge-web e2e.
- Docker build/healthcheck verified where Docker is available; otherwise the
  compose/Dockerfile render tests and healthcheck unit tests stand in and the
  Docker job runs in CI.

## 8. References

- [Deployment and Operations](../design/20-deployment-and-operations.md),
  sections 20.1-20.4, 20.7-20.10.
- [Security and Source Distribution](../design/21-security-and-source-distribution.md),
  sections 21.4, 21.6, 21.7, 21.9.
- [Contract 07: Deployment, Observability, and Operations](../contracts/07-deployment-observability-and-operations.md).
- [Contract 08: Security, Permissions, and Audit](../contracts/08-security-permissions-and-audit.md).
- [ADR-008: Docker Deployment](../design/decisions/ADR-008-docker-deployment.md).
- [Runbook index](../runbooks/README.md).
