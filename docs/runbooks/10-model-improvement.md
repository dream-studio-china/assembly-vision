# Runbook 10: Model Improvement

## Trigger

An approved model change request: new or missing-component data discovered on the
line, a new product/component, a classification regression found in review, or an
accepted accuracy improvement.

## Preconditions

- A checked-out `main` (or `dev`) workspace with `uv sync` completed
  (ultralytics installed).
- A labeled dataset (X-AnyLabeling export or a Roboflow export adapted with
  `scripts/adapt-roboflow-dataset.py`) using a leakage-safe train/val split.
- The model artifacts to be replaced, plus their manifests and checksums, are
  preserved for rollback.

## Procedure

1. **Collect and label data.** Add corrected or new samples to the component
   dataset; create missing-component variants for every required component. Do not
   reuse the held-out/verification images in training.
2. **Retrain the product detector** (if product localization changed):
   ```bash
   uv run av-train product <dataset_product> --semver 0.2.0 --epochs 120 --no-augment \
     --out-weights models/weights/product-yolo-0.2.0.pt \
     --out-manifest models/manifests/product-manifest.json
   ```
3. **Regenerate the component ROI dataset** from the new product detector (the
   manifest is checksum-verified; frames with zero or multiple products are
   recorded in `exclusions.json`, not silently picked):
   ```bash
   uv run av-train prepare-components <dataset_components> \
     --product-manifest models/manifests/product-manifest.json \
     --min-area 10000 --min-retention 0.80 --out-dir <roi-dataset>
   ```
4. **Retrain the component detector**:
   ```bash
   uv run av-train component <roi-dataset> --semver 0.2.0 --epochs 150 --no-augment \
     --out-weights models/weights/component-yolo-0.2.0.pt \
     --out-manifest models/manifests/component-manifest.json
   ```
5. **Verify no regression** on the held-out set. A false negative (NG predicted as
   OK) fails the verify gate and must block promotion:
   ```bash
   uv run assemblyvision verify <test> --config <pipeline.yaml> --rule <rule.yaml> \
     --expected test-expected.json --output verify-out/
   ```
6. **Bump versions together.** The rule engine rejects a component model that is
   not listed in the rule's `compatible_component_model_versions`
   (`VERSION_INCOMPATIBLE`). Update all three together:
   - `pipeline.yaml` → `component_detection.model_version: component-yolo-0.2.0`
   - `product-rule.yaml` → add `"component-yolo-0.2.0"` to
     `compatible_component_model_versions` and increment `rule_version`
   - `pipeline.yaml` → `product_detection.model_version: product-yolo-0.2.0` when
     the product detector changed
7. **Distribute.** Ship the new immutable weights, manifests, and updated
   config/rule to the edge (manual checksum-verified install in the MVP; governed
   distribution later).

## Exit Criteria

New model artifacts and manifests are written, checksums recorded, the held-out
verification shows no regression, all version references (config + rule) are
updated, and the previous artifacts remain available for rollback.

## Related

- [Model Rollback](08-model-rollback.md)
- [Rule Rollback](09-rule-rollback.md)
- [Training and Evaluation](../design/19-training-and-evaluation.md)
- [ADR-011: Labeled Train-and-Inspect MVP](../design/decisions/ADR-011-labeled-train-and-inspect-mvp.md)
