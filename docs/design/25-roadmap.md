# 25. Implementation Roadmap

## 25.1 Purpose and Planning Principles

This roadmap sequences AssemblyVision implementation by technical dependency and risk. Dates are planning targets, not guarantees. Camera/SDK access, production data, customer decisions, and hardware availability can change timing. Quality evidence takes precedence over nominal feature completion.

## 25.2 Scope Boundaries

- **Static train-and-inspect MVP:** X-AnyLabeling YOLO labels through product/component training, static two-stage inspection, rule decisions, traceable output, and held-out verification.
- **One-month target:** first integrated edge and central capability suitable for controlled customer-site evaluation, not unrestricted production autonomy.
- **Production target:** hardened offline operation, governed releases, security, observability, acceptance evidence, and support readiness.
- **Future scope:** Kubernetes centrally, Tauri wrapper, PLC/MES integration, advanced fleet management, automated retraining, and multi-angle optimization.

## 25.3 Preconditions

Before implementation, obtain representative static images, X-AnyLabeling product and component box labels in YOLO format, draft product/component rules, a class mapping, permitted development data, a separate held-out fixture set with filename `OK` or `NG` ground truth, and access to the developer Apple Silicon Mac with 16 GB memory. Name owners for ground truth, camera mechanics, network/security, and acceptance. Unknowns are tracked explicitly rather than encoded as defaults.

## 25.4 Static Train-and-Inspect MVP

### 25.4.1 Foundation and Dataset Preparation

1. Establish one root `uv` workspace with `edge-service`, a developer-only `training` distribution, and shared `domain` and `vision-core` packages; defer TypeScript workspace setup.
2. Validate the X-AnyLabeling YOLO export layout, class order, image/label basename pairing, normalized bounds, and leakage-safe train/validation grouping.
3. Implement folder image input, deterministic output naming, model-manifest generation, and focused tests for image errors, ROI clipping, coordinate mapping, and serialization.
4. Train a small full-frame product detector on the developer hardware and record model metadata, class mapping, artifact checksum, and training configuration.
5. Generate product ROIs for component training images, crop them, map component boxes into ROI coordinates, and validate round trips and out-of-ROI handling.

### 25.4.2 Train, Inspect, and Verify

1. Train a component detector on prepared ROI images and produce a versioned, checksummed manifest.
2. Replace static detector stubs with real Ultralytics product and component adapters; preserve deterministic single-product selection, ROI mapping, and failure reason codes.
3. Define a minimal versioned product rule listing required components, evaluate presence deterministically, and produce `OK` or `NG` plus reasons.
4. Save annotated full image, annotated ROI where useful, component evidence, model/rule versions, and JSON results.
5. Provide `av-train` commands for product training, component-dataset preparation, and component training; provide `assemblyvision inspect` for one image/folder and `assemblyvision verify` for machine-readable held-out reports.
6. Run the held-out static fixture suite and report NG recall, false negatives, false positives, per-component support, and documented limitations.

### 25.4.3 Explicit Exclusions

Camera SDK, live video, temporal aggregation, barcode implementation, local service/dashboard, central server, authentication, production deployment, PLC/MES integration, automated retraining, model encryption, and `.pyc`-only runtime packaging are not part of this MVP. Training code remains developer-only and is not included in any runtime distribution.

### 25.4.4 Exit Evidence

The training and inspection flow is repeatable from a locked labeled dataset; failures are explicit; full-frame-to-ROI transforms are test-covered; output identifies dataset, model, and rule versions; and held-out verification reports decision metrics. This proves a static training-to-inspection flow, not production accuracy, timing, or operational readiness.

## 25.5 One-Month Controlled Integration Demonstrator

This is a multi-stream target for a small team with camera, model, data, and site access already
available. It is not a promise of production acceptance. The scope is intentionally limited to one
product family, one camera, one window mechanism, one barcode path, and one central ingestion path.

### 25.5.1 Week 1: Inspection Core and Baseline

- Stabilize the labeled train-and-inspect baseline: dataset validation, product training, ROI component-dataset preparation, component training, real detector adapters, deterministic rules, schemas, CLI, and held-out verification.
- Establish leakage-safe dataset manifests, locked regression sets, and reproducible model manifests.
- Profile training and inference on the developer Apple Silicon hardware if available.

Dependencies: representative images, initial product/component definitions, candidate models. Risks: insufficient NG examples and model fit.

### 25.5.2 Week 2: Edge Acquisition and Persistence

- Integrate the selected camera adapter and trigger/window prototype. The
  `FrameSource` abstraction (ADR-013) ships first with simulated sources
  (folder, video, OpenCV local/virtual device, RTSP, HTTP-image) so the
  acquisition path is developed and tested without camera hardware; the vendor
  SDK adapter then implements the same protocol.
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
Labeled static data and product rules
  -> dataset validation and baseline models
  -> static train-and-inspect pipeline
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
| Static train-and-inspect complete | Validated YOLO labels, reproducible product/component artifacts, deterministic fixtures, reason codes, version traceability, held-out verification report |
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
- [ADR-011: Labeled Train-and-Inspect MVP](decisions/ADR-011-labeled-train-and-inspect-mvp.md)
