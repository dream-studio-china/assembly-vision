# Runbook 11: Data Collection and Annotation (Real-Data Baseline)

## Trigger

Acquiring the real-data baseline for the one-month scope, or adding data for a
model-improvement cycle (runbook 10): the pipeline needs real production images
annotated for the two-stage detector (product + required components) with
held-out verification data.

## Preconditions

- A checked-out workspace with `uv sync` completed.
- One fixed camera station (camera, optics, mounting, lighting, conveyor
  background, capture software) matching production conditions.
- The required-component list and the missing-component scenarios to cover
  (each missing location is a separate failure mode).
- [X-AnyLabeling](https://github.com/CVHub520/X-AnyLabeling) installed for
  annotation; permission/consent and retention rules for production images
  agreed (design 19.16).
- Authority to construct physically missing-component products.

## Procedure

1. **Collect OK images.** Capture 100-300 OK products across batches/dates with
   ordinary position variation (start with 40-60 for a minimal closed loop).
2. **Construct and collect NG images.** For every missing location, physically
   build the missing-component product and capture ≥ 100 samples (10-20 for a
   minimal loop); include missing-multiple combinations. Do not generate NG by
   digitally erasing components (design 19.4).
3. **Collect edge cases.** Empty conveyor/background (30-60), partial
   entry/exit (20-40), multiple products in frame (10-20), blur/reflection/
   occlusion/exposure variation (10-20 each), and barcode readable/damaged/
   unreadable cases.
4. **Annotate the product dataset.** Draw one full-board `product` box on every
   image, including missing-component boards. Background images get an explicit
   empty label file (no product box, no other labels).
5. **Annotate the component dataset.** Draw full-frame boxes for every required
   component class. A missing component is left unlabeled (no box); never add a
   generic `missing_*` class.
6. **Review.** A second reviewer checks every NG sample, all ambiguous labels,
   and a sample of ordinary labels; adjudicate disputes against the locked
   ontology before bulk relabeling (design 19.5).
7. **Export.** From X-AnyLabeling, export the YOLO layout with train/val/test
   splits (`classes.txt` or `data.yaml` class names). The test split is the
   held-out verification set only; it is never copied into training.
8. **Adapt.** Convert the export into the two-stage layout:

   ```bash
   uv run python scripts/adapt-xanylabeling.py <export> <out> \
     --product-class product \
     --required '<component,comma,separated>'
   ```

   This validates every label line, enforces the two-stage rules (independent
   product box required; component-only images rejected; background negatives
   kept as explicit empty labels), and produces `dataset_product`,
   `dataset_components`, `test-expected.json`, and `manifest.json`. Roboflow
   exports use `scripts/adapt-roboflow-dataset.py` instead. A populated output
   directory is rejected to avoid stale data.
9. **Verify leakage-safe splits.** The adapter already rejects byte-identical
   overlap between train/val and held-out test; confirm grouping by physical
   instance/session per design 19.6 before training.
10. **Hand over.** Record the dataset path (outside Git), per-class and
    per-missing-scenario counts, checksums of images and annotations, the
    ontology/annotation version, review sign-off, and license/consent
    classification. `av-train` will validate the layout and freeze the
    manifests.

## Exit Criteria

- `dataset_product` and `dataset_components` pass `validate_dataset` and
  `av-train` validation with no warnings.
- Every required component class and every missing location has its planned
  sample count or a documented limitation.
- The held-out `test` split is disjoint from training/validation by checksum
  and instance group.
- All NG samples are reviewed; checksums and annotation version are frozen.
- The two-stage pipeline runs end to end: `av-train product` ->
  `prepare-components` -> `av-train component` -> `assemblyvision inspect` ->
  `assemblyvision verify` on the held-out set.

## Related

- [Design 19.17 - Single-Product Data Acquisition and Annotation Checklist](../design/19-training-and-evaluation.md#1917-single-product-data-acquisition-and-annotation-checklist)
- [Model Improvement](10-model-improvement.md)
- [Training and Evaluation](../design/19-training-and-evaluation.md)
- [Imaging Workflow and Training Cost](../research/03-imaging-workflow-and-training-cost.md)
- [ADR-011: Labeled Train-and-Inspect MVP](../design/decisions/ADR-011-labeled-train-and-inspect-mvp.md)
