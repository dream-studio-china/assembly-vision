# 09 — Training and Datasets

How the dataset pipeline and the `av-train` training CLI work internally,
and how to train/extend the two-stage models. This is developer-only tooling
— the runtime never imports it.

## Two-stage dataset layout

Both detectors train from standard YOLO datasets:

```text
dataset/
├── data.yaml          # names list (authoritative class-ID order), nc, train/val
├── images/{train,val}/
└── labels/{train,val}/
```

`dataset_product` = one class `product` (full-board box, mandatory on every
product image); `dataset_components` = required component classes in fixed
order. **Missing components are expressed by the absence of a box — never a
generic `missing_*` class.**

## Dataset validation (`training/src/assemblyvision_training/dataset.py`)

`validate_dataset(dataset_dir, *, allow_missing_labels=False) -> DatasetInfo`
raises `ConfigError` on:

- missing directory or `data.yaml`; `names` empty; `nc != len(names)`.
- missing `images/<split>`/`labels/<split>` for `train`/`val`; empty splits.
- **missing label file for any image** (image/label pairing required;
  explicit empty label files for background negatives) — unless the
  `--allow-missing-labels` legacy opt-in is used, which is recorded into
  `data.yaml` idempotently (`record_missing_labels_optin`).
- malformed label lines: not exactly 5 fields; class id out of `[0, nc)`;
  `cx/cy/w/h` outside `[-1e-4, 1+1e-4]`; zero-sized boxes; boxes outside the
  image.

## The real-data pipeline

1. **Collect and annotate** (X-AnyLabeling): one `product` box per product
   image (including missing-component boards); component boxes for present
   parts only; explicit empty label files for background negatives; second
   reviewer; export YOLO layout with train/val/test.
2. **Adapt** (strict validation, atomic publish):
   ```bash
   uv run python scripts/adapt-xanylabeling.py <export> <out> \
     --product-class product --required 'chip,capacitor,boot'
   # or Roboflow exports:
   uv run python scripts/adapt-roboflow-dataset.py <src> <out> \
     --product-class product --required 'chip,capacitor,boot'
   ```
   Both adapters: drop `missing*` classes; require an independently annotated
   `product` class (the union of component boxes is rejected); component-only
   images rejected; image/label pairing enforced; stem collisions rejected;
   `valid` normalized to `val`; **SHA-256 split disjointness** (train vs val,
   and held-out test vs both); populated output dirs rejected; staging +
   atomic rename. Outputs `dataset_product/`, `dataset_components/`,
   `test/` (held-out), `test-expected.json`, `manifest.json` with
   dataset-relative `data.yaml` paths.
3. **Synthetic option** (framework testing only):
   `uv run python scripts/generate-synthetic-dataset.py /tmp/av-synth
   --n-train 30 --n-val 8` — fixed seed 2026, 800×600, components
   screw/chip/connector/diode, guaranteed missing-scenario coverage, 6 OK + 6
   NG held-out test images.

## Training loop (`av-train`)

```bash
# 1. product detector (full frames)
uv run av-train product <dataset_product> --semver 0.1.0 --epochs 120 --no-augment \
  --out-weights models/weights/product-yolo-0.1.0.pt \
  --out-manifest models/manifests/product-manifest.json

# 2. regenerate the component ROI dataset from the VERIFIED product manifest
uv run av-train prepare-components <dataset_components> \
  --product-manifest models/manifests/product-manifest.json \
  --conf 0.10 --iou 0.50 --min-area 10000 --min-retention 0.80 --out-dir <roi-dataset>

# 3. component detector (ROI crops)
uv run av-train component <roi-dataset> --semver 0.1.0 --epochs 150 --no-augment \
  --out-weights models/weights/component-yolo-0.1.0.pt \
  --out-manifest models/manifests/component-manifest.json

# 4. inspect + verify the held-out set (verify exits non-zero on any FN/gap)
uv run assemblyvision inspect <test> --config <pipeline.yaml> --rule <rule.yaml> --output out/
uv run assemblyvision verify <test> --config <pipeline.yaml> --rule <rule.yaml> \
  --expected test-expected.json --output verify-out/
```

Internals:

- `train_detector` (`train.py`) caches base weights in
  `training/.cache/weights/yolo11{size}.pt`, calls Ultralytics
  `model.train(data=..., epochs, imgsz, device, project, name, exist_ok,
  seed)`; `--no-augment` sets `mosaic=0.0, scale=0.2, translate=0.05,
  fliplr=0.0, hsv_*=0.0`. Returns `project/run/weights/best.pt`; project dir
  is `<weights-parent>/.train-runs`.
- `prepare_components` (`prepare_components.py`): checksum-verifies the
  product manifest + class map; runs the product model on each frame;
  **exactly one** `product` candidate → ROI, zero/multiple → recorded in
  `exclusions.json` (`NO_PRODUCT_OR_AMBIGUOUS`, never a guessed box); remaps
  component labels into ROI coordinates with `apply_transform`; drops boxes
  outside the ROI; **keeps negative ROI crops with empty labels**; stages +
  atomic publish; refuses a populated output dir.
- `place_weights` (`artifact.py`): refuses to overwrite existing weights with
  different bytes (bump `--semver` or remove the file).
- `write_manifest`: enforces `^\d+\.\d+\.\d+$`; `model_version_id =
  uuid5(NAMESPACE, f"{task}:{semver}")`; artifact `uri` relative to the
  manifest dir; `runtime="ultralytics"`, `source_revision="av-train"`,
  `split_strategy="by_capture_session"`, limitations note. Existing manifest
  republication is accepted only when the canonical payload (all fields
  except `created_at`) matches exactly.
- `write_run_metadata`: sidecar `<manifest-stem>.run.json` recording
  reproducibility (dataset dir + `data.yaml` SHA-256, epochs, imgsz, seed,
  model size, augmentation flag, device, weights SHA-256/size, Python +
  Ultralytics versions, created_at); refuses to overwrite differing content.

## Version bump discipline

`av-train --rule <product-rule.yaml>` prints the coordinated bump after
training (see `03-cli-reference.md`). The rule engine rejects a component
model not listed in `compatible_component_model_versions`
(`VERSION_INCOMPATIBLE`), so update all three together:

- `pipeline.yaml` → `component_detection.model_version` (and
  `product_detection.model_version` when the product detector changed);
- `product-rule.yaml` → add the label to `compatible_component_model_versions`
  and increment `rule_version`.

A false negative on the held-out set fails `verify` and **blocks promotion**.
Previous artifacts stay available for rollback.

## Extending to a new product/component

1. Collect + annotate (runbook 11 / design 19.17): OK products, physically
   constructed NG per missing location, background negatives.
2. Adapt → train product → prepare-components → train component → verify.
3. Bump pipeline.yaml + rule together; validate load-time compatibility
   checks (config validation refuses unknown components or model/rule
   mismatches).
