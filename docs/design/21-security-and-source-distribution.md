# 21. Security and Source Distribution

## 21.1 Purpose and Security Position

AssemblyVision protects production evidence, configuration integrity, credentials, and administrative actions while preserving offline edge inspection. Security controls are risk-based; neither Docker nor Python bytecode is represented as a strong source-code security boundary.

### 21.1.1 Scope Distinction

- **Static train-and-inspect MVP:** no authentication is required while the training and inspection CLIs are used only in an isolated development environment with non-production data. Training code, datasets, notebooks, and experiment configuration are developer-only and are not included in a runtime distribution. Model encryption and `.pyc`-only packaging are deferred.
- **One-month target:** local access controls, central authentication, TLS, device credentials, audit logs, non-root containers, and controlled artifact distribution.
- **Production target:** customer-integrated identity where practical, role-based authorization, certificate lifecycle management, signed model/configuration packages, vulnerability management, backup encryption, and incident response.
- **Future scope:** hardware-backed keys, remote attestation, stronger native compilation/obfuscation, or licensing controls only if justified by contractual threat analysis.

## 21.2 Assets and Trust Boundaries

Protected assets include inspection decisions, images and clips, barcodes, product configurations, rules, model packages, credentials, audit logs, source/build artifacts, and personal information in user accounts. Trust boundaries exist between camera/edge hardware, local browser/edge API, edge/central network, central API/workers, object storage, administrators, and the build/registry environment.

Customer control of edge hardware means a sufficiently privileged customer administrator can inspect containers, volumes, memory, and traffic. The architecture prevents casual browsing and unauthorized application-level access; it cannot guarantee resistance to a determined privileged reverse engineer.

## 21.3 Identity and Authorization

Central users authenticate through customer identity federation when available or a securely managed local identity provider. Sessions use short-lived tokens and secure, HTTP-only cookies where browser architecture permits. Service-to-service and edge-to-central access uses a unique per-device identity; credentials are revocable and must not be shared across devices.

Recommended roles are:

| Role | Permitted actions |
|---|---|
| Operator | View current state, acknowledge alarms, initiate authorized retry/pause/resume |
| Reviewer | View evidence and record review outcomes |
| Product engineer | Draft product and rule configuration |
| Release approver | Approve and deploy signed rule/model/application releases |
| Site administrator | Manage devices and site-scoped users |
| Auditor | Read inspections, reviews, release history, and audit logs |

Authorization is deny-by-default and scoped by organization/site/line/device. Drafting and approving safety-relevant configuration should be separated where staffing permits. All permission, configuration, rule, model, retention, and review changes are audited with actor, time, old/new values or checksum, reason, and correlation identifier.

Local dashboard access must reflect site constraints. A loopback-only kiosk can reduce exposure but does not replace authentication where other users can reach the host. Emergency pause may be locally available; configuration changes require stronger authorization.

## 21.4 Network and API Security

- Use TLS for edge-to-central and browser-to-central traffic; validate hostnames and trust chains.
- Prefer outbound-only edge connections so the factory firewall need not expose the edge API centrally.
- Authenticate every upload and bind it to a registered device.
- Apply request size limits, schema validation, rate limits, and safe media content handling.
- Use idempotency keys without treating them as authentication.
- Keep database, Redis, and object-storage interfaces on private networks.
- Restrict local API listening addresses and cross-origin policy.
- Do not place secrets, raw SQL errors, filesystem paths, or stack traces in client responses.
- Treat uploaded filenames and metadata as untrusted; generate storage keys server-side.

WebSocket connections use the same authentication and authorization rules as REST, expire with their session, and carry status notifications rather than authoritative state transitions.

## 21.5 Data Protection

Inspection evidence may reveal product identifiers and factory operations. Collection is minimized to the configured upload policy: representative evidence for OK records and richer evidence for NG or exceptions. Retention is explicit by media class. Access to images, clips, barcode values, and exports is logged and site-scoped.

Encryption at rest should use platform or volume encryption at the edge and database/object-store encryption centrally. Key ownership and backup-key handling must be agreed with the customer. Logs must avoid credentials and redact sensitive barcode content when full values are unnecessary. Browser caches must not retain sensitive media beyond the intended session.

## 21.6 Configuration, Model, and Supply-Chain Integrity

Every deployable artifact has a version, cryptographic checksum, compatibility metadata, provenance, and approval state. Production packages are signed; edge clients verify checksum, signature, device/product compatibility, minimum application version, and required rule/model pairing before installation. Activation occurs between inspection windows and retains a last known-good set.

Build controls include pinned dependencies, reviewed lock-file changes, software bills of materials, container and dependency scanning, restricted registry publishing, protected release credentials, and reproducible build records. Models and datasets are handled as controlled artifacts: production images, training data, notebooks, and experiment credentials are excluded from runtime images.

## 21.7 Source Distribution Approach

The customer receives runnable edge artifacts, not the Git repository. The distribution pipeline should:

1. Build Python wheels or application trees in a private build stage.
2. Compile project Python modules to checked-hash `.pyc` files.
3. Remove original project `.py` files where imports and diagnostics remain reliable.
4. Copy only runtime dependencies and artifacts into the final image.
5. Build Vue applications and deploy only generated static assets.
6. Exclude `.git`, tests, documentation not needed at runtime, source maps unless operationally approved, training datasets, model-training code, notebooks, and internal experiment configuration.
7. Run under a non-root user with a read-only root filesystem where practical.
8. Put models, rules, databases, logs, media, and temporary files in explicit mounts with minimum permissions.
9. Inject short-lived or rotatable secrets at deployment time; never bake long-term secrets into images.

Third-party Python source may still be included by dependency packaging and must follow its license. License notices and required attribution must remain available. Debug symbols and frontend source maps must be intentionally controlled; removing them can make support harder and does not prevent reconstruction of client behavior.

## 21.8 Source Distribution Caveats

- `.pyc` is straightforward to analyze with available tools and is not strong anti-reverse-engineering protection.
- Docker packages files and processes but is not a source-code security boundary against a host administrator.
- Built frontend JavaScript is necessarily delivered to the browser and can be inspected.
- Model files and rule definitions can reveal system behavior even without Python source.
- Removing source can reduce diagnostic quality, complicate traceback analysis, and create obligations to supply corresponding source for some third-party licenses.
- Image encryption cannot protect code while the authorized machine is actively executing it without additional trusted hardware.

This level is accepted for the MVP because the immediate requirement is to avoid direct casual source browsing, not to guarantee protection from advanced reverse engineering. Licensing servers, aggressive obfuscation, custom packers, and hardware-bound activation are deliberately not introduced without a concrete commercial and operational requirement.

## 21.9 Secrets Management

Secrets are classified, inventoried, and assigned an owner and rotation method. Local secrets should be readable only by the service account and supplied through a customer-approved OS secret store, Docker secret mount, or protected file. Environment variables are acceptable only when process and support tooling exposure is understood. Frontend build-time variables are public and must never contain secrets.

Rotation must support overlap so queued uploads survive credential replacement. Revoking one device must not invalidate other devices. Logs display credential identifiers, never credential values.

## 21.10 Security Operations

### 21.10.1 Suspected Device Credential Compromise

1. Revoke the device credential centrally and disable its package/configuration access.
2. Preserve audit logs, upload receipts, and device diagnostics.
3. Continue local inspection if safe, but quarantine outbound synchronization until re-enrollment.
4. Reimage or inspect the edge host according to customer incident policy.
5. Issue a new unique credential only after host trust is restored; reconcile queued records by inspection ID and checksum.

### 21.10.2 Unauthorized Configuration Change

1. Stop further activation and retain the current evidence and audit trail.
2. Identify actor, scope, old/new checksums, affected devices, and inspection time range.
3. Restore the last approved configuration atomically.
4. Re-review potentially affected inspections using preserved model/rule versions and evidence.
5. Correct permissions or credential exposure before service normalization.

### 21.10.3 Vulnerable Runtime Dependency

1. Establish whether the vulnerable component and code path exist in deployed images.
2. Apply compensating network or feature controls where needed.
3. Rebuild from patched pinned dependencies, scan, test, sign, and stage rollout.
4. Preserve release provenance and notify customers according to severity and contract.

## 21.11 Verification

Security verification includes authorization matrix tests, tenant/site isolation tests, device revocation, malformed upload handling, dependency/container scanning, secret scanning, package signature failure, rollback safety, audit-log completeness, backup restoration, and an external penetration test before broad deployment where contractually required.

## 21.12 Open Questions and Validation Required

- Customer identity provider, MFA policy, account lifecycle, and role-separation feasibility.
- Edge users, physical access controls, local network reachability, and kiosk/browser model.
- Certificate authority, device enrollment, revocation, rotation, and offline renewal process.
- Data classification for barcodes, images, video, logs, and exports.
- Encryption-at-rest requirements and key ownership for edge, central, and backups.
- Required retention, legal hold, deletion, and audit-log retention periods.
- Contractual source-delivery, escrow, open-source license, support, or obfuscation obligations.
- Required vulnerability response times and approved registry/scanning products.

## 21.13 Related Decisions

- [ADR-001: Edge-first inspection](decisions/ADR-001-edge-first-inspection.md)
- [ADR-005: Local-first storage and delayed upload](decisions/ADR-005-local-first-storage-and-delayed-upload.md)
- [ADR-008: Docker deployment](decisions/ADR-008-docker-deployment.md)
