# AssemblyVision Introduction

## 1. Purpose

AssemblyVision is a conveyor-line computer-vision system intended to inspect completed products for the presence of required assembly components. Inspection targets may include the complete product, large components, a manual or instruction sheet, a barcode, and the product model or type.

For each physical product, the business result is:

- `OK`: all required components have sufficient valid evidence under the active rule.
- `NG`: a component is missing, evidence is uncertain, product identity cannot be resolved reliably, or inspection cannot be completed reliably.

The system prioritizes avoiding the release of defective or incomplete products incorrectly marked `OK`. It therefore favors conservative `NG` decisions and human review during early operation. This is an engineering objective, not an accuracy guarantee.

## 2. Confirmed Operating Context

The known environment comprises an approximately four-megapixel industrial camera, fixed lighting, a normally fixed camera, and a controlled inspection area. Products can shift slightly and are not perfectly registered, but large uncontrolled rotations are not normal. Current inspection concerns large parts and component presence rather than micro-components or tiny screws.

AssemblyVision must implement camera capture, barcode recognition, image/video persistence, and result persistence. These are required capabilities, not pre-existing factory services. The edge machine must continue inspecting when disconnected from the central server.

## 3. Stakeholders and Concerns

| Stakeholder role | Primary concerns |
|---|---|
| Line operator | Clear current status, conservative result, actionable reason, offline continuity |
| Quality reviewer | Evidence, version traceability, correction capture, searchable history |
| Factory support | Camera/device health, disk state, restart recovery, diagnostics |
| Vision engineer | Representative data, per-component metrics, model/config compatibility |
| Software engineer | Deterministic interfaces, testability, observability, deployability |
| Administrator | Device, product, rule, model, user, and permission governance |
| Business owner | High NG recall, controlled rollout, measurable acceptance |

The roles describe required viewpoints and do not assert the customer's organization structure.

## 4. System Boundaries

AssemblyVision includes:

- Edge acquisition, barcode decoding, product-type resolution, two-stage detection, optional OpenCV checks, temporal aggregation, deterministic rules, local API/dashboard, local persistence, health monitoring, and synchronization.
- Central ingestion, centralized history, fleet and configuration management, reporting, manual review, audit, and later model-package distribution.
- Training and evaluation workflows that produce versioned model manifests and validation reports, while remaining outside the production decision path.

The central server is not in the real-time decision path. Physical conveyor actuation, PLC/MES behavior, camera hardware selection, and factory network operation are external unless later integrations explicitly bring them into scope. The documentation does not assume that an `NG` result automatically stops or diverts a product.

## 5. Architectural Principles

### 5.1 Safety-Biased Decisions

Only complete, valid, sufficiently strong evidence may yield `OK`. Missing, stale, mixed, low-quality, unresolved, or incompatible evidence yields internal `UNCERTAIN` or `NG`; internal `UNCERTAIN` always maps to business `NG`.

### 5.2 Edge Autonomy

Inspection must not wait for central APIs. Configuration and model packages used by the decision path are installed and validated locally before activation. Upload is asynchronous and recoverable.

### 5.3 Evidence and Reproducibility

Results retain enough structured evidence and immutable version identifiers to explain which inputs, models, configurations, and rules produced a decision. Media storage follows explicit retention policy and must not be treated as the sole record.

### 5.4 Deterministic Policy Around Probabilistic Models

Models provide detections and confidence values. A separately testable, deterministic rule engine applies approved thresholds and required-component policy. Temporal aggregation improves system robustness by combining frame evidence; it does not improve a model's inherent single-frame accuracy.

### 5.5 Incremental Delivery

The implementation starts with a labeled static-image train-and-inspect vertical slice, then adds physical acquisition and local durability, then synchronization and central workflows, and finally production hardening based on measured evidence.

## 6. Scope by Horizon

### 6.1 Static Train-and-Inspect MVP

X-AnyLabeling produces YOLO product and component box labels. A developer-only training CLI trains full-frame product and ROI component models, while the static-image runtime CLI consumes their manifests, inspects a separate folder, evaluates rules, and writes JSON, ROI images, annotated images, and a held-out verification report. It establishes schemas and deterministic behavior without camera, video, central services, or dashboards. Training code is not part of the runtime distribution.

### 6.2 One-Month Target

The target connects a camera and barcode decoder, creates one inspection record per physical product window, persists locally, exposes a local FastAPI/Vue interface, aggregates frame evidence per component, and uploads selected records/evidence to an initial central service. Docker Compose packaging, offline testing, retry, retention, health, and customer-site evaluation are included.

### 6.3 Production Target

Production adds validated operational limits, access control, tamper-evident audit history where required, package approval and rollback, robust disk/power/clock handling, monitored service objectives, review workflows, documented support runbooks, and customer acceptance using held-out production data.

### 6.4 Future

Potential extensions include central model distribution, optional Kubernetes for central scale, a Tauri edge wrapper, PLC/MES integration, justified PostgreSQL at larger edge installations, and retraining automation with explicit approval gates. They must not complicate the MVP without evidence of need.

## 7. Reading Guide

Start with [Requirements](02-requirements.md), then [Architecture Overview](03-architecture-overview.md). Implementation teams should use [Edge Client Architecture](04-edge-client-architecture.md) and [Central Server Architecture](05-central-server-architecture.md). Shared terminology, reason codes, trace conventions, and unresolved decisions are in [Appendices](appendices.md).

## 8. Assumptions

- The inspection environment remains controlled enough to evaluate a fixed-angle model; a significant camera-angle change requires revalidation.
- A reliable method for delimiting physical products can be integrated, but its mechanism is not yet selected.
- Local storage can be provisioned for the agreed retention/upload policy.
- Representative production examples, including intentionally missing components, can be collected under an approved safety process.
- Human review is available during cautious rollout; its staffing and workflow are not yet confirmed.

These assumptions are validation items, not factory facts.

## 9. Open Questions and Validation Required

1. What products, required components, and product-to-rule mappings define the first release?
2. Which physical event delimits an inspection window: sensor, trigger, barcode, tracking, zones, timeout, or a validated combination?
3. How is an `NG` business result consumed operationally, and is automatic line actuation in scope?
4. What camera, barcode hardware/standard, compute hardware, operating system, and accelerator are available?
5. What are the measured cycle time, field of view, blur/exposure limits, and acceptable decision latency?
6. Who performs review and sample audits, and how are corrected labels approved for training?
7. What security, privacy, retention, and hosting constraints apply?
8. See the consolidated [Global Open Questions](appendices.md#3-global-open-questions).
