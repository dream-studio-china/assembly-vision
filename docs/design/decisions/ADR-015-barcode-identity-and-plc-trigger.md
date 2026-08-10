# ADR-015: Barcode Identity and PLC Trigger Correlation

## 1. Status

Accepted

## 2. Context

The one-month demonstrator needs product identity for inspection decisions, but
the customer has no fixed barcode prefix standard and no single validated PLC
model. Design 07 ranks a PLC/photo-eye boundary first and barcode events second;
design 04 requires barcode output with raw value, symbology, timestamp, source,
quality/status, and a versioned resolver. The current runtime only accepts a
development-only `mock` trigger and writes `BarcodeResult(NOT_REQUIRED)`, so a
barcode-required rule can never be satisfied by a real flow.

The absence of a validated PLC model means a Modbus adapter must define a
contract the PLC must meet rather than guessing register semantics. The absence
of a fixed barcode prefix means product resolution must be exact per-instance
mapping, never prefix or pattern inference from the barcode content.

## 3. Decision

1. **Barcode identity is an opt-in, exact-mapped edge capability.**
   `identity.barcode` configuration enables visual decoding (ZXing-cpp) of a
   captured single frame and/or an explicitly simulated keyboard input for
   development. A configured mapping file maps complete barcode values to
   product codes; prefix/pattern matching is prohibited. A resolved value that
   is unreadable, conflicting, unsupported-symbology, unknown, or mapped to a
   product other than the active rule product type is unverified and records an
   `NG` result when identity collection is enabled.
2. **The rule engine remains the sole decision authority.** Barcode resolution
   only supplies `product_identity_verified` and the persisted
   `barcode_result`/`product_resolution` fields; it never bypasses rules and
   never returns `OK` without a verified, compatible identity when the rule
   requires a barcode.
3. **`barcode_required` rules require enabled, required identity config at
   load time.** A configuration that declares a barcode-required rule without
   the matching identity configuration is a `ConfigError`, so a misconfiguration
   can never silently allow unverified `OK`.
4. **Simulated keyboard input is explicitly labeled development-only.** It is
   exposed only through the ADR-014 dev harness, is reported as
   `SIMULATED_KEYBOARD_INPUT`, and must never be presented as scanner hardware
   availability.
5. **PLC/photo-eye triggers use a FIFO/snapshot Modbus contract, disabled by
   default.** The Modbus adapter models PLC-supplied ENTRY/EXIT/ABORT events with
   an increasing sequence, a product token, heartbeat, and overflow state read
   through a consistent snapshot. Ordinary coil polling is rejected because a
   transient photo-eye pulse cannot be proven not to have been missed. A live
   transport requires a site-validated register profile; the adapter contract is
   delivered now, integration remains deployment-gated.
6. **Barcode identity is rejected with temporal inspection until windowed
   correlation exists.** A temporal window cannot truthfully persist a single
   barcode result from per-frame reads without source timing and conflict
   semantics. Startup rejects the combination instead of emitting misleading
   `NOT_REQUIRED` evidence.

## 4. Consequences

### 4.1 Positive

- A barcode-required rule now has a real, verified path instead of a permanent
  `NOT_REQUIRED` dead end.
- Dynamic instance barcodes work with exact per-instance mappings, matching the
  mixed-standard customer requirement.
- Misconfiguration fails closed at load time (contract 03 §5).
- The Modbus contract is honest: no placeholder register addresses claim to
  support an unvalidated PLC.

### 4.2 Negative and Trade-offs

- Exact mappings must be maintained for every product instance; there is no
  barcode-derived product-type inference.
- Visual decoding depends on barcode quality, placement, motion blur, and
  lighting; it must be validated on production samples.
- Simulated keyboard input is a development convenience only and is not a
  production acquisition path.
- Modbus TCP live integration remains blocked on a selected PLC model and
  register profile.

## 5. Open Questions and Validation Required

- Confirm symbologies, label size/placement, and read-rate targets on real
  samples.
- Select a PLC model/register map and validate ENTRY/EXIT timing, FIFO depth,
  heartbeat cadence, and reconnect behavior on site.
- Decide whether barcode-only identity can be a validated production boundary
  for a specific line or remains bench/development only.

## 6. Links

- [Camera and Image Acquisition](../07-camera-and-image-acquisition.md)
- [Rule Engine](../11-rule-engine.md)
- [REST API and Events](../15-rest-api-and-events.md)
- [ADR-014: Web Dev Test Harness](ADR-014-web-dev-test-harness.md)
- [ADR-010: Per-Component Temporal Aggregation](ADR-010-per-component-temporal-aggregation.md)
