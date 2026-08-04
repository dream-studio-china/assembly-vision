# Runbook 08: Model Rollback

## Trigger

Model load failure, compatibility failure, latency/resource regression, or approved quality regression.

## Recovery

1. Stop new inspection windows and let the active window complete or abort conservatively.
2. Record failed model/application/rule/product versions, metrics, and evidence.
3. Verify the previous model artifact, checksum, runtime, class map, and rule compatibility.
4. Atomically reactivate the last-known-good release between windows.
5. Run health, latency, and known-sample checks before authorized resume.

## Exit Criteria

The previous model pair is active and traceable, smoke checks pass, affected inspections are identified,
and the failed release remains quarantined for analysis.
