# Runbook 09: Rule Rollback

## Trigger

Invalid required-component set, threshold/policy regression, model compatibility failure, or publication error.

## Recovery

1. Stop activation and new windows at a safe boundary; preserve the immutable failed rule version.
2. Identify devices/inspections that used the affected rule and retain their evidence.
3. Verify the previous rule against active product configuration and both model class maps.
4. Atomically reactivate the last-known-good rule between inspection windows.
5. Run golden-rule tests and known-sample smoke inspections before authorized resume.

## Exit Criteria

The previous rule is active and audited, affected records are queryable, and no historical edge decision was rewritten.
