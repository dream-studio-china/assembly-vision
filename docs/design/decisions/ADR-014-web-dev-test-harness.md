# ADR-014: Web Dev Test Harness (File-Based, Not Production Acquisition)

## 1. Status

Accepted

## 2. Context

Testing the inspection pipeline on real imagery without production hardware is
slow: a developer must copy images or videos to the edge host, run the CLI, and
then inspect the dashboard. A browser already has a camera (including mobile
phones via the OS camera UI), so a developer-facing web tool can take a photo,
upload an image, or upload a short video and get an inspection result
immediately.

This must stay a **test harness**: the edge API is read-only in M1 (ADR-012),
and production real-time acquisition uses the native app / RTSP / camera
sources (design 07). The web must never stream a continuous video into the
pipeline, and no new production ingestion surface should be implied.

## 3. Decision

1. **Gated dev endpoints** under `/api/v1/dev/` are **disabled by default** and
   return `404 DEV_TOOLS_DISABLED` unless `serve` is started with
   `--enable-web-test`. Authentication reuses the existing viewer bearer
   token / session (a shared credential, not per-actor authorization, exactly
   like the M1 development mode).
2. **File-based request/response only**:
   - `POST /api/v1/dev/inspect-frame`: raw image bytes → the instance
     pipeline's single-frame inspection → returns `InspectionRecord`. Writes
     an evidence bundle by default (so results appear in dashboard history)
     unless `persist=false`.
   - `POST /api/v1/dev/inspect-video`: raw video bytes (streamed to a
     temporary file) → decoded with the shared `VideoFrameSource` → at most
     30 sampled frames inspected without persisting → returns a per-frame
     summary (`VideoInspectResult`). No video is ever streamed.
3. **Limits**: image ≤ 20 MB; video < 100 MB and ≤ 30 analyzed frames
   (`step` sampling). These bound CPU and disk cost on the edge host.
4. **Frontend**: a `/dev` page groups developer tools (Test and Logs tabs; more
   tools may follow). The Test tab provides photo/image/video inputs and draws
   the product bounding box overlay client-side from the returned record.
5. **Boundary**: this harness is not a production acquisition path. Production
   inspection stays on the native app / RTSP / camera sources; the web dev
   tools never feed a continuous stream and are never enabled in a default
   `serve` run.

## 4. Consequences

### 4.1 Positive

- Fast, hardware-free testing from any browser, including mobile photo/video
  capture via the OS camera UI (no `getUserMedia` secure-context dependency).
- Results are traceable when persisted: image tests write bundles that appear
  in dashboard history and are picked up by reconciliation.
- The read-only M1 boundary (ADR-012) is preserved: the endpoints 404 unless a
  developer explicitly enables them.

### 4.2 Negative and Trade-offs

- The dev endpoints are mutations (they write bundles / consume CPU), so they
  must never be enabled on a production host; the flag is a developer opt-in.
- Video analysis is per-frame and CPU-bound; the 30-frame cap prevents runaway
  cost but limits long-video testing.
- The shared viewer token is not per-actor authorization; dev-mode is
  explicitly not production authentication (consistent with ADR-012).

## 5. Open Questions and Validation Required

- Whether future dev tools (camera preview, config/DB inspection) join the
  same `/api/v1/dev/` namespace.
- Whether production-grade media upload (multipart, resumable, presigned) is
  ever needed for data collection; if so it is a separate feature, not this
  harness.

## 6. Links

- [REST API and Events](../15-rest-api-and-events.md)
- [Edge Dashboard](../16-edge-dashboard.md)
- [ADR-012: Edge API M1 Viewer Auth and Read-Only Boundary](ADR-012-edge-api-m1-viewer-auth.md)
- [Camera and Image Acquisition](../07-camera-and-image-acquisition.md)
