# 26. Customer Acceptance

## 26.1 Purpose and Acceptance Principle

Customer acceptance establishes measured fitness for a defined product mix, line, camera setup, software/model/rule release, and operating procedure. The primary inspection metric is real NG recall. Acceptance uses customer production data not used for model training and does not claim a universal or unvalidated numerical guarantee.

## 26.2 Scope Definition

### 26.2.1 MVP Acceptance

The static train-and-inspect MVP is accepted as an engineering prototype when it reproducibly trains from a locked labeled static-image set, executes inspection against a separate held-out static-image set, reports verification results, and emits traceable evidence. It is not accepted for autonomous production disposition.

### 26.2.2 Pilot Acceptance

The one-month target may run a controlled baseline on selected edge hardware and one bounded customer-line path with human verification. It covers camera, barcode, local decision, persistence, offline operation, synchronization, central history, and review, but it is not final production acceptance.

### 26.2.3 Production Acceptance

Production acceptance adds representative unseen data, agreed metric targets, resilience and long-running evidence, operational/security readiness, training, support ownership, and signed approval of residual risks.

### 26.2.4 Out of Scope Unless Added

Unvalidated product types, camera angles/locations, lighting regimes, tiny components, PLC/MES behavior, and throughput outside the tested envelope are not implicitly accepted.

## 26.3 Acceptance Baseline and Target Agreement

The supplier and customer first lock the candidate application, model, rule, product configuration, camera configuration, and hardware. They then execute a baseline on representative, previously unused customer data. Based on measured sample counts, class distribution, confidence intervals, operational consequences, and review capacity, both parties record target values and decision rules in an acceptance protocol.

The protocol must define:

- Primary NG recall target and treatment of `UNCERTAIN` if adopted.
- Allowed false-negative findings and escalation/retest policy.
- False-positive/manual-review expectations as secondary operational metrics.
- Per-product and per-component minimum evidence and pass rules.
- Product-detection, ROI, barcode, latency, throughput, upload, and recovery targets.
- Statistical reporting method and handling of inconclusive ground truth.
- Conditions that trigger remediation, partial acceptance, restricted scope, or rejection.

No value is inserted until the baseline and customer risk decision exist. A target applies only to the tested domain and release.

## 26.4 Dataset Independence and Governance

Acceptance items are not used to train, tune thresholds, choose checkpoints, or select rules before the acceptance run. They are grouped by physical product, production batch, capture session/date, and scenario so adjacent video frames cannot leak across development and acceptance.

The acceptance manifest records stable item/product identifiers, product type, expected component state, barcode ground truth, scenario, capture conditions, source group, adjudication status, and checksums. Access is restricted. If acceptance data is later approved for training, it leaves the locked acceptance set and a new independent set is required for the next acceptance claim.

Ground truth is established by authorized customer product experts. Ambiguous cases are adjudicated or reported as inconclusive; they are not silently counted in the favorable class.

## 26.5 Required Test Matrix

Each applicable product type is tested separately and in the mixed operational flow.

| Scenario | Purpose | Required assertions |
|---|---|---|
| Product type | Prevent aggregate results hiding weak variants | Correct mapping, applicable rules, component-level result |
| Each missing component | Measure actual defect detection | NG/approved uncertain path, correct missing reason and evidence |
| Missing manual | Validate document-presence case | Missing-manual reason and traceability |
| Barcode failure | Verify fail-safe identity behavior | No unverified OK under wrong/unknown product mapping |
| Product-position shift | Validate detected ROI rather than fixed coordinates | Usable ROI or explicit NG/uncertain/error |
| Normal production variation | Validate representative domain | Segmented quality and latency results |
| Consecutive OK products | Test boundaries and duplicates | One correct inspection per product, no frame mixing |
| Consecutive NG products | Test boundaries and sustained review/upload | One correct inspection per product and reasons |
| Mixed product types | Test barcode/type/rule switching | Correct versioned rule per physical product |
| Offline operation | Prove central independence | Local inspection, evidence, and durable queue continue |
| Network recovery | Prove synchronization | Backoff, complete drain, no duplicate central record, checksum match |
| Application restart | Prove safe state recovery | No fabricated OK or duplicate; incomplete window handled explicitly |
| Long-running operation | Detect resource/state degradation | Stable resource use, latency, capture, storage, and queue behavior |

Additional cases are added for no product, multiple products, occlusion, blur/reflection, camera reconnect, disk pressure, central outage, model/rule mismatch, package rollback, and unauthorized configuration attempts when applicable to the release.

## 26.6 Evidence Required for Every Test

Each executed test preserves:

- Inspection result and reason codes.
- Original and selected image evidence, plus annotated/ROI evidence as configured.
- Ground truth and adjudication provenance.
- Application, model, rule, product-configuration, and review-policy versions.
- Source and receive timestamps and device identifier.
- Barcode/product mapping result.
- Relevant structured logs, health events, and stage timings.
- Upload task and central receipt/checksum where synchronization is in scope.
- Reviewer outcome where human verification is part of the procedure.

Evidence is immutable or checksum-protected and linked through the inspection identifier.

## 26.7 Metrics and Reporting

Report NG recall and false-negative rate first, then false-positive rate, per-component recall, per-product recall, product-detection success, ROI-generation success, barcode-read success, average/P95 latency, throughput, upload delay, review rate, and correction rate. Include numerator, denominator, excluded/inconclusive count, confidence interval where meaningful, and segmentation by release version.

Overall accuracy alone is not an acceptance measure. Results must distinguish naturally occurring NG products from staged or synthetic scenarios and disclose any coverage gaps.

## 26.8 Execution Procedure

1. Approve the protocol, domain, roles, target-setting method, and stop conditions.
2. Verify camera mount, focus, exposure, lighting, edge hardware, time synchronization, disk capacity, and network setup.
3. Lock and checksum application/model/rule/configuration artifacts and acceptance manifest.
4. Run calibration/smoke cases without using acceptance outcomes to tune the locked candidate.
5. Execute randomized or production-representative cases under witness, recording all evidence.
6. Exercise offline, recovery, restart, and duration scenarios.
7. Reconcile product counts, duplicate/missing inspections, media, logs, and upload receipts.
8. Adjudicate only predeclared inconclusive cases without changing original records.
9. Produce segmented metrics and compare them with the jointly completed protocol.
10. Record approval, restricted approval, remediation/retest, or rejection with signatures and residual risks.

If a release-blocking problem is found, preserve the run. Remediation creates a new candidate version and a controlled rerun; historical failures are not overwritten.

## 26.9 Operational Acceptance Checklist

- Installation and rollback are demonstrated on representative hardware.
- Camera disconnect, central/network outage, disk pressure, restart, and power-loss procedures are exercised safely.
- Operators can identify `OK`, `NG`, degraded, unavailable, and queue states.
- Reviewers can inspect evidence and append auditable corrections.
- Configuration/model/rule changes require authorized, traceable activation.
- Backups restore successfully and pending uploads survive interruption.
- Retention protects pending evidence and respects agreed deletion policy.
- Alerts, support contacts, severity paths, and responsibility boundaries are documented.
- Security access, device credentials, TLS, audit, and source-distribution caveats are accepted.
- Known limitations and excluded operating domains are signed off.

## 26.10 Acceptance Outcomes and Change Control

Acceptance is version- and domain-specific. Any significant camera movement/angle change, lighting change, product/component change, barcode mapping change, rule/model update, inference runtime change, or material hardware/throughput change triggers impact assessment and proportional revalidation. A camera-angle change near 45 degrees is treated as a meaningful domain change requiring explicit model testing, likely new data, fine-tuning where needed, and complete system revalidation.

Conditional acceptance lists restrictions, compensating human review, expiration/review condition, owner, and required remediation. Manual review may not be reduced merely because a calendar period elapsed.

## 26.11 Open Questions and Validation Required

- Exact customer acceptance thresholds, confidence method, and rules for inconclusive cases after baseline evaluation.
- Product types, required components, criticality, and minimum independent samples per stratum.
- Availability and authorization to create staged missing-component/manual scenarios.
- Conveyor speed, expected throughput, latency budget, duty cycle, and long-running test duration.
- Camera/SDK/hardware and the allowable position, focus, exposure, and lighting envelope.
- Barcode standard and expected unreadable/unknown-code handling.
- Customer witnesses, ground-truth adjudicators, signatories, and retest responsibility.
- Accepted operational environment, data retention, security controls, and support objectives.

## 26.12 Related Documents

- [Testing and Quality Assurance](22-testing-and-quality-assurance.md)
- [Human-in-the-Loop Operations](24-human-in-the-loop.md)
- [Risks and Mitigations](27-risks-and-mitigations.md)
