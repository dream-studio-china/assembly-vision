# 08 — Camera Sources and Vision-Core

How image acquisition, the ROI engine, and model manifests work in
`packages/python/vision-core` (`assemblyvision_vision`), and how to add a new
camera source.

## The `FrameSource` protocol

Every acquisition source implements this protocol
(`sources/frame_source.py`):

```python
class FrameSource(Protocol):
    def open(self) -> CameraCapabilities: ...
    def configure(self, settings: CameraSettings) -> AppliedSettings: ...
    def frames(self, stop: Event) -> Iterator[CapturedFrame]: ...
    def close(self) -> None: ...
```

`CapturedFrame` (frozen dataclass, `eq=False`):
`monotonic_ts_ns` (int), `wall_clock_utc` (datetime), `sequence` (int),
`pixel_format` (str), `status` (str), `image` (PIL RGB), plus optional
`product_identity` and `multi_product` (stamped by the identity correlator).

**Fail-safe rule**: read/decode failures raise `FrameStreamError` — frames
are never silently skipped (ADR-013). Raw buffers are never silently
reinterpreted; unsupported formats fail before inspection.

## Implemented sources

| Source | Class | Config fields | Notes |
|---|---|---|---|
| folder | `FolderSource` | `path`, `loop`, `fps` | Deterministic sorted iteration; supported `.jpg .jpeg .png .bmp .tif .tiff .webp` |
| video | `VideoFrameSource` | `path`, `fps`, `loop` | OpenCV `VideoCapture`, seeks to 0 to loop |
| opencv-device | `OpenCVCameraSource` | `device` (index or `/dev/videoN`), `fps`, `width`, `height`, `reconnect` | Bounded exponential backoff reconnect (`ReconnectPolicy` 250 ms → 10 s); also virtual cameras (v4l2loopback, OBS) |
| rtsp | `RTSPFrameSource` | `url` (`rtsp://`/`rtsps://`), `fps`, `reconnect` | PyAV primary (`rtsp_transport=tcp`), OpenCV fallback |
| http-image | `HttpImageSource` | `url` (`http(s)://`), `fps`, `timeout_seconds` | httpx polling; transient transport failures retried, undecodable content faults the source |
| gige-vision | `GigEVisionFrameSource` | `serial`, `gentl_producer`, `trigger_mode`, `pixel_format`, `exposure_us`, `gain_db`, `packet_size`, `fps`, `width`, `height`, `reconnect` | GenICam/GenTL via Harvester + vendor `.cti`; serial-bound (never IP); only `Mono8`/`RGB8`/`BGR8` convert deterministically; node-map config verified by read-back; Linux/Windows only (macOS gige extra resolves to nothing) |

Lazy backend helpers (`_opencv.py`, `_av.py`, `_harvester.py`) raise clear
errors asking for the matching `vision-core[extra]` when the optional
dependency is missing.

## Factory

`sources/factory.py` — `SourceType = Literal["folder", "video",
"opencv-device", "rtsp", "http-image", "gige-vision"]`;
`build_frame_source(config: FrameSourceConfig) -> FrameSource` validates the
required fields per source type and constructs the source. The factory is
called from `assemblyvision_edge.config._parse_camera_source` (edge config)
and the instance pipeline build.

## Adding a new camera source

1. Create `sources/your_source.py` implementing the `FrameSource` protocol.
   - `open()` returns `CameraCapabilities` (source dims, fps, pixel format,
     serial/model/firmware/GenTL producer where available).
   - `frames(stop)` yields `CapturedFrame`s with monotonic + UTC timestamps,
     sequence, dims, pixel format, status, PIL RGB image; raise
     `FrameStreamError` on decode failure (never skip).
   - Implement bounded reconnect (see `ReconnectPolicy` in
     `sources/reconnect.py`).
   - If a vendor SDK is optional, load it lazily via a `_your_backend.py`
     helper and add a `vision-core[your-extra]` extra in `pyproject.toml`
     (mirror `_harvester.py`).
2. Register the source type:
   - `sources/factory.py`: add to `SourceType`, extend `build_frame_source`,
     and validate the required `FrameSourceConfig` fields.
   - `assemblyvision_edge/config.py` `_SOURCE_TYPES` + `_parse_camera_source`
     validation so the YAML config accepts it.
3. Wire the pipeline: the edge `CameraSourceManager` only needs a `FrameSource`
   — no other runtime changes.
4. Add tests in `packages/python/vision-core/tests/` following the existing
   pattern: inject a fake backend via
   `monkeypatch.setattr(_your_backend, "_module", FakeModule)` (no real
   hardware needed), and assert reconnect, stop semantics, decode-failure
   fail-safe, and factory validation.
5. Update docs: design 07, ADR-013-style decision if the change is
   architectural, and this manual.

## ROI engine

`roi/roi_engine.py`:

- `ROIConfig` (frozen dataclass): `margin_x_ratio=0.05`,
  `margin_y_ratio=0.05`, `min_area_pixels=250_000`,
  `min_expanded_area_retained=0.90`, `normalize_perspective=False`.
  Constructor raises `ROIGenerationError` for invalid margins/area/retention
  or `normalize_perspective=True` (unsupported by the MVP).
- `ROIEngine.generate(frame, frame_id, product_box) -> GeneratedROI`:
  expand by margins → clip to frame → reject (`ROI_INVALID`) when the
  clipped area < `min_area_pixels` or `retained_fraction <
  min_expanded_area_retained` → crop → build `ROIResult` with
  `transform_full_to_roi` (translation only).

`roi/geometry.py` (pure, no I/O) — `Box` (xyxy + area), `expand`, `clip`,
`retained_fraction`, `translation_transform`, `inverse_transform`,
`apply_transform`. This is the same transform code used by
`training/prepare_components.py` so dataset prep and runtime inference share
exact coordinate semantics.

## Model manifests (`manifests.py`)

- `load_model_manifest(path) -> ModelManifest`: JSON → Pydantic
  (`extra="forbid"`), requires `runtime == "ultralytics"`, else `ConfigError`.
- `verify_manifest_artifact(manifest, manifest_path) -> Path`: resolves the
  **first artifact only**; URI must be relative (no leading `/`, no `://`
  scheme, no drive segments); resolved path must stay inside the model
  bundle root (manifest directory's parent, symlink-safe); file must exist;
  `size_bytes` and SHA-256 must match — else `ConfigError`. This permits the
  documented `models/manifests` + sibling `models/weights` layout.
- `verify_model_class_map(names, manifest)`: Ultralytics `model.names` must
  be contiguous `0..n-1` and exactly equal `class_names` in order.
- `model_version_label(task, semver)`: `product-yolo-<semver>` /
  `component-yolo-<semver>`; `manifest_model_version(manifest)` derives the
  canonical label used for `pipeline.yaml` `model_version` declaration.

## Adding a new component class (no code changes needed)

A new component class is **configuration data**, not code:

1. The component detector must have been trained on it (see
   `09-training-and-datasets.md`) and its manifest `class_names` updated.
2. `pipeline.yaml` → `component_detection.components.<code>:
   {observation_threshold: <t>}`.
3. `product-rule.yaml` → add `<code>: {expected_count: 1}` to
   `required_components`, and ensure the manifest label is in
   `compatible_component_model_versions`.
4. Validate: the pipeline load rejects components missing from either the
   config or the manifest; rule/component compatibility is checked at load.
