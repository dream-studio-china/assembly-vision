# 05 — Edge-Service Internals

How the runtime really works, function by function. All paths relative to
`apps/edge-service/src/assemblyvision_edge/`.

## How an image becomes an inspection record (`inspect`)

1. `cli._run_inspect` → `_open_durable_rule_registry(output)` opens
   `EdgeRepository.open(output / "edge.sqlite3")` (the durable rule-identity
   registry, shared with `serve`; fail-closed if it cannot open).
2. `_build_pipeline` loads config + rule + both manifests and validates:
   `validate_model_version_declaration` (declared `model_version` must equal
   the manifest label) and `validate_rule_component_compatibility` (every
   rule-required component exists in config; the component manifest version
   is in `compatible_component_model_versions`; a `barcode_required` rule
   requires enabled+required `identity.barcode` config). Detectors are built
   from manifests.
3. For each `(source, path)`: `pipeline.inspect_image(source, path, writer)`.

`InspectionPipeline._inspect_impl` (`pipeline.py:536`) — the core flow:

1. Generate `inspection_id`, `frame_id`, `started_at` (UTC).
2. `_detect_frame(frame, frame_id)`:
   - `product_detector.detect(frame, frame_id)`; `DetectionError` → append its
     `reason_code` (e.g. `INFERENCE_ERROR`); no selection → `NO_PRODUCT`.
   - Provenance check `_validate_product_provenance`: `detection.frame_id ==
     frame_id`, `model_version_id == manifest.model_version_id`, and the box
     dimensions match the frame — any mismatch → `INFERENCE_ERROR`.
   - `roi_engine.generate(frame, frame_id, product_box)`; failure →
     `ROI_INVALID`; success sets gate `roi_valid=True`.
   - `component_detector.detect(roi_image, frame_id, required_components,
     transform_full_to_roi, frame_size)`.
   - Component provenance check: transform must be a pure translation,
     per-observation `frame_id`/`model_version_id` must match, `roi_bbox`
     size == ROI size, `full_frame_bbox` size == frame size, and
     `apply_transform(roi_box, inverse) == full_frame_box` within
     `_COORD_TOLERANCE = 1e-6` — else observations dropped +
     `INFERENCE_ERROR`.
3. `_build_evidence(observations, gates, frame_readable, frame_id)`:
   per required component → `PRESENT` (hits), `MISSING` (valid inference, no
   hits, `COMPONENT_MISSING` policy reason), or `UNCERTAIN`
   (`COMPONENT_UNVERIFIABLE`) when inference was invalid.
4. Identity: `identity_verified = identity.verified if identity else not
   rule.barcode_required`; unverified identity adds
   `PRODUCT_IDENTITY_UNVERIFIED`.
5. `rule_engine.evaluate(context, rule)` — any raised
   `RuleEvaluationError` → extra reason `RULE_EVALUATION_ERROR`,
   `decided=None`.
6. **Fail-closed merge**: `final_reasons = decided.reasons ∪ extra_reasons`;
   `internal = NG if final_reasons else OK`; `business_result = NG if
   internal != OK else OK`. Any extra reason (read error, detection failure,
   provenance mismatch, unverified identity, rule-eval error) forces `NG`.
7. Collect inference metadata (model, version, input size, latency, device,
   thresholds), build the `InspectionRecord`
   (`aggregation_policy_version="single-frame-mvp-1"` for single frames),
   annotate the frame (product boxes green, component boxes red), then
   `writer.save(...)`.

`OutputWriter.save` (`output/writer.py:96`) — atomic publish:
staging dir `.staging-<inspection_id>-<uuid>` → write `key_frame.jpg`
(`KEY_FRAME`), `product_roi.jpg` (`PRODUCT_ROI`), `annotated_frame.jpg`
(`ANNOTATED_FRAME`) via temp+fsync+rename (JPEG q90) → write
`inspection.json` (`record.model_dump(mode="json")`, indent 2, sort_keys) →
fsync dir → rename staging to `<output>/<inspection_id>/` → fsync parent.
`record.media` reflects exactly what was written. Re-publishing the same
inspection id → `OutputError`. At critical/stop disk pressure, only *OK*
samples suppress optional media; NG evidence and metadata always persist.

## How `serve` runs live inspection

Composition root `api/app.py:create_app(settings)`:
- `runtime = EdgeRuntime(settings)`; lifespan: open repository → create
  `RuntimeEventBus(source_id=device_id)` → `reconcile_output_root` +
  `scan_storage_integrity` → `runtime.load_config(repository)` (multi-instance
  `load_edge_config`, falling back to the legacy single pipeline) →
  optionally start `UploadScheduler` + `RetentionCleanupWorker`.

`EdgeRuntime.load_instances` (`api/state.py:170`):
- Load edge config; per-instance build pipeline with the shared
  `ModelRegistry`; `device_id = uuid5(_INSTANCE_NAMESPACE, instance_id)`
  unless configured; build `IdentityCorrelator(MockTriggerSource(...))` when
  a `trigger:` block exists; `build_frame_source(...)` per camera (a failing
  instance is non-fatal); instances with `inspection.enabled and pipeline`
  subscribe a bounded queue (maxsize 8) and start a daemon
  `_inspection_loop`.

Capture thread (`camera_manager.py`): `source.open()` → `_capture_loop`
iterates `source.frames(stop)` → `_publish_frame`: stores `state.last_frame`
(preview memory) and `inspection_queue.put_nowait(frame)`; on `queue.Full`
increments `frames_dropped` and sets `degraded=True` (explicit overflow,
never silent loss).

`_inspection_loop` (`api/state.py:268`) per iteration:
1. If paused → drain queue, sleep.
2. `refresh_storage()` — on failure latches `storage_write_fault`.
3. If write-faulted → `probe_persistence()` clears the latch only when a
   SQLite probe write **and** a probe file write+fsync both succeed.
4. If blocked (`write_fault or integrity_fault or mode == "STOP"`) → drain,
   no intake.
5. `optional = _optional_capture_suppressed()` (CRITICAL/STOP modes).
6. `next_frame(instance_id)`:
   - `None` → `window_manager.expire(now)`; an expired window → `inspect_window`
     → `_persist_projection`.
   - Frame → `correlator.annotate(frame)` stamps `product_identity`; then
     - **Temporal branch**: `pipeline.frame_observations(frame)` →
       `window_manager.feed(observation, frame.monotonic_ts_ns/1e9)`
       (acquisition-time monotonic clock); new window → publish
       `inspection.started`; closed window → `inspect_window` →
       `_persist_projection`.
     - **Single-frame branch**: publish `inspection.started` (before
       inference) → resolve barcode identity if enabled →
       `pipeline.inspect_frame(frame, writer, inspection_id=..., identity=...)`
       → `_persist_projection`.
7. Shutdown → `window_manager.force_close()` → interrupted window closed as
   `NG` with `INSPECTION_INTERRUPTED` (partial evidence never reconstructed).

`_persist_projection` (`api/state.py:464`):
`repository.persist_inspection_and_enqueue_uploads(record, retention=...)`
— atomic upsert of the immutable projection + one `INSPECTION` task + one
`MEDIA` task per artifact in a single transaction. Failure → latch
`storage_write_fault`, **no** `inspection.completed` event published.
Success → publish `inspection.completed` with
`{inspection_id, instance_id, business_result, internal_decision}`.

## Config loading and validation gates

`config.py`:
- `load_pipeline_config` → `_parse_pipeline_doc`: unknown top-level keys
  rejected; `product_detection` keys `{model_version, confidence_threshold
  (default 0.7), iou_threshold (default 0.5)}`; `component_detection` keys
  `{model_version, iou_threshold, components}` with per-component
  `observation_threshold` (default 0.5); at least one component; `roi` built
  into `ROIConfig` (invalid geometry → `ConfigError`);
  `normalize_perspective=True` rejected; `identity.barcode`
  `{enabled, required, allowed_symbologies, mapping_file}` with a
  duplicate-key-rejecting YAML loader for the flat exact barcode→product
  map.
- `load_rule_definition` → `RuleDefinition.model_validate` →
  `_register_rule_identity`: process-local registry keyed
  `(rule_id, rule_version)` against the SHA-256 of canonical JSON; re-loading
  the same identity with different content → `ConfigError`; then the durable
  callback into SQLite `rule_identities` (`RepositoryError` on mismatch).
- `load_edge_config`: per-instance gates — unique `instance_id`; `device_id`
  parses as UUID; camera source type-specific required fields; `fps > 0`;
  `reconnect.maximum_delay_ms >= initial_delay_ms`; `gige-vision` requires
  `serial` + `gentl_producer`; temporal: `medium_confidence` strictly `<
  high_confidence`, `observation_threshold <= medium_confidence`,
  `identity.barcode` rejected with temporal, enabled temporal inspection
  requires `window_strategy: identity`; `trigger` accepts only
  `source: mock`.
- `_build_instance_pipeline` adds
  `validate_temporal_against_rule` (exactly one policy per rule-required
  component).

## Rule engine

`rules/rule_engine.py`:
- `rule_version_id(rule)` = `uuid5(NAMESPACE, canonical JSON)` — any content
  change yields a new identity.
- `RuleEngine.evaluate(context, rule)` (static, deterministic) checks in
  order, accumulating reasons (any reason → NG):
  1. `schema_version != 1` → `CONFIG_INVALID`.
  2. empty `required_components` → `CONFIG_INVALID`.
  3. `component_model_version not in compatible_component_model_versions` →
     `VERSION_INCOMPATIBLE`.
  4. `barcode_required and not product_identity_verified` →
     `PRODUCT_IDENTITY_UNVERIFIED`.
  5. mandatory gates: `context.gates.get(gate) is not expected` →
     `GATE_FAILED:<gate>`.
  6. per component: missing evidence → `COMPONENT_UNVERIFIABLE:<key>`;
     state != `PRESENT` → `COMPONENT_MISSING|UNCERTAIN|UNVERIFIABLE:<key>`;
     **incomplete PRESENT evidence** (`usable_frame_count < 1`,
     `best_confidence is None`, non-finite confidence, or no supporting
     frame ids) → `COMPONENT_UNVERIFIABLE`; `detection_count !=
     expected_count` → `COMPONENT_COUNT_INVALID`; `_spatial_violation`
     (missing/non-finite/out-of-range area ratio or center outside
     `allowed_zone`) → `COMPONENT_SPATIAL_INVALID`.
- `InspectionDecision` carries sorted `missing_components`,
  `low_confidence_components`, sorted `reason_codes`.

## Temporal windows

`temporal/window_manager.py` — `ProductWindowManager.feed(observation,
now_monotonic)`:
- Stale watermark: frames older than the cutoff are dropped (counted), even
  after a window closes (a late queued pre-expiry frame cannot open a new
  window).
- `multi_product` → close active window as integrity violation
  (`MULTIPLE_PRODUCTS`).
- Identity strategy: no active window + no identity → drop; quarantined
  identity → drop; active + identity None → close `IDENTITY_MISSING`; active
  + different identity → close `IDENTITY_TRANSITION` + open new; same
  identity → feed.
- Gap: `now - last_frame_at >= maximum_window_ms` → close `GAP`, open new.
- Max duration: identity strategy closes as `MAX_DURATION`
  (`WINDOW_MAX_DURATION_EXCEEDED`) with identity quarantine; time strategy
  closes and opens new.
- `expire(now)` closes the active window as `GAP` on idle.
- `force_close()` (shutdown) → `INTERRUPTED` + `INSPECTION_INTERRUPTED`,
  frames cleared.

`temporal/aggregator.py` — `TemporalAggregator.aggregate(frames,
required_components)`:
- Deduplicate by `frame_id` when configured; keep only usable opportunities.
- Per component `_resolve_component`: opportunities < `minimum_valid_frames`
  → `UNVERIFIABLE` (`INSUFFICIENT_VALID_FRAMES`); no policy →
  `UNVERIFIABLE` (`COMPONENT_POLICY_MISSING`); no hits → `MISSING`
  (`COMPONENT_MISSING`); any hit ≥ `high_confidence` → `PRESENT`; medium
  policy requires `medium_hits` distinct frame sequences with
  `require_adjacent_hits` honoring `max_frame_gap` → else `UNCERTAIN`.
- `_present`: `detection_count` = **max per single frame** of detections at
  or above `count_threshold` (policy `medium_confidence` at minimum) — a
  low-confidence hit cannot inflate an exact count.
- `temporal_policy_version(config)` = SHA-256 of the canonical policy
  document, persisted as `aggregation_policy_version`.

## Detectors and model registry

- `ProductDetector.from_manifest` requires `task == PRODUCT_DETECTION` and
  class_names containing `product`; `ComponentDetector.from_manifest`
  requires every configured component in class_names. Both call
  `verify_manifest_artifact` (size + SHA-256, relative URI inside the bundle
  root) and `verify_model_class_map` (contiguous 0..n-1 matching the
  manifest order). Inference `imgsz = (input_height, input_width)`.
- `ComponentDetector.detect` filters to rule-required codes and per-component
  `observation_threshold`, maps `roi_bbox` → `full_frame_bbox` via the
  inverse translation transform.
- `ModelRegistry` (`detection/registry.py`): key `"{artifact_sha256}:{device
  or 'default'}"`; first load wins, shared inference lock per handle
  (ultralytics predictors keep mutable state; distinct artifacts/devices
  never share).

## Persistence/upload/retention (see also 07)

- `persist_inspection_and_enqueue_uploads` — one transaction: immutable
  inspection + evidence + media + outbox tasks.
- `UploadScheduler` — claims due tasks under lease + fencing token; `MEDIA`
  tasks due only after their inspection task has a verified receipt;
  transient failures → full-jitter backoff honoring `Retry-After`; missing/
  corrupt evidence and server conflicts → permanent failures; 2xx counts
  only with a matching typed receipt.
- `RetentionCleanupWorker` — receipt-gated eligibility, fenced deletion via
  `O_NOFOLLOW` dir file descriptors; missing files are integrity faults;
  zero deletion without an approved enabled policy.
