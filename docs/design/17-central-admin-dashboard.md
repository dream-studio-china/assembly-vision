# 17. Central Administration Dashboard

## 17.1 Purpose and Boundary

The central administration dashboard provides fleet-wide history, review, configuration, model lifecycle visibility, reporting, users, and audit. It does not execute production inspection and must not be a runtime dependency of an edge device.

The Vue 3 application uses the central contracts in [REST API and Events](15-rest-api-and-events.md), schemas in [Data Model and Database](14-data-model-and-database.md), and evaluation semantics in [Training and Evaluation](19-training-and-evaluation.md).

## 17.2 Roles and Permissions

| Capability | Viewer | Reviewer | Config manager | Fleet admin | Org admin/auditor |
|---|---:|---:|---:|---:|---:|
| Dashboard/history/media | Yes | Yes | Yes | Yes | Yes |
| Submit review correction | No | Yes | No | No | Configurable |
| Draft/publish products and rules | No | No | Yes | No | Configurable |
| Register/publish model versions | No | No | Yes | No | Configurable |
| Enroll/assign/disable devices | No | No | No | Yes | Configurable |
| Manage users and roles | No | No | No | No | Yes |
| View audit logs/export sensitive data | Explicit permission | Explicit permission | Explicit permission | Explicit permission | Yes |

The server enforces every permission and organization scope. Route guards improve usability but are not a security boundary. Sensitive exports and publication actions require recent authentication if the identity provider supports it.

## 17.3 Navigation and Pages

| Route | Page | Core functions |
|---|---|---|
| `/overview` | Fleet overview | KPIs, outcome/latency trends, active alerts, device state, upload delay |
| `/devices` and `/devices/:id` | Fleet management | Site/line filtering, last seen, versions, assignment, event history |
| `/inspections` and `/inspections/:id` | Inspection history | Cross-device search, evidence/media, version traceability, review status |
| `/reviews` | NG review work queue | Claim/open, compare evidence, correct outcome/components, submit reason |
| `/products` | Product management | Stable products, immutable versions, barcode mappings, components |
| `/rules` | Rule management | Draft, validate, compare, publish, assignment impact |
| `/models` | Model registry | Manifest/artifacts, evaluation summary, lifecycle, compatibility |
| `/reports` | Reports and exports | Saved filters, asynchronous jobs, expiring downloads |
| `/users` | Users and roles | Organization assignments and least-privilege roles |
| `/audit` | Audit trail | Actor/action/resource/time search and before/after detail |

Site and line filters are persistent in the URL so views can be shared and revisited. The selected time zone is explicit; stored data remains UTC. The UI never silently changes metric filters between pages.

## 17.4 Fleet Overview

The overview begins with data freshness and filter context, then presents:

- Total inspections and OK/NG/uncertain counts for the selected period.
- NG recall only when reviewed ground truth is sufficient; otherwise label it unavailable or preliminary.
- Outcome rate, barcode-read failure, product-detection failure, ROI failure, and manual correction rate.
- Average and P95 inspection latency, inspection throughput, upload delay, and oldest pending upload.
- Missing-component distribution by component and product.
- Model/rule-version comparison with sample counts and confidence intervals where applicable.
- Device state table showing ready, inspecting, paused, faulted, offline, last seen, disk state, active versions, and backlog.

Charts must show numerator, denominator, sample count, time bucket, and active filters in tooltips or adjacent detail. “Accuracy” must not be the sole headline metric. Empty or delayed data is not plotted as zero.

## 17.5 Device Management

The device list supports organization-authorized site, line, operational state, model/rule version, and last-seen filters. Device detail includes identity, enrollment/certificate status, desired versus reported configuration, health timeline, upload backlog, recent inspections, and events.

Configuration assignment is a versioned desired-state operation:

1. Select compatible published product/rule/model bundle.
2. Display class, runtime, and product-version compatibility validation.
3. Preview affected devices and current versions.
4. Require reason and optional rollout window.
5. Save with optimistic concurrency.
6. Track desired, downloaded, validated, activated, failed, and rolled-back reports from devices.

MVP may assign one device at a time. Staged fleet rollout, canaries, automatic rollback, and maintenance windows are later features, but schema/state names should not imply immediate successful activation.

## 17.6 Inspection Search and Evidence Review

Search supports bounded time, site, line, device, outcome, barcode, product, component reason, review state, model version, and rule version. Results use server-side keyset pagination. Filter chips and URL query state make active constraints unambiguous.

Inspection detail shows device capture and central receive timestamps separately, final decision, barcode/product, evidence, quality, media, exact immutable versions, upload receipt, and review revisions. Detection overlays use source dimensions and share the tested viewer package with the edge dashboard. Media URLs are short-lived and refreshed only after authorization.

## 17.7 Manual NG Review Workflow

The queue prioritizes unresolved NG/uncertain cases and may support product/reason sampling. It must not imply that only AI-flagged NG cases establish false-negative performance; sampled OK audits and intentionally defective acceptance data are required.

Review flow:

1. Open a stable inspection revision and display original result without modification.
2. Inspect key frames, ROI, annotated image, optional clip, component evidence, and quality reasons.
3. Select reviewed outcome and component corrections.
4. Require a controlled reason code; allow a bounded comment.
5. Show the exact change and submit with an idempotency key and optimistic revision.
6. Append a `ReviewRecord`; do not overwrite the inspection result.
7. Surface eligible corrections to the training backlog through a separate curated workflow.

Concurrent review returns a conflict and displays the newer revision. The reviewer chooses whether a new correction is still necessary. Keyboard shortcuts must not submit without explicit confirmation.

## 17.8 Product and Rule Configuration

Stable product identity is separated from immutable product versions. Product drafts define barcode mappings and required component codes. Rule drafts define per-component confidence/temporal policies, minimum usable frames, and uncertain handling.

The editor provides structured fields, units, ranges, controlled component references, validation errors, and a semantic diff from the prior published version. Publication requires:

- No duplicate component codes or ambiguous barcode mapping within the applicable scope.
- Every required component represented by a compatible component-model class.
- Threshold ordering and temporal counts valid.
- Product, rule, and model compatibility check passed.
- Actor, reason, timestamp, and audit record captured.

Published versions are read-only. Rollback means assigning an earlier valid version, not editing history.

## 17.9 Model Registry

The registry stores metadata and artifact references, not arbitrary training execution. A version page shows task, runtime, input shape, classes, SHA-256, dataset version, evaluation report, creation/publish state, and current device assignments.

Publication requires verified artifacts and an approved evaluation record. The UI clearly distinguishes offline detector metrics from product-level system acceptance. It must not permit direct replacement of an artifact under a published version. Model binary upload uses staged object storage, progress feedback, checksum verification, and server-side authorization.

Automated training, hyperparameter search, and deployment promotion pipelines are later scope. Initial model registration and approval may be a controlled manual process.

## 17.10 Reports and Exports

Interactive dashboard queries remain bounded. Larger CSV/JSON reports run as asynchronous jobs because aggregation and file creation may exceed an HTTP request lifetime. A report captures filter snapshot, columns, requester, creation/expiry, row count, status, and failure code. Downloads use expiring URLs and are audited.

Spreadsheet exports protect against formula injection by escaping cells beginning with spreadsheet control characters. Exports respect organization scope, permissions, retention, and barcode masking policy. Do not include raw media in tabular exports; use separately authorized evidence packages if required.

## 17.11 Users and Audit

User management displays identity-provider status and organization roles. Role replacement requires optimistic concurrency and prevents removal of the final organization administrator. Device credentials are managed separately from human users.

Audit search supports actor, action, resource, request ID, and bounded time. Before/after JSON is rendered as a safe structured diff with secret fields redacted. Audit records cannot be edited or deleted through the dashboard.

## 17.12 Frontend Architecture

- `admin-web` owns routes, page composition, authorization directives, and central-specific stores.
- Generated API clients and domain schemas are shared; the detection viewer and basic status/UI primitives may be shared with edge.
- Pinia stores session, permissions, organization context, and small UI preferences. Query results use a request/query layer with cancellation and stale handling rather than a global mirrored database.
- ECharts adapters standardize empty values, sample counts, accessible descriptions, units, and timezone labels.
- Central WebSocket invalidates active device, inspection, review, and report queries. REST refresh is authoritative.
- Long filter values are serialized predictably in the URL; sensitive tokens and comments are never placed there.

## 17.13 Performance, Resilience, and Security

- Lazy-load route bundles, media viewer, and chart modules. Use server aggregation rather than downloading raw inspections to calculate charts.
- Cancel obsolete requests when filters change. Limit comparison series to avoid unreadable charts and expensive queries.
- Display data freshness and partial-result warnings. On WebSocket loss, polling may continue at a bounded interval.
- Apply CSP, CSRF protection for cookie sessions, output escaping, dependency pinning, and no third-party runtime CDN requirement.
- Prevent cross-tenant cache keys by including organization and authorization context. Clear query caches on organization/session change.
- Record security-sensitive actions and exports with request IDs. Never expose object-storage credentials or internal stack traces.

## 17.14 Testing and Acceptance

Vitest covers permission matrices, metric formatting, timezone conversion, filters, diff rendering, and review validation. Component tests cover chart empty/partial states, large tables, media expiration, and conflicts. Playwright covers login/session expiry, organization isolation, inspection search/detail, concurrent review, product/rule publication validation, model registration, device assignment, report completion, role changes, and audit search.

API contract tests verify the generated client against OpenAPI. Security tests attempt direct route/API access across roles and organizations. Performance tests use realistic cardinalities and verify bounded dashboard query latency; exact thresholds must be agreed after infrastructure sizing.

## 17.15 MVP and Later Scope

One-month MVP: device overview/detail, inspection history/detail, basic NG review, product/rule listing and controlled version creation, simple model registry, basic summary charts, and audit capture. Reports, comprehensive user administration, staged rollouts, saved dashboard views, alert acknowledgements, and advanced model comparison can follow. The central dashboard is absent from the two-day static-image MVP.

## 17.16 Open Questions and Validation Required

- Confirm organization/site/line hierarchy, tenant model, and cross-organization support roles.
- Select OIDC provider, MFA/step-up requirements, session duration, and role approval process.
- Agree dashboard metric definitions, time zones, refresh frequency, and acceptable query latency.
- Confirm manual-review reason taxonomy, sampling policy for OK audits, and reviewer assignment/claim rules.
- Confirm report formats, masking, maximum ranges, retention, and approval requirements.
- Define model publication approvers and evidence required before device assignment.
- Confirm whether configuration rollout needs maintenance windows or immediate device polling in the MVP.
