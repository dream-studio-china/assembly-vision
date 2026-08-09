# ADR-013: Camera Frame Sources and Multi-Instance Edge

## 1. Status

Accepted

## 2. Context

The static train-and-inspect MVP and the read-only M1 edge API run from
static folder input. The one-month target requires camera acquisition
(design 07) and, in practice, one edge host must drive several independent
inspection lines, each with its own camera and its own models/rule/product
(design 04 §2 component diagram shows a single coordinator; the fleet model
in design 14 treats one device per line).

Real camera SDKs (Basler, FLIR, vendor IP cameras) are deployment-dependent
and must not block development or CI. A recorded or simulated source must
exercise the exact same downstream pipeline as a live camera, so the
`FrameSource` protocol in design 07 §7.3 is the single seam. Remote sources
arrive over TCP/IP: RTSP streams are the common industrial-camera transport,
and a plain HTTP image endpoint is a cheap fallback for cameras or PLC
snapshots that expose a single JPEG.

This decision records how sources are abstracted, how multiple independent
instances are configured and run by `assemblyvision serve`, and how previews
reach the dashboard before the WebSocket runtime milestone exists.

## 3. Decision

1. **`FrameSource` protocol in `vision-core`** (design 07 §7.3): `open() ->
   CameraCapabilities`, `configure(settings) -> AppliedSettings`,
   `frames(stop: Event) -> Iterator[CapturedFrame]`, `close()`. Frames carry a
   monotonic timestamp, wall-clock UTC, sequence number, dimensions, pixel
   format, acquisition status, and a PIL RGB image. Read/decode failures raise
   `FrameStreamError`; they never silently skip evidence (fail-safe).
2. **Pluggable sources, all implementing the protocol**: `folder` (static image
   directory, optional loop), `video` (local video file), `opencv-device`
   (local camera index or `/dev/videoN`, including virtual cameras such as
    Linux `v4l2loopback` or OBS Virtual Camera), `rtsp` (remote RTSP stream via
    PyAV with an OpenCV fallback), `http-image` (poll a remote JPEG URL at a
    configured interval), and `gige-vision` (GenICam/GenTL via Harvester and a
    vendor GenTL producer). Vendor SDK adapters can be added later behind the
    same protocol without changing the pipeline.
   The production-preferred adapter is the `gige-vision` GenICam/GenTL
   consumer, while `opencv-device` remains the UVC USB compatibility source.
   Linux is the primary production runtime; Windows is supported only where the
   selected camera's GenTL producer or UVC driver passes the same conformance
   suite. The initial target profile is approximately 4 megapixels at 25-30
   FPS. GigE Vision devices bind by serial number, support
   continuous/software/hardware trigger modes, and record applied pixel format
   and acquisition settings. Hardware trigger is preferred for production
   boundaries. PTP is not required initially; monotonic time controls duration
   and UTC remains traceability metadata. Jumbo frames are optional and require
   validated camera/NIC/switch support.
3. **Multi-instance configuration** (`pipeline.yaml`, `instances:` list): each
   instance is an independent inspection pipeline with its own `camera`,
   models, thresholds, ROI, and rule. The existing flat single-config form
   remains supported for `inspect`, `av-train`, and the M1 `serve` behavior.
   Unknown instance IDs, duplicate `instance_id`, missing `url`/`path`/`device`
   for the selected source type, and invalid `fps` are rejected at load.
4. **Per-instance device identity**: when `device_id` is not configured,
   `device_id = uuid5(NAMESPACE, instance_id)` so a restarted service keeps a
   stable identity per line and records remain traceable per instance. An
   explicit `device_id` overrides the derivation.
5. **`serve` lifecycle**: `serve` opens every configured source at startup;
   a failing instance is reported (non-fatal) without blocking the others and
   without affecting already-readable history/health. Shutdown sets each
   source's stop event and closes all sources. Each instance with
   `inspection.enabled: true` runs a capture/inspection loop that feeds the
   existing single-frame pipeline per captured frame (each frame is one
   inspection, matching current MVP semantics); the default is
   `inspection.enabled: false` so `serve` only opens sources and serves
   previews until the window/temporal milestone lands.
6. **Preview before WebSocket**: `GET /api/v1/camera/{instance_id}/preview`
   returns the most recently captured frame as a rate-limited JPEG (latest
   frame only, no unbounded buffering; `404` unknown instance, `503` not
   ready). This REST preview is the interim transport for the dashboard live
   view; the WebSocket runtime channel (design 15 §15.4) later reuses the same
   frame pipeline without replacing it.
7. **Runtime dependencies**: `opencv-python-headless` (video, local device,
   MJPEG fallback), `av` (PyAV, RTSP), and `httpx` (HTTP image polling) are
   runtime dependencies of `edge-service`; `vision-core` keeps them as optional
   extras (`video`, `rtsp`, `http`) so central/lightweight consumers stay free
   of them.

## 4. Consequences

### 4.1 Positive

- The same pipeline consumes live, recorded, and simulated frames, so
  deterministic regression fixtures work across acquisition modes.
- Development and CI need no camera hardware: folder, video, and local HTTP
  servers exercise every code path the real camera uses.
- One edge host serves multiple independent lines, each with stable per-line
  device identity, matching the fleet model (one device per line).
- Remote TCP/IP sources (RTSP, HTTP images) integrate without vendor SDKs, and
  vendor adapters remain a future protocol implementation.
- The dashboard gets a real camera preview before the WebSocket milestone.

### 4.2 Negative and Trade-offs

- Each instance loads its own model instances; memory grows linearly with the
  number of instances until weight sharing is justified (the "shared model"
  open question in context Phase 3 remains open).
- RTSP reliability depends on PyAV/OpenCV builds and network behavior; bounded
  reconnect with backoff is implemented, but frame-loss and jitter behavior
  must be validated on the target network.
- Per-frame inspection (one inspection per captured frame) is not a product
  window; overlapping products and evidence mixing are not addressed until the
  product-window/temporal milestone.
- The REST preview is a stopgap; it must not grow into a streaming path, and
  the WebSocket milestone should supersede it for live dashboards.
- Adding dependencies (`av`, `opencv-python-headless`, `httpx`) increases the
  runtime footprint and image size.

## 5. Open Questions and Validation Required

- Select the real camera vendor/SDK and validate the vendor adapter against the
  `FrameSource` contract and reconnect behavior.
- Validate RTSP latency, reconnect, and frame loss on the target production
  network.
- Decide whether per-instance model weight sharing is needed before memory
  becomes a constraint (context Phase 3 "shared model").
- Confirm whether HTTP-image polling is sufficient for the customer snapshot
  cameras or an MJPEG parser is required.

## 6. Links

- [Camera and Image Acquisition](../07-camera-and-image-acquisition.md)
- [Edge Client Architecture](../04-edge-client-architecture.md)
- [REST API and Events](../15-rest-api-and-events.md)
- [Edge Dashboard](../16-edge-dashboard.md)
- [ADR-009: Static-Image-First MVP](ADR-009-static-image-first-mvp.md)
- [ADR-011: Labeled Train-and-Inspect MVP](ADR-011-labeled-train-and-inspect-mvp.md)
