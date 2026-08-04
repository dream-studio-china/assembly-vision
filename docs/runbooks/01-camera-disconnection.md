# Runbook 01: Camera Disconnection

## Trigger

No fresh frame within the validated watchdog interval, adapter disconnect, or camera health failure.

## Immediate Safety Action

1. Stop opening inspection windows; do not infer `OK` without valid frames.
2. Record camera state, adapter error, device ID, time, and active inspection ID.
3. Signal the approved line/operator fault state.

## Recovery

1. Check power, cable, interface, vendor service, and exclusive device ownership.
2. Restart only the adapter or `edge-service` when safe; preserve local records and upload tasks.
3. Verify exposure, focus, framing, and configuration checksum.
4. Run a known-sample smoke inspection and retain its evidence.

## Exit Criteria

Camera health is stable, frames pass quality gates, smoke evidence is approved, and an authorized
operator resumes inspection. Escalate repeated disconnects with the support bundle.
