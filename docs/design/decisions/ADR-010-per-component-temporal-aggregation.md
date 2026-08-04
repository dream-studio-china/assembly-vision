# ADR-010: Per-Component Temporal Aggregation

## 1. Status

Accepted

## 2. Context

YOLO produces detections per frame, while the business decision applies to one physical product. Individual frames may be blurred, occluded, poorly exposed, or show different components. Whole-product majority voting can hide a consistently missing component behind otherwise strong frames and does not express evidence for each required rule item.

## 3. Decision

Group frames into an explicit physical-product inspection window, then aggregate evidence independently for each required component. Policies are versioned and configurable, including one high-confidence detection, multiple medium-confidence detections, adjacent-frame evidence, minimum visible area, minimum frame quality, and exclusion of unusable frames. The deterministic rule engine evaluates the resulting per-component states.

Temporal aggregation does not increase the underlying YOLO model's single-frame accuracy. It increases system-level robustness by combining evidence across frames. Ambiguous product boundaries, frame provenance, or multiple products cause an explicit non-OK/aborted path rather than mixed evidence.

## 4. Scope

This applies when live/video acquisition is implemented. The static-image MVP emits frame-level evidence without temporal aggregation. Window mechanisms may use hardware trigger, barcode event, tracking, entry/exit zones, time bounds, or conveyor sensor integration based on site validation.

## 5. Consequences

### 5.1 Positive

- Preserves component-specific absence evidence and reason codes.
- Reduces sensitivity to one unusable or transiently occluded frame.
- Supports product-specific criticality and thresholds.
- Provides inspectable evidence behind each final component state.

### 5.2 Negative and Trade-offs

- Correct product-window boundaries become critical to prevent frame mixing.
- More configuration, state, latency, and test cases are required.
- Permissive evidence rules can turn one false detection into a false OK.
- Correlated adjacent frames do not provide independent statistical evidence.

## 6. Alternatives

- **Single best frame:** rejected as unnecessarily sensitive to blur, occlusion, and timing.
- **Whole-product majority voting:** rejected because it does not evaluate each required component.
- **Average all confidence values:** rejected because missing detections, unusable frames, visibility, and correlated frames require explicit semantics.
- **Any detection means present:** allowed only as a deliberately validated per-component policy with a sufficiently high threshold, not as a universal rule.
- **Tracking model as final decision:** may support windowing but does not replace component rules and evidence aggregation.

## 7. Open Questions and Validation Required

- Product-window signal, conveyor speed, product spacing, and maximum overlapping products.
- Per-component thresholds, adjacency/quality policies, and latency budget from validation data.
- Whether internal `UNCERTAIN` detail is exposed to operators and APIs; its business result remains `NG`.

## 8. Links

- [Testing and Quality Assurance](../22-testing-and-quality-assurance.md)
- [Risks and Mitigations](../27-risks-and-mitigations.md)
- [ADR-004: Two-stage detection](ADR-004-two-stage-detection.md)
- [ADR-005: Local-first storage and delayed upload](ADR-005-local-first-storage-and-delayed-upload.md)
