# AssemblyVision Software Architecture: Cover and Status

## 1. Document Control

| Field | Value |
|---|---|
| System | AssemblyVision - Industrial Assembly Inspection System |
| Document set | Software architecture and implementation blueprint |
| Status | Draft for engineering validation |
| Architecture baseline | Edge-client and central-server architecture |
| Quality priority | Minimize false negatives, preserve traceability, then reduce false positives |
| Source of project facts | [docs/source-brief.md](../source-brief.md) |

This document set describes a proposed implementation. It does not claim that AssemblyVision is deployed, that image or barcode recording already exists, or that any accuracy target has been achieved. Production acceptance must be based on measured customer data that was not used for training.

## 2. Document Set

| Document | Purpose |
|---|---|
| [Introduction](01-introduction.md) | Business context, boundaries, principles, and readers |
| [Requirements](02-requirements.md) | Functional and quality requirements with identifiers |
| [Architecture Overview](03-architecture-overview.md) | System boundaries, deployment, data flow, and technology baseline |
| [Edge Client Architecture](04-edge-client-architecture.md) | Offline inspection runtime, local persistence, and edge operations |
| [Central Server Architecture](05-central-server-architecture.md) | Ingestion, fleet administration, review, reporting, and distribution |
| [Appendices](appendices.md) | Terminology, consistency rules, open questions, reason codes, and traceability conventions |

## 3. Scope Horizons and Status

The horizons are scope labels, not promises that calendar time alone establishes production readiness.

| Horizon | Intended result | Included | Explicitly excluded or deferred | Status |
|---|---|---|---|---|
| Two-day MVP | Prove static-image processing end to end | Folder input, product detection, generated ROI, component detection, deterministic rules, JSON, ROI and annotated image output, CLI, minimal tests | Camera SDK, video, temporal aggregation, central server, dashboards, authentication, PLC/MES, retraining | Defined; model artifacts and representative images required |
| One-month target | Demonstrate a controlled integrated pilot for one bounded product/camera path | Camera/barcode adapters, durable local decision, edge API/dashboard, product windows, aggregation, persistent upload queue, one central ingestion/history/review path, minimum pilot security, Compose, targeted resilience baseline | Generalized administration/reports, remote package delivery, final acceptance, full resilience/soak matrix, production guarantees | Proposed; requires ready hardware, models, data, and a small parallel team |
| Production target | Operate cautiously with measured acceptance | Hardened recovery, retention, audit, access control, configuration/model governance, observability, human review, release/rollback, production acceptance | Any claim of 100% accuracy | Requires validation and customer agreement |
| Future | Extend only after operational evidence | Model-package distribution, optional central Kubernetes, optional Tauri edge shell, justified edge PostgreSQL, integrations and automation | Not part of the initial commitment | Candidate scope |

## 4. Architecture Decisions in Force

1. Production-critical acquisition, inference, aggregation, rules, and final decisions execute on the edge industrial computer.
2. Loss of central connectivity must not stop inspection; local persistence and delayed synchronization are mandatory.
3. The first implementation processes static images before integrating camera/video paths.
4. Product detection creates the product ROI; component detection operates on that ROI. A hard-coded region may only be a coarse or fallback capture zone.
5. Required component presence is detected directly. The design does not depend on a generic `missing_component` model class.
6. Barcode decoding is a separate capability; object detection may locate a barcode but does not replace decoding.
7. Temporal evidence is aggregated per required component, not by whole-product majority vote.
8. The rule engine is deterministic and versioned independently of models.
9. `UNCERTAIN` is an internal decision state and always maps to business `NG`; uncertainty cannot produce `OK`.
10. Every persisted inspection identifies device, time, product type resolution, model versions, rule version, product-configuration version, evidence, decision, and reason codes.
11. The central server receives selected evidence, not every frame. Complete or rolling video remains local where policy requires it.
12. Runtime data, production media, secrets, and model weights are not stored in the Git repository.

The [Appendices](appendices.md#2-decision-consistency-checklist) contain the consistency checklist used when extending this set.

## 5. Quality and Acceptance Position

The engineering objective is high NG recall and an extremely low false-negative rate. Early rollout permits additional false NG outcomes because they can be reviewed manually. Overall accuracy alone is not an acceptable success measure; validation must report NG recall, false-negative and false-positive rates, per-component and per-product performance, barcode/product/ROI success, latency, throughput, and operational resilience.

No numerical acceptance threshold is defined here. Thresholds and confidence policies require baseline evaluation against segregated customer production data, including intentionally incomplete products and operational failure scenarios.

## 6. Ownership and Change Control

Architecture changes that affect edge autonomy, decision semantics, traceability fields, upload idempotency, or model/rule compatibility require explicit review across all affected documents. A change is complete only when requirements, diagrams, interfaces, state machines, reason codes, and trace links remain consistent.

Suggested document roles are:

- Product owner: business classification and review policy.
- Vision lead: datasets, model manifests, thresholds, and evaluation evidence.
- Edge lead: acquisition, decision path, local durability, and recovery.
- Platform lead: ingestion, identity, administration, and central operations.
- Customer operations representative: site constraints and acceptance approval.

These roles are responsibilities, not confirmed staffing facts.

## 7. Open Questions and Validation Required

1. Who approves requirements and production acceptance, and what change-control process will be used?
2. Which product types and component classes are in the first release?
3. What measured acceptance thresholds will be agreed after baseline evaluation?
4. Which target dates are commitments, and what hardware/site access is available before them?
5. Which data classifications, retention obligations, and customer policies apply?
6. Which items in the global list in [Appendices](appendices.md#3-global-open-questions) block the two-day MVP, one-month target, and production release?
