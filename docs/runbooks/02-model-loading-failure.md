# Runbook 02: Model-Loading Failure

## Trigger

Artifact missing, checksum/signature mismatch, runtime incompatibility, class-map mismatch, or model
health check failure.

## Immediate Safety Action

1. Keep `/api/v1/health/live` healthy if the process is alive but mark inspection readiness false.
2. Stop new inspection windows; never substitute a permissive model or default `OK`.
3. Record manifest, artifact checksum, runtime/driver version, and bounded error details.

## Recovery

1. Re-verify package identity, storage integrity, runtime compatibility, and available resources.
2. If the active release is invalid, follow [Model Rollback](08-model-rollback.md).
3. Load the last-known-good model and validate classes against the active rule/product configuration.
4. Run model health and known-sample smoke checks.

## Exit Criteria

Both detector models load, checksums/classes match, readiness is healthy, and smoke results are retained.
