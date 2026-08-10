# 13 — Debugging and Observability

Practical guidance for developing and debugging the system locally: how to
start it, what the health/status/log surfaces tell you, common failure
signatures and their causes, and the dev tools available.

## Starting points for a bug hunt

- **CLI path** (`assemblyvision inspect`): the fastest repro. Look at the
  per-image stdout line (`path\tOK|NG\treasons\tinspection_id`) and the
  `<output>/<inspection_id>/inspection.json` bundle (full record with reason
  codes, evidence, versions). Config errors exit `2` with the message on
  stderr.
- **Server path** (`assemblyvision serve`): check `/health/live`,
  `/health/ready`, `/device/status`, `/inspection/state`, `/logs`, then
  `/inspections` for persisted records. The WebSocket runtime channel shows
  live transitions (`inspection.started`/`completed`,
  `device.status_changed`, `upload.changed`).
- **Frontend**: `VITE_API_MODE=mock` runs with deterministic data (no
  backend); `VITE_API_MODE=http` talks to the real service. Browser devtools
  network tab shows the actual `/api/v1` requests and `problem+json`
  bodies.

## Health and status surfaces

| Endpoint | Meaning | Typical failure reading |
|---|---|---|
| `GET /api/v1/health/live` | Process alive (unauthenticated) | non-2xx → process down or shutting down |
| `GET /api/v1/health/ready` | Decision-critical deps permit inspection | `503 NOT_READY` → pipeline not loaded or storage cannot guarantee persistence |
| `GET /api/v1/device/status` | Full state | see field table below |
| `GET /api/v1/inspection/state` | Window/pause/fault state | `faulted: true`, `paused: true` |
| `GET /api/v1/logs` | Bounded log ring (500 entries) | component/level/message/trace |

### `device/status` fields that matter when debugging

- `inspection_ready` / `inspection_error_code` — false with
  `CONFIG_INVALID` etc. means config/rule/manifest validation failed at load;
  check stderr of `serve`.
- `sync_ready` — false when no upload destination is configured or central
  unreachable; **does not** block inspection.
- `camera_connected`, `model_loaded` — false → check the camera source config
  and model weights presence.
- `storage_mode`: `NORMAL | WARNING | CRITICAL | STOP`; `storage_write_fault:
  true` latches until `probe_persistence` succeeds (probe file + fsync +
  `BEGIN IMMEDIATE` write).
- `upload_circuit_state`: `CLOSED | OPEN | HALF_OPEN` — OPEN means the worker
  hit the consecutive-failure threshold and is not attempting uploads
  (queue truth is in `/api/v1/uploads`).
- `alerts[]`: stable tokens — `STORAGE_WRITE_FAULT`, `DISK_STOP`,
  `DISK_CRITICAL`, `DISK_WARNING`, `STORAGE_INTEGRITY_FAULT`,
  `CLEANUP_FAULT`, `UPLOAD_BLOCKED`, `UPLOAD_FAILING`, `UPLOAD_CIRCUIT_OPEN`.
- `cleanup_*_count` — retention worker progress/errors.
- `integrity_scan_*` — startup integrity scan results.

## Common failure signatures and causes

| Signature | Likely cause | Where to look |
|---|---|---|
| `inspect` exits `2` "configuration error" | Invalid config/rule/manifest (unknown key, threshold out of range, model version mismatch, rule/component mismatch, rule identity reused with different content) | config/rule YAML, manifests; stderr message |
| `inspect` exits `1` with per-image error | Image read / inference / ROI / output failure for at least one image | stderr per-image error; bundle dirs |
| `verify` exits `1` `DANGER: NG predicted as OK` | Model regression on held-out set — **blocks promotion** | report rows; the failing image + evidence bundle |
| `verify` `DANGER: ... full expected set` | Unlabeled/failed/unmatched samples | per-image rows; `--expected` file |
| `/health/ready` 503 `NOT_READY` | No `--config`/`--rule` (pipeline not built) or storage cannot guarantee persistence | serve args; `device/status` storage fields |
| `device/status` `inspection_ready: false`, `inspection_error_code: CONFIG_INVALID` | Config/rule/manifest validation failed during `serve` load | serve stderr; `configuration/effective` |
| 401 `UNAUTHENTICATED` on every route except `/health/live` | Missing/wrong `Authorization: Bearer` header or session | token config (`AV_EDGE_API_TOKEN` / `--api-token`) |
| 429 `RATE_LIMITED` | >5 failed auth attempts per IP per minute | wait for `Retry-After: 60`; fix the token |
| 404 `DEV_TOOLS_DISABLED` on `/dev/*` | Dev harness not enabled | restart `serve` with `--enable-web-test` |
| 410 `MEDIA_PURGED` on media content | Retention purged the artifact (audit tombstone remains) | retention policy + `cleanup_*` counters; expected behaviour |
| `storage_write_fault: true` latched | A persistence/write probe failed (ENOSPC/EROFS/I-O) | filesystem state; probe clears only on success |
| Upload tasks stuck `IN_PROGRESS` | Worker died mid-lease; stale tasks reclaimed after lease expiry | `/api/v1/uploads`; lease settings |
| `UPLOAD_CIRCUIT_OPEN` | Consecutive retryable failures (transport/408/429/5xx) | fix connectivity/credentials; half-open probe after `open_seconds` |

## Reproducing pipeline issues

- **No model weights**: the placeholder manifests under `models/manifests/`
  reference non-existent weights — any inspect/serve with them fails closed
  at load (size/SHA-256 mismatch). Run `scripts/e2e-demo.sh` to produce real
  weights, or point the manifests at real artifacts.
- **Pipeline logic without training**: use the fake-detector test idiom —
  `FakeProductDetector`/`RaisingComponentDetector`/`RaisingRuleEngine` in
  `apps/edge-service/tests/test_pipeline.py` drive the real
  `InspectionPipeline` with stub detection results.
- **Config validation**: `config/examples/*.yaml` + `load_pipeline_config`
  unit tests are the reference for valid shapes; add a test for every new
  validation gate.
- **API/DB issues**: `TestClient(create_app(ServerSettings(output_root=tmp,
  db_path=tmp/...)))` with a tmp output root and `Bearer test-edge-token`
  (see `tests/test_api_auth.py`).

## Dev tools (web test harness, ADR-014)

- Gated behind `serve --enable-web-test`; disabled by default
  (`404 DEV_TOOLS_DISABLED`).
- `POST /api/v1/dev/inspect-frame` — upload a photo/image through the
  instance pipeline; `persist=true` writes an evidence bundle that appears in
  history; optional `barcode` query simulates keyboard scanner input.
- `POST /api/v1/dev/inspect-video` — per-frame summary (≤30 sampled frames,
  <100 MB), nothing persisted.
- Dashboard `/dev` page (admin) groups the tools with a Logs tab and a
  client-side product-bbox overlay. Never enable on a production host.

## Structured logging

- Logs are JSON-shaped records served by `/api/v1/logs` (in-memory ring,
  capacity 500) with `logged_at`, `level`, `component`, `message`,
  `trace_id`.
- Fields used by the runtime (per design 23): `event`, `device_id`,
  `inspection_id`, `correlation_id`, model/rule versions, `attempt`,
  `error_code`, `retry_at`. `X-Request-ID` propagates through API responses.
- Never log credentials, authorization headers, raw image bytes, or full
  barcode values (masked when policy requires); absolute filesystem paths
  are scrubbed from viewer-served log messages.
- Local log format from the CLIs: `%(asctime)s %(levelname)s %(name)s:
  %(message)s` (stderr); `-q/--quiet` suppresses INFO.

## Isolation tips

- Storage/retention faults latch and only clear via `probe_persistence` —
  reproduce by removing write permission, filling the volume, or corrupting
  a bundle; verify the fault latches across restart.
- Upload/retention tests use `_AdvancingClock` and `_ScriptedSink` fixtures
  (`tests/test_upload_scheduler.py`) to simulate time and central responses
  deterministically.
- Frame sources are testable without hardware by injecting fake OpenCV/PyAV/
  Harvester backends via `monkeypatch.setattr(backend, "_module", Fake)`.
