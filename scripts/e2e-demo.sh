#!/usr/bin/env bash
# End-to-end smoke test:
#   synthetic data -> train product -> prepare ROI -> train component ->
#   inspect held-out images -> verify (NG recall / FN / FP) with a hard gate.
#
# Fails (exit 1) if verification reports any false negative (NG predicted as
# OK). Requires: uv-synced workspace (ultralytics + torch installed).
#
# Usage:
#   scripts/e2e-demo.sh [workdir]        # workdir defaults to /tmp/av-e2e
# Env overrides: N_TRAIN, N_VAL, EPOCHS_PRODUCT, EPOCHS_COMPONENT
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
WORK="${1:-/tmp/av-e2e}"
N_TRAIN="${N_TRAIN:-30}"
N_VAL="${N_VAL:-8}"
EPOCHS_PRODUCT="${EPOCHS_PRODUCT:-120}"
EPOCHS_COMPONENT="${EPOCHS_COMPONENT:-150}"

mkdir -p "$WORK"
cd "$ROOT"

echo "=== 0. generate synthetic datasets ($N_TRAIN train / $N_VAL val / 12 test) ==="
uv run python scripts/generate-synthetic-dataset.py "$WORK" --n-train "$N_TRAIN" --n-val "$N_VAL"

cat > "$WORK/pipeline.yaml" << CFG
application_version: "0.1.0"
models:
  product_manifest: $WORK/manifests/product-manifest.json
  component_manifest: $WORK/manifests/component-manifest.json
product_detection:
  model_version: product-yolo-0.1.0
  confidence_threshold: 0.10
  iou_threshold: 0.50
component_detection:
  model_version: component-yolo-0.1.0
  iou_threshold: 0.50
  components:
    screw: { observation_threshold: 0.10 }
    chip: { observation_threshold: 0.10 }
    connector: { observation_threshold: 0.10 }
    diode: { observation_threshold: 0.10 }
roi:
  margin_x_ratio: 0.05
  margin_y_ratio: 0.05
  min_area_pixels: 10000
  min_expanded_area_retained: 0.80
  normalize_perspective: false
CFG
cat > "$WORK/product-rule.yaml" << RULE
schema_version: 1
rule_id: demo-presence
rule_version: 1
product_type: demo_board
compatible_component_model_versions: [component-yolo-0.1.0]
barcode_required: false
required_components:
  screw: { expected_count: 1 }
  chip: { expected_count: 1 }
  connector: { expected_count: 1 }
  diode: { expected_count: 1 }
mandatory_gates:
  product_detected: true
  roi_valid: true
  minimum_valid_frames_met: true
RULE
echo "config written: $WORK/pipeline.yaml, $WORK/product-rule.yaml"

echo "=== 1. train product detector (${EPOCHS_PRODUCT} epochs) ==="
uv run av-train product "$WORK/dataset_product" --semver 0.1.0 --epochs "$EPOCHS_PRODUCT" \
  --imgsz 320 --device cpu --seed 0 --no-augment \
  --out-weights "$WORK/weights/product-yolo-0.1.0.pt" \
  --out-manifest "$WORK/manifests/product-manifest.json"

echo "=== 2. prepare component ROI dataset ==="
uv run av-train prepare-components "$WORK/dataset_components" \
  --product-manifest "$WORK/manifests/product-manifest.json" \
  --conf 0.10 --iou 0.50 \
  --min-area 10000 --min-retention 0.80 --out-dir "$WORK/dataset_roi"

echo "=== 3. train component detector (${EPOCHS_COMPONENT} epochs) ==="
uv run av-train component "$WORK/dataset_roi" --semver 0.1.0 --epochs "$EPOCHS_COMPONENT" \
  --imgsz 320 --device cpu --seed 0 --no-augment \
  --out-weights "$WORK/weights/component-yolo-0.1.0.pt" \
  --out-manifest "$WORK/manifests/component-manifest.json"

echo "=== 4. inspect held-out test images ==="
rm -rf "$WORK/out"
uv run assemblyvision inspect "$WORK/test" --config "$WORK/pipeline.yaml" \
  --rule "$WORK/product-rule.yaml" --output "$WORK/out"

echo "=== 5. verify held-out test images (filename fallback, hard gate on FN) ==="
rm -rf "$WORK/verify-out"
if ! uv run assemblyvision verify "$WORK/test" --config "$WORK/pipeline.yaml" \
    --rule "$WORK/product-rule.yaml" --output "$WORK/verify-out"; then
    echo "FAIL: verification reported false negatives (NG predicted as OK)." >&2
    exit 1
fi

echo
echo "Done. Outputs under $WORK/out and $WORK/verify-out."
echo "Expected: 6 OK + 6 NG with NG recall 1.000 and zero false negatives."
