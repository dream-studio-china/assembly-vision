# AssemblyVision Quickstart

## Prerequisites

- [uv](https://docs.astral.sh/uv/) (Python package manager; installs Python 3.12 automatically)
- macOS / Linux (the edge runtime targets Linux; development works on both)

## Setup

```bash
git clone https://github.com/dream-studio-china/assembly-vision.git
cd assembly-vision
git checkout feat/mvp
uv sync
```

This creates a virtual environment with all workspace packages:

| Package | Description |
|---|---|
| `assemblyvision-domain` | Canonical Pydantic models, errors, reason codes |
| `assemblyvision-vision` | ROI geometry, image sources, manifest loading |
| `assemblyvision-edge` | Inspection CLI, pipeline, rule engine, detectors |

## Verify everything works

```bash
uv run ruff check apps          # lint
uv run mypy apps/edge-service/src \
  packages/python/domain/src \
  packages/python/vision-core/src  # type check
uv run pytest                     # 42 tests
```

## Run the inspection CLI

```bash
# train the models first (see av-train), then inspect a folder of images
uv run assemblyvision inspect /path/to/images \
  --config config/examples/pipeline.yaml \
  --rule config/examples/product-rule.yaml \
  --output out/
```

Each image gets its own output directory under `out/<inspection_id>/`:

```text
out/<inspection_id>/
├── inspection.json        # full versioned record
├── key_frame.jpg          # original frame
├── annotated_frame.jpg    # annotated frame (boxes when detectors succeed)
└── product_roi.jpg        # product ROI crop (when a product is detected)
```

### Example with synthetic images

```bash
uv run python -c "
from PIL import Image
d = 'demo-images'
import os; os.makedirs(d, exist_ok=True)
Image.new('RGB', (800, 600), (180, 180, 180)).save(f'{d}/sample.png')
Image.new('RGB', (400, 300), (200, 200, 200)).save(f'{d}/sample2.jpg')
"

uv run assemblyvision inspect demo-images \
  --config config/examples/pipeline.yaml \
  --rule config/examples/product-rule.yaml \
  --output out/
```

## Run tests

```bash
uv run pytest                           # all tests
uv run pytest apps/edge-service/tests/test_rule_engine.py -v  # rule engine only
```

## Project layout

```text
pyproject.toml                  # root uv workspace (members: apps/, packages/)
apps/edge-service/              # inspection runtime (CLI, pipeline, rules, detectors)
packages/python/domain/         # shared domain models, errors, reason codes
packages/python/vision-core/    # shared ROI engine, image sources, manifests
config/examples/                # example pipeline, rule, and manifest config
models/manifests/               # model metadata (weights outside Git)
tests/fixtures/                 # small non-sensitive test fixtures
docs/                           # architecture, contracts, ADRs, runbooks
```

## What's next

- **M4 `verify`** — held-out verification with NG recall / false negative reporting
- **M5 End-to-end demo** — train on real labeled data and inspect

> `assemblyvision inspect` now runs real Ultralytics YOLO detectors. It loads
> weights from the model manifests; if the trained weights are missing it exits
> with a configuration error before processing any image. To use it, first train
> the product and component detectors with `av-train`, then point the pipeline
> config at the resulting manifests.
