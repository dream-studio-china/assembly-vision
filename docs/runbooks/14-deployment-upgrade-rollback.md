# Runbook 14: Deployment Upgrade and Rollback

## Trigger

New application, model, or rule release; a failed activation or health check;
or a required rollback to the last known-good release.

## Before You Begin

- Record site/device, start/end time, actor, affected inspections, evidence
  bundle, actions, result, and escalation reference.
- Take a verified backup (runbook 12) before any upgrade. A backup is not
  operational until a representative restore has succeeded.
- Confirm the upgrade is an atomic release set: application, compatible model,
  and compatible rule versions together. Never activate a model without its
  compatible rule or a rule without its model (design 20.8).

## Upgrade Procedure

1. Build immutable artifacts from a reviewed commit; verify checksums and
   compatibility metadata on the device before installation.
2. Deploy to a non-production edge or a rollout ring and run smoke inspections.
3. Stop opening new product windows and allow the active window to complete so
   no physical product spans two releases.
4. Apply database migrations, install the release set, and run readiness
   checks (`/api/v1/health/ready`, model/rule versions, storage).
5. Resume inspection and compare latency, evidence integrity, and NG behavior
   with the baseline before widening rollout.

## Rollback Procedure

1. Stop opening new windows and allow the active window to complete.
2. Restore the previous application/model/rule release set (install from the
   preserved last known-good artifacts or the verified backup).
3. Confirm inspection and upload data are preserved; a rollback must not
   delete pending evidence or the database.
4. Run readiness checks and a smoke inspection, then resume.

## Exit Criteria

Readiness passes, the active window never spans two releases, inspection and
upload data survive, and a smoke inspection behaves as expected. On failure,
the previous known-good release remains active and the failure is reported with
diagnostics.

## Related

- [Backup and Recovery](12-backup-and-recovery.md)
- [Model Rollback](08-model-rollback.md)
- [Rule Rollback](09-rule-rollback.md)
- [Repeated Container Restart](06-repeated-container-restart.md)
