# 28. Edge Acceptance Report

## 28.1 Purpose and Evidence Principle

The Edge acceptance report is the single evidence-based record used to declare an Edge release accepted, conditionally accepted, or rejected for a defined domain (site, device, camera setup, product mix, and software/model/rule/configuration release). It consolidates the executed test matrix, measured metrics, resilience evidence, locked artifacts, and residual-risk decisions that acceptance (design 26) is based on.

The report never claims a universal or unvalidated numerical guarantee, and it never claims 100% accuracy. Every measured figure is tied to the tested domain and release; unmeasured fields are recorded as `NOT_MEASURED` and are never fabricated. A report with `NOT_MEASURED` metrics may document prep readiness, but it cannot by itself declare production acceptance.

## 28.2 When a Report Is Required and When It Can Be Issued

An Edge acceptance report is required before an Edge release is declared accepted or conditionally accepted for production use, and whenever revalidation after a significant change requires a new acceptance claim (design 26.10).

The report is produced in two phases:

- **E6-prep draft:** A report may be drafted during E6-prep without a real environment. It records the environment and prerequisites, candidate versions, locked artifacts, the acceptance protocol reference, and the planned test matrix. Metrics and resilience evidence default to `NOT_MEASURED`. A prep draft is a readiness record, not an acceptance.
- **On-site acceptance run:** Formal acceptance requires executed on-site evidence against a real environment and unseen customer data. The prep draft is completed with the executed test matrix, measured metrics, resilience evidence, soak evidence, deviations, and sign-off.

A report drafted without real-environment inputs must explicitly state the missing inputs (for example, hardware, camera/SDK, unseen data, or witness availability) and mark every affected field `NOT_MEASURED`. A backup is not considered operational until a representative restore has succeeded (design 20.10), so a report may only treat backup/restore as evidence when an executed restore is recorded. A prep-only report never triggers sign-off as a production acceptance.

## 28.3 Report Structure

The report follows this section-by-section template. Unmeasured or inapplicable fields are marked `NOT_MEASURED` or `NOT_EXECUTED`, never omitted silently.

### 28.3.1 Cover

- Candidate versions: application, product/component model and checksum, rule, product configuration, and review policy, each with version and checksum.
- Device/hardware identifier and hardware description.
- Site and line.
- Report dates: draft date, execution start/end, and sign-off date.
- Status: `DRAFT` (E6-prep), `COMPLETE-PENDING-SIGN-OFF`, `ACCEPTED`, `CONDITIONALLY-ACCEPTED`, or `REJECTED`.

### 28.3.2 Environment and Prerequisites

- Hardware: edge computer, CPU, GPU, memory, storage, and UPS where applicable.
- GPU model and driver/SDK versions.
- Camera vendor, model, SDK/driver, and trigger interface.
- Barcode scanner model and decoder/SDK.
- PLC/trigger integration and signal definition where in scope.
- Docker/OS: operating system, Docker Engine, and runtime versions.
- Network: topology, DNS, firewall, and declared connectivity assumptions.

Every prerequisite is recorded as `PRESENT`, `ABSENT`, or `NOT_MEASURED`. Absent prerequisites require a stated impact and prevent on-site acceptance until resolved.

### 28.3.3 Locked Artifacts and Checksums

- Application image/package digest and version.
- Product/component model artifact and checksum.
- Rule artifact and checksum.
- Product configuration and checksum.
- Review policy and checksum.
- Acceptance manifest and checksum (design 26.4).

The locked artifact set is the set that was executed during the acceptance run. No acceptance evidence may reference artifacts outside the locked set.

### 28.3.4 Acceptance Protocol Reference

- Link to the agreed acceptance protocol and its version/date.
- Metric targets agreed with the customer after baseline evaluation.
- Statistical reporting method and handling of inconclusive ground truth.
- Stop conditions and remediation/retest policy.

Targets are never invented in this document; they come from the jointly completed protocol (design 26.3).

### 28.3.5 Executed Test Matrix

| ID | Scenario | Classification | Result | Evidence link | Notes |
|---|---|---|---|---|---|
| T-01 | Product type | Required | `PASS`/`FAIL`/`SKIP`/`NOT_EXECUTED` | Link/ID | ... |

Each row records the scenario (from the required matrix in design 26.5 and the resilience cases in 22.8), classification (required/optional), result, evidence link, and notes. `SKIP` requires a stated reason; `NOT_EXECUTED` is recorded when a scenario was planned but not run and is treated as unmeasured evidence.

### 28.3.6 Metrics Table

| Metric | Measured value | Target | Confidence interval | Sample count | State |
|---|---|---|---|---|---|
| NG recall | value | protocol | CI | count | `MEASURED`/`NOT_MEASURED` |

The metric list and definitions are those in section 28.5. Targets are filled only from the agreed protocol after baseline.

### 28.3.7 Resilience Evidence

| Fault | Injection method | Required behavior | Result | Evidence |
|---|---|---|---|---|
| Offline | central endpoint/DNS blocked | local decisions continue; queue persists | ... | ... |

Each resilience case from design 22.8 (offline, network flap, restart, power loss, disk pressure, GPU failure, DB corruption, backup/restore, container restart, clock drift, checksum failure) records the injection method, observed behavior against the required behavior, result, and evidence. A backup/restore case counts only when a representative restore succeeded.

### 28.3.8 Long-Running and Soak Evidence

- Duration, workload profile, duty cycle, and agreed target.
- Resource trends: CPU, GPU, memory, temperature, disk I/O, file descriptors, and queue growth.
- Latency stability over the soak window.
- Any degradation or data-loss events.

### 28.3.9 Deviations and Open Items

- Deviations from the agreed protocol, matrix, or target set, each with rationale and owner.
- Open items that do not block the stated outcome, with owners and due dates.

### 28.3.10 Risks and Residual-Risk Sign-Off

- Residual risks from the risk register (design 27) applicable to this release and domain.
- Accepted residual risk, owner, and compensating controls.
- Explicit statement that residual risks are accepted by an authorized customer representative.

### 28.3.11 Excluded Operating Domains

- Product types, camera angles/locations, lighting regimes, components, PLC/MES behaviors, and throughput ranges outside the validated envelope (design 26.2.4).
- A clear statement that excluded domains are not covered by this acceptance claim.

### 28.3.12 Sign-Off Block

- Supplier: role, name, date, signature.
- Customer: role, name, date, signature.
- Witnesses and ground-truth adjudicators where applicable.
- Outcome: accepted, conditionally accepted (with restrictions), or rejected.
- Restricted approval conditions: compensating human review, scope limits, owner, and required remediation.
- Expiration/review condition and next review date.

## 28.4 Evidence and Traceability Requirements

Every executed test preserves (mirroring design 26.6):

- Inspection result and reason codes.
- Original and selected image evidence, plus annotated/ROI evidence as configured.
- Ground truth and adjudication provenance.
- Application, model, rule, product-configuration, and review-policy versions.
- Source and receive timestamps and device identifier.
- Barcode/product mapping result.
- Relevant structured logs, health events, and stage timings.
- Upload task and central receipt/checksum where synchronization is in scope.
- Reviewer outcome where human verification is part of the procedure.

Evidence is immutable or checksum-protected and linked through the inspection identifier and the report's evidence links. Traceability must be complete enough to reconstruct which locked artifacts, on which device, at which timestamps, produced each result (design 22.11 gate 7).

## 28.5 Metrics Definitions

Each metric reports definition, numerator/denominator, excluded/inconclusive count, confidence interval where meaningful, and segmentation by release version. The default for any field without executed measurement is `NOT_MEASURED`; no numeric value is fabricated. Targets are agreed per customer protocol after baseline evaluation (design 26.3, 22.7).

| Metric | Definition | Numerator/Denominator | Default |
|---|---|---|---|
| NG recall | Real NG products classified as NG or routed to the adopted uncertain/manual path | NG routed to NG/manual path / real NG products | `NOT_MEASURED` |
| False-negative rate | Real NG products classified as OK | Real NG classified OK / real NG products | `NOT_MEASURED` |
| False-positive rate | Real OK products classified as NG | Real OK classified NG / real OK products | `NOT_MEASURED` |
| Per-component recall | Recall for each missing required component scenario | Component routed NG / component absent cases | `NOT_MEASURED` |
| Per-product recall | NG recall segmented by product type | Per-product NG routed / per-product real NG | `NOT_MEASURED` |
| Product-detection success | Usable product ROI produced when a product is inspectable | Successful product detections / inspectable products | `NOT_MEASURED` |
| ROI-generation success | Valid, correctly mapped ROI among product detections | Valid ROIs / product detections | `NOT_MEASURED` |
| Barcode-read success | Correctly resolved barcode among readable target barcodes | Correct reads / readable targets | `NOT_MEASURED` |
| Latency (average and P95) | Capture/trigger to durable decision | Sum of stage timings / inspections (P95 from distribution) | `NOT_MEASURED` |
| Throughput | Completed product decisions per time under the validated line profile | Completed decisions / elapsed time | `NOT_MEASURED` |
| Upload delay | Decision time to central durable receipt, segmented by connectivity | Receipt time minus decision time | `NOT_MEASURED` |
| Review rate | Manual review rate by decision/version | Reviewed inspections / total inspections | `NOT_MEASURED` |
| Correction rate | Corrections by decision/version | Corrected decisions / reviewed decisions | `NOT_MEASURED` |

Overall accuracy alone is not an acceptance measure; the report segments results by product, component, model, and rule version and discloses coverage gaps and staged versus naturally occurring defects (design 26.7).

## 28.6 Acceptance Outcomes and Change Control

Outcomes mirror design 26.10:

- **Accepted:** the executed evidence meets the agreed protocol targets for the defined domain and release.
- **Conditionally accepted:** lists restrictions, compensating human review, expiration/review condition, owner, and required remediation. Manual review may not be reduced merely because a calendar period elapsed.
- **Rejected / retest:** a release-blocking problem preserves the run; remediation creates a new candidate version and a controlled rerun. Historical failures are not overwritten (design 26.8).

Acceptance is version- and domain-specific. Any significant camera movement/angle change, lighting change, product/component change, barcode mapping change, rule/model update, inference runtime change, or material hardware/throughput change triggers impact assessment and proportional revalidation (design 26.10). A camera-angle change near 45 degrees is treated as a meaningful domain change requiring explicit model testing, likely new data, fine-tuning where needed, and complete system revalidation. Revalidation records the trigger, scope, and outcome in a new or updated report.

## 28.7 Open Questions and Validation Required

- Exact customer acceptance thresholds, confidence method, and rules for inconclusive cases after baseline evaluation.
- Availability and authorization of unseen customer data, naturally occurring NG samples, and staged missing-component/manual scenarios.
- Hardware envelope: edge computer, GPU/driver, camera/SDK, trigger/PLC, and the allowable position, focus, exposure, and lighting range.
- Barcode standard and expected unreadable/unknown-code handling.
- Customer witnesses, ground-truth adjudicators, signatories, and retest responsibility.
- Backup/restore frequency and customer-agreed RPO/RTO for the acceptance claim.
- Long-running test duration, production duty cycle, and expected outage duration for soak evidence.

## 28.8 Related Documents

- [Customer Acceptance](26-customer-acceptance.md)
- [Testing and Quality Assurance](22-testing-and-quality-assurance.md)
- [Deployment and Operations](20-deployment-and-operations.md)
- [Risks and Mitigations](27-risks-and-mitigations.md)
- [Human-in-the-Loop Operations](24-human-in-the-loop.md)
- [E6: Edge Acceptance](../tasks/E6-edge-acceptance.md)
