# 03 — CLI Reference

Real behavior of the `assemblyvision` and `av-train` commands, with exact
flags, output formats, and exit codes. All output shown is what the commands
actually print (from `cli.py`, `verify.py`, `backup.py`, and their tests).

## `assemblyvision` (top level)

```text
usage: assemblyvision [-h] [--version] {inspect,verify,serve,backup,restore} ...
```

- Version: `assemblyvision --version` → `assemblyvision 0.1.0`.
- A subcommand is required — running bare `assemblyvision` exits `2`.
- Invoke as the `assemblyvision` console script or `python -m
  assemblyvision_edge`.
- Exit-code conventions: argparse misuse → `2`; configuration/validation
  failures → `2`; per-command codes below.

## `assemblyvision inspect`

```text
usage: assemblyvision inspect <paths...> --config <pipeline.yaml>
       --rule <rule.yaml> --output <dir> [--device-id <uuid>] [-q]
```

| Flag | Default | Meaning |
|---|---|---|
| `paths` (positional, required) | — | Images or folders (folders scanned in deterministic sorted order for `.jpg .jpeg .png .bmp .tif .tiff .webp`) |
| `--config` (required) | — | Pipeline configuration file |
| `--rule` (required) | — | Product rule definition file |
| `--output` (required) | — | Output directory |
| `--device-id` | random `uuid4()` | Stable device UUID |
| `-q` / `--quiet` | off | Suppress INFO logs (per-image stdout lines stay) |

Behavior:
- Opens the durable rule registry at `<output>/edge.sqlite3` (shared with
  `serve`); validates manifests, model-version declarations, and
  rule/component compatibility before processing any image.
- Writes `<output>/<inspection_id>/inspection.json`, `key_frame.jpg`,
  `annotated_frame.jpg`, `product_roi.jpg`.

Real stdout (one tab-separated line per image):

```text
/tmp/av-e2e/test/ok_000.png        OK   -                                          1f4b5c8e-0000-4000-8000-0000000000aa
/tmp/av-e2e/test/ng_missing_000.png NG   COMPONENT_MISSING:chip                     1f4b5c8e-0000-4000-8000-0000000000ab
```

stderr summary (INFO level; suppressed with `-q`):

```text
INFO ...: summary: 6 OK, 6 NG, 0 errors
```

Exit codes: `0` when `error_count == 0` (**NG results do not affect the exit
code** — only errors do); `1` when any image raised an error; `2` on
config/registry errors.

## `assemblyvision verify`

```text
usage: assemblyvision verify <paths...> --config <pipeline.yaml>
       --rule <rule.yaml> [--expected <test-expected.json>]
       --output <dir> [--device-id <uuid>] [-q]
```

| Flag | Default | Meaning |
|---|---|---|
| `--expected` | filename fallback | Expected-labels JSON `{"img.png": {"ok": true, "present": [...], "missing": [...]}}`; supplying it **disables** the filename fallback |
| (other flags) | same as `inspect` | |

Filename fallback: basename tokens — `ng`/`missing` → NG, `ok` → OK,
otherwise unlabeled.

Evaluability gate: a record is unscorable (counted `failed`) when it has no
evidence, contains `IMAGE_READ_ERROR` / `INFERENCE_ERROR` / `ROI_INVALID` /
`RULE_EVALUATION_ERROR` / `CONFIG_INVALID` / `VERSION_INCOMPATIBLE` in its
reason codes, or has any `UNCERTAIN` evidence. Duplicate sample identities
are rejected.

Real stdout:

```text
ng_missing_001.png      expected=NG      predicted=NG      match    COMPONENT_MISSING:chip
ok_001.png              expected=OK      predicted=OK      match    -

=== Verification report ===
total            : 12
expected OK      : 6
expected NG      : 6
unlabeled        : 0
failed           : 0
unmatched expect.: 0
matched          : 12/12
NG recall        : 1.000 (6/6)
false negatives  : 0  (FN rate 0.000)
false positives  : 0  (FP rate 0.000)
```

On gaps the report appends `DANGER: verification did not cover the full
expected set (...)`; on false negatives it appends
`DANGER: NG predicted as OK (false negatives):` followed by one
`  - <image>` line per FN.

Exit codes: `0` only when `false_negative == 0` and no gaps; `1` when a
false negative or gap exists; `2` on config errors.

## `assemblyvision serve`

```text
usage: assemblyvision serve --output <dir> [--db <file>] [--config <file>]
       [--rule <file>] [--static <dir>] [--host 127.0.0.1] [--port 8000]
       [--device-id <uuid>] [--api-token <token>] [--allow-dev-auth]
       [--enable-web-test] [--upload-base-url <url>] [--upload-sink-dir <dir>]
       [--upload-insecure-http] [--tls-cert <cert>] [--tls-key <key>]
```

Key behavior:
- `--db` defaults to `<output>/edge.sqlite3`; reconciles existing CLI
  bundles into the index at startup.
- `--api-token` falls back to `AV_EDGE_API_TOKEN` (then Docker secret file
  `/run/secrets/edge_api_token`).
- Bind validation: a non-loopback host without a token and without
  `--allow-dev-auth` → exit `2`. Loopback binding never requires a token.
- TLS: `--tls-cert`/`--tls-key` (or `AV_EDGE_TLS_CERT`/`AV_EDGE_TLS_KEY`)
  must be provided together, files must exist, and the key must not be
  group/other readable; the pair must match.
- Without `--config`/`--rule` the pipeline is not built: history/health are
  served and `inspection_ready=false`.
- `--enable-web-test` turns on the gated `/api/v1/dev/*` endpoints
  (otherwise they 404 before auth).
- Blocks running uvicorn; exits `2` on config/validation errors.

## `assemblyvision backup`

```text
usage: assemblyvision backup --output <dir> [--db <file>]
       [--config <file>] [--rule <file>] --dest <out.tar.gz>
```

- Fails closed if the output root, the DB, any governed `--config`/`--rule`
  file, or the referenced model manifests are missing.
- Takes a consistent SQLite snapshot (online backup API), includes pending
  media + their `inspection.json` records (SHA-256 per entry), and governed
  files; a missing/changed pending file aborts the backup.
- stderr success line:
  `backup written to <path>: N governed files, N pending media, sha256=<hex>`.
- Exit: `0` success, `2` failure.

## `assemblyvision restore`

```text
usage: assemblyvision restore --backup <bundle.tar.gz> --output <dir>
       [--db <file>] [--governed-dest <dir>]
```

- Verifies every bundle checksum before applying anything; refuses on DB
  checksum mismatch; preflights media targets (conflicting files → error
  with the active DB unchanged); keeps `<db>.pre-restore`; restores governed
  files only into `--governed-dest`; reconciles the store so pending upload
  tasks survive.
- stderr success line:
  `restore from <path>: db=<db>, media=N, governed=N, reconciled=N`.
- Exit: `0` success, `2` failure.

## `python -m assemblyvision_edge.healthcheck`

```text
python -m assemblyvision_edge.healthcheck <url>
```

- GET with a 5 s timeout; exit `0` on 2xx/3xx, `1` on failure, `2` on misuse.
- Used by the container HEALTHCHECK.

## `av-train` (training CLI, developer-only)

```text
usage: av-train [-h] [--version] {product,prepare-components,component} ...
```

### `av-train product <dataset> --semver X.Y.Z`

| Flag | Default | Meaning |
|---|---|---|
| `--epochs` | 50 | Training epochs |
| `--imgsz` | 640 | Model input size |
| `--model-size` | `n` | YOLO scale `n/s/m/l` |
| `--device` | `cpu` | `cpu/mps/cuda` |
| `--seed` | 0 | Reproducibility seed |
| `--no-augment` | off | Disable heavy augmentation (stable for small datasets) |
| `--allow-missing-labels` | off | Legacy opt-in: accept images without label files (recorded in `data.yaml`) |
| `--out-weights` | `models/weights/product-yolo.pt` | Output weights path |
| `--out-manifest` | `models/manifests/product-manifest.json` | Output manifest path |
| `--rule` | — | Optional rule YAML to print the suggested version bump |

### `av-train prepare-components <dataset> --product-manifest <file> --out-dir <dir>`

| Flag | Default | Meaning |
|---|---|---|
| `--margin-x` / `--margin-y` | 0.05 / 0.05 | ROI margin ratios |
| `--min-area` | 10000 | Minimum ROI area (px) |
| `--min-retention` | 0.80 | Minimum clip retention ratio |
| `--conf` / `--iou` | 0.5 / 0.5 | Product-detection thresholds |
| `--device` | `cpu` | torch device |
| `--allow-missing-labels` | off | Legacy opt-in |

Regenerates the ROI-cropped component dataset from the **checksum-verified**
product manifest; zero/multiple product candidates → `exclusions.json`
(`NO_PRODUCT_OR_AMBIGUOUS`), never a guessed box; staging + atomic publish;
keeps negative ROI crops with empty labels.

### `av-train component <roi-dataset> --semver X.Y.Z`

Same flags as `product`, except `--imgsz` defaults to **320** and the default
outputs are `models/weights/component-yolo.pt` /
`models/manifests/component-manifest.json`.

### Improvement hints output

After `product`/`component` training, `av-train` prints the coordinated
bump (real output for a component run with `--rule product-rule.yaml`):

```text
=== Next steps: model improved ===
1. pipeline.yaml: set component_detection.model_version: 'component-yolo-0.2.0'
2. product-rule.yaml: add 'component-yolo-0.2.0' to compatible_component_model_versions
   suggested: rule_version 3 -> 4
   suggested compatible: ['component-yolo-0.1.0'] -> ['component-yolo-0.1.0', 'component-yolo-0.2.0']
3. re-run: assemblyvision verify <test> --config <pipeline.yaml> --rule <rule.yaml> --output out/
   see docs/runbooks/10-model-improvement.md
```

For `product` runs, step 2 is instead the `prepare-components` regeneration
message.

## Environment variables read by `serve` (all in `cli.py`)

Auth/secrets: `AV_EDGE_API_TOKEN`, `AV_EDGE_UPLOAD_TOKEN` (separate upload
credential, never the viewer token), `AV_EDGE_TLS_CERT`, `AV_EDGE_TLS_KEY`.

Upload worker (active only when `AV_EDGE_UPLOAD_BASE_URL` or
`AV_EDGE_UPLOAD_SINK_DIR` is set):

| Variable | Default |
|---|---|
| `AV_EDGE_UPLOAD_BASE_URL` / `AV_EDGE_UPLOAD_SINK_DIR` | — (HTTPS endpoint / local dev sink) |
| `AV_EDGE_UPLOAD_CONNECT_TIMEOUT_SECONDS` | 5.0 |
| `AV_EDGE_UPLOAD_REQUEST_TIMEOUT_SECONDS` | 30.0 |
| `AV_EDGE_UPLOAD_INTERVAL_SECONDS` | 1.0 |
| `AV_EDGE_UPLOAD_BATCH_SIZE` | 4 |
| `AV_EDGE_UPLOAD_LEASE_SECONDS` | 120 |
| `AV_EDGE_UPLOAD_BASE_RETRY_SECONDS` | 2.0 |
| `AV_EDGE_UPLOAD_MAXIMUM_RETRY_SECONDS` | 900.0 |
| `AV_EDGE_UPLOAD_EXPONENT_CAP` | 8 |
| `AV_EDGE_UPLOAD_MAXIMUM_BANDWIDTH_MBPS` | None (disabled) |
| `AV_EDGE_UPLOAD_INSECURE_HTTP` | False |
| `AV_EDGE_UPLOAD_CIRCUIT_FAILURE_THRESHOLD` | 5 |
| `AV_EDGE_UPLOAD_CIRCUIT_OPEN_SECONDS` | 60.0 |
| `AV_EDGE_UPLOAD_MEDIA_CHUNK_BYTES` | 8388608 (reserved) |

Storage (active when any is set): `AV_EDGE_STORAGE_WARNING_FREE_PERCENT` (20.0),
`AV_EDGE_STORAGE_CRITICAL_FREE_PERCENT` (10.0),
`AV_EDGE_STORAGE_STOP_FREE_PERCENT` (5.0) — strictly ordered.

Retention: `AV_EDGE_RETENTION_ENABLED` (False — cleanup off by default),
`AV_EDGE_RETENTION_DURATIONS` (JSON like `{"KEY_FRAME": "30d"}`; compact
durations `s/m/h/d`).

Integrity scan (active when any is set):
`AV_EDGE_STORAGE_INTEGRITY_VERIFY_CHECKSUMS` (True),
`AV_EDGE_STORAGE_INTEGRITY_SAMPLE_LIMIT`,
`AV_EDGE_STORAGE_INTEGRITY_SAMPLE_MAX_BYTES`.

Frontend: `VITE_API_MODE` (`mock` dev / `http` production), `VITE_API_BASE_URL`
(same-origin when omitted), `VITE_CAMERA_INSTANCE_ID` (`line-1`),
`VITE_DEV_SERVER_URL` (edge-desktop dev).
