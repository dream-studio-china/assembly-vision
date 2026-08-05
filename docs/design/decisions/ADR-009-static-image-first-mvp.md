# ADR-009: Static-Image-First MVP

## 1. Status

Accepted; superseded in part by [ADR-011: Labeled Train-and-Inspect MVP](ADR-011-labeled-train-and-inspect-mvp.md).

## 2. Context

The end system requires camera capture, live video, product windows, barcode, temporal aggregation, persistence, synchronization, and Web applications. Implementing all of these before validating core product/ROI/component/rule behavior would combine model, hardware, timing, state, and network uncertainty and make failures difficult to isolate.

## 3. Decision

Build a static-image MVP first. It reads one image or a folder, detects the product, generates and maps the ROI, detects components, evaluates a versioned deterministic rule, outputs `OK` or `NG` with reasons, and saves JSON, ROI, and annotated evidence through a CLI.

The MVP excludes camera SDK integration, real-time video, temporal aggregation, central services, full dashboards, authentication, PLC/MES integration, and automated retraining. Its interfaces and schemas should be reusable by later live acquisition rather than becoming an alternate production pipeline. The original training exclusion is superseded by ADR-011; all other exclusions remain in force.

## 4. Scope

This decision governs initial implementation sequence, not the final operational architecture. Static files also remain valuable as deterministic regression fixtures after live integration.

## 5. Consequences

### 5.1 Positive

- Validates the core two-stage and rule boundaries quickly.
- Produces inspectable deterministic artifacts for debugging and model evaluation.
- Decouples vision/data issues from camera/window/network issues.
- Establishes tests and schemas before asynchronous behavior is added.

### 5.2 Negative and Trade-offs

- Does not validate frame timing, camera SDK, motion blur, barcode, or product identity windows.
- Single-image results do not demonstrate temporal system robustness.
- Prototype success can be misinterpreted as production acceptance unless limitations are explicit.
- Some interfaces will evolve after real camera constraints are known.

## 6. Alternatives

- **Live camera first:** rejected because hardware/timing failures obscure basic model and rule behavior.
- **Central/dashboard first:** rejected because it does not reduce the core inspection risk.
- **Model notebook only:** rejected because it omits production-style schemas, rules, evidence, CLI, and tests.
- **Simulated video first:** useful after static flow, but unnecessary for the static-image objective.

## 7. Open Questions and Validation Required

- Availability and rights for representative static production images and missing-component examples.
- Initial model artifacts, classes, and product rules.
- How MVP outputs map to the final versioned inspection schema.

## 8. Links

- [Roadmap](../25-roadmap.md)
- [Testing and Quality Assurance](../22-testing-and-quality-assurance.md)
- [ADR-004: Two-stage detection](ADR-004-two-stage-detection.md)
- [ADR-011: Labeled Train-and-Inspect MVP](ADR-011-labeled-train-and-inspect-mvp.md)
