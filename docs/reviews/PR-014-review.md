# PR-014 Review: Camera Frame Sources, Multi-Instance Edge, and Web Dev Test Harness

## Scope

Code review of `feat/camera-frame-sources` against `main` (PR #14). The
review covers ADR-013 camera sources and multi-instance runtime behavior,
ADR-014's gated file-based developer harness, API/OpenAPI/client contracts,
and the new developer-tools view.

Relevant requirements reviewed:

- `docs/design/07-camera-and-image-acquisition.md`
- `docs/design/decisions/ADR-013-camera-frame-sources-and-multi-instance.md`
- `docs/design/decisions/ADR-014-web-dev-test-harness.md`
- `docs/contracts/03-ai-rule-and-safety-contracts.md`
- `docs/contracts/05-data-api-and-versioning-contracts.md`
- `docs/contracts/06-testing-quality-and-ci-contracts.md`
- `docs/contracts/08-security-permissions-and-audit.md`

## Merge Decision

**Do not merge until F1-F9 are resolved.**

The implementation establishes useful source and test-harness seams, and the
existing focused tests pass. However, the current capture loop can silently
lose inspection evidence, pause does not stop inspection, several source
failures violate the non-fatal/fail-safe lifecycle, and the public dev API
contract is not representable by the committed OpenAPI and generated client.

F10-F12 are non-blocking follow-up work, but should be resolved before the
developer tools are used beyond controlled local development.

## Resolution Status

All findings in this review (F1-F14) have been fixed and validated on
`feat/camera-frame-sources` by four parallel implementation agents followed by
contract regeneration and the full quality gates. Each fix carries regression
tests that failed before the fix and pass after:

- **F1** - Bounded per-instance inspection queue; overflow is recorded
  (`frames_dropped`/`degraded`, `FRAME_OVERFLOW` alert) instead of silent loss;
  preview still serves the latest captured frame.
- **F2** - Inspection loops gate on pause and drain stale frames as documented
  overflow on pause/resume; multi-instance device status reports `PAUSED` and
  `inspection_ready=false`.
- **F3** - Missing-folder sources raise `FrameStreamError`; source construction
  failures are caught as `AssemblyVisionError` and registered
  `CAMERA_UNAVAILABLE` without aborting healthy instances.
- **F4** - HTTP-image transport vs decode failures are separated (decode
  failures fault the source); PyAV open/decode/conversion exceptions are
  wrapped as `FrameStreamError`; the capture loop has a final
  unexpected-exception handler that marks the instance disconnected.
- **F5** - Image bodies stream into a bounded buffer with an early `413`;
  decoded limits (`_MAX_IMAGE_PIXELS`, `_MAX_IMAGE_DIMENSION`) reject
  decompression bombs as `400 INVALID_IMAGE`.
- **F6** - `step` is bounded (`le=100`); total decoded frames and decode
  wall-clock budgets stop iteration and set `truncated` on the video summary.
- **F7** - Persisted dev inspections are upserted into the SQLite projection
  immediately, visible without restart; `persist=false` imports nothing.
- **F8** - The dev enablement gate runs before viewer authentication: disabled
  endpoints return `404 DEV_TOOLS_DISABLED` even unauthenticated; enabled
  endpoints keep `401` for unauthenticated callers.
- **F9** - `generate-edge-openapi.py` now declares required binary request
  bodies and `400/404/413/503` problem responses for both dev operations;
  OpenAPI and TypeScript types regenerated; drift test updated.
- **F10** - DevToolsView uploads are sequenced with a monotonic request id so
  stale responses cannot overwrite the current result or clear `busy`.
- **F11** - The HTTP client sends the Blob's own media type
  (`application/octet-stream` fallback) instead of fabricating jpeg/mp4.
- **F12** - `VideoFrameInspectResult` uses the canonical `BusinessResult` /
  `InternalDecision` enums; TS unions and runtime validation enforce
  `OK|NG` / `OK|NG|UNCERTAIN`.
- **F13** (added during execution) - Multi-instance `inspection_state` no
  longer reports `faulted=true` while an enabled instance is healthy, and
  surfaces the most recent per-instance result.
- **F14** (added during execution) - Reconnect policies with
  `maximum_delay_ms < initial_delay_ms` are rejected as `ConfigError`.

Validation executed at the end of the fix pipeline (all green):

```text
git diff --check
uv run ruff check .
uv run ruff format --check .
uv run pytest          # full repo suite, exit 0 (no failures)
pnpm -r build          # exit 0
pnpm -r lint           # exit 0
pnpm -r test           # 91 passed (api-client 45, ui 13, edge-web 30, desktop 3)
cd apps/edge-web && pnpm test:e2e   # 12 passed
uv run mkdocs build --strict
```

The post-review packaging follow-up is resolved: `assemblyvision_edge` now
ships `py.typed`, and the test fixture imports `assemblyvision_edge.config`
directly so mypy resolves the typed submodule. `mypy .` passes across all 119
source files; the built wheel was verified to contain the marker.

## Validation Performed

Executed without modifying tracked implementation files:

```text
git diff --check main...HEAD
git diff --check
uv run pytest apps/edge-service/tests/test_dev_api.py apps/edge-service/tests/test_instances.py apps/edge-service/tests/test_camera_manager.py apps/edge-service/tests/test_camera_api.py packages/python/vision-core/tests/test_http_image_source.py packages/python/vision-core/tests/test_rtsp_source.py packages/python/vision-core/tests/test_folder_source.py
pnpm --filter @assemblyvision/api-client test -- --run
pnpm --filter @assemblyvision/edge-web test -- --run tests/dev-tools.test.ts
pnpm --filter edge-web test -- --run tests/dev-tools.test.ts
```

Results:

- Both diff checks passed.
- The focused Python suite passed: `45 passed` (one third-party
  `starlette.testclient` deprecation warning).
- The API-client suite passed: `37 passed`.
- The first requested edge-web command did not run because no workspace matches
  `@assemblyvision/edge-web`; the corrected `pnpm --filter edge-web ...`
  command passed: `28 passed`.
- These passing tests do not cover the failure and resource-boundary cases
  below.

## Blocking Findings

### F1. Latest-frame replacement silently discards inspection evidence

**Severity:** P0 / High

**Locations:**

- `apps/edge-service/src/assemblyvision_edge/camera_manager.py:101-105`
- `apps/edge-service/src/assemblyvision_edge/api/state.py:204-214`

`CameraSourceManager` retains only one frame. The inspection loop reads that
slot after inference completes and detects only that its sequence has changed.
When capture is faster than inference, all intervening frames are overwritten
without a record, backpressure signal, or degraded/NG outcome. For example, a
25 FPS source and 500 ms inference can discard roughly twelve frames for every
completed inspection. This conflicts with ADR-013's explicit current-MVP
semantics of one inspection for each captured frame and design 07's rule that
capture failures and missing evidence must not be silently skipped.

**Resolution:** Keep the one-frame cache exclusively for preview. Feed enabled
inspection loops from a bounded per-instance queue. Define queue saturation as
an explicit, observable condition: either apply capture backpressure or mark
the affected inspection path degraded/faulted according to the documented
policy. Do not replace a queued inspection frame with a later frame.

**Acceptance criteria:**

- A source that emits numbered frames faster than a blocking test pipeline
  either causes every accepted frame to be inspected in sequence, or produces
  the documented overflow state and metric/reason code.
- The preview endpoint still returns the most recently captured frame while
  the inspection queue is consumed independently.
- A regression test fails on the current implementation and passes after the
  queue/overflow behavior is implemented.

### F2. Pausing leaves enabled multi-instance inspection loops running

**Severity:** P0 / High

**Locations:**

- `apps/edge-service/src/assemblyvision_edge/api/state.py:204-214`
- `apps/edge-service/src/assemblyvision_edge/api/state.py:216-226`
- `apps/edge-service/src/assemblyvision_edge/api/state.py:267-307`

`pause()` updates only state fields. `_inspection_loop()` never reads
`self.paused`, so it continues to invoke `inspect_frame()` and persist results.
The multi-instance device-status path also ignores pause and can report `READY`
and `inspection_ready=true`. An operator can therefore be told inspection is
paused while the process is still emitting physical inspection decisions.

**Resolution:** Gate each inspection loop on pause before dequeuing/processing
new work. In multi-instance mode, report `PAUSED` with
`inspection_ready=false` while paused. Preserve preview/camera health if that
is intentional, but make the distinction explicit in status and documentation.

**Acceptance criteria:**

- Start an enabled instance and verify inspections occur; pause it and verify
  no further calls to `inspect_frame()` or persisted records occur.
- While paused, device status is `PAUSED`, `inspection_ready` is false, and
  alerts include `NOT_READY`.
- Resuming restarts processing only for subsequently accepted frames and does
  not treat skipped/ambiguous queue contents as positive evidence.

### F3. A bad folder-source configuration can abort all instances at startup

**Severity:** P0 / High

**Locations:**

- `packages/python/vision-core/src/assemblyvision_vision/sources/folder_source.py:35-37`
- `apps/edge-service/src/assemblyvision_edge/api/state.py:168-178`

`FolderSource` raises `ImageReadError` when its directory is missing, but
`load_instances()` catches only `FrameStreamError` around source construction.
The `ImageReadError` escapes, prevents `self.instances` and the camera manager
from being installed, and stops healthy configured instances from starting.
This violates ADR-013's required non-fatal per-instance source failure.

**Resolution:** Normalize construction errors from every `FrameSource` to
`FrameStreamError`, or catch the common `AssemblyVisionError` at the instance
boundary and install a failed source state for that instance. Do not catch
arbitrary programming errors.

**Acceptance criteria:**

- Configure one missing-folder instance and one valid looping-folder instance.
- Startup succeeds; the valid instance produces preview frames and may inspect
  when enabled.
- The invalid instance is present in status with a stable unavailable error
  code, and it cannot be selected as a usable inspection pipeline.

### F4. HTTP corrupt images and PyAV failures do not obey the frame-error contract

**Severity:** P0 / High

**Locations:**

- `packages/python/vision-core/src/assemblyvision_vision/sources/http_image_source.py:79-91`
- `packages/python/vision-core/src/assemblyvision_vision/sources/http_image_source.py:96-106`
- `packages/python/vision-core/src/assemblyvision_vision/sources/rtsp_source.py:113-137`
- `apps/edge-service/src/assemblyvision_edge/camera_manager.py:54-75`
- `apps/edge-service/src/assemblyvision_edge/camera_manager.py:98-115`

`HttpImageSource._fetch()` maps both transport errors and corrupt image bytes
to `FrameStreamError`, then `frames()` retries both cases. A corrupt response
is consequently silently skipped, contrary to ADR-013/design 07's requirement
that decode failures surface rather than disappear as absent evidence.

`RTSPFrameSource` does not translate exceptions from `av.open()`,
`container.decode()`, or `to_image()` into `FrameStreamError`. At startup an
ordinary PyAV exception escapes `CameraSourceManager.start()` and can abort
other instances. During capture it escapes the thread rather than following a
defined source error/reconnect policy.

**Resolution:** Split recoverable transport disconnects from invalid/decode
data. Retry only documented transport failures with bounded backoff; propagate
corrupt-image/decode failures as `FrameStreamError` so the manager marks the
instance failed. Wrap PyAV open/decode/conversion exceptions at the adapter
boundary as `FrameStreamError`, and add a final unexpected-exception handler in
the manager which records a camera error before terminating the thread.

**Acceptance criteria:**

- An HTTP server that returns valid bytes, corrupt bytes, then valid bytes
  faults the source on corrupt bytes; it must not emit the final frame as if no
  failure happened.
- Mocked PyAV failures at open and decode leave a healthy sibling instance
  running and expose `CAMERA_UNAVAILABLE` or `CAMERA_STREAM_ERROR` for the
  failed instance.
- No adapter exception escapes `CameraSourceManager.start()` or leaves the
  manager reporting the stream as connected after a failure.

### F5. Image uploads are fully buffered and decoded without a pixel limit

**Severity:** P0 / High

**Locations:**

- `apps/edge-service/src/assemblyvision_edge/api/routers/dev.py:61-76`

The 20 MB image limit is checked only after `await request.body()` has buffered
the complete payload. A chunked request with no `Content-Length` can consume
arbitrarily more edge-process memory before it is rejected. Also, a compressed
image below 20 MB can expand to an unbounded pixel buffer at `convert("RGB")`.
An authenticated user of an explicitly enabled development endpoint can exhaust
memory and disrupt local inspection.

**Resolution:** Stream request chunks into a bounded buffer while counting
bytes, as the video route already does. Before conversion, enforce maximum
width, height, and total pixels; treat Pillow decompression-bomb warnings and
errors as `INVALID_IMAGE`. Pick limits explicitly and document them beside the
20 MB wire-size limit.

**Acceptance criteria:**

- An over-limit chunked ASGI request is rejected with `413 PAYLOAD_TOO_LARGE`
  before a body larger than the configured limit is accumulated.
- A small compressed fixture exceeding the decoded-pixel limit returns
  `400 INVALID_IMAGE` and does not invoke the pipeline.
- A valid image within both byte and pixel limits produces the same
  `InspectionRecord` behavior as before.

### F6. Video sampling bounds inspected frames but not decode work

**Severity:** P1 / High

**Locations:**

- `apps/edge-service/src/assemblyvision_edge/api/routers/dev.py:94`
- `apps/edge-service/src/assemblyvision_edge/api/routers/dev.py:141-152`

`step` has no maximum. Every skipped frame is fully decoded by
`VideoFrameSource` before the modulo condition is evaluated. With a large
`step`, the route may inspect one frame and then decode the remaining 100 MB
video searching for the next selected frame. The advertised maximum of thirty
frames bounds inference calls only, not decoder CPU time or elapsed request
time.

**Resolution:** Bound `step` and total decoded frames independently, and add a
wall-clock decode budget. Prefer seek-based sampling if codec support permits;
otherwise return a bounded problem response when the decode-frame or time
budget is reached. Document the selected policy in ADR-014/API documentation.

**Acceptance criteria:**

- A fake source with many frames and a very large `step` stops at the decoded
  frame/time budget instead of iterating the complete source.
- A too-large `step` is rejected by request validation.
- The response clearly identifies whether results are complete or stopped by a
  documented resource limit; it must not imply that all video frames were
  analyzed.

### F7. Persisted developer inspections are not visible until process restart

**Severity:** P1 / High

**Locations:**

- `apps/edge-service/src/assemblyvision_edge/api/routers/dev.py:86-87`
- `apps/edge-service/src/assemblyvision_edge/api/app.py:81-85`

The persisted frame path writes an output bundle only. Reconciliation imports
bundles only during application startup, so the returned inspection is absent
from history and inspection-detail endpoints until the service restarts. This
contradicts ADR-014's stated behavior that persisted results appear in dashboard
history.

**Resolution:** After successful atomic bundle publication, import/upsert the
record through the same repository reconciliation path before returning `200`.
Preserve the output bundle as the source of truth for the current M1 read
projection, and define a fail-safe response if publication succeeds but the
projection cannot be updated.

**Acceptance criteria:**

- POST a persisted frame to a live application, then immediately request its
  inspection detail and history entry without restart; both return the record.
- `persist=false` does not create a bundle or projection entry.
- Reconciliation after restart remains idempotent and does not duplicate the
  immediately imported record.

### F8. Disabled dev endpoints return 401 before their required 404 gate

**Severity:** P1 / Medium

**Locations:**

- `apps/edge-service/src/assemblyvision_edge/api/app.py:135-147`
- `apps/edge-service/src/assemblyvision_edge/api/routers/dev.py:39-50`

All routers receive the application-level `require_viewer` dependency before
the dev router's dependency runs. With an API token configured and
`enable_web_test=false`, an unauthenticated request receives `401
UNAUTHENTICATED`, rather than ADR-014's required `404 DEV_TOOLS_DISABLED`.
The disabled surface is consequently distinguishable and the explicit
disabled-by-default contract is not met. The current tests include the router
in isolation and do not exercise this dependency ordering.

**Resolution:** Route dev requests through the enablement gate before viewer
authentication, while retaining viewer authentication whenever the feature is
enabled. This can be an application-level conditional dependency or a small
dedicated router inclusion path; do not weaken auth for enabled endpoints.

**Acceptance criteria:**

- In a full `create_app()` instance with a configured token and web tests
  disabled, authenticated and unauthenticated dev requests both return `404
  DEV_TOOLS_DISABLED`.
- With web tests enabled, unauthenticated requests return the standard `401`
  and valid bearer/session authentication can invoke the endpoints.

### F9. OpenAPI and generated TypeScript do not describe the shipped dev API

**Severity:** P1 / High

**Locations:**

- `apps/edge-service/openapi/edge-openapi.json:2156-2275`
- `packages/typescript/api-client/src/edge/generated/api.ts:1231-1293`
- `apps/edge-service/src/assemblyvision_edge/api/routers/dev.py:53-96`

The generated operations have `requestBody?: never` and only document success
and validation responses, while the routes require raw image/video media and
return `400`, `404`, `413`, and `503` problem responses. Consumers generated
from the committed contract cannot make a typed call to the API or handle its
actual errors. This breaks the OpenAPI-to-TypeScript boundary required for
shipped APIs.

**Resolution:** Declare required binary request bodies with the accepted media
types and document every runtime error as `application/problem+json` using the
canonical `Problem` schema. Regenerate `edge-openapi.json` and TypeScript API
types, then make the handwritten wrapper consume the generated request/response
types instead of bypassing them.

**Acceptance criteria:**

- Both dev operations specify required binary request bodies and enumerate
  `200`, `400`, `404`, `413`, and `503` responses as applicable.
- Regenerated TypeScript types accept image/video request bodies and expose the
  declared responses.
- An OpenAPI regression test asserts the media schemas and problem responses;
  the existing OpenAPI drift check passes.

## Follow-Up Findings

### F10. The developer-tools page allows stale concurrent results to overwrite the current upload

**Severity:** P2 / Medium

**Locations:**

- `apps/edge-web/src/pages/DevToolsView.vue:31-62`

Selecting image A starts request A; selecting image B resets the UI and starts
request B. If A completes after B, it overwrites the result while the preview
still displays B. A's `finally` also clears `busy` while B remains active. This
can display a decision for a different image and permits duplicate submission.

**Resolution:** Abort the previous request or use a monotonically increasing
request ID and apply `record`, `videoResult`, `error`, and `busy` changes only
for the current request.

**Acceptance criteria:** A deferred-promise component test starts two uploads,
resolves the first after the second, and proves only the second result remains
while `busy` stays true until the second settles.

### F11. Client content types are fabricated for non-JPEG/non-MP4 uploads

**Severity:** P2 / Medium

**Locations:**

- `apps/edge-web/src/pages/DevToolsView.vue:96-104`
- `packages/typescript/api-client/src/edge/HttpApiClient.ts:215-242`

The UI accepts all browser image/video media, but the HTTP client labels every
image `image/jpeg` and every video `video/mp4`. PNG, HEIC, WebM, MOV, and AVI
payloads are therefore misrepresented to proxies and future media validators.

**Resolution:** Send `Blob.type` when available and use
`application/octet-stream` only as a fallback. Narrow the file-picker types or
expand the documented API media types to exactly match the decoders that are
supported.

**Acceptance criteria:** Client tests using PNG and WebM/QuickTime `File`
objects verify that outgoing `Content-Type` preserves each file's MIME type,
and OpenAPI states the supported set.

### F12. Video decision fields are weakened to arbitrary strings

**Severity:** P2 / Medium

**Locations:**

- `apps/edge-service/src/assemblyvision_edge/api/schemas.py:77-93`
- `packages/typescript/api-client/src/edge/types.ts:399-414`
- `packages/typescript/api-client/src/edge/validate.ts:222-236`

`VideoFrameInspectResult` uses unconstrained strings for both decisions, and
the frontend validator accepts any values. The API can therefore represent a
business result of `UNCERTAIN`, even though the safety contract permits only
`OK` or `NG` as a business result.

**Resolution:** Use the canonical `BusinessResult` and `InternalDecision`
enums in the Pydantic response model, regenerate API types, and validate the
same allowed values at the TypeScript boundary.

**Acceptance criteria:** OpenAPI exposes decision enums, TypeScript uses the
corresponding unions, and validation rejects `business_result: "UNCERTAIN"` and
unknown internal decisions.

## Findings Added During Execution (F13, F14)

The runtime audit that produced F1-F4 also surfaced two additional defects in
the same lifecycle/configuration surfaces. They were implemented together with
the blocking fixes and are recorded here for completeness.

### F13. Multi-instance inspection state always reported faulted

**Severity:** P1 / Medium

**Locations:** `apps/edge-service/src/assemblyvision_edge/api/state.py:324-334`

In multi-instance mode `self.pipeline` is always `None`, so
`inspection_state()` reported `faulted=true` even while enabled instances were
inspecting, and it surfaced no per-instance last result.

**Resolution:** Derive fault from the configured instances (faulted only when
no instance has a usable pipeline) and surface the most recent per-instance
last result in multi-instance mode.

**Acceptance criteria:** A healthy enabled multi-instance runtime reports
`faulted=false` and exposes an instance's latest result.

### F14. Reconnect backoff allowed maximum delay below initial delay

**Severity:** P1 / Medium

**Locations:** `apps/edge-service/src/assemblyvision_edge/config.py:521-542`

A reconnect policy with `maximum_delay_ms < initial_delay_ms` was accepted,
making the first retry exceed the declared maximum and violating the bounded
backoff contract.

**Resolution:** Reject such policies with `ConfigError`.

**Acceptance criteria:** Loading an instance with `initial_delay_ms: 1000` and
`maximum_delay_ms: 100` raises `ConfigError`.

## Global Acceptance Rules

Every blocking item is accepted only when:

- A regression test fails on this branch and passes after the fix.
- Tests exercise the applicable public/lifecycle boundary, not only mocked
  private helpers: HTTP for F5-F9, manager/runtime lifecycle for F1-F4.
- `ruff check .`, `ruff format --check .`, `mypy .`, `pytest`, the TypeScript
  build/lint/tests, API generation/drift validation, and the correct edge-web
  developer-tools test command all pass.
- The design documents and ADRs are updated if resource limits, overflow
  semantics, or error/reconnect behavior change.
