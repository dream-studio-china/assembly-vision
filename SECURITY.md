# Security Policy

AssemblyVision is an edge-first industrial assembly inspection system. This
document summarizes the security position, controls, and operational
procedures defined in the repository's design documents, engineering
contracts, and accepted ADRs. It is a summary; the referenced documents are
authoritative.

## Supported Versions

| Version | Status |
|---|---|
| `main` | Static train-and-inspect MVP (ADR-011), the read-only M1 edge API (PR #8), the real-data baseline tooling and dataset adapters (PRs #9-#11). Actively developed and supported. |
| `dev` | Development branch, kept in sync with `main`; not a release on its own. |

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
| One-month target | Local access controls, central authentication, TLS, device credentials, audit logs, non-root containers, controlled artifact distribution. |
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
- No mutating routes are exposed in M1 (pause/resume, camera reconnect, and
  upload retry return `404`). An inspection coordinator and operator commands
  are a later milestone requiring the documented operator/admin role model.
- CORS never uses `*`; only anchored loopback development origins
  (`localhost` / `127.0.0.1`) are allowed. The served dashboard is same-origin.
- If no token is configured the service runs in an explicit M1 development
  mode. This must never be presented as production authentication.

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
permits.

### Privileged operations (contract 08)

Model activation, rule publication, threshold changes, data deletion, remote
device configuration, user management, and human-review actions that append or
supersede a human disposition require elevated permissions. Review never
overwrites the immutable edge `internal_decision` or `business_result`.

### Audit logging (contract 08)

Audit product-configuration changes, rule changes, threshold changes, model
activation, human review, record deletion, permission changes,
device-configuration changes, and remote operations. Entries record actor,
action, target, before/after state or checksum, timestamp, device/site, and
trace ID. Logs display credential identifiers, never credential values.

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

## Verification

Security verification includes authorization matrix tests, site isolation
tests, device revocation, malformed upload handling, dependency and container
scanning, secret scanning, package signature failure, rollback safety,
audit-log completeness, backup restoration, and an external penetration test
before broad deployment where contractually required (design 21.11).

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
