#!/usr/bin/env bash
# End-to-end smoke test: synthetic data -> train -> prepare -> train -> inspect.
# Demonstrates the full labeled train-and-inspect flow on generated images.
# Requires: uv-synced workspace (ultralytics + torch installed).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
WORK="${1:-/tmp/av-e2e}"
DEMO="$WORK"
mkdir -p "$DEMO"
cd "$ROOT"

echo "=== generating synthetic datasets in $WORK ==="
uv run python - "$WORK" << 'PY'
import pathlib, sys
from PIL import Image, ImageDraw
import yaml

root = pathlib.Path(sys.argv[1])

def make_image(path, dx=0, dy=0):
    im = Image.new("RGB", (800, 600), (245, 245, 240))
    d = ImageDraw.Draw(im)
    x1, y1, x2, y2 = 100+dx, 80+dy, 700+dx, 520+dy
    d.rectangle((x1, y1, x2, y2), fill=(20, 60, 160))
    d.rectangle((200+dx, 150+dy, 260+dx, 210+dy), fill=(220, 30, 30))
    d.rectangle((400+dx, 200+dy, 460+dx, 260+dy), fill=(30, 180, 30))
    d.rectangle((300+dx, 350+dy, 360+dx, 410+dy), fill=(240, 200, 20))
    im.save(path)

for split, n in (("train", 24), ("val", 8)):
    for ds in ("dataset_product", "dataset_components"):
        (root/ds/"images"/split).mkdir(parents=True)
        (root/ds/"labels"/split).mkdir(parents=True)

shifts = [(-30,-20),(-20,-10),(-10,-5),(0,0),(10,5),(20,10),(30,20),(-25,15),(15,-25),(0,10),(-12,-6),(18,12),
          (-8,22),(22,-8),(6,6),(-6,6),(0,-15),(-15,0),(15,0),(0,15),(-35,0),(35,0),(0,-25),(25,0)]
for i, (dx, dy) in enumerate(shifts):
    for ds in ("dataset_product", "dataset_components"):
        make_image(root/ds/"images/train"/f"p{i:03d}.png", dx, dy)
    (root/"dataset_product/labels/train"/f"p{i:03d}.txt").write_text("0 0.5 0.5 0.75 0.733333\n")
    boxes = [(0,200+dx,150+dy,260+dx,210+dy),(1,400+dx,200+dy,460+dx,260+dy),(2,300+dx,350+dy,360+dx,410+dy)]
    lines = [f"{c} {(x1+x2)/2/800:.6f} {(y1+y2)/2/600:.6f} {(x2-x1)/800:.6f} {(y2-y1)/600:.6f}" for c,x1,y1,x2,y2 in boxes]
    (root/"dataset_components/labels/train"/f"p{i:03d}.txt").write_text("\n".join(lines)+"\n")
valshifts = [(-18,-12),(12,8),(24,-4),(-4,18),(-28,10),(20,-14),(5,-20),(-9,3)]
for i, (dx, dy) in enumerate(valshifts):
    for ds in ("dataset_product", "dataset_components"):
        make_image(root/ds/"images/val"/f"p{i:03d}.png", dx, dy)
    (root/"dataset_product/labels/val"/f"p{i:03d}.txt").write_text("0 0.5 0.5 0.75 0.733333\n")
    boxes = [(0,200+dx,150+dy,260+dx,210+dy),(1,400+dx,200+dy,460+dx,260+dy),(2,300+dx,350+dy,360+dx,410+dy)]
    lines = [f"{c} {(x1+x2)/2/800:.6f} {(y1+y2)/2/600:.6f} {(x2-x1)/800:.6f} {(y2-y1)/600:.6f}" for c,x1,y1,x2,y2 in boxes]
    (root/"dataset_components/labels/val"/f"p{i:03d}.txt").write_text("\n".join(lines)+"\n")

(root/"dataset_product/data.yaml").write_text(yaml.dump({"nc":1,"names":["product"],"train":str((root/"dataset_product/images/train").resolve()),"val":str((root/"dataset_product/images/val").resolve())}))
(root/"dataset_components/data.yaml").write_text(yaml.dump({"nc":3,"names":["component_a","component_b","manual"],"train":str((root/"dataset_components/images/train").resolve()),"val":str((root/"dataset_components/images/val").resolve())}))

td = root/"test"; td.mkdir(parents=True)
make_image(td/"ok_001.png", -5, -3)
make_image(td/"ok_002.png", 7, 5)
im = Image.new("RGB", (800, 600), (245, 245, 240))
d = ImageDraw.Draw(im)
d.rectangle((100, 80, 700, 520), fill=(20, 60, 160))
d.rectangle((200, 150, 260, 210), fill=(220, 30, 30))
d.rectangle((400, 200, 460, 260), fill=(30, 180, 30))
im.save(td/"ng_missing_manual_001.png")
print("datasets generated")
PY

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
    manual: { observation_threshold: 0.10 }
    component_a: { observation_threshold: 0.10 }
    component_b: { observation_threshold: 0.10 }
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
product_type: demo
compatible_component_model_versions: [component-yolo-0.1.0]
barcode_required: false
required_components:
  component_a: { expected_count: 1 }
  component_b: { expected_count: 1 }
  manual: { expected_count: 1 }
mandatory_gates:
  product_detected: true
  roi_valid: true
  minimum_valid_frames_met: true
RULE
echo "config written"

echo "=== 1. train product detector ==="
uv run av-train product "$WORK/dataset_product" --semver 0.1.0 --epochs 120 --imgsz 320 --device cpu --seed 0 --no-augment \
  --out-weights "$WORK/weights/product-yolo-0.1.0.pt" --out-manifest "$WORK/manifests/product-manifest.json"

echo "=== 2. prepare component ROI dataset ==="
uv run av-train prepare-components "$WORK/dataset_components" \
  --product-weights "$WORK/weights/product-yolo-0.1.0.pt" \
  --min-area 10000 --min-retention 0.80 --out-dir "$WORK/dataset_roi"

echo "=== 3. train component detector ==="
uv run av-train component "$WORK/dataset_roi" --semver 0.1.0 --epochs 150 --imgsz 320 --device cpu --seed 0 --no-augment \
  --out-weights "$WORK/weights/component-yolo-0.1.0.pt" --out-manifest "$WORK/manifests/component-manifest.json"

echo "=== 4. inspect held-out test images ==="
uv run assemblyvision inspect "$WORK/test" --config "$WORK/pipeline.yaml" --rule "$WORK/product-rule.yaml" --output "$WORK/out" || true

echo
echo "Done. Outputs under $WORK/out/<inspection_id>/"
echo "Expected: ok_001 -> OK, ng_missing_manual_001 -> NG (COMPONENT_MISSING:manual)."
