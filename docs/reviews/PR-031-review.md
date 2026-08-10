# PR-031 Review: Edge-Local Human Review (Optional, ADR-016)

## 1. Review Decision

**Status: RESOLVED**

The edge-local human review feature (`feat/edge-local-human-review`) is a
strictly additive, optional capability that satisfies the requested properties:
it is non-invasive (no existing record, endpoint, flow, contract, or frontend
logic changed), decoupled across the established layers, and built on an
append-only model that extends cleanly toward the future central review flow.

The review found no P1 blockers. One P2 security hardening item (unbounded
`component_corrections` list), one P2 functional gap (review queue showing
empty reason codes for open items), and a set of P2 documentation/contract
consistency issues were identified and fixed in the review pass (section 3).
Remaining accepted trade-offs (self-asserted reviewer identity, no review
upload-sync yet, no review retention policy) are explicit in ADR-016 and
section 4 below.

## 2. Scope and Evidence

Reviewed branch: `feat/edge-local-human-review` (into `main`), 7 commits plus
the review-pass fixes:

```text
8061c0b feat(domain): add append-only human review models
019d271 feat(edge): persist append-only human review records
4abd58d feat(edge): add review queue and submission API
88560b3 test(edge): cover review repository and API
96e35df feat(api-client): expose review queue and submission
749cb52 feat(edge-web): add review queue page and inspection review panel
e918b5f docs(edge): record ADR-016 edge-local human review
```

Review method: four parallel sub-agent reviews covering documentation/contract
consistency, security, decoupling/non-invasiveness, and extensibility, followed
by a consolidated fix pass.

Primary requirements:

- [Human-in-the-Loop Operations](../design/24-human-in-the-loop.md), sections
  24.1-24.14.
- [ADR-016: Edge-Local Human Review](../design/decisions/ADR-016-edge-local-human-review.md).
- [REST API and Events](../design/15-rest-api-and-events.md), section 15.3.3.
- [Data Model and Database](../design/14-data-model-and-database.md), sections
  14.3/14.5.
- [Contract 01: Architecture Boundaries](../contracts/01-architecture-boundaries.md).
- [Contract 05: Data, API, and Versioning](../contracts/05-data-api-and-versioning-contracts.md).

Verification executed during the review pass (all passed): `ruff check/format`,
`mypy` (173 files), `pytest` (exit 0), api-client build/lint/test (60 tests),
edge-web build/lint/test (49 tests), edge-web Playwright e2e (15 passed),
`mkdocs build --strict`, and `git diff --check`.

## 3. Required Findings

### 3.1 Fixed During Review

#### PR31-F01 - P2: Documented 422 code `REVIEW_VALIDATION_FAILED` was dead code and a construction could 500

The `ReviewRecord` construction sat outside the `try` in
`api/routers/reviews.py`, so a domain-level validation error would surface as
an internal 500 instead of a documented 422. Fixed by moving the construction
inside the `try` that maps `ValidationError` to `422 REVIEW_VALIDATION_FAILED`
(the request-body path keeps the global `VALIDATION_FAILED`, matching the
documented 15.3.3 errors).

#### PR31-F02 - P2: Design 24.3 "corrected OK" terminology diverged from the implemented disposition set

Design 24.3 listed "corrected OK" for an `NG` outcome while the implementation
(and ADR-016/15.3.3) uses `CONFIRMED_OK` for both an `NG`-to-`OK` correction and
an `OK` confirmation; there is no `CORRECTED_OK` value. Updated design 24.3 to
"confirmed OK" and documented that the original machine outcome on the record
distinguishes the two cases. Disposition sets were verified identical across
`allowed_review_dispositions()`, `ReviewPanel.vue`, and
`MockApiClient.allowedDispositions()`.

#### PR31-F03 - P2: Edge review queue showed empty reason codes for open items

`list_review_queue` sourced `reason_summary` from the latest review's snapshot,
which is empty before any review exists — exactly the triage data a reviewer
needs for open `NG` items. Fixed to read the inspection's own machine reason
codes (`_decision_reasons`), consistent with the mock client. Also adds a
`test_review_queue_reports_review_state` assertion for the open-item codes.

#### PR31-F04 - P2: Unbounded `component_corrections` list (security hardening)

`SubmitReviewRequest` and `ReviewRecord.component_corrections` accepted an
unbounded list; a large body would be buffered and stored in one `TEXT` cell
with read amplification. Added `max_length=64` at both the API schema and
domain model; OpenAPI and generated TS regenerated.

#### PR31-F05 - P2: Design 14 did not document the edge `review_records` table or the edge review model

Design 14 documented only the central `ReviewRecord` (user FK, revision chain),
while the edge table (migration 0008) is a distinct append-only model. Added the
`review_records` row to the §14.5 edge schema table and a note in §14.3
distinguishing the edge (caller-supplied reviewer, `supersedes_review_id`) from
the future central model.

#### PR31-F06 - P2: TS nullability/request-type divergence between hand-written and generated contracts

`types.ts` treated `reason`/`note`/`original_reason_codes`/
`component_corrections`/`supersedes_review_id` as always present while the
generated `api.ts` marked them optional, and `SubmitReviewRequest` reused
`ComponentCorrection` instead of the generated `ComponentCorrectionRequest`.
Added the `ComponentCorrectionRequest` alias in `types.ts` (the hand-written
types remain the accurate wire contract; the generated looseness is accepted
and now documented in `types.ts`).

#### PR31-F07 - P2: Malformed review-queue cursor could return 500 instead of 400

`_decode_cursor` did not reject non-dict JSON payloads or catch `TypeError`, so
a crafted `?cursor=` on `GET /reviews` escaped `InvalidCursorError`. Fixed in
the shared helper (also hardening `list_inspections`/`list_uploads`), now
raising `400 INVALID_CURSOR`.

#### PR31-F08 - P2: Mock client diverged from server validation

`MockApiClient.submitReview` did not enforce the non-empty reviewer or
`INCONCLUSIVE`-requires-reason rules the server applies. Added identical checks
(422 `VALIDATION_FAILED`) plus a consistency contract test asserting every
documented disposition is a known `REVIEW_DISPOSITIONS` value.

#### PR31-F09 - P3: Log injection via reviewer name

`repository.submit_review` logged the free-text reviewer with `%s`, allowing
control characters to forge log lines (CWE-117). Changed to `%r`
(repr-escaped), matching the `retry_upload` pattern.

#### PR31-F10 - P3: Documentation gaps closed

- §15.2.1 general auth rule now names the ADR-016 review-submission exception
  to the "mutating routes require operator/edge_admin" statement.
- §15.3.3 idempotency cell changed from the meaningless "Deterministic per
  review_id" to "None: each call appends a new review", and `409
  REVIEW_CONFLICT` is documented to also cover a `supersedes_review_id` that
  names no review of that inspection.
- §16.3 information-architecture table gained the `/review` route row.
- ADR-016 decision 2 now explicitly defers the design 24.3 "system exception"
  row (and operational-fault disposition) until central review exists.

### 3.2 Accepted Trade-offs and Deferred Work

#### PR31-T01 - P2: Reviewer identity is caller-supplied free text (impersonation surface)

Anyone holding the single viewer credential can record a review attributed to
any reviewer name; the API does not bind the name to the authenticated session.
This is the explicit, accepted ADR-016 decision 3/7 (no edge role model), and
the audit log uses repr-escaped identity. A server-derived operator identity or
trusted-operator allow-list is the documented future hardening.

#### PR31-T02 - P2: Review records have no upload/sync plumbing yet

`review_records` has no `device_id`/`synchronization_status`/`payload_hash`, and
no `upload_tasks` rows are created for reviews. ADR-016 §5 records this as an
open question and design 24.11 allows "review items synchronize later". Because
reviews are append-only with a locally generated `review_id`, future sync maps
directly onto the existing outbox pattern (idempotency key
`review:{device_id}:{review_id}`) without the inspection content-hash
machinery. Deferred, not blocking.

#### PR31-T03 - P3: No review retention policy or submission rate limit

`review_records` grows without bound (append-only) and submissions are not
rate-limited; `list_inspection_reviews` is unpaginated. Acceptable at MVP
scale; a retention/compaction policy and rate limiting are future hardening.

#### PR31-T04 - P3: Disposition evolution touches ~8 hand-maintained locations

Adding a disposition requires edits in the domain enum, `allowed_review_dispositions`,
generated OpenAPI/TS (CI-checked), `types.ts`, `validate.ts`,
`MockApiClient.allowedDispositions`, and two Vue components. The review added a
consistency contract test; deriving `REVIEW_DISPOSITIONS` from the generated
schemas is the recommended next refactor.

## 4. Confirmed Non-Invasive and Decoupled

- **Domain**: only additive models appended after `ModelManifest`;
  `InspectionRecord` untouched.
- **Persistence**: `inspections` table untouched; new `review_records` table +
  migration 0008 (`down_revision=0007`) appended; repository methods added,
  existing methods byte-identical.
- **API**: 12 existing routers untouched (0-line diffs); `app.py` gained one
  import + one `include_router` entry; OpenAPI diff has 0 removed lines.
- **Inspection flow**: `pipeline.py`, `state.py`, `config.py`, rules, engine:
  0-line diffs. Inspect-frame/video, persistence, upload, and retention
  behavior unchanged.
- **Frontend**: `InspectionDetailView.vue` +8 lines (one import, one additive
  `<ReviewPanel>`); `App.vue` +1 nav link; `router/index.ts` +1 route. New
  components import only `@assemblyvision/api-client`, `@assemblyvision/ui`,
  `vue`, and the existing client factory — no edge-web → edge-service imports.
- **api-client**: three new methods/types/validators; existing signatures and
  mock data untouched.
- **Dependency direction** respects architecture boundaries (domain → edge
  service → api-client → web).

## 5. Security Assessment

- SQL injection: clean (all values bound; f-strings only over module-level
  table-name constants).
- Cursor filter bypass: clean (SHA-256 filter fingerprint embedded in cursor).
- Input bounds: clean after F04 (`reason` 200, `note` 2000, `reviewer` 128,
  `component_corrections` ≤ 64; `extra="forbid"`; strip validators).
- XSS: clean (no `v-html`; all reviewer/reason/note/disposition rendered via
  escaped Vue interpolation; CSP `script-src 'self'`).
- Tamper resistance: `original_business_result`/`internal_decision`/
  `reason_codes` are server-derived from the stored inspection, never the
  request; disposition compatibility and supersede ownership re-checked
  atomically in one transaction.
- Auth wiring: reviews router under `Depends(require_viewer)`; session cookie
  `HttpOnly` + `SameSite=strict` (no CSRF exposure); 401 covered by tests.
- Migration safety: additive create-table + indexes, FK to `inspections`,
  schema.py/migration mirrored column-for-column.

## 6. Extensibility Assessment

- Append-only record semantics and a single authoritative domain disposition
  policy make future adjudication/reassignment additive (new record kinds or
  columns), never in-place updates (design 24.6/24.7).
- Schema evolution uses the established Alembic chain; adding
  `adjudication_state`/`assignment_history` later follows the 0004/0006
  `op.add_column` pattern.
- Queue ordering/sampling (design 24.4 priority and OK audit sampling) is the
  main future change; the keyset cursor is bound to the current
  `(completed_at, inspection_id)` order, so a scored ordering requires binding
  the cursor to new sort keys.
- Per-component correction UI slots in additively (`ComponentCorrection` is
  already modeled end-to-end; the UI does not send it yet).
- OpenAPI + generated TS are CI-drift-checked; the hand-maintained
  `types.ts`/`validate.ts`/client layer is the remaining drift risk (T04).

## 7. Files Changed (Review Pass)

```text
apps/edge-service/src/assemblyvision_edge/api/routers/reviews.py
apps/edge-service/src/assemblyvision_edge/api/schemas.py
apps/edge-service/src/assemblyvision_edge/persistence/repository.py
apps/edge-service/openapi/edge-openapi.json
packages/python/domain/src/assemblyvision_domain/models.py
packages/typescript/api-client/src/edge/types.ts
packages/typescript/api-client/src/edge/MockApiClient.ts
packages/typescript/api-client/src/edge/generated/api.ts
packages/typescript/api-client/tests/client.test.ts
docs/design/14-data-model-and-database.md
docs/design/15-rest-api-and-events.md
docs/design/16-edge-dashboard.md
docs/design/24-human-in-the-loop.md
docs/design/decisions/ADR-016-edge-local-human-review.md
```
