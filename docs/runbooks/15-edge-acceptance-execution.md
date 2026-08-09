# Runbook 15: Edge Acceptance Execution

## Purpose and Boundary

Use this checklist to execute the on-site Edge acceptance protocol for one
locked candidate and one defined customer domain. It implements design 26.8
and E6d. It does not establish acceptance without executed on-site evidence on
the agreed hardware, line, and previously unused customer data.

An unavailable item is `NOT_EXECUTED`, not `PASS`. An incomplete record is
`INCOMPLETE`, not `PASS`. Record the missing prerequisite, affected matrix row,
owner, and required follow-up in the acceptance report.

## Before the Site Run

1. Record the site, line, device, camera setup, product domain, planned start
   and end time, supplier and customer roles, witnesses, ground-truth
   adjudicators, and authorized signatories.
2. Attach the jointly approved acceptance protocol. Record target-setting
   method, metrics, sample and segmentation requirements, permitted staged
   cases, decision rules, retest policy, and release-blocking stop conditions.
3. Stop the run and preserve all evidence if a safety failure, unverified
   candidate artifact, missing required evidence, data-loss risk, or other
   protocol stop condition occurs. Do not resume under the same candidate until
   the protocol owner authorizes it.
4. Open the [edge acceptance report template](../design/28-edge-acceptance-report.md)
   and create one matrix record per applicable E6 row before execution.

## Verify Environment

1. Verify and record camera mount, position, focus, exposure, lighting,
   trigger/PLC mapping, barcode reader, edge computer, accelerator, storage,
   UPS where applicable, and device identifiers.
2. Verify network topology, DNS, firewall, central connectivity assumptions,
   time synchronization, available disk capacity, health/readiness state, and
   logging/evidence storage paths.
3. Record each prerequisite as `PRESENT`, `ABSENT`, or `NOT_MEASURED`. An
   absent required prerequisite prevents the affected acceptance item from
   passing and is recorded as `NOT_EXECUTED`.

## Lock Candidate

1. Lock the application image/package, product and component models, rules,
   product configuration, review policy, and acceptance manifest before the
   first acceptance case.
2. Record version, source, and checksum for every locked artifact in the
   report. Verify each checksum on the executing device.
3. Do not substitute, tune, retrain, alter thresholds, select a different
   checkpoint, or change rules during the run. A changed candidate requires a
   new version and a controlled rerun.

## Calibration and Smoke

1. Run the agreed calibration and smoke cases to confirm capture, product
   mapping, evidence persistence, and safe failure behavior.
2. Record all results and evidence. Calibration identifies environmental
   readiness; acceptance outcomes must not be used to tune the locked
   candidate.
3. If calibration exposes a release-blocking problem, stop, preserve the run,
   and record the issue for remediation and retest.

## Witnessed Representative Execution

1. Execute randomized or production-representative cases under the recorded
   witness arrangement, including each applicable product type, missing
   component/manual case, barcode failure, position shift, consecutive and
   mixed-product flow, and normal production variation.
2. For every execution, retain inspection identifiers, result and reason codes,
   original and selected media, configured ROI/annotation evidence, ground
   truth provenance, timestamps, device ID, artifact versions, barcode/product
   mapping, structured logs, stage timings, and upload evidence where in scope.
3. Record naturally occurring and staged cases separately. Treat unavailable
   equipment, data, or authorization as `NOT_EXECUTED`; do not infer a pass
   from another case or local automation.

## Resilience and Soak

1. Safely exercise the protocol-approved offline, network recovery/flap,
   application and container restart, power-loss, camera disconnect, disk
   pressure, accelerator fault, database recovery, backup/restore, clock-drift,
   and checksum-failure cases where applicable.
2. Execute the agreed representative soak duration and workload. Record duty
   cycle, latency, resource trends, queue growth, file descriptors, storage,
   temperature where available, degradation, and data-loss events.
3. Do not simulate an unavailable on-site capability as a passing acceptance
   result. Mark the affected item `NOT_EXECUTED` or `INCOMPLETE` and state why.

## Reconcile Evidence

1. Reconcile physical product counts with product windows and inspection
   records. Investigate and record duplicate, missing, or mixed-frame
   inspections.
2. Reconcile inspection records with media, checksums, structured logs, health
   events, upload tasks, and central receipts where synchronization is in
   scope.
3. Confirm that no evidence, pending upload, or database record required for
   traceability was deleted or altered during execution.

## Adjudicate and Report

1. Adjudicate only cases predeclared as potentially inconclusive, using the
   authorized product expert and retained evidence. Preserve the original AI
   decision and reason codes; append reviewer or adjudicator outcomes without
   overwriting them.
2. Complete segmented metrics with numerators, denominators,
   excluded/inconclusive counts, confidence treatment, evidence links, and
   deviations in the [edge acceptance report template](../design/28-edge-acceptance-report.md).
   Use `NOT_MEASURED` for metrics without executed evidence.
3. Compare results with the agreed protocol and record acceptance, restricted
   acceptance, remediation/retest, or rejection, including residual risks,
   scope restrictions, compensating controls, owners, and due dates.
4. Obtain supplier, customer, witness, and adjudicator sign-off as applicable.
   A prep draft, local runner output, unsigned report, or report with missing
   on-site evidence is not an acceptance claim.

## Exit Criteria

The report contains the locked candidate, executed matrix and resilience/soak
evidence, reconciliations, adjudication provenance, measured or explicitly
unmeasured metrics, outcome, residual risks, and required signatures. A
release-blocking finding preserves the historical run; remediation uses a new
candidate version and controlled rerun.

## Related

- [Customer Acceptance](../design/26-customer-acceptance.md)
- [Edge acceptance report template](../design/28-edge-acceptance-report.md)
- [E6: Edge Acceptance](../tasks/E6-edge-acceptance.md)
