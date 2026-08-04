# 22. Testing and Quality Assurance

## 22.1 Purpose and Quality Objective

AssemblyVision testing demonstrates measured behavior under representative production conditions. The primary quality objective is high recall of real NG products and an extremely low false-negative rate, supported by traceable evidence and cautious human verification. No test plan or model is represented as guaranteeing 100% accuracy.

## 22.2 Scope by Delivery Stage

- **Two-day MVP:** unit tests for ROI/rules/serialization, static pipeline integration tests, deterministic fixtures, CLI smoke test, and baseline model evaluation.
- **One-month target:** camera and barcode adapters, local persistence, temporal aggregation, APIs, dashboards, synchronization, failure injection, deployment smoke tests, and customer-site acceptance candidates.
- **Production target:** independent acceptance data, long-running tests, power-loss and disk-full recovery, security/contract testing, release regression suites, and model/rule promotion gates.
- **Future scope:** multi-line load simulation, hardware-in-the-loop rigs, automated fleet canaries, and additional camera-domain test sets.

## 22.3 Test Levels

| Level | Focus | Representative examples |
|---|---|---|
| Unit | Pure behavior and boundary conditions | ROI clipping, confidence aggregation, rule reason codes, retention eligibility |
| Component | One service with controlled dependencies | camera adapter reconnect, SQLite repository, upload state machine |
| Integration | Real boundaries | API plus database, object storage checksum, model runtime plus ROI mapping |
| End-to-end | User/product workflow | capture through local decision; upload through central review |
| Model evaluation | Statistical performance on held-out groups | NG recall by component/product and confidence distributions |
| Resilience | Recovery and safe degradation | network outage, power loss, disk full, corruption, restart |
| Acceptance | Customer production behavior | agreed matrix in document 26 using unseen production data |

Tests use the same versioned model, rule, application, and configuration artifacts intended for release.

## 22.4 Unit and Component Testing

Python tests use Pytest and cover valid, invalid, and boundary data. Property-based testing is appropriate for bounding-box clipping, coordinate transforms, idempotency, and state transitions. Time, UUID generation, camera input, and network behavior are injectable.

Required unit subjects include:

- Product-window opening/closing and ambiguous identity handling.
- ROI margin expansion, boundary clipping, coordinate round trips, and no-product behavior.
- Frame-quality rejection and per-component temporal evidence policies.
- Deterministic rule evaluation, including missing and low-confidence reason codes.
- Product/barcode mapping and fail-closed behavior.
- Upload retry/backoff, idempotency key stability, checksum mismatch, and terminal errors.
- Retention rules that protect pending media.
- Configuration/model manifest validation and compatibility checks.
- Database transaction behavior and incomplete-record recovery.

Vue component tests use Vitest for status states, tables, detection overlays, review controls, form validation, permission behavior, and offline/error presentation. Browser end-to-end tests verify critical workflows without substituting for actual camera testing.

## 22.5 Integration and Contract Testing

Integration tests run against supported database and object-storage versions. SQLite edge tests include write contention and unclean process termination. PostgreSQL migration tests cover upgrade from every supported release and rollback constraints.

OpenAPI is the contract source for generated TypeScript clients. Contract tests verify status codes, schemas, pagination, authorization, idempotent upload replay, WebSocket event envelopes, media range/download behavior, and forward-compatible unknown fields. Edge/central compatibility is tested across the explicitly supported version matrix.

Camera adapters have a common conformance suite:

1. Enumerate/connect/disconnect and reconnect.
2. Acquire frame with timestamp and camera metadata.
3. Apply or report exposure and trigger configuration.
4. Handle timeout, malformed frame, SDK exception, and device removal.
5. Release resources without preventing restart.

Real-camera tests run on the selected hardware because mocks cannot validate SDK, driver, trigger timing, exposure, focus, or frame transport.

## 22.6 End-to-End Scenarios

At minimum, automate or execute repeatably:

- OK product with every required component.
- Each required component absent, including the manual.
- No product, partial product, and unusable frame.
- Barcode success, unreadable barcode, unknown barcode, and product mismatch.
- Slight position shifts and normal production variation.
- Multiple products in one window and frame mixing attempts.
- Consecutive OK, consecutive NG, and mixed product types.
- Edge inspection while central services and network are unavailable.
- Network recovery with queue drain, duplicate replay, and checksum verification.
- Application restart during capture, decision persistence, and upload.
- Manual review and correction with audit history.
- Model/rule installation, compatibility rejection, activation, and rollback.

Every scenario asserts the final decision and reason codes, not only HTTP success.

## 22.7 Model and System Evaluation

Dataset partitions are grouped by physical product instance, batch, capture session, and production date. Adjacent video frames from one product must not be split across training and validation. Acceptance data remains separate from model development.

Required reports include:

| Metric | Definition and use |
|---|---|
| NG recall | Real NG products classified as NG or routed to the adopted uncertain/manual path divided by real NG products |
| False-negative rate | Real NG products classified as OK divided by real NG products |
| False-positive rate | Real OK products classified as NG divided by real OK products |
| Per-component recall | Recall for each missing required component scenario |
| Per-product recall | NG recall segmented by product type |
| Product-detection success | Usable product ROI produced when a product is inspectable |
| ROI-generation success | Valid, correctly mapped ROI among product detections |
| Barcode-read success | Correctly resolved barcode among readable target barcodes |
| Latency | Capture/trigger to durable decision; report average and P95 |
| Throughput | Completed product decisions per time under the validated line profile |
| Upload delay | Decision time to central durable receipt, segmented by connectivity |
| Review metrics | Manual review rate and correction rate by decision/version |

Overall accuracy may be reported but is never the sole promotion criterion because class imbalance can conceal missed defects. Confidence intervals and sample counts accompany rates. Any ambiguous ground truth is adjudicated and reported rather than silently removed.

## 22.8 Failure and Resilience Testing

| Fault | Injection | Required behavior |
|---|---|---|
| Camera disconnect | Remove device/stop simulator | No fabricated `OK`; alarm, reconnect, recover safely |
| Network outage | Block central endpoint/DNS | Local decisions continue; queue persists |
| Central outage | Return timeout/5xx | Backoff with jitter; no decision blockage |
| Duplicate upload | Replay same idempotency key | One central inspection and consistent receipt |
| Power loss | Kill host/process during selected states | Recover database/queue; ambiguous window not marked OK |
| Disk full | Fill test volume or enforce quota | Alert, safe cleanup, pause before traceability is lost |
| Database failure | Lock/corrupt disposable test database | Fail safely, preserve diagnostics, execute tested restore path |
| Container restart | Restart each service independently | Supervisory recovery without duplicate product decision |
| Clock drift | Offset wall clock | Preserve monotonic ordering/correlation and alert on drift |
| Checksum failure | Alter media/package bytes | Reject artifact and retain recoverable task/version |

Fault tests run only in isolated environments with disposable data. Power-loss testing includes interruptions before/after database commit, media rename, queue creation, upload transfer, and receipt persistence.

## 22.9 Performance and Stability

Performance testing uses production-resolution images and the candidate edge hardware. Measure stage timings for capture, barcode, product detection, ROI, component detection, aggregation, rules, persistence, and UI/event delivery. Report warm-up separately and monitor CPU, GPU, memory, temperature, disk I/O, and queue growth.

Long-running tests include normal product flow, bursts, idle periods, camera reconnects, central outages, and retention cleanup. Passing means no unbounded memory/file-descriptor/queue growth, no data loss, and stable latency within customer-agreed limits. Duration and workload are agreed from actual operating patterns; this document does not invent them.

## 22.10 Test Data and Ground Truth Governance

Fixtures contain no uncontrolled customer data. Each evaluation item has an immutable identifier, source group, product type, expected component state, barcode ground truth where applicable, annotation/review provenance, and permitted use. Corrections create a new annotation version. Training, validation, test, and customer acceptance manifests are checksum-controlled.

Real NG examples are intentionally collected for every required missing-component condition. Synthetic removal or staging may supplement but must be reported separately from naturally occurring defects. Dataset quantities in the training strategy are starting points, not guarantees.

## 22.11 Release Quality Gates

A candidate is promotable only when:

1. Required static checks (`Ruff`, `MyPy`, ESLint, formatting) and automated tests pass.
2. Database and API compatibility checks pass.
3. Security scans have no unaccepted release-blocking findings.
4. Model/system metrics are compared against the approved baseline by product, component, model, and rule version.
5. No unexplained NG-to-OK regression appears in the locked regression set.
6. Offline, restart, retry, disk-pressure, and rollback tests pass for the release scope.
7. Evidence, version, timestamp, device, and log traceability are complete.
8. Customer-specific targets, once established through baseline evaluation, are met or an explicit deviation is approved.

Numeric gates are recorded in the release/acceptance plan after representative baseline measurement; they are not invented here.

## 22.12 Defect Management and Evidence

Defects include severity, environment, application/model/rule/configuration versions, device/camera identifiers, timestamps, steps, expected/actual result, relevant images/logs, and privacy classification. A missed NG is treated as the highest inspection-quality concern and triggers containment, affected-range analysis, regression fixture creation, and release review.

Test reports and manifests are retained with release provenance. Flaky tests are quarantined only with an owner and remediation deadline; quarantining cannot bypass a safety-relevant gate.

## 22.13 Open Questions and Validation Required

- Customer-agreed acceptance thresholds and statistical confidence approach after baseline evaluation.
- Product types, exact required component classes, defect taxonomy, and ground-truth owner.
- Candidate camera/SDK, edge CPU/GPU, conveyor rate, and latency/throughput budget.
- Required supported-version compatibility window for edge and central releases.
- Long-running test duration, production duty cycle, and expected outage duration.
- Availability of naturally occurring NG samples and permission to stage missing-component cases.
- Required browsers, operating systems, security scanners, and external test obligations.
- Retention period and access controls for test evidence containing customer production data.

## 22.14 Related Documents

- [Customer Acceptance](26-customer-acceptance.md)
- [Risks and Mitigations](27-risks-and-mitigations.md)
- [ADR-009: Static-image-first MVP](decisions/ADR-009-static-image-first-mvp.md)
- [ADR-010: Per-component temporal aggregation](decisions/ADR-010-per-component-temporal-aggregation.md)
