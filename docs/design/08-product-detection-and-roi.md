# 8. Product Detection and ROI

## 8.1 Responsibility

Stage one locates the complete product in the full camera frame and generates the normalized input region for [component detection](09-component-detection.md). It handles modest positional variation without assuming a perfectly fixed product location. It does not determine component presence or the final `OK`/`NG` result.

## 8.2 Scope

| Scope | Behavior |
|---|---|
| Static-image MVP | YOLO product detector, confidence filtering, one-product selection, margin expansion, clipped crop |
| Production target | Frame-quality integration, optional tracking identity, geometric plausibility checks, per-frame ROI metadata |
| Future | Validated orientation/perspective normalization and multiple-product tracking |

A configured full-frame capture zone may reject irrelevant areas or provide diagnostics, but it is not the final product ROI. A hard-coded final ROI is not acceptable unless a separate deployment validation proves product position is mechanically constrained.

## 8.3 Product Detection Contract

Input is a valid full-resolution frame and pinned model manifest. Output contains all candidate detections after non-maximum suppression, the selected product or failure, and diagnostics. The manifest defines class mapping, input size, preprocessing, confidence threshold limits, checksum, and model version.

Selection is deterministic:

```text
candidates = detections matching configured product classes
candidates = candidates passing confidence, size, and capture-zone constraints
if count(candidates) != 1:
    return failure(NO_PRODUCT or MULTIPLE_PRODUCTS)
selected = highest confidence, then largest area, then stable coordinate order
return selected
```

The tie-breakers make replay stable; they do not make multiple plausible products safe. If more than one candidate passes inspectability constraints, production behavior is `NG` unless a validated tracker assigns exactly one candidate to the current window.

## 8.4 ROI Generation

Given product box `(x1, y1, x2, y2)`, apply configurable fractional or pixel margins, then clip to `[0, width] x [0, height]`. Reject zero-area, undersized, excessively clipped, or implausible aspect-ratio results. Record both boxes and the affine translation between spaces.

```python
expanded = expand(product_box, margin_x, margin_y)
clipped = clip(expanded, frame_width, frame_height)
if clipped.area < min_roi_area or clipped_retention(expanded, clipped) < min_retention:
    return ROIResult.invalid("ROI_OUT_OF_BOUNDS")
roi = frame[clipped.y1:clipped.y2, clipped.x1:clipped.x2]
return ROIResult(roi=roi, full_frame_box=clipped, offset=(clipped.x1, clipped.y1))
```

Mapping an ROI detection back to the full frame adds the ROI offset to both corners. If resize/letterbox preprocessing is used, reverse padding and scale before applying that offset. Persist enough transform metadata to reproduce overlays exactly.

## 8.5 Optional Normalization

Orientation or perspective normalization is disabled by default. Enable it only when landmarks or segmentation boundaries are reliable and validation demonstrates improved NG recall without hiding defects. Store the forward and inverse transform matrices. A failed normalization invalidates that frame rather than falling back silently to a geometrically different inference path.

## 8.6 Configuration

```yaml
product_detection:
  model_version: product-yolo-1.0.0
  allowed_classes: [product]
  confidence_threshold: 0.70
  iou_threshold: 0.50
  max_inspectable_products: 1
  min_box_area_ratio: 0.15
roi:
  margin_x_ratio: 0.05
  margin_y_ratio: 0.05
  min_area_pixels: 250000
  min_expanded_area_retained: 0.90
  normalize_perspective: false
```

Thresholds are starting configuration only. They require model-version-specific validation and configuration versioning. Runtime code must reject thresholds outside centrally governed safe ranges.

The M1 static pipeline accepts `model_version`, `confidence_threshold`, and
`iou_threshold` for the product detector; `allowed_classes`,
`max_inspectable_products`, and the product-level `min_box_area_ratio` shown
above are deferred to the windowed production pipeline (AUDIT-001).

## 8.7 Failure Semantics

| Condition | Result |
|---|---|
| No qualifying product | Frame unusable; product becomes `NG` if no sufficient valid frame exists |
| Multiple qualifying products | Frame/window ambiguous and `NG` unless validated tracking resolves it |
| Product confidence below threshold | No positive product evidence; never assume fixed location |
| Box clipped beyond tolerance | Invalid ROI |
| Empty/corrupt crop or transform error | Invalid ROI and structured error |
| Model unavailable or class map mismatch | Detector not ready; affected inspection `NG` |

Previous-frame boxes may guide tracking but cannot be reused as current positive detection after tracking confidence expires.

## 8.8 Observability and Artifacts

Persist selected and rejected boxes, confidence, class, ROI box, clipping ratio, transform, model version, inference latency, and reason codes. Annotated images must distinguish full-frame product boxes from ROI component boxes and must not overwrite raw evidence.

## 8.9 Verification

- Unit-test expansion, clipping, resize reversal, coordinate round trips, and boundary pixels.
- Test empty frames, partial products, two products, reflections, occlusion, and position extremes.
- Evaluate product-detection recall and ROI-generation success separately by product type and position range.
- Verify model manifest checksum and class-map incompatibility prevent readiness.
- Regression-test overlays against persisted transform fixtures.
- Test that every invalid or ambiguous ROI path prevents an `OK` decision.

## 8.10 Open Questions and Validation Required

- Confirm the number and visual diversity of product types and whether stage one needs one class or type-specific classes.
- Measure valid product size, aspect ratio, position, and clipping ranges from production data.
- Determine whether products can overlap or appear simultaneously.
- Validate whether orientation or perspective normalization is beneficial.
- Agree model-specific confidence and geometric thresholds from held-out production captures.
