# C1 Central Server M1: Pilot Ingestion, History, and Review

## 1. Purpose

Deliver the first central-server path for AssemblyVision without weakening the
edge-first architecture. The central server is a management and evidence plane:
it receives delayed edge uploads, stores selected evidence, provides
cross-device history and human review, and remains unavailable without changing
or blocking any production inspection decision at the edge.

This task implements the central one-month / M1 boundary defined by design 05:

- device-scoped idempotent inspection and media ingestion;
- PostgreSQL inspection history and selected evidence metadata;
- S3-compatible object storage through MinIO;
- pilot device upload authentication and a single administrator path;
- minimal central administration views for overview, history, and review;
- Docker Compose deployment and targeted resilience evidence.

The work must make E6-A16 (duplicate upload idempotency against a verified
central receipt) executable. It does not complete E6 on-site acceptance, which
still requires real hardware, unseen customer data, and customer witnesses.

## 2. Scope and Non-Goals

### In scope

- A new `apps/central-service` FastAPI application in the uv workspace.
- A new `apps/admin-web` Vue 3 + TypeScript application in the pnpm workspace.
- PostgreSQL migrations and a tenant-scoped central persistence model.
- MinIO in the central Compose deployment, accessed through a typed storage
  abstraction with opaque, tenant-scoped object keys.
- The current edge-compatible single-envelope upload endpoint:
  `POST /api/v1/inspection-uploads`.
- Strict verified receipts, idempotent replay, payload-conflict detection, and
  media-to-inspection binding.
- Central inspection history, detail, and authorized media metadata queries.
- Pilot authentication: separate per-device upload credentials plus a single
  administrator session/token path for the administration UI.
- Append-only central human review queue and review submission.
- Initial central product/rule/model metadata registration and immutable
  version publication needed to validate ingested references. Package delivery
  remains manual at the edge.
- Typed OpenAPI output and generated/synchronized TypeScript central API types.
- Compose health checks, controlled schema migrations, focused backup/restore
  documentation, and tests required by the repository quality gates.

### Out of scope

- Any synchronous central dependency in the edge inspection pipeline.
- OIDC PKCE, external identity-provider integration, complete production RBAC,
  device mTLS/PKI, credential rotation, or multi-organization self-service.
- Remote configuration/model package distribution, staged rollout, activation,
  rollback, or acknowledgement flows (CENTRAL-007 production scope).
- Reports/exports, asynchronous report workers, generalized administration,
  advanced analytics, warehouse/BI integration, or Redis.
- `WS /api/v1/ws/organization`; M1 uses bounded REST refresh/polling.
- Pre-signed uploads, multipart uploads, or resumable/chunked media transfer.
  The edge `media_chunk_bytes` setting is a dormant placeholder until the
  edge-to-central resumable protocol is explicitly frozen and implemented on
  both sides.
- Central ingestion of edge-local `review_records`. M1 central reviews are
  newly created central append-only records for centrally ingested inspections;
  edge-local review synchronization requires a separate governed contract.
- Central retention automation, lifecycle deletion, data-residency policy, and
  production backup/DR objectives. M1 preserves sufficient metadata and object
  lifecycle state for those later controls.

## 3. Locked M1 Decisions

| Decision | M1 choice | Production follow-up |
|---|---|---|
| Delivery scope | One-month pilot boundary from design 05 | Full administration, analytics, governance, and fleet rollout |
| Repository layout | `apps/central-service`, `apps/admin-web`, and `packages/typescript/api-client-central` in this monorepo | Keep the same bounded module interfaces |
| Data store | PostgreSQL | Partitioning/materialized views only after measured volume requires them |
| Object store | MinIO, using an S3-compatible abstraction from the first release | Customer-selected S3-compatible service / lifecycle policy |
| Device authentication | Per-device pilot upload token, bound to a registered device | mTLS or short-lived device credentials, rotation, quarantine/re-enrollment |
| Human authentication | One pilot administrator session/token path | OIDC Authorization Code + PKCE and full organization-scoped RBAC |
| Admin UI | Overview, history/detail, review | Fleet/configuration/model/report/user/audit screens |
| Live updates | REST refresh and bounded polling | Best-effort organization WebSocket with REST re-sync |
| Media transfer | Existing small single POST envelope, written by central to MinIO | Pre-signed/resumable flow only after contract and edge support are delivered |

## 4. Mandatory Safety and Compatibility Invariants

Every implementation and test in this task must preserve these invariants.

1. Central unavailability, rejection, slow responses, or maintenance must never
   block, delay-commit, or alter edge inspection decisions. The edge durable
   outbox remains authoritative for pending uploads.
2. The central server must preserve the original edge inspection record as an
   immutable fact. Central review records are append-only linked facts and
   never overwrite the original AI/internal/business decisions, timestamps,
   model checksums, rule versions, or source media identities.
3. The current edge upload wire contract is the M1 compatibility boundary.
   M1 must accept the existing JSON envelope before requesting any edge upload
   implementation change.
4. A successful receipt is returned only after the relevant metadata has been
   durably committed. A MEDIA receipt is returned only after bytes are written,
   size/checksum verified, and bound to the inspection with a durable central
   object identifier.
5. `(device_id, idempotency_key)`, `(device_id, inspection_id)`, and
   `(device_id, device_sequence)` uniqueness protect effectively-once
   persistence. Identical replay returns the original receipt; a reused key or
   source identity with a different canonical request hash returns `409` and
   preserves the original.
6. All tenant-owned database rows carry `organization_id`; every query scopes
   it server-side, even though M1 has one administrator and a pilot tenancy.
7. Object keys are generated by the central server. The server must never
   expose storage credentials or accept client-controlled filesystem paths.
8. PostgreSQL must not claim media `AVAILABLE` until the final MinIO object is
   present and checksum-verified. Partial/orphan object handling is explicit
   through `PENDING`, `AVAILABLE`, `FAILED`, and later reconciliation.
9. Pilot device credentials are distinct from human credentials, never logged,
   and accepted only over HTTPS outside explicit loopback development.
10. Request validation is typed and bounded. Unknown fields are rejected at
    mutation boundaries; errors use RFC 7807 `application/problem+json` and
    never expose credentials, object keys, internal paths, SQL, or stack traces.
11. M1 must not silently activate an edge configuration. A desired assignment
    is not an activation acknowledgement.
12. No dashboard metric may present reviewed labels as raw AI predictions or
    imply an accuracy/recall value without measured sample coverage.

## 5. Existing Edge Contract to Implement First

### 5.1 Endpoint and authentication

The existing edge `HttpUploadSink` posts to:

```text
POST {AV_EDGE_UPLOAD_BASE_URL}/inspection-uploads
```

The configured edge base URL includes `/api/v1`; therefore M1 provides:

```text
POST /api/v1/inspection-uploads
```

The request carries `Authorization: Bearer <device-upload-token>` and
`Content-Type: application/json`. The central service resolves the token to
exactly one registered active device and rejects a mismatched `device_id` from
the decoded inspection payload.

### 5.2 Envelope accepted in M1

M1 accepts the edge's current bounded JSON envelope for both `INSPECTION` and
`MEDIA` tasks:

```json
{
  "idempotency_key": "inspection:{device_id}:{inspection_id}",
  "kind": "INSPECTION",
  "object_id": "edge-object-uuid",
  "inspection_id": "edge-inspection-uuid-or-null",
  "checksum_sha256": "sha256-or-null",
  "size_bytes": 123,
  "payload_b64": "base64-payload"
}
```

For `INSPECTION`, `payload_b64` decodes to the versioned edge
`InspectionRecord`. For `MEDIA`, it decodes to the raw selected media bytes;
the inspection upload must already have a verified receipt because the edge
scheduler enforces metadata-before-media ordering.

The central boundary adapter must convert this wire envelope into typed central
commands. The core domain and repository interfaces must use typed models, not
unstructured dictionaries.

### 5.3 Required receipt

The response body is at most 64 KiB and must include:

```json
{
  "idempotency_key": "same value as request",
  "object_id": "same value as request",
  "kind": "INSPECTION or MEDIA",
  "checksum_sha256": "same value as request",
  "size_bytes": 123,
  "central_object_id": "required and non-empty for MEDIA"
}
```

The edge validates every echoed field before accepting a `2xx` result. MEDIA
receipts without `central_object_id` are permanent `INVALID_RECEIPT` failures
at the edge and must never be emitted by central.

### 5.4 Status semantics

| Condition | Central response | Edge treatment |
|---|---|---|
| New valid inspection/media persisted | `201` + verified receipt | Success |
| Same device/key/hash replay | `200` or `201` + original receipt | Success, no duplicate |
| Same device/key or source identity, different hash | `409 PAYLOAD_CONFLICT` | Permanent failure; local evidence remains |
| Referenced inspection/version/device invalid | `409` or typed `422` problem | Permanent failure |
| Temporary DB/object-store/maintenance failure | `503` + optional numeric `Retry-After` | Retryable |
| Rate limit / timeout | `429` / `408` + optional `Retry-After` | Retryable |
| Authentication/authorization failure | `401` / `403` | Permanent until operator/configuration intervention |
| Malformed, oversized, or invalid evidence | `400` / `413` / `422` problem | Permanent failure |

The central implementation must test these semantics against edge-compatible
request fixtures and receipt validation logic. It must not return `202` for an
inspection unless the response explicitly contains a receipt state that is safe
for the edge to use; normal M1 ingestion commits before success.

### 5.5 Deliberate M1 transfer boundary

M1 does **not** implement `media-uploads:initiate`, `complete`, direct browser
upload, pre-signed upload, or media chunking. The currently deployed edge sends
single Base64 envelopes and does not consume those paths. Prematurely exposing
an unused alternative would create two incompatible sources of truth.

After M1 is accepted, a separate contract/ADR may introduce resumable upload:
stable upload-task identity, zero-based chunk idempotency, total SHA-256 and
size confirmation, and object-to-inspection binding. Only then may the edge
consume its reserved `media_chunk_bytes` setting.

## 6. Target Architecture and Code Organization

```text
apps/
  central-service/                 # FastAPI API, repositories, migrations, storage
  admin-web/                       # Vue 3 central administration application
packages/
  python/
    domain/                        # Existing canonical edge/central inspection models
  typescript/
    api-client-central/            # Generated/synchronized central OpenAPI client
    ui/                            # Existing shared display primitives where appropriate
```

`central-service` starts as one deployable with explicit domain modules:

```text
central_service/
  api/             # routers, auth dependencies, problem responses, OpenAPI
  ingest/          # envelope adapter, canonical hash, receipt service
  persistence/     # SQLAlchemy Core schema, Alembic, repositories
  storage/         # MinIO/S3 interface, staging/finalization, integrity checks
  review/          # queue policy and append-only review service
  query/           # history/detail/dashboard projections
  auth/            # pilot administrator/device upload credentials
  observability/   # structured logs, metrics, health/readiness
```

No worker, Redis, package-distribution service, or microservice split is added
without a measured M1 need. Long-running jobs are out of scope for this task.

## 7. Delivery Pipeline

Each phase is independently reviewable and should normally be delivered as one
or more focused PRs into `main`.

### C1a: Workspace, Service, and Compose Foundation

**Implementation**

- Add `apps/central-service` to `[tool.uv.workspace].members` with Python 3.12
  compatible FastAPI, SQLAlchemy Core, Alembic, PostgreSQL driver, and typed
  MinIO/S3 client dependencies.
- Add `apps/admin-web` to the pnpm workspace with Vue 3, TypeScript, Pinia,
  Element Plus, ECharts, Vitest, and Playwright conventions aligned to
  `apps/edge-web`.
- Add `packages/typescript/api-client-central` and central OpenAPI generation /
  drift checks, mirroring the edge API contract discipline.
- Add central Compose services: PostgreSQL, MinIO, `central-service`, and built
  `admin-web`; use named persistent volumes, non-root images, health checks,
  explicit environment/secret files, and no implicit migration race.
- Add `/health/live` and `/health/ready`. Readiness fails when required schema,
  PostgreSQL, MinIO bucket access, or pilot credential configuration is invalid.

**Exit criteria**

- Compose brings up all four services from a clean volume set.
- The API migration command is a controlled release step and is not run by
  every API replica concurrently.
- OpenAPI is generated, committed, and checked for drift.
- No central dependency is imported by edge runtime code.

### C1b: Tenant, Device, and Pilot Authentication Foundation

**Implementation**

- Create migrations for `organizations`, `sites`, `production_lines`,
  `devices`, pilot administrator identity/session records, device upload token
  hashes, and minimum `audit_logs` support.
- Seed or bootstrap exactly one pilot organization, site, line, registered
  device, upload credential, and administrator through an explicit migration,
  admin command, or Compose bootstrap flow. No implicit default device is
  created on an upload request.
- Implement device-upload authentication for ingest routes and a pilot
  administrator token/session path for the administration UI. Device and human
  credentials are separate and cannot authorize each other's routes.
- Implement `GET /api/v1/auth/me`, `GET /api/v1/sites`, `GET /api/v1/lines`,
  and minimal `GET /api/v1/devices` / `GET /api/v1/devices/{id}`.

**Exit criteria**

- Unknown, disabled, or organization-mismatched device tokens fail closed.
- Device credentials cannot query human administration endpoints.
- Administrator credentials cannot impersonate a device upload.
- Every tenant-owned query is organization-scoped in repository tests.

### C2a: Inspection Ingestion and Verified Receipts

**Implementation**

- Add `upload_receipts`, `inspections`, and `inspection_components` migrations.
  Preserve edge `inspection_id`, device sequence, capture/completion times,
  original decisions, product resolution, reason codes, model/rule/config
  versions and checksums, inference metadata, and central receive time.
- Implement a strict typed envelope parser for
  `POST /api/v1/inspection-uploads`, including bounded Base64 decoding,
  canonical request hashing, schema-version validation, payload-size limits,
  device identity matching, and immutable version/reference checks.
- Persist accepted inspection payload, receipt, and audit event in one
  PostgreSQL transaction. Identical replay returns the original persisted
  receipt without a second inspection or audit acceptance event.
- Record payload conflict attempts as bounded security/data-integrity audit
  events without altering the original accepted resource.

**Exit criteria**

- Integration tests send the exact current edge inspection envelope.
- Replaying identical bytes returns the same receipt and leaves exactly one
  inspection row.
- Reusing an idempotency key, inspection ID, or device sequence with a
  different canonical hash returns `409 PAYLOAD_CONFLICT` and preserves data.
- A real edge `HttpUploadSink` test fixture accepts the receipt as verified.

### C2b: MinIO Media Ingestion and Binding

**Implementation**

- Add `inspection_media` migration with edge source media ID, inspection FK,
  media kind, content type, bytes, SHA-256, central object ID/key, lifecycle,
  capture/receive times, and immutable binding fields.
- For the existing `MEDIA` envelope, validate parent inspection availability,
  decode within bounded limits, stage to MinIO under a generated tenant-scoped
  key, calculate/verify size and SHA-256, finalize the object, then transact
  metadata + receipt + audit event.
- On failure, preserve a `PENDING` or `FAILED` lifecycle record only when safe
  for reconciliation; never report `AVAILABLE` before final object existence.
- Return `central_object_id` only after the object is bound and verified.
- Add an idempotent integrity/reconciliation command for staged/orphan objects
  and rows. It is an M1 maintenance command, not a continuous worker.

**Exit criteria**

- MEDIA receipts contain a non-empty central object ID and satisfy edge receipt
  validation.
- Size/checksum mismatch returns a permanent typed problem and creates no
  `AVAILABLE` media row.
- Replayed media uploads create one final object/binding only.
- An end-to-end edge outbox test reaches `SYNCED` only after all required media
  receipts are verified; the E6-A16 duplicate-upload acceptance case executes
  against central rather than a directory sink.

### C3: History, Detail, Media Access, and Overview

**Implementation**

- Implement `GET /api/v1/inspections` with bounded filters: site, line,
  device, UTC time range, barcode, product, business/internal decision,
  reason, model/rule version, and review state. Use keyset pagination and bind
  cursors to normalized filters.
- Implement `GET /api/v1/inspections/{id}` and media metadata access. Show edge
  capture/completion time separately from central receive time.
- Implement authorized short-lived MinIO URLs or authorized streaming for media;
  never return bucket credentials, raw object keys, or permanent public links.
- Implement M1 `GET /api/v1/dashboard/summary` and
  `GET /api/v1/dashboard/timeseries` with explicit scope/time filters, sample
  counts, and no invented accuracy or recall metric.
- Build `admin-web` pilot login/session handling, overview page, inspection
  history with bounded filters/keyset pagination, and inspection detail with
  evidence/media access.

**Exit criteria**

- Cross-device queries cannot escape organization scope and reject invalid
  cursors/filter ranges with typed problems.
- Media access rejects unauthorized, cross-organization, unavailable, and
  purged objects.
- Browser e2e proves administrator login, history filtering, detail rendering,
  and authorized evidence display against Compose services.

### C4: Central Append-Only Human Review

**Implementation**

- Add `review_records` migration with inspection/reviewer FKs, original
  decision snapshot, disposition, bounded component corrections, reason code,
  bounded comment, revision, timestamp, and
  `UNIQUE(inspection_id, revision)`.
- Implement a versioned M1 review-routing policy that prioritizes NG and
  uncertain inspections. It is auditable and does not imply that every NG will
  always require review after pilot policy is revised.
- Implement `GET /api/v1/reviews/queue` and
  `POST /api/v1/inspections/{id}/reviews`. Submission requires an idempotency
  key and optimistic review revision (`If-Match`); concurrent changes return
  `409 REVIEW_CONFLICT` without overwriting prior facts.
- Write an audit event for every review append. Corrected outcomes become
  governed training candidates only as a separate future workflow; they never
  trigger automatic edge model/rule/threshold updates.
- Build the `admin-web` review queue and inspection review panel. It presents
  original machine evidence and decision, then appends a reviewer disposition.

**Exit criteria**

- Original inspection decision/version fields remain byte-for-byte unchanged
  after review submission.
- Parallel review submission tests prove linear append revisions or explicit
  conflict; no silent replacement occurs.
- The dashboard shows reviewed outcomes distinctly from original automated
  outcomes.

### C5: Initial Metadata and Manual Configuration Governance

**Implementation**

- Add products/components, product versions, rules/rule versions, model
  packages/model versions, and desired configuration assignment migrations.
- Implement minimum list/create/draft/publish APIs. Published versions are
  immutable; changes create a new version. Publication validates component
  uniqueness, bounded policy values, model/rule compatibility, and actor/reason
  audit metadata.
- Implement desired configuration recording for one device at a time. M1
  records desired versions but has no remote download/validation/activation
  endpoint. UI text must state that packages are installed manually and a
  desired assignment is not proof of activation.
- Add minimal configuration read views in `admin-web`; rich editors, rollout
  previews, artifact upload, and package delivery remain deferred.

**Exit criteria**

- Published versions cannot be updated in place.
- Desired assignment does not change edge behavior or claim activation.
- Every publish/assignment path writes an immutable audit event.

**Implementation status**

- Delivered in migration `0006_metadata_governance`: organization-scoped
  components, products, rules, and model packages; immutable draft/publish
  versions with public UUID `version_id`; exact-barcode mappings; explicit
  rule/model compatibility; single-device desired configuration; and
  request/reason/before/after audit correlation on `audit_logs`.
- APIs under `/api/v1/components`, `/products`, `/product-versions`,
  `/rules`, `/rule-versions`, `/models`, `/model-versions`, and
  `/devices/{id}/desired-configuration` plus the `/device-configurations`
  read list. Stable-create and draft-create require `Idempotency-Key`;
  assignment uses `If-Match`; repeated publish returns the published version.
- Model publication is declarative registration: artifact bytes are never
  fetched or verified server-side in M1 (audit states this explicitly); the
  edge validates bytes/checksum/compatibility and last-known-good rollback
  locally during manual installation.
- `admin-web` adds read-only Configuration pages (products, rules, models,
  desired configurations) with the mandatory manual-install notice in all
  four locales; no edit/publish/assign controls ship in C5.
- Verification: central-service Ruff/format/MyPy and 162 Pytest cases
  (29 new C5 repository/API tests), regenerated OpenAPI + TypeScript client
  with build/tests, admin-web lint/build and 30 unit tests, e2e smoke against
  Compose, plus a live end-to-end browser check of the C5 pages.

### C6: M1 Hardening and Operational Evidence

**Implementation**

- Add request IDs, structured log correlation across device/inspection/media/
  receipt/audit IDs, bounded request/media limits, safe problem responses,
  rate limits, and readiness dependency reporting.
- Add controlled PostgreSQL backup and representative restore procedure;
  document MinIO data backup/restore alignment and M1 limits.
- Add targeted restart, PostgreSQL/MinIO temporary-failure, replay, receipt,
  media-integrity, and unauthorized-access fault tests.
- Add central runbook sections for ingestion backlog, object-store failure,
  credential compromise, backup/restore, and pilot upgrade/rollback.
- Update design/status/context documentation and record review evidence.

**Exit criteria**

- A Compose restart preserves accepted inspections, objects, and replayable
  receipts.
- Temporary dependencies yield retryable `503`/`Retry-After` behavior without
  issuing false success receipts.
- A representative backup restore succeeds before M1 is described as
  operationally ready.
- M1 does not claim production HA, final RPO/RTO, full retention enforcement,
  OIDC, or remote rollout capability.

**Implementation status**

- Delivered hardening: structured log correlation (per-request `request_id`
  bound through a context variable and appended to every record; ingest log
  lines carry device/inspection/object/receipt correlation and correlate with
  `audit_logs.request_id`), per-client sliding-window rate limiting
  (`429 RATE_LIMITED` + `Retry-After`, health endpoints exempt,
  `AV_CENTRAL_RATE_LIMIT_REQUESTS_PER_MINUTE`, 0 disables), and database
  connectivity failures mapped to retryable `503 DATABASE_UNAVAILABLE` +
  `Retry-After` (constraint violations keep their explicit conflict
  semantics). Request-body and payload caps (`413`) already existed from
  C2a/C2b and remain covered by tests.
- Fault tests added: object-store outage returns `503 OBJECT_STORE_UNAVAILABLE`
  with no receipt or binding persisted; database outage returns
  `503 DATABASE_UNAVAILABLE`; controlled restart (engine disposed and
  reopened) preserves inspections, media bindings, receipts, and audit rows,
  and receipts stay replayable; a representative backup/restore round-trip
  (consistent snapshot opened as a fresh database) preserves the same
  invariants. A real PostgreSQL `pg_dump`/`pg_restore` round-trip to a fresh
  database was executed and verified (schema at head, rows intact) as the
  representative restore evidence for exit criterion 4.
- Central runbooks added: ingestion backlog (C1), object-store failure (C2),
  credential compromise (C3), backup/restore (C4), and pilot upgrade/rollback
  (C5), all indexed in `docs/runbooks/README.md` and the mkdocs nav
  (`uv run mkdocs build --strict` passes).
- M1 remains labeled a controlled pilot: no claim of production HA, final
  RPO/RTO, full retention enforcement, OIDC, or remote rollout (section 13
  exit criterion 8).

## 8. M1 Database and Object Storage Rules

### 8.1 Required M1 tables

| Domain | Tables | M1 purpose |
|---|---|---|
| Tenant/device | `organizations`, `sites`, `production_lines`, `devices`, pilot credential/session records | Scope every request and authenticate edge uploads |
| Ingestion | `inspections`, `inspection_components`, `inspection_media`, `upload_receipts` | Immutable edge facts, evidence, and idempotency |
| Review/audit | `review_records`, `audit_logs` | Append-only review and accountability |
| Initial governance | `products`, `product_components`, `product_versions`, `rules`, `rule_versions`, `model_packages`, `model_versions`, desired assignments | Validate/pin metadata; manual package installation only |

Rows must use timezone-aware UTC timestamps. Inspection records preserve both
edge-observed/captured timestamps and central receive timestamps. JSON is only
used for bounded immutable snapshots, evidence detail, or audit before/after
data; it is not a replacement for the filterable columns and uniqueness
constraints above.

### 8.2 Required indexes and uniqueness

- `UNIQUE(device_id, idempotency_key)` on `upload_receipts`.
- `UNIQUE(device_id, inspection_id)` and `UNIQUE(device_id, device_sequence)`.
- `UNIQUE(device_id, source_media_id)` for edge-originated media identity.
- `(organization_id, completed_at DESC, id DESC)` and
  `(device_id, completed_at DESC, id DESC)` for keyset history pagination.
- Partial barcode index `(organization_id, barcode, completed_at DESC)` where
  barcode is non-null; barcode is never globally unique.
- Query indexes for product/result, model/rule versions, pending review, and
  bounded reason-code filtering only after test/query plans establish need.

### 8.3 Object key and lifecycle rules

- Generate opaque keys such as
  `org/{organization_id}/device/{device_id}/{year}/{month}/{media_id}`.
- Store no media bytes in PostgreSQL and no edge-provided path as a storage key.
- Stage, verify, finalize, then mark `AVAILABLE`; retain explicit `PENDING` /
  `FAILED` states for interrupted work.
- M1 does not delete central media automatically. It records lifecycle and
  retention metadata needed for future governed cleanup.
- Media URLs are authorized and short-lived. Browser/admin users never receive
  MinIO root credentials or bucket-wide permissions.

## 9. API, Type, and Error Contract Rules

- Central public request/response schemas are typed Pydantic models and have
  `extra="forbid"` for mutation bodies.
- FastAPI OpenAPI is committed and drift-checked. `api-client-central` is
  generated or synchronized from it; `admin-web` must not hand-cast server
  JSON.
- All errors use `application/problem+json` with bounded
  `type`, `title`, `status`, `detail`, `code`, `request_id`, and field errors.
- Cursor pagination uses `{items, next_cursor}` with default 50/max 200 and
  rejects cursor/filter mismatch.
- Mutating human/admin APIs use `If-Match` revision checks where concurrent
  edits matter. Retriable device ingestion uses idempotency keys instead.
- All immutable edge identifiers and original decisions are write-once after
  accepted ingestion.
- New central fields are additive within a schema version. Removing/changing
  field meaning requires a new API/schema version and coordinated migration.

## 10. Admin-Web M1 Scope

### Overview (`/overview`)

- Selected site/line/time scope, inspection count, OK/NG/uncertain split,
  upload delay, oldest pending upload, device last-seen state, and bounded
  outcome/latency time series.
- Every metric shows scope, period, count/denominator where relevant, and
  preserves empty data as empty rather than zero.

### Inspections (`/inspections`, `/inspections/:id`)

- Cross-device bounded filter/search, keyset pagination, inspection/version
  traceability, original decision/evidence/reasons, receipt state, and
  authorized selected media display.

### Reviews (`/reviews`)

- Priority queue of eligible M1 NG/uncertain inspections, original evidence,
  append-only disposition/reason/comment submission, conflict feedback, and
  clear separation of machine outcome from reviewed outcome.

The M1 UI intentionally excludes reports, product/rule/model editors, user
management, fleet rollout, audit explorer, and organization self-service.

## 11. Mandatory Test Matrix

| Area | Required cases |
|---|---|
| Device auth | valid device upload; unknown/disabled/mismatched token; device cannot access admin routes; admin cannot impersonate device |
| Inspection ingestion | exact edge envelope; valid commit+receipt; same replay; key/hash conflict; duplicate inspection ID; invalid evidence/version/device; body limits |
| Media ingestion | parent required; staged/finalized lifecycle; size/checksum mismatch; one final object on replay; MEDIA central object ID required |
| Edge compatibility | run current edge scheduler/HTTP sink fixtures against central; metadata-before-media; `SYNCED` only after verified receipts; E6-A16 duplicate replay |
| Query/history | organization isolation; time/filter bounds; cursor tamper/filter mismatch; capture versus receive time; media authorization |
| Review | allowed disposition; immutable machine fields; idempotency; `If-Match` conflict; append revision; audit event |
| Metadata | immutable publish; invalid policy/compatibility rejected; desired assignment is not activation |
| Object store | temporary MinIO outage maps to retryable response; orphan/staged reconciliation; no object-key/credential leak |
| Admin web | pilot login/session; overview scope; history filters/detail; authorized media; review submit/conflict; no unauthorized routes |
| Operations | Compose cold start; migration control; restart persistence; backup/restore; liveness/readiness; request correlation |

## 12. Quality, Security, and Documentation Gates

Every central PR must run the repository gates applicable to changed code:

```text
uv run ruff check .
uv run ruff format --check .
uv run mypy .
uv run pytest
pnpm -r build
pnpm -r lint
pnpm -r test
cd apps/admin-web && pnpm test:e2e
uv run mkdocs build --strict
```

Additional mandatory checks:

- OpenAPI snapshot/drift and generated TypeScript client checks.
- PostgreSQL migration upgrade from an empty database and from every committed
  predecessor migration.
- MinIO integration tests with checksum/object-binding assertions.
- An end-to-end edge outbox fixture that validates the actual central receipt.
- Security tests for cross-organization access, device/human credential
  separation, payload limits, unsafe media metadata, and no internal error
  leakage.

Update relevant design/status/runbook documentation, OpenAPI artifacts, and
the central review record whenever an API, persistence schema, configuration,
or operation changes.

## 13. M1 Exit Criteria

M1 is ready for a controlled pilot only when all of the following are true:

1. A registered edge device sends current inspection and selected media
   envelopes over HTTPS; central returns verified compatible receipts.
2. Identical replay is duplicate-free and returns the previous receipt;
   payload conflicts fail closed with `409` and do not overwrite evidence.
3. A real edge scheduler reaches `QUEUED` → `PARTIAL` → `SYNCED` only after
   required central receipts, making E6-A16 executable against central.
4. Central PostgreSQL history and MinIO evidence bindings survive controlled
   restart and representative backup/restore.
5. Pilot administrator UI supports overview, cross-device history/detail, and
   append-only review while enforcing organization scope.
6. Original edge decisions and evidence provenance remain immutable through
   ingestion and review.
7. Compose health/readiness, migration, request/error, authentication, and
   recovery evidence is recorded; all mandatory quality gates pass.
8. Documentation explicitly labels M1 as a controlled pilot and does not claim
   production HA, final data-residency compliance, complete RBAC, remote
   rollout, resumable media upload, or universal accuracy.

## 14. Risks, Dependencies, and Deferred Decisions

| Item | M1 treatment | Required before production |
|---|---|---|
| OQ-021 tenancy hierarchy | Persist org/site/line/device hierarchy, one pilot organization | Confirm customer tenancy/organization model and enforce final isolation policy |
| OQ-022 IdP/device PKI | Pilot tokens with secret-file/environment support | OIDC, device credential rotation/revocation, mTLS/PKI, signing policy |
| OQ-017 retention/residency | Preserve media lifecycle metadata, no automatic deletion | Legal holds, data residency, central retention/deletion/backup policy |
| OQ-019 hosting/DR | Compose pilot on selected controlled host | Availability topology, RPO/RTO, tested DR, network/proxy/TLS ownership |
| OQ-020 scale | Indexes and bounded filters; no worker/Redis | Measured media volume, device count, concurrency, partition/worker strategy |
| Large media | Existing bounded envelope only | File-size measurements, frozen resumable/pre-signed contract, edge implementation |
| Edge-local reviews | Do not ingest them silently | Separate immutable synchronization/provenance contract if required |
| Remote packages | Manual verified edge install only | CENTRAL-007 package, validation, activation, acknowledgement, rollback lifecycle |

## 15. References

- [Central Server Architecture](../design/05-central-server-architecture.md)
- [Data Model and Database](../design/14-data-model-and-database.md)
- [REST API and Events](../design/15-rest-api-and-events.md)
- [Upload and Synchronization](../design/13-upload-and-synchronization.md)
- [Central Admin Dashboard](../design/17-central-admin-dashboard.md)
- [Human in the Loop](../design/24-human-in-the-loop.md)
- [Security and Source Distribution](../design/21-security-and-source-distribution.md)
- [Roadmap](../design/25-roadmap.md)
- [Customer Acceptance](../design/26-customer-acceptance.md)
- [Risks and Mitigations](../design/27-risks-and-mitigations.md)
- [Appendices: Global Open Questions](../design/appendices.md#3-global-open-questions)
- [Contract 04: Edge, Storage, and Upload Contracts](../contracts/04-edge-storage-upload-contracts.md)
- [Contract 05: Data, API, and Versioning](../contracts/05-data-api-and-versioning-contracts.md)
- [Contract 06: Testing, Quality, and CI](../contracts/06-testing-quality-and-ci-contracts.md)
- [Contract 08: Security, Permissions, and Audit](../contracts/08-security-permissions-and-audit.md)
- [E3 Pipeline: Upload Resilience](E3-upload-resilience.md)
- [E5 Pipeline: Deployment and Security](E5-deployment-and-security.md)
- [E6 Pipeline: Edge Acceptance](E6-edge-acceptance.md)
