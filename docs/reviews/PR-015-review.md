# PR-015 Review: Per-Component Temporal Aggregation and Product Windows

## Scope

Code review of `feat/temporal-aggregation` against `main` (PR #15). The
review covers the ADR-010 product-window and per-component aggregation
implementation, its edge-runtime integration, configuration, generated API
contracts, documentation, and focused tests.

Relevant requirements reviewed:

- `docs/design/10-temporal-aggregation.md`
- `docs/design/decisions/ADR-010-per-component-temporal-aggregation.md`
- `docs/contracts/03-ai-rule-and-safety-contracts.md`
- `docs/contracts/06-testing-quality-and-ci-contracts.md`

## Merge Decision

**Do not merge until F1-F7 are resolved.**

The PR introduces the correct high-level separation of frame observations,
temporal aggregation, and rule evaluation. However, its current time-only
window implementation can merge evidence from different physical products and
return `OK`. It also fails to finalize idle windows, uses processing time rather
than acquisition time, accepts unusable frames as evidence, and permits
unconfigured or insufficiently qualified evidence to satisfy rules. These are
product-decision safety defects, not cosmetic follow-up work.

## Resolution Status

All findings in this review (F1-F7) have been fixed and validated on
`feat/temporal-aggregation` by focused commits, each carrying regression tests
that failed before the fix and pass after:

- **F1** - `window_strategy: identity` seals each product window to one
  validated per-frame product identity carried on `CapturedFrame`; a missing
  identity, a mid-window identity transition, or a confirmed multi-product
  frame closes the window as an integrity violation
  (`PRODUCT_IDENTITY_MISSING` / `PRODUCT_IDENTITY_TRANSITION` /
  `MULTIPLE_PRODUCTS`) that can never release `OK`. The time-only strategy is
  an explicit development fallback. Integration tests prove complementary
  components from two identities inside one interval never produce `OK`, a
  same-identity complete window still produces exactly one `OK`, and a missing
  identity mid-window aborts as `NG`. A detector-confirmed
  `MULTIPLE_PRODUCTS` outcome is propagated to this integrity path rather than
  retained as a diagnostic-only frame reason.
- **F2** - `ProductWindowManager.expire()` finalizes an idle window as `GAP`;
  the inspection loop calls it on every empty capture poll. A final product
  with no further frames is decided normally, and shutdown after normal expiry
  adds no second record.
- **F3** - the runtime feeds windows with `CapturedFrame.monotonic_ts_ns`
  (acquisition time) instead of post-inference `time.monotonic()`; stale
  out-of-order timestamps are dropped and counted. Idle expiry retains a
  capture-time cutoff, preventing a queued pre-expiry frame from reopening a
  finalized product window. Fast vs. delayed inference therefore cannot change
  window membership.
- **F4** - `frame_observations()` derives `quality_usable` from the
  product-detection quality gate and preserves its reason codes; unusable
  frames contribute no detections, no valid opportunities, and no count
  evidence.
- **F5** - per-frame rejection reasons are frame diagnostics in
  `FrameQualitySummary` only; the rule engine decides from aggregated evidence,
  and only window-integrity violations (interruption, identity mixing, missing
  identity, rule-evaluation failure) independently force `NG`.
- **F6** - an enabled temporal configuration must provide exactly one policy
  for every rule-required component (validated after the rule loads at
  instance pipeline build) and rejects policies for unrequired components; a
  missing policy resolves defensively to `UNVERIFIABLE` with
  `COMPONENT_POLICY_MISSING`; `medium_confidence < high_confidence` is strict
  in both the dataclass and the YAML parser.
- **F7** - `detection_count`, box-area, and center summaries include only
  detections at or above the policy `medium_confidence` count-evidence
  threshold; a low-confidence box cannot inflate an exact `expected_count`.

## Follow-up TODOs

- [x] **Policy identity**: `aggregation_policy_version` stores the full
  SHA-256 of the canonical temporal policy document, including format, window
  parameters, and component thresholds/hit rules. A regression test verifies
  that a policy change produces a distinct persisted identity.
- [x] **Production boundary enforcement**: configuration rejects
  `inspection.enabled: true` with `window_strategy: time`; time-only grouping
  remains usable only in disabled/local development configuration and cannot
  prove physical-product isolation.
- [x] **Maximum-duration isolation**: an identity-sealed window that reaches
  `maximum_window_ms` closes as `NG` with `WINDOW_MAX_DURATION_EXCEEDED`; the
  identity is quarantined and cannot begin a new window until a different
  validated identity proves a product transition. Regression tests cover both
  the window-manager and end-to-end decision paths.

Validation executed after the fixes (all green):

```text
git diff --check origin/main...HEAD
uv run ruff check .
uv run ruff format --check .
uv run mypy .
uv run pytest            # full repo suite, exit 0
pnpm -r build            # exit 0
pnpm -r lint             # exit 0
pnpm -r test             # TS unit suites
cd apps/edge-web && pnpm test:e2e
uv run mkdocs build --strict
```

## Validation Performed

Executed on `feat/temporal-aggregation` without modifying implementation
files:

```text
git diff --check origin/main...HEAD
uv run pytest apps/edge-service/tests/test_temporal_aggregator.py apps/edge-service/tests/test_product_window.py apps/edge-service/tests/test_temporal_pipeline.py apps/edge-service/tests/test_edge_config.py apps/edge-service/tests/test_instances.py apps/edge-service/tests/test_rule_engine.py -q
```

Results:

- The diff check passed.
- The focused temporal, runtime, configuration, and rule-engine tests passed.
- The passing tests do not exercise the safety cases described below.

## Blocking Findings

### F1. Time-only grouping can merge different products and return `OK`

**Severity:** P0 / Critical

**Locations:**

- `apps/edge-service/src/assemblyvision_edge/temporal/window_manager.py:117-139`
- `apps/edge-service/src/assemblyvision_edge/api/state.py:250-255`

`ProductWindowManager.feed()` accepts every non-duplicate frame that arrives
within `maximum_window_ms`. No product identity, trigger boundary, barcode,
entry/exit event, validated tracker continuity, or multiple-product check
separates its evidence. Therefore a first product that supplies only
`component_a` and a second product that supplies only `component_b` and
`manual` can form one all-`PRESENT` window and be evaluated as `OK`.

This violates the physical-product evidence-isolation invariant in design 10
sections 10.2 and 10.3, the mixed-window exclusion requirement in section
10.8, ADR-010 section 3, and contract 06 section 5's required mixed-product
test.

**Resolution:**

1. Make a validated correlation/boundary mechanism an explicit requirement for
   enabled temporal inspection: for example, a hardware trigger, barcode event,
   validated tracker identity, or site-validated entry/exit-zone protocol.
2. Carry the correlation identity and capture-time provenance in
   `FrameObservation` and enforce continuity in `ProductWindowManager`.
3. If continuity cannot be proven, close/abort the window with a durable
   window-integrity reason and produce `NG`/`UNVERIFIABLE`; never aggregate its
   observations with another product.
4. Do not present a plain time-only gap as a production-safe product boundary
   unless the site-validation constraints that prove no overlap are encoded and
   enforced.

**Acceptance criteria:**

- An integration test puts complementary required-component detections from two
  different product identities inside one duration/gap interval and verifies
  that neither product produces `OK`.
- An identity transition, missing boundary signal, and confirmed multi-product
  frame each result in an aborted or unverified `NG` record with a stable reason
  code.
- A same-identity window with all required component evidence can still produce
  exactly one `OK` record.
- The contract-required mixed-product test is retained in the normal test suite.

### F2. A final idle window is never normally finalized

**Severity:** P1 / High

**Locations:**

- `apps/edge-service/src/assemblyvision_edge/api/state.py:246-255`
- `apps/edge-service/src/assemblyvision_edge/temporal/window_manager.py:117-139`

Gap expiration is checked only by `feed()` when a later frame arrives. When
`next_frame()` times out, the runtime immediately continues. A product at the
end of a stream therefore remains open until process shutdown, at which point
`force_close()` discards the collected evidence and emits an interrupted `NG`.
This fails design 10 section 10.8's timeout-close behavior and loses otherwise
complete decisions.

**Resolution:**

1. Add a non-interrupted `expire(now_monotonic)` operation to
   `ProductWindowManager`; it should close the active window as `GAP` once its
   idle duration reaches the configured limit.
2. Call `expire(time.monotonic())` on every empty `next_frame()` poll and send
   a returned window through `inspect_window()`.
3. Keep `force_close()` exclusively for shutdown/restart interruption.

**Acceptance criteria:**

- A complete window followed by no frames for `maximum_window_ms` persists one
  normal decision without receiving a trigger frame.
- Shutting down after normal expiry does not create a second, interrupted
  record.
- Shutting down before expiry creates one `NG` record containing
  `INSPECTION_INTERRUPTED` and no reconstructed partial evidence.

### F3. Window membership is determined by post-inference time, not capture time

**Severity:** P1 / High

**Locations:**

- `apps/edge-service/src/assemblyvision_edge/api/state.py:251-252`
- `packages/python/vision-core/src/assemblyvision_vision/sources/frame_source.py:33-38`

The runtime supplies `time.monotonic()` after `frame_observations()` completes.
Inference latency, queue backlog, or scheduler delay can consequently split
contiguous captured frames or merge separately captured products. Each
`CapturedFrame` already contains its acquisition monotonic timestamp in
`monotonic_ts_ns`, but it is not used by the window manager.

**Resolution:**

1. Convert `CapturedFrame.monotonic_ts_ns` to seconds and pass it to
   `ProductWindowManager.feed()` for all membership and duration comparisons.
2. Use the runtime monotonic clock only for idle-expiration polling.
3. Reject stale/out-of-order capture timestamps deterministically as unusable
   evidence or a window-integrity failure; do not silently reorder them.

**Acceptance criteria:**

- Given identical capture timestamps, a fast detector and an intentionally
  delayed detector produce identical window membership and final decisions.
- Queued frames from different capture-time windows cannot merge merely because
  they are drained quickly after a stall.
- Out-of-order timestamps have documented `NG`/discard behavior and regression
  coverage.

### F4. The temporal path marks every detected-product frame as quality-usable

**Severity:** P1 / High

**Locations:**

- `apps/edge-service/src/assemblyvision_edge/pipeline.py:254-272`
- `apps/edge-service/src/assemblyvision_edge/temporal/window_manager.py:65-70`

`frame_observations()` sets `quality_usable=True` unconditionally, although the
available `ProductDetection.quality.usable` carries the actual quality-gate
result. A blurred or otherwise unusable frame with a high-confidence component
detection can count toward `minimum_valid_frames` and establish `PRESENT`.
This violates contract 03 section 5 and design 10 sections 10.3 and 10.6.

**Resolution:**

1. Set `FrameObservation.quality_usable` from the evaluated frame-quality gate
   (`outcome.product_detection.quality.usable` when a product is detected).
2. Preserve frame-quality rejection reason codes in the observation and
   `FrameQualitySummary`.
3. Ensure an unusable frame cannot contribute detections, valid opportunities,
   or count evidence to the temporal aggregator.

**Acceptance criteria:**

- A `quality.usable=False` frame with high-confidence component boxes does not
  establish `PRESENT` and does not increment `usable_frame_count`.
- A window whose remaining usable frames are below `minimum_valid_frames`
  resolves every required component to `UNVERIFIABLE` and produces `NG`.
- The persisted frame-quality summary counts the rejected frame and includes
  its quality reason code.

### F5. Any rejected frame forces `NG` despite sufficient valid temporal evidence

**Severity:** P1 / High

**Locations:**

- `apps/edge-service/src/assemblyvision_edge/pipeline.py:289-328`

All per-frame failure reasons are copied into `window_reasons`, unioned into
the final decision reasons, and `final_reasons` unconditionally changes an
otherwise successful rule decision to internal `NG`. Thus a window with the
required valid high-confidence evidence plus one transient `NO_PRODUCT`, ROI
failure, or detector error cannot be `OK`.

This contradicts design 10 sections 10.3 and 10.8: rejected frames do not
contribute, while queue loss and inference errors reduce valid opportunities and
can only move evidence toward `UNCERTAIN` or `UNVERIFIABLE`. It also makes the
new aggregation robustness ineffective for intermittent rejected frames.

**Resolution:**

1. Persist rejected-frame reasons as frame diagnostics and in
   `FrameQualitySummary`, rather than treating all of them as window-level
   decision reasons.
2. Let the rule engine decide from aggregated evidence and mandatory gates.
3. Independently force `NG` only for documented window-integrity failures, such
   as interruption, identity mixing, or mandatory barcode/product-resolution
   failure.

**Acceptance criteria:**

- A window meeting all component policies and `minimum_valid_frames` remains
  `OK` when it also contains one rejected non-integrity frame.
- That frame's reason remains persisted and its usable-opportunity count is
  zero.
- An interrupted or mixed-identity window remains `NG` even if other frames
  satisfy every component policy.

### F6. Missing policies and equal thresholds are not fail-closed

**Severity:** P1 / High

**Locations:**

- `apps/edge-service/src/assemblyvision_edge/temporal/aggregator.py:127-164`
- `apps/edge-service/src/assemblyvision_edge/config.py:599-622`

Required components need not have a temporal policy. The aggregator substitutes
`1.0` for both thresholds when a policy is absent, and uses inclusive `>=`, so
an exact-confidence `1.0` detection can become `PRESENT` without a configured,
versioned policy. The configuration parser also allows
`medium_confidence == high_confidence`, despite the design 10 requirement
`observation_threshold <= medium_confidence < high_confidence`.

**Resolution:**

1. After loading the rule, reject an enabled temporal configuration unless it
   supplies exactly one policy for every required component and no unknown
   component keys.
2. Enforce `medium_confidence < high_confidence` in both
   `ComponentTemporalPolicy` and configuration parsing.
3. Defensively resolve missing policies to `UNVERIFIABLE` with an explicit
   configuration reason if invalid configuration reaches the aggregator.

**Acceptance criteria:**

- Configuration loading rejects missing required policies, extra policy keys,
  and equal medium/high thresholds.
- An aggregation unit test proves that an absent policy cannot yield `PRESENT`,
  including for confidence `1.0`.
- A valid complete policy retains the documented high-hit and medium-hit paths.

### F7. Below-threshold detections can satisfy exact component counts

**Severity:** P1 / High

**Locations:**

- `apps/edge-service/src/assemblyvision_edge/temporal/aggregator.py:159-164`
- `apps/edge-service/src/assemblyvision_edge/temporal/aggregator.py:201-240`

Once a high-confidence or qualifying medium hit establishes `PRESENT`,
`_present()` computes `detection_count`, boxes, and centers from every raw
detection for that component in the selected frame. A low-confidence false
positive can therefore inflate a frame from one qualifying detection to the
rule's exact expected count. For example, with `expected_count=2`, detections
at `0.95` and `0.50` in one frame can report `detection_count=2` after the
`0.95` detection establishes presence.

**Resolution:**

1. Define and document a count-evidence confidence threshold; at minimum it
   must be `medium_confidence`.
2. Pass only qualifying detections to the count, area-ratio, and center summary
   used by count/spatial rules.
3. Keep below-threshold observations available in diagnostics if needed, but
   never use them to satisfy a business rule.

**Acceptance criteria:**

- One high-confidence detection plus one below-medium detection reports a
  count of one and fails an `expected_count=2` rule as `NG`.
- Two qualifying detections in one valid frame satisfy an `expected_count=2`
  rule.
- Area and spatial evidence used for count-based rules comes only from the same
  qualifying set as the count.

## Residual Review Notes

- The OpenAPI enum, generated TypeScript type, and runtime validator correctly
  include `UNVERIFIABLE`.
- The aggregation unit tests cover many threshold, duplicate, adjacency, and
  component-isolation cases. They need the product-isolation, idle-expiry,
  acquisition-time, quality-gate, missing-policy, and count-confidence cases
  specified above before the implementation is safe to merge.
