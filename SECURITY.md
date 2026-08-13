# Security Policy

AssemblyVision is an edge-first industrial assembly inspection system. This
document summarizes the security position, controls, and operational
procedures defined in the repository's design documents, engineering
contracts, and accepted ADRs. It is a summary; the referenced documents are
authoritative.

## Supported Versions

| Version | Status |
|---|---|
| `main` | Edge production-candidate (MVP, dashboard, M1 edge API, camera sources, temporal aggregation, durable upload outbox, E1–E5 gates, E6 acceptance-prep tooling, barcode identity / PLC trigger, edge-local human review) and the Central server M1 pilot (ingestion, media, history/detail, append-only review, metadata governance, hardening). Edge-local human review (ADR-016, PR #31) and the central M1 pilot (C1a–C6, PRs #37–#48) are merged. Actively developed and supported. |
| `dev` | Development branch, kept in sync with `main`; not a release on its own. |

The central M1 pilot is a **controlled pilot**, not a production deployment.
Its security boundary is summarized below in the "Current central API" section
and tracked in
[`docs/reviews/AUDIT-002-central-server-review.md`](docs/reviews/AUDIT-002-central-server-review.md).

## Reporting a Vulnerability

Do **not** open a public issue for an active exploit or a credential leak.

- Report privately through GitHub's private vulnerability reporting on the
  repository's **Security** tab ("Report a vulnerability").
- Include: affected component and version, steps to reproduce, impact on the
  inspection decision (OK/NG) where relevant, and any log or evidence excerpts.
  Do not include secrets, model weights, or production media in the report.

After receiving a report the maintainers will acknowledge it, reproduce and
assess the issue, and coordinate a fix and disclosure. Production deployments
must never treat "no report" as a guarantee; see the accepted scope limitations
below.

## Security Position

Security controls are risk-based (design 21.1). Neither Docker nor Python
bytecode is treated as a strong source-code security boundary. The protection
goal is to prevent casual source browsing and unauthorized application-level
access, not to resist a determined privileged reverse engineer.

Scope by phase:

| Phase | Boundary |
|---|---|
| Static MVP | CLIs used only in an isolated development environment with non-production data. Training code, datasets, notebooks, and experiment configuration are developer-only and not distributed. Model encryption and `.pyc`-only packaging are deferred. |
| One-month target | Local access controls, central authentication, TLS, device credentials, audit logs, non-root containers, controlled artifact distribution. Delivered so far: non-root read-only-rootfs edge image, optional local HTTPS, runtime secrets via environment or Docker secrets, checksummed backup/restore bundles (E5), the barcode identity / PLC trigger contract (ADR-015), edge-local human review (ADR-016), and the Central server M1 pilot (C1a–C6) with separated device/admin authentication, fail-closed secrets, verified media receipts, and append-only review. |
| Production target | Customer-integrated identity, role-based authorization, certificate lifecycle, signed model/configuration packages, vulnerability management, backup encryption, incident response. |

## Threat Model Summary

Protected assets include inspection decisions, images and clips, barcodes,
product configurations, rules, model packages, credentials, audit logs, and
build artifacts (design 21.2). Trust boundaries exist between camera/edge
hardware, the local browser/edge API, the edge/central network, central
API/workers, object storage, administrators, and the build/registry
environment.

Because customers control edge hardware, a sufficiently privileged customer
administrator can inspect containers, volumes, memory, and traffic. The
architecture prevents casual browsing and unauthorized application-level
access; it cannot guarantee resistance to a determined privileged reverse
engineer.

## Authentication and Authorization

Authorization is **deny-by-default** and scoped by organization/site/line/device.
Hiding UI buttons is not an authorization boundary; permissions are enforced by
the backend (contract 08). Do not treat loopback binding or CORS as
authentication (design 15.2.1).

### Current edge API (M1, ADR-012)

- Every route except the deliberately minimal `GET /api/v1/health/live` requires
  `Authorization: Bearer <token>` or a short-lived, HttpOnly, same-origin
  viewer-session cookie and returns `401 UNAUTHENTICATED` otherwise.
- The token is configured via `AV_EDGE_API_TOKEN` (or `serve --api-token`).
  `POST /api/v1/auth/session` exchanges a valid bearer token for the session
  cookie; the served dashboard `/login` provides this one-time entry so neither
  API JSON requests nor media `<img>` requests need the token in browser
  storage.
- The API is **read-only for inspection control**: pause/resume and camera
  reconnect are not exposed. The controlled upload retry
  (`POST /api/v1/uploads/{id}/retry`, E3) is the only mutating route on
  `main`; review submission (`POST /api/v1/inspections/{id}/reviews`,
  ADR-016) uses the same viewer credential as a documented deviation (see
  "Privileged operations" below) until an edge role model exists.
- Uploads use a separate credential (`AV_EDGE_UPLOAD_TOKEN` /
  `--upload-base-url`); the viewer token is never reused for uploads. Upload
  destinations require HTTPS; plaintext HTTP is allowed only for a loopback
  development host with `--upload-insecure-http`.
- Optional local HTTPS via `--tls-cert`/`--tls-key` (or `AV_EDGE_TLS_CERT` /
  `AV_EDGE_TLS_KEY`) with startup validation of existence, private-key
  permissions, and certificate/key match. Viewer and upload tokens also fall
  back to Docker secret files under `/run/secrets/` when the environment
  variables are absent (E5).
- The WebSocket runtime channel (`WS /api/v1/ws/runtime`, E4) uses the same
  viewer model as REST: browsers exchange the credential for a short-lived,
  single-use ticket (`POST /api/v1/ws/runtime/ticket`) sent as the negotiated
  `Sec-WebSocket-Protocol` value, never in the URL.
- CORS never uses `*`; only anchored loopback development origins
  (`localhost` / `127.0.0.1`) are allowed. The served dashboard is same-origin.
- If no token is configured the service runs in an explicit M1 development
  mode. This must never be presented as production authentication.

### Current central API (M1 pilot)

The central server M1 pilot (`apps/central-service`, `apps/admin-web`) is a
management and evidence plane and is never in the real-time inspection path.
Its boundary is pilot-grade and tracked in
[`docs/reviews/AUDIT-002-central-server-review.md`](docs/reviews/AUDIT-002-central-server-review.md):

- Device uploads authenticate with a dedicated upload token; administrators
  exchange a long-lived pilot bearer token for a short-lived HttpOnly,
  `SameSite=Strict`, `Secure` session cookie. Device and administrator
  authentication are strictly separated and cannot be substituted.
- The Compose profile ships no usable credential defaults; every PostgreSQL,
  MinIO, administrator, and device secret is a required non-empty value and
  fails closed when unset.
- Ingestion is idempotent and bounded (envelope/payload caps), media bytes are
  size- and SHA-256-verified before an `AVAILABLE` receipt, review appends are
  content-addressed, desired-configuration assignments use an atomic
  `If-Match`, and per-client rate limiting derives identity only from a
  trusted proxy address.
- M1 has a single all-powerful pilot administrator: there is no OIDC, no
  role-based authorization, no automated credential rotation, and no device
  disable/re-enroll path. A credential compromise follows the manual
  revocation procedure in runbook C3. TLS is terminated by an external reverse
  proxy (the shipped nginx listens on HTTP only).
- The API uses the MinIO root credential and the migration owner database
  credential in the pilot; bucket-scoped service accounts and separate
  migration/runtime roles are production scope.

Central OIDC/roles, credential rotation and unique credential identity, and the
governed ingestion reference policy remain production scope (AUDIT-002 H02,
H07, H12 deferred).

### Recommended roles (design 21.3, contract 08)

| Role | Permitted actions |
|---|---|
| Operator | View current state, acknowledge alarms, initiate authorized retry/pause/resume |
| Reviewer | View evidence and record review outcomes |
| Product engineer | Draft product and rule configuration |
| Release approver | Approve and deploy signed rule/model/application releases |
| Site administrator | Manage devices and site-scoped users |
| Auditor | Read inspections, reviews, release history, and audit logs |

Central users authenticate through OIDC Authorization Code with PKCE where
available; API authorization uses organization-scoped roles (`viewer`,
`reviewer`, `config_manager`, `fleet_admin`, `org_admin`). Drafting and
approving safety-relevant configuration should be separated where staffing
permits. These are production-target controls; the central M1 pilot has no
roles and a single administrator (see "Current central API" above).

### Privileged operations (contract 08)

Model activation, rule publication, threshold changes, data deletion, remote
device configuration, user management, and human-review actions that append or
supersede a human disposition require elevated permissions. On the current
edge, the only privileged-class action exposed — review submission — rides the
single viewer credential (ADR-016 decision 3/7) as a documented operator-
convenience trade-off until an edge role model exists (PR31-T05). The central
M1 pilot has the same gap in a different form: every authenticated pilot
administrator can review, publish metadata, and assign desired configuration,
because M1 has no role separation. The elevated-permission requirement and
role model apply to the mature designs.
Review never overwrites the immutable edge `internal_decision` or
`business_result`.

### Audit logging (contract 08)

Audit product-configuration changes, rule changes, threshold changes, model
activation, human review, record deletion, permission changes,
device-configuration changes, and remote operations. Entries record actor,
action, target, before/after state or checksum, timestamp, device/site, and
trace ID. Logs display credential identifiers, never credential values.

## Deployment contexts

Central runs in one of two optional deployment modes. Both keep the edge out of
the real-time decision path, and in both the edge reaches central directly over
the factory network (never through a VPN).

| Dimension | A. Network deployment | B. Factory intranet + controlled Tailscale |
|---|---|---|
| Central reachability | Reachable on the regular factory/enterprise network | Factory intranet only; not exposed publicly |
| Edge to central | Intranet direct | Intranet direct (never through Tailscale) |
| TLS termination | External reverse proxy | Intranet reverse proxy, optionally over Tailscale's WireGuard |
| Remote maintenance | Regular network + TLS + admin session | Temporary Tailscale during operator-led maintenance only |
| Primary threats | Network attack surface plus insider | Insider lateral movement plus a compromised Tailscale node |
| H02/H06/H11/H12 (AUDIT-002) | Close or strictly mitigate | Accepted risk (mitigations applied) |
| H07 (AUDIT-002) | Production scope (functional completeness) | Production scope (functional completeness) |
| M12 (MinIO root, AUDIT-002) | Medium | Production hardening |

In mode B, Tailscale is a compensating control with mandatory constraints:

- Tailscale is enabled only during operator-led maintenance windows and
  disabled afterwards; it is never a permanent administrative channel.
- A Tailscale ACL allowlist admits only the authorized maintenance nodes.
- A site operator owns the Tailscale keys and ACL.
- Tailscale node identity is layered with, and never replaces, application
  authentication (the administrator session cookie).

## Network and API Security

- Use TLS for edge-to-central and browser-to-central traffic; validate
  hostnames and trust chains (design 21.4).
- Prefer outbound-only edge connections so the factory firewall need not expose
  the edge API centrally.
- Authenticate every upload and bind it to a registered device. Idempotency
  keys are not authentication.
- Apply request size limits, schema validation, rate limits, and safe media
  content handling. Treat uploaded filenames and metadata as untrusted;
  generate storage keys server-side.
- Keep database, Redis, and object-storage interfaces on private networks.
  Restrict local API listening addresses and cross-origin policy.
- Never place secrets, raw SQL errors, filesystem paths, or stack traces in
  client responses.
- WebSocket channels use the same authentication and authorization rules as
  REST, expire with their session, and carry notifications rather than
  authoritative state transitions. Tokens must not appear in URL query logs
  (design 15.5).

## Data Protection

Inspection evidence may reveal product identifiers and factory operations.
Collection is minimized to the configured upload policy: representative
evidence for OK records, richer evidence for NG or exceptions (design 21.5).
Retention is explicit by media class, and access to images, clips, barcode
values, and exports is logged and site-scoped.

Encryption at rest should use platform or volume encryption at the edge and
database/object-store encryption centrally; key ownership and backup-key
handling are agreed with the customer. Browser caches must not retain sensitive
media beyond the intended session.

## Supply-Chain and Artifact Integrity

Every deployable artifact has a version, cryptographic checksum, compatibility
metadata, provenance, and approval state (design 21.6). Production packages are
signed; edge clients verify checksum, signature, device/product compatibility,
minimum application version, and the required rule/model pairing before
installation. Activation occurs between inspection windows and retains a last
known-good set.

Build controls include pinned dependencies, reviewed lock-file changes,
software bills of materials, container and dependency scanning, restricted
registry publishing, protected release credentials, and reproducible build
records. Production images, training data, notebooks, and experiment
credentials are excluded from runtime images.

Models and rules follow a release lifecycle (contract 08): Draft → Validated →
Approved → Active → Retired. Production rules must not be edited in place
without versioning.

## Source Distribution

The customer receives runnable edge artifacts, not the Git repository
(design 21.7, contract 08). The distribution pipeline builds Python wheels or
application trees in a private build stage, may compile project modules to
`.pyc`, removes original `.py` files where reliable, copies only runtime
dependencies, deploys only built frontend assets, runs under a non-root user
with a read-only root filesystem where practical, and injects short-lived or
rotatable secrets at deployment time.

Explicit caveats (design 21.8, contract 08):

- `.pyc` is straightforward to analyze and is not strong anti-reverse-engineering
  protection.
- Docker is not a source-code security boundary against a host administrator.
- Built frontend JavaScript is delivered to the browser and can be inspected.
- Model files and rule definitions can reveal system behavior even without
  Python source.
- Long-term secrets must never be embedded in images.

## Secrets Management

Secrets are classified, inventoried, and assigned an owner and rotation method
(design 21.9). Local secrets are readable only by the service account and
supplied through a customer-approved secret store, Docker secret mount, or
protected file. Frontend build-time variables are public and must never contain
secrets. Rotation supports overlap so queued uploads survive credential
replacement; revoking one device must not invalidate other devices.

## Security Operations

Prescribed recovery procedures (design 21.10):

- **Suspected device credential compromise**: revoke the credential centrally,
  preserve audit logs and upload receipts, quarantine outbound synchronization,
  reimage or inspect the host, and issue a new unique credential only after
  host trust is restored.
- **Unauthorized configuration change**: stop activation and retain evidence,
  identify actor/scope/checksums, restore the last approved configuration
  atomically, re-review potentially affected inspections with preserved model/
  rule versions, and correct permissions before normalization.
- **Vulnerable runtime dependency**: establish whether the vulnerable component
  and code path exist in deployed images, apply compensating controls, rebuild
  from patched pinned dependencies, scan, test, sign, and stage rollout while
  preserving release provenance.

Operational runbooks cover the related recovery paths: runbook 05 (database
recovery), runbook 12 (backup and recovery), runbook 13 (TLS certificate
rotation), and runbook 14 (deployment upgrade and rollback). Central pilot
runbooks C1–C5 cover the ingestion backlog, object-store failure, credential
compromise (including the M1 manual revocation procedure, since automated
rotation is deferred), backup/restore (with a quiesced, consistent recovery
point), and pilot upgrade/rollback.

## Verification

Security verification includes authorization matrix tests, site isolation
tests, device revocation, malformed upload handling, dependency and container
scanning, secret scanning, package signature failure, rollback safety,
audit-log completeness, backup restoration, and an external penetration test
before broad deployment where contractually required (design 21.11).

CI enforces the Python and frontend gates (ruff, mypy, pytest, OpenAPI/
TypeScript contract drift, frontend build/lint/unit, Playwright e2e) on every
push, and the E6 acceptance runner (`scripts/edge-acceptance-run.py`) executes
the locally automatable security and operations items while on-site hardware
items stay `NOT_EXECUTED` (never reported as pass). The central server is
covered by a dedicated review (`docs/reviews/AUDIT-002-central-server-review.md`);
a real PostgreSQL concurrency test verifies the desired-configuration
`If-Match` guard when `AV_CENTRAL_TEST_DATABASE_URL` is set.

## Open Questions and Validation Required

The following remain unconfirmed and block parts of the production security
posture (design 21.12): customer identity provider and MFA policy, edge user
and kiosk/browser model, certificate authority and device enrollment/revocation/
rotation, data classification for barcodes/images/video/logs, encryption-at-rest
and key ownership, retention and legal-hold periods, contractual source-delivery
and escrow obligations, and vulnerability response times.

## Related Documentation

- [Design 21 — Security and Source Distribution](docs/design/21-security-and-source-distribution.md)
- [Design 15 — REST API and Events (authentication, idempotency, WebSocket)](docs/design/15-rest-api-and-events.md)
- [Contract 08 — Security, Permissions, and Audit](docs/contracts/08-security-permissions-and-audit.md)
- [ADR-012 — Edge API M1 Viewer Authentication](docs/design/decisions/ADR-012-edge-api-m1-viewer-auth.md)
- [AGENTS.md — Repository coding and safety rules](AGENTS.md)
