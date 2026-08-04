# 25. Implementation Roadmap

## 25.1 Purpose and Planning Principles

This roadmap sequences AssemblyVision implementation by technical dependency and risk. Dates are planning targets, not guarantees. Camera/SDK access, production data, customer decisions, and hardware availability can change timing. Quality evidence takes precedence over nominal feature completion.

## 25.2 Scope Boundaries

- **Two-day MVP:** static images from a folder through two-stage detection, rules, JSON, ROI, and annotated output.
- **One-month target:** first integrated edge and central capability suitable for controlled customer-site evaluation, not unrestricted production autonomy.
- **Production target:** hardened offline operation, governed releases, security, observability, acceptance evidence, and support readiness.
- **Future scope:** Kubernetes centrally, Tauri wrapper, PLC/MES integration, advanced fleet management, automated retraining, and multi-angle optimization.

## 25.3 Preconditions

Before implementation, obtain representative camera images, draft product/component rules, runnable model artifacts, class mappings, permitted development data, a small held-out fixture set, and access to candidate edge hardware. Name customer owners for ground truth, camera mechanics, network/security, and acceptance. The two-day clock starts only after this readiness gate passes; unknowns are tracked explicitly rather than encoded as defaults.

## 25.4 Two-Day Static-Image MVP

### 25.4.1 Day One

1. Establish one Python workspace/project and the Ruff, MyPy, and Pytest commands needed by the static spike; defer TypeScript workspace setup.
2. Implement folder image input and deterministic output naming.
3. Load the product detector and record model metadata.
4. Detect the product, expand/clip its bounds, and save the mapped ROI.
5. Serialize initial inspection/frame/ROI JSON with failure reason codes.
6. Add focused tests for image errors, no-product behavior, ROI clipping, and serialization.

### 25.4.2 Day Two

1. Load the component detector against the product ROI.
2. Define a minimal versioned product rule listing required components.
3. Evaluate component presence deterministically and produce `OK` or `NG` plus reasons.
4. Save annotated full image, annotated ROI where useful, component evidence, and versions.
5. Provide a CLI for one image/folder and machine-readable exit/report behavior.
6. Run the initial held-out static fixture suite and document limitations.

### 25.4.3 Explicit Exclusions

Camera SDK, live video, temporal aggregation, barcode implementation, local service/dashboard, central server, authentication, production deployment, PLC/MES integration, and automated retraining are not part of this two-day MVP.

### 25.4.4 Exit Evidence

The pipeline is repeatable on supplied static images, failures are explicit, coordinate mappings are test-covered, outputs identify model/rule versions, and results can seed baseline evaluation. This proves software flow, not production accuracy.

## 25.5 One-Month Controlled Integration Demonstrator

This is a multi-stream target for a small team with camera, model, data, and site access already
available. It is not a promise of production acceptance. The scope is intentionally limited to one
product family, one camera, one window mechanism, one barcode path, and one central ingestion path.

### 25.5.1 Week 1: Inspection Core and Baseline

- Complete static pipeline, product detector adapter, ROI engine, component detector adapter, deterministic rule engine, schemas, CLI, and baseline evaluation.
- Establish leakage-safe dataset manifests and a locked regression set.
- Profile inference on candidate hardware if available.

Dependencies: representative images, initial product/component definitions, candidate models. Risks: insufficient NG examples and model fit.

### 25.5.2 Week 2: Edge Acquisition and Persistence

- Integrate the selected camera adapter and trigger/window prototype.
- Implement barcode reading as a separate capability and product-type resolution.
- Add SQLite schema/migrations, atomic media storage, recovery states, and retention safeguards.
- Add local FastAPI and a basic Vue dashboard for camera, latest result, health, and recent history.
- Add minimum pilot security: unique device credentials, TLS, one authenticated administrator role,
  protected inspection/media access, and audit of mutations.

Dependencies: camera/SDK/hardware, barcode samples/standard, operating environment. Risks: driver/container compatibility, exposure, trigger ambiguity.

### 25.5.3 Week 3: Video Robustness and Synchronization

- Implement product-window management and frame-quality filtering.
- Add per-component temporal aggregation and explicit ambiguous-window handling.
- Implement persistent idempotent upload queue, retry/backoff, checksums, and receipts.
- Add one central ingestion API, PostgreSQL schema, selected-media storage, basic inspection history,
  and a minimal review capture view. Defer generalized product/rule administration and analytics.

Dependencies: stable camera timestamps/window signal, network path, identity approach. Risks: frame mixing, duplicate inspection, queue pressure.

### 25.5.4 Week 4: Deployment, Resilience, and Site Evaluation

- Build non-root multi-stage Docker images, Compose profiles, Nginx configuration, volumes, health checks, and release manifests.
- Test the critical pilot subset: offline operation, restart recovery, retry/idempotency, duplicate
  upload, and protected-evidence cleanup. Full power-loss, disk-full, and soak matrices remain
  production gates.
- Add structured logs, edge health, central upload status, and a bounded audit trail.
- Execute a controlled customer-site baseline with unseen examples when access and ground truth are
  available; this is not final customer acceptance.
- Deliver runbooks required for the pilot paths; expand the complete runbook set before production.

Dependencies: site access, customer network/security decisions, acceptance cases and ground truth. Risks: late domain shift and insufficient test duration.

## 25.6 Production Hardening After the One-Month Target

The following work is driven by baseline findings rather than compressed into the first month:

1. Expand real production data by failed product/component strata and revalidate models.
2. Finalize acceptance thresholds and confidence treatment with the customer.
3. Expand pilot authentication into full role-based access, external identity where required,
   credential rotation, signed packages, vulnerability response, backups, and audit retention.
4. Prove long-running stability and restoration on production-equivalent hardware.
5. Validate camera-mount/exposure controls and change-detection procedures.
6. Establish release rings, rollback exercises, support ownership, and quality monitoring.
7. Reduce manual review only after production evidence supports it.

## 25.7 Dependency and Critical Path

```text
Production data and product rules
  -> baseline models
  -> static pipeline
  -> camera/barcode integration
  -> product-window identity
  -> temporal aggregation
  -> durable local decision
  -> delayed synchronization
  -> site resilience tests
  -> independent customer acceptance
  -> controlled production rollout
```

The camera/window identity path and representative NG data are the main critical-path risks. Central dashboards can progress in parallel but cannot compensate for unresolved edge decision integrity.

## 25.8 Delivery Gates

| Gate | Evidence required |
|---|---|
| Static pipeline complete | Deterministic fixtures, reason codes, artifacts, version traceability |
| Edge integration ready | Camera/barcode conformance, durable decision, restart recovery, health states |
| Connected pilot ready | Idempotent synchronization, central history/review, offline tests, access controls |
| Acceptance candidate | Locked artifacts, unseen customer dataset, complete evidence, runbooks |
| Production rollout | Customer-approved targets/results, rollback, monitoring, support and security readiness |

No gate uses an invented accuracy, latency, or availability number. Numeric criteria are added after representative baseline measurement and customer agreement.

## 25.9 Future Options

- PLC/conveyor sensor integration for stronger window boundaries.
- MES integration for product identity and disposition.
- Tauri wrapper when browser kiosk management is insufficient.
- Central Kubernetes deployment when service scale justifies operational complexity.
- Multi-angle or additional-line model adaptation after domain evaluation.
- Governed retraining automation after manual dataset/release governance is mature.

## 25.10 Open Questions and Validation Required

- Camera vendor/SDK, edge operating system/GPU, hardware delivery date, and container access method.
- Conveyor speed, trigger/window source, product spacing, and expected multiple-product behavior.
- Barcode standard, scanner/decoder choice, and authoritative product mapping source.
- Product types, required components, sample availability, and ground-truth ownership.
- Customer site/network availability, central location, security review, and deployment windows.
- Acceptance threshold-setting workshop, sample design, and permitted staged NG cases.
- Team size/skills and whether camera, frontend, MLOps, and site work can proceed in parallel.
- PLC/MES requirements and whether they alter the first production release.

## 25.11 Related Documents

- [Deployment and Operations](20-deployment-and-operations.md)
- [Testing and Quality Assurance](22-testing-and-quality-assurance.md)
- [Customer Acceptance](26-customer-acceptance.md)
- [ADR-009: Static-image-first MVP](decisions/ADR-009-static-image-first-mvp.md)
