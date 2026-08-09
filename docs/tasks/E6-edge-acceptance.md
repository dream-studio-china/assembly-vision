# E6 Pipeline: Edge Acceptance

## 1. Purpose

E6 establishes measured fitness of the edge runtime for a defined customer
line, model/rule release, camera setup, and operating procedure. Milestones
E1-E4 are merged. E5 is implemented in open PR #24 and is not merged. E6 is
the acceptance gate that follows the Edge delivery work and the last Edge
production-candidate gate before central work starts. Full
acceptance cannot be completed in the current environment because it requires a
real customer site, selected hardware, and unseen customer data. E6 is
therefore split into two phases:

- **E6-prep**: deliverables that require no real environment and can be built,
  tested, and merged now. These are the acceptance test matrix (section 6), the
  local automation runner (E6b), the acceptance report template (E6c), and the
  on-site execution plan with its runbook/checklist updates (E6d).
- **On-site acceptance**: a separate gated phase that executes the acceptance
  matrix, resilience and soak evidence, and metrics on real hardware and unseen
  customer data (E6d).

E6 cannot be declared complete without real hardware, unseen customer data, and
executed on-site resilience and soak evidence. No fabricated pass results are
ever recorded: a missing real-environment input is reported as `NOT_EXECUTED`,
never as a pass. This document is the source of truth for E6 and supersedes any
informal acceptance claims.

## 2. Scope and Non-Goals

### In scope

- E6a: the acceptance test matrix (section 6), covering behavior, resilience,
  performance, and stability assertions with an honest classification of what
  each item requires.
- E6b: `scripts/edge-acceptance-run.py`, a local automation runner that
  executes every locally automatable matrix item and emits a machine-readable
  evidence manifest; on-site items are emitted as `NOT_EXECUTED` with the
  required environment recorded.
- E6c: the edge acceptance report template
  `docs/design/28-edge-acceptance-report.md` with version/environment, matrix
  results, metrics, evidence links, deviations, risks, and sign-off fields.
- E6d: the on-site acceptance execution plan in [Runbook 15: Edge Acceptance
  Execution](../runbooks/15-edge-acceptance-execution.md) (a gated phase,
  recorded here but not executed in this environment).

### Out of scope

- Running on-site acceptance, capturing customer data, or producing final
  metrics: gated on hardware and unseen customer data (E6d).
- The central server (ingestion API, PostgreSQL, object storage, manual review):
  not implemented and intentionally out of scope until the Edge gates pass.
- Claiming a universal accuracy guarantee or adopting metrics without measured
  evidence: only measured results with numerators, denominators, and confidence
  treatment are reported (design 22.7, contract 10).
- Model training, threshold tuning, or rule selection using acceptance data
  (design 26.4).

## 3. Safety Invariants

The following invariants are mandatory in every E6 change and test:

1. Never return `OK` when inspection evidence is incomplete, invalid, or
   unverifiable; incomplete evidence maps to `NG` or the adopted
   uncertain/manual path according to policy (design 11, 22.6).
2. A missing real-environment input (hardware, unseen customer data, central
   server) is reported as `NOT_EXECUTED` with the required environment
   recorded, never as a pass and never as `OK`.
3. No claim of 100% accuracy is ever made; only measured recall and
   false-negative results are reported (design 22.7, contract 10).
4. Acceptance data is never used for training, threshold tuning, checkpoint
   selection, or rule selection before the acceptance run (design 26.4).
5. Original AI decisions are preserved unchanged during human review;
   corrections are stored separately and never overwrite the original decision
   (design 24, contract 10 §5).
6. Evidence is immutable or checksum-protected and linked through the
   inspection identifier (design 26.6).
7. A backup is not considered operational until a representative restore has
   succeeded (design 20.10).
8. On-site execution never deletes or alters evidence, pending uploads, or
   database records needed for traceability (design 20.11).

## 4. Required Decisions Before On-Site Acceptance

The following decisions remain open and are recorded as such in the acceptance
report until the customer and supplier agree. They are not invented here
(design 22.13, 26.11):

- Customer TLS termination choice: edge-service local TLS vs. an existing
  factory reverse proxy, and certificate source and rotation owner (design
  20.6, contract 08).
- Backup destination, schedule, retention, and restore RPO/RTO agreed with the
  customer; exact frequencies are acceptance decisions (design 20.10).
- Hardware device mapping: camera vendor/SDK and device paths, GPU device(s),
  and the trigger interface required at the customer site (design 20.2,
  20.13).
- Acceptance thresholds: primary NG recall target, allowed false negatives and
  the escalation/retest policy, false-positive and manual-review expectations,
  and the statistical confidence method and handling of `UNCERTAIN` and
  inconclusive ground truth (design 26.3).
- Barcode standard and the expected handling of unreadable and unknown codes
  (design 22.13, 26.11).
- Conveyor speed, expected throughput, latency budget, duty cycle, and
  long-running test duration (design 22.9, 26.11).
- Ground-truth owner, adjudicators, witnesses, signatories, and retest
  responsibility (design 26.3, 26.11).

## 5. Delivery Pipeline

Each gate is independently reviewable.

### E6a: Acceptance Test Matrix

The complete mandatory matrix is in section 6. It is the single source of
truth for what E6 must demonstrate, what is locally automatable, and what is
gated on hardware, customer data, or the central server.

**Exit criteria**

- Every scenario required by design 26.5 and 22.8 appears with a classification
  and a local runner coverage answer; no required scenario is silently
  automated-local when it needs a real environment.

### E6b: Local Automation Runner

**Implementation**

- `scripts/edge-acceptance-run.py` locks the application, product-model,
  component-model, rule, and configuration artifacts supplied through
  `--artifact`, plus the acceptance manifest supplied through
  `--acceptance-manifest`, before execution. A missing required artifact makes
  the run incomplete and nonzero rather than successful.
- The runner executes explicit targeted pytest assertions for every runnable
  behavior matrix row, records every matrix row in its evidence manifest, and
  records the assertions and locked-artifact checksums for each executed row.
- For every matrix item, emit a machine-readable evidence manifest entry
  containing: matrix ID, scenario, status, required environment when not
  executed, executed assertions, evidence links, timestamps, and artifact
  checksums.
- Never emit `PASS` for an item whose required environment is unavailable or
  whose local execution is unsupported; record it as `NOT_EXECUTED` or
  `INCOMPLETE`, with the missing input or limitation (hardware, customer data,
  central server, or unsupported local capability).
- Where a scenario combines a locally automatable behavioral assertion with a
  gated acceptance metric, record the behavioral assertion as executed and the
  acceptance item itself as `NOT_EXECUTED`.

**Exit criteria**

- The runner completes against the current repository without external
  hardware, customer data, or central services, and records every matrix row.
  Hardware/customer/central items and unavailable or unsupported local items
  are `NOT_EXECUTED` or `INCOMPLETE`, never `PASS`.
- Tests cover the runner's manifest emission; the manifest schema is typed and
  versioned.

### E6c: Edge Acceptance Report Template

**Implementation**

- Add `docs/design/28-edge-acceptance-report.md` with fields for:
  - release and environment: application, model, rule, and configuration
    versions and checksums, hardware, camera, network, and device ID;
  - matrix results: one row per matrix ID with status and evidence link;
  - metrics: NG recall, false-negative rate, false-positive rate,
    per-component recall, per-product recall, product-detection success,
    ROI-generation success, barcode-read success, average and P95 latency,
    throughput, upload delay segmented by connectivity, review rate, and
    stability, each with numerator, denominator, and confidence treatment
    (design 26.7, contract 10);
  - evidence links, deviations, residual risks, and sign-off with roles and
    residual-risk approval (design 26.8 step 10).
- Any metric without customer data is recorded as `NOT_MEASURED`, never as a
  zero, a placeholder, or a pass.

**Exit criteria**

- MkDocs strict passes with the new design document; the template is
  cross-referenced from the runbook/checklist updates and this task.

### E6d: On-Site Acceptance Execution Plan

This is the gated phase; it cannot run in the current environment. The
procedure follows design 26.8:

1. Approve the acceptance protocol, domain, roles, target-setting method, and
   stop conditions; record the section 4 decisions as resolved or explicitly
   open.
2. Verify camera mount, focus, exposure, lighting, edge hardware, time
   synchronization, disk capacity, and network setup; record the device
   mapping.
3. Lock and checksum the application/model/rule/configuration artifacts and the
   acceptance manifest.
4. Run calibration and smoke cases without using acceptance outcomes to tune
   the locked candidate.
5. Execute randomized or production-representative cases under witness,
   recording all evidence.
6. Exercise offline, recovery, restart, and duration (soak) scenarios.
7. Reconcile product counts, duplicate and missing inspections, media, logs,
   and upload receipts.
8. Adjudicate only predeclared inconclusive cases without changing original
   records.
9. Produce segmented metrics and compare them with the jointly approved
   protocol.
10. Record approval, restricted approval, remediation/retest, or rejection with
    signatures and residual risks.

If a release-blocking problem is found, preserve the run; remediation creates a
new candidate version and a controlled rerun, and historical failures are not
overwritten (design 26.8).

**Exit criteria**

- [Runbook 15: Edge Acceptance Execution](../runbooks/15-edge-acceptance-execution.md)
  and the [edge acceptance report template](../design/28-edge-acceptance-report.md)
  are executable from this plan; no E6-prep gate is blocked by E6d, and E6 is
  not declared complete until E6d has produced executed on-site evidence.

## 6. Mandatory Test Matrix

Column semantics: Classification is the strictest environment an acceptance run
requires (`automated-local`, `hardware-required`, `customer-data-required`,
`central-required`). Local runner coverage is `yes` when the runner executes
the matrix row's explicit targeted pytest assertion or Docker restart check;
the evidence manifest records the exact assertion, so a skipped or failed
assertion can never yield `PASS`. Otherwise it is `no` and the runner emits
`NOT_EXECUTED` with the required environment. Power loss, real barcode decode,
real camera disconnect, GPU/accelerator failure, long soak, and any
customer-data scenario are never `automated-local`.

| ID | Scenario | Required assertions/behavior | Classification | Local runner coverage | Notes |
|---|---|---|---|---|---|
| E6-A1 | Product type (each applicable) | Correct product mapping, applicable versioned rule, component-level result; segmented per-type metrics | customer-data-required | no | Metrics and acceptance evidence require unseen customer data |
| E6-A2 | Each missing component | NG or adopted uncertain/manual path, correct missing reason and evidence | customer-data-required | no | Staged cases at the customer line; staged vs naturally occurring defects reported separately (22.10) |
| E6-A3 | Missing manual | Missing-manual reason and traceability | customer-data-required | no | Document-presence case (26.5) |
| E6-A4 | Barcode failure | No unverified OK under wrong, unknown, or unreadable product mapping | hardware-required | no | Real barcode decode required (22.5); local mocks are not acceptance evidence |
| E6-A5 | Product-position shift | Usable ROI or explicit NG/uncertain/error; no fixed-coordinate assumption | customer-data-required | no | Requires unseen captures across the approved operating range |
| E6-A6 | Normal production variation | Segmented quality and latency results representative of the domain | customer-data-required | no | Representative production flow |
| E6-A7 | Consecutive OK products | One correct inspection per product; no duplicate or frame mixing | customer-data-required | no | Operational-flow metrics require customer production sequences |
| E6-A8 | Consecutive NG products | One correct inspection per product with reasons; sustained review and upload | customer-data-required | no | Operational-flow metrics require customer production sequences |
| E6-A9 | Mixed product types | Correct versioned rule per physical product | customer-data-required | no | Requires customer mixed-product production sequences |
| E6-A10 | No product | Explicit no-product handling or no window opened; never a fabricated OK | automated-local | yes | Deterministic no-product frames (22.6) |
| E6-A11 | Multiple products | Window integrity: explicit NG or error rather than mixed evidence | automated-local | yes | Multi-product fixture (22.6) |
| E6-A12 | Offline operation | Local inspection, evidence, and durable queue continue without central | automated-local | yes | Central independence (ADR-001, 22.8) |
| E6-A13 | Network outage | Local decisions continue; queue persists; no data loss | automated-local | yes | Blocked endpoint simulation |
| E6-A14 | Repeated network disconnect (flap) | No central round trip; queue persists; backoff with jitter and the circuit breaker bound traffic; no data loss or duplicate uploads; backlog drains | automated-local | yes | Oscillating connectivity (22.8) |
| E6-A15 | Central outage | Backoff with jitter; no decision blockage | automated-local | yes | Edge-side behavior; end-to-end central reconciliation is central-required once central exists |
| E6-A16 | Duplicate upload idempotency | One central inspection and consistent receipt per idempotency key | central-required | no | Edge replay against a sink is locally exercised; verified central receipt requires the not-yet-implemented central server |
| E6-A17 | Application restart | No fabricated OK or duplicate; incomplete window handled explicitly; state recovered | automated-local | yes | Restart during capture, decision, and upload states |
| E6-A18 | Power loss | Database and queue recovery; ambiguous window not marked OK; no evidence loss | hardware-required | no | Kill of host/process in selected states; needs a hardware environment (22.8) |
| E6-A19 | Disk full/pressure | Alert, safe cleanup, pause before traceability is lost; NG evidence persists | automated-local | yes | Quota or filled test volume (22.8) |
| E6-A20 | GPU/accelerator failure | No fabricated OK; a recoverable failure reloads or switches to a validated CPU runtime with the same manifest and records the switch; a non-recoverable failure faults and blocks inspection | hardware-required | no | Recovery path has unit coverage; a real accelerator failure needs hardware (22.8, design 09.7) |
| E6-A21 | Database failure/corruption | Fail safely, preserve diagnostics, execute the tested restore path | automated-local | yes | Disposable test database (22.8) |
| E6-A22 | Backup + restore | Representative restore succeeds; pending evidence and upload tasks survive | automated-local | yes | Not operational until a restore succeeded (20.10) |
| E6-A23 | Container restart | Supervisory recovery without a duplicate product decision | automated-local | yes | Requires Docker; run where available |
| E6-A24 | Clock drift | Preserve monotonic ordering and correlation; alert on drift | automated-local | no | Requires a dedicated clock-drift harness; until then the runner records `NOT_EXECUTED` |
| E6-A25 | Checksum failure | Reject the artifact and retain the recoverable task or version | automated-local | yes | Altered media or package bytes (22.8) |
| E6-A26 | Long-running soak | No unbounded resource, file-descriptor, or queue growth; no data loss; stable latency within customer-agreed limits | hardware-required | no | Duration and workload agreed from actual operating patterns (22.9) |
| E6-A27 | Camera disconnect | No fabricated OK; alarm, reconnect, and recover safely | hardware-required | no | Real device removal; simulator-based reconnect covered by the adapter conformance suite (22.5) |

## 7. Mandatory Evidence Requirements

Every executed test preserves (design 26.6, contract 10 §6):

- Inspection result and reason codes.
- Original and selected image evidence, plus annotated/ROI evidence as
  configured.
- Ground truth and adjudication provenance.
- Application, model, rule, product-configuration, and review-policy versions
  and checksums.
- Source and receive timestamps and the device identifier.
- Barcode and product mapping result.
- Relevant structured logs, health events, and stage timings.
- Upload task and central receipt/checksum where synchronization is in scope.
- Reviewer outcome where human verification is part of the procedure.

Evidence is immutable or checksum-protected and linked through the inspection
identifier. `NOT_EXECUTED` entries record the required environment instead of
evidence. Reported metrics include numerator, denominator, excluded and
inconclusive counts, confidence interval where meaningful, and segmentation by
release version (design 26.7).

## 8. Merge and Release Gates

- Focused changes with typed interfaces and typed, versioned Pydantic
  manifests.
- Regression tests for every changed safety invariant.
- Passing mandatory quality commands: `ruff check`, `ruff format --check`,
  `mypy`, `pytest`, `mkdocs build --strict`, `pnpm -r build/lint/test`, and
  edge-web e2e.
- The edge acceptance report is issued only after on-site evidence exists; a
  template or prep-only state never reads as accepted.
- A backup is not considered operational until a representative restore has
  succeeded (design 20.10).

## 9. References

- [Customer Acceptance](../design/26-customer-acceptance.md), sections
  26.3-26.8.
- [Testing and Quality Assurance](../design/22-testing-and-quality-assurance.md),
  sections 22.7-22.9.
- [Contract 10: Model, Rule Release, and Acceptance](../contracts/10-model-rule-release-and-acceptance.md).
- [Deployment and Operations](../design/20-deployment-and-operations.md),
  section 20.10.
- [E5: Deployment and Security](E5-deployment-and-security.md).
- [Runbook 15: Edge Acceptance Execution](../runbooks/15-edge-acceptance-execution.md).
- [Edge acceptance report template](../design/28-edge-acceptance-report.md).
- `scripts/edge-acceptance-run.py` (local automation runner emitting the
  evidence manifest).
- [Full project context](../ai/context.md), section 9 (open items and current
  status).
