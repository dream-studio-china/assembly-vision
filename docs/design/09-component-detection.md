# 9. Component Detection

## 9.1 Responsibility

Stage two detects configured component classes within a valid product ROI from [product detection and ROI](08-product-detection-and-roi.md). It emits frame-level observations to [temporal aggregation](10-temporal-aggregation.md); it does not directly issue `OK` or infer an abstract global `missing_component` class.

## 9.2 Detection Model

Ultralytics YOLO is the initial implementation. Required classes may include `component_a`, `component_b`, `component_c`, and `manual`, but the actual taxonomy is product-configuration data. Barcode decoding remains a separate subsystem; YOLO may locate a barcode region but must not replace standards-based decoding.

Each model package contains:

- immutable version and SHA-256 checksum;
- weights and runtime format;
- class ID-to-name mapping;
- expected color space, dimensions, and letterbox policy;
- validated threshold ranges and compatible product-configuration schema versions;
- training/evaluation provenance and release status.

Loading fails if checksum, class mapping, runtime compatibility, or required configured classes do not validate.

## 9.3 Frame-Level Contract

For each valid ROI, return raw qualifying detections and normalized `ComponentDetection` records with component key, confidence, ROI box, full-frame box, visible-area estimate where available, frame ID, quality status, and model version. Preserve detections before business aggregation so thresholds can be audited.

```python
def detect_components(roi, required, manifest):
    predictions = model.predict(roi.image)
    observations = map_to_domain(predictions, roi.transform, manifest.class_map)
    return [
        item for item in observations
        if item.component_key in required
        and item.confidence >= required[item.component_key].observation_threshold
        and spatially_valid(item, required[item.component_key])
    ]
```

`observation_threshold` controls evidence collection and is not itself proof of presence. The aggregator applies the stronger per-component acceptance policy.

## 9.4 Product-Specific Spatial Constraints

Rules may define expected normalized zones, minimum box area, maximum box area, or allowed count for each component. These constraints reduce false matches but must tolerate measured production position and assembly variation. Coordinates are normalized within the generated product ROI, not the full frame.

When duplicate boxes refer to one physical component, model NMS handles overlap first. Business count constraints are evaluated later. If the rule requires exactly one manual and two are confidently detected, the evidence is contradictory and cannot produce `OK` without an explicit rule.

## 9.5 Configuration

```yaml
component_detection:
  model_version: component-yolo-1.0.0
  iou_threshold: 0.50
components:
  manual:
    observation_threshold: 0.45
    high_confidence: 0.85
    medium_confidence: 0.65
    expected_count: 1
    min_box_area_ratio: 0.02
    allowed_zone: [0.05, 0.10, 0.95, 0.90]
  component_a:
    observation_threshold: 0.50
    high_confidence: 0.90
    medium_confidence: 0.70
    expected_count: 1
```

Per-component settings are versioned with the rule/product configuration. Product windows pin both configuration and model version. Threshold changes require audit records and regression evaluation.

## 9.6 Evidence Semantics

- A qualifying detection is positive frame evidence for only its mapped component.
- No detection is absence of positive evidence, not proof by itself that the component is missing.
- A low-confidence observation is retained for diagnostics but cannot be promoted to present unless the temporal policy explicitly accumulates sufficient independent evidence.
- Rejected-quality frames provide no positive or negative evidence.
- Evidence for one component cannot compensate for another component.
- Unknown model classes are recorded and ignored for required-component satisfaction.

## 9.7 Failure Handling

Inference timeout, out-of-memory, malformed output, model process crash, transform failure, or version mismatch invalidates the affected frame. If required evidence cannot be established, the final result is `NG`. The implementation must never carry detections forward from another frame, ROI, product, or model invocation.

After a recoverable accelerator failure, the worker may reload or use a validated CPU runtime if configured. The fallback runtime must use the same manifest and be separately performance-tested; switching runtime is recorded. Server connectivity has no effect on local inference.

## 9.8 Performance and Concurrency

Keep model instances warm and bound concurrency to measured GPU/CPU capacity. Backpressure must be explicit. Optimize input size, runtime, or frame sampling only after measuring per-component NG recall; silently dropping frames to meet throughput is prohibited. Sampling must preserve the minimum valid-frame requirement and product-window identity.

## 9.9 Verification

- Unit-test class mapping, threshold boundaries, spatial constraints, counts, and coordinate conversion.
- Contract-test model manifests and incompatible package rejection.
- Evaluate precision and recall per component, product type, position, batch, and model version.
- Include intentionally missing components, difficult present components, empty ROIs, reflections, and occlusions.
- Split datasets by physical product, capture session, batch, or date, not adjacent video frames.
- Fault-inject timeout, OOM, malformed tensor, and worker restart; none may yield `OK` from incomplete evidence.
- Benchmark average/P95 inference latency and sustained throughput on deployment hardware.

## 9.10 Open Questions and Validation Required

- Define the exact component taxonomy, required counts, and product-type mappings.
- Determine which components need spatial constraints or additional OpenCV checks.
- Select model input size and runtime after edge-hardware benchmarking.
- Establish per-component observation, medium, and high-confidence thresholds from held-out production data.
- Collect sufficient real missing-component examples and confirm labeling guidance.
