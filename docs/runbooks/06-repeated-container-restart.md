# Runbook 06: Repeated Container Restart

## Trigger

Restart count or crash-loop alert exceeds the approved threshold.

## Immediate Safety Action

1. Stop automatic restart loops after bounded attempts and signal inspection unavailable.
2. Preserve exit codes, resource metrics, logs, core dumps where policy permits, and incomplete-window state.
3. Do not clear volumes, queues, or databases as a first response.

## Recovery

1. Classify OOM/resource exhaustion, configuration, migration, model/driver, camera SDK, or application fault.
2. Correct the dependency or roll back the failed release.
3. Reconcile incomplete windows and upload leases after startup.
4. Verify camera, models/rules, storage, database, API readiness, and a known sample.

## Exit Criteria

The service remains stable for the site-defined observation period and inspection is explicitly resumed.
