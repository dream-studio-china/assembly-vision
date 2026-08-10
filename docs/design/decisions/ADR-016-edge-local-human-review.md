# ADR-016: Edge-Local Human Review (Optional)

## 1. Status

Accepted

## 2. Context

Design 24 places human review on the central server: evidence uploads, a
central review queue, and append-only dispositions. The central server does not
exist yet, and design 24.11 requires that edge inspection and review keep
working while the central server is unavailable. Operators need to disposition
`NG` cases (and audit-sampled `OK` cases) locally, with the machine decision
kept immutable.

There is no backend role model on the edge: the API exposes a single viewer
credential. Introducing an RBAC system just for review would be a large
architectural change with no customer requirement behind it.

## 3. Decision

1. **Human review is optional and additive.** It is never required for an
   inspection to complete, never mutates `InspectionRecord` or its projection,
   and adds no fields or endpoints to the existing inspection API. Review data
   lives in a separate append-only `review_records` table (migration 0008) and
   a separate `ReviewRecord` domain model.
2. **Any inspection may be reviewed**, but the disposition must be compatible
   with the machine outcome (design 24.3): `UNCERTAIN` may be confirmed NG/OK,
   reinspected, or inconclusive; plain `NG` may be confirmed NG/OK or
   inconclusive; sampled `OK` may be confirmed OK, corrected to NG, or
   inconclusive. An incompatible disposition is rejected (`422
   REVIEW_DISPOSITION_INVALID`) rather than recorded. The design 24.3 "system
   exception" row (with the operational-fault disposition) is outside
   edge-local scope and is deferred until central review exists.
3. **Reviewer identity is caller-supplied and local.** The reviewer name is a
   required field on the submission; there is no edge role system. The record
   snapshots the original machine outcome and reason codes so it stays
   interpretable even if the inspection projection is later purged.
4. **Records are append-only and chain by reference.** A later review of the
   same inspection supersedes the previous latest review (unless the caller
   explicitly targets another review of that inspection); records are never
   overwritten, and a review may only supersede a review of the same
   inspection (`409 REVIEW_CONFLICT`).
5. **`INCONCLUSIVE` always requires a reason**, enforced by the request model
   and the domain record.
6. **The review queue lists every inspection** with its review state
   (`has_review`, `latest_disposition`) and supports business-result and
   reviewed filters, so the initial all-NG rollout policy and OK audit sampling
   are both expressible. The web UI defaults to NG/open items.
7. **Review is exposed only through the existing viewer credential.** A future
   central review flow or RBAC is a separate ADR; local review records remain
   valid input for later synchronization (design 24.5/24.11).

## 4. Consequences

### 4.1 Positive

- Review works offline and without a central server, matching design 24.11.
- Zero intrusion into the existing inspection pipeline, API, or UI: no
  `InspectionRecord` changes, no existing endpoint changes, and the detail view
  integrates via an additive `ReviewPanel` component.
- The machine decision stays immutable; corrections supersede by reference.

### 4.2 Negative and Trade-offs

- Reviewer identity is self-asserted; there is no edge-side authorization for
  who may review. Deployment must document who is allowed to operate the
  dashboard.
- Local reviews are not yet synchronized anywhere; the central-server review
  queue and training-backlog handoff remain future work.
- `CORRECTED_NG` and `CONFIRMED_OK` are recorded locally but do not alter
  statistics or drive any automated retraining (design 24.9 keeps training
  governed and offline).

## 5. Open Questions

- Whether edge-local review dispositions should be uploaded as part of the
  inspection synchronization once a central server exists, and how they map to
  central review records.
- Whether dual review/adjudication for critical defect classes is needed and
  where it lives.

## 6. Links

- [Human-in-the-Loop Operations](../24-human-in-the-loop.md)
- [REST API and Events](../15-rest-api-and-events.md)
- [Data Model and Database](../14-data-model-and-database.md)
