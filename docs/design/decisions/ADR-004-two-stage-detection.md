# ADR-004: Two-Stage Detection

## 1. Status

Accepted

## 2. Context

Products can shift within the approximately four-megapixel camera image even though the camera and lighting are normally fixed. Hard-coded absolute component regions would be brittle. The inspection needs both product identity/location and detailed presence evidence for product-specific required components.

## 3. Decision

Use two detectors. Stage one processes the full frame and detects the complete product and product class where applicable. The ROI engine expands/clips the detected box, records full-frame/ROI coordinate mapping, and optionally normalizes validated orientation or perspective. Stage two detects configured component classes within the product ROI.

Rules evaluate required detected components; the model is not trained around a generic global `missing_component` class. Barcode recognition remains a separate decoder capability, although detection may locate a barcode region.

## 4. Scope

This decision applies to static images and live/video frames. A hard-coded full-frame region may remain a coarse capture zone or fallback, but it is not the normal final product ROI. Micro-component inspection and large uncontrolled rotations are outside current scope.

## 5. Consequences

### 5.1 Positive

- Handles expected position variation without making all component coordinates absolute.
- Gives the component model a normalized, higher-relevance image region.
- Separates product localization failures from component evidence failures.
- Supports product-specific rules and traceable coordinate overlays.

### 5.2 Negative and Trade-offs

- Stage-one failure prevents reliable stage-two inspection.
- Two models add latency, version compatibility, training, and observability needs.
- Crop margins and coordinate transforms require careful tests.
- Significant perspective/angle change remains a domain change, not automatically solved by cropping.

## 6. Alternatives

- **One detector on the full frame for product and components:** viable baseline but rejected as the primary design because position/background variation consumes resolution and couples tasks.
- **Fixed absolute ROI:** rejected because product position is not perfectly fixed.
- **Image classification of complete versus incomplete product:** rejected because it gives weak component-level reasons and poor rule configurability.
- **Generic missing-component class:** rejected because absence is better expressed by deterministic rules over required presence evidence.

## 7. Open Questions and Validation Required

- Exact product/component classes and whether product type is visually distinguishable.
- ROI margins, input resolution, and optional orientation normalization based on data.
- Candidate-model latency and recall on production hardware.

## 8. Links

- [Testing and Quality Assurance](../22-testing-and-quality-assurance.md)
- [Risks and Mitigations](../27-risks-and-mitigations.md)
- [ADR-010: Per-component temporal aggregation](ADR-010-per-component-temporal-aggregation.md)
