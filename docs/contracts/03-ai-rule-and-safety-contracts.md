# 03. AI, Rule Engine, and Fail-Safe Contracts

## 1. Detector Responsibilities

A detector is responsible only for:

- Receiving an image
- Running inference
- Returning structured detections

A detector must not:

- Decide `OK` or `NG`
- Access databases
- Upload files
- Perform authorization
- Publish WebSocket events
- Implement business rules

## 2. Model Loading Contract

- Models must be loaded during process startup.
- Models must not be reloaded for every request.
- Model versions must be queryable.
- Model classes must match the Model Manifest.
- Model checksums must be verifiable.
- A failed model load must make the service unavailable for inspection.
- The system must never return a default `OK` after a model-loading failure.

## 3. Inference Traceability

Each inference must record at least:

- Model name
- Model version
- Input size
- Inference latency
- CPU or GPU device
- Detection class
- Confidence
- Bounding box
- Timestamp

## 4. Rule Engine Contract

The Rule Engine must:

- Be deterministic
- Produce the same result for the same input
- Remain independent from FastAPI
- Remain independent from the database
- Remain independent from YOLO
- Remain independent from environment-variable access

Inputs may include:

- Product type
- Required-component configuration
- Aggregated component evidence
- Rule version
- Barcode status
- Frame-quality status

Outputs include:

- `OK`
- `NG`
- `UNCERTAIN`
- Missing components
- Low-confidence components
- Reason codes
- Rule version

## 5. Fail-Safe Principle

The following states must never produce `OK`:

- Model unavailable
- Empty image
- Product not found
- Invalid ROI
- Unknown product type
- Missing rule
- No usable frames
- Severe image blur
- Inspection timeout
- Incomplete result data
- Barcode failure when a barcode is mandatory

Default behavior:

```text
Unable to reliably confirm completeness
→ NG or UNCERTAIN
```

Forbidden behavior:

```text
exception
→ catch
→ return OK
```

## 6. Temporal Aggregation

- Business decisions are made per physical product, not per frame.
- Evidence must be aggregated per component.
- Whole-product majority voting is forbidden as the primary decision rule.
- Policies may accept one high-confidence detection or repeated medium-confidence detections.
- A single low-confidence detection must not automatically prove presence.
- No usable frames must never result in `OK`.

## 7. Two-Stage Detection Contract

```text
Full frame
→ Product Detector
→ Product Bounding Box
→ ROI Engine
→ Component Detector
→ Temporal Aggregator
→ Rule Engine
```

Responsibility boundaries:

- Product Detector locates the product.
- ROI Engine crops and preserves coordinate mappings.
- Component Detector estimates component presence.
- Rule Engine produces the final business decision.

## Related Documents

- [AI Detection Pipeline](../design/06-ai-detection-pipeline.md)
- [Product Detection and ROI](../design/08-product-detection-and-roi.md)
- [Component Detection](../design/09-component-detection.md)
- [Temporal Aggregation](../design/10-temporal-aggregation.md)
- [Rule Engine](../design/11-rule-engine.md)
- [Appendices - reason codes](../design/appendices.md#4-reason-code-glossary)
- [ADR-004: Two-Stage Detection](../design/decisions/ADR-004-two-stage-detection.md)
- [ADR-010: Per-Component Temporal Aggregation](../design/decisions/ADR-010-per-component-temporal-aggregation.md)
