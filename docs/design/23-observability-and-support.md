# 23. Observability and Support

## 23.1 Purpose and Scope

Observability must explain inspection behavior, device health, synchronization state, and configuration provenance without requiring central connectivity for local diagnosis. Support procedures preserve production evidence and never turn an unavailable or ambiguous inspection into `OK`.

### 23.1.1 Delivery Scope

- **MVP:** structured local logs, per-stage timing, decision JSON, model/rule versions, and CLI health output.
- **One-month target:** local health API/dashboard, persistent device events, queue/disk/camera metrics, central fleet view, correlation identifiers, and diagnostic bundles.
- **Production target:** alert routing, service objectives agreed from baseline data, runbooks, clock monitoring, controlled remote diagnostics, and version-segmented quality dashboards.
- **Future scope:** OpenTelemetry tracing across fleet services and integration with customer monitoring platforms.

## 23.2 Observability Principles

1. Local inspection observability remains available while offline.
2. An inspection ID correlates frames, decision, media, upload tasks, receipt, and manual review.
3. Logs and metrics distinguish application, model, rule, product, line, and device versions.
4. Health endpoints describe software readiness; they do not replace physical verification of camera framing, lighting, focus, or line behavior.
5. Telemetry is bounded and subject to retention so it cannot exhaust the edge disk.
6. Barcodes, images, credentials, and customer identifiers are minimized or redacted according to policy.

## 23.3 Structured Logs

JSON logs use UTC timestamps and stable event names. Recommended fields are:

```json
{
  "timestamp": "2026-08-04T10:15:31.412Z",
  "level": "warning",
  "event": "upload_retry_scheduled",
  "service": "edge-service",
  "device_id": "device-reference",
  "inspection_id": "inspection-reference",
  "correlation_id": "request-reference",
  "product_model_version": "product-model-reference",
  "component_model_version": "component-model-reference",
  "rule_version": "rule-reference",
  "attempt": 3,
  "error_code": "CENTRAL_TIMEOUT",
  "retry_at": "2026-08-04T10:16:04Z"
}
```

Do not log credentials, authorization headers, full image bytes, or arbitrary exception payloads. Full barcode values are logged only when approved; otherwise store a masked value or stable restricted-access reference. Tracebacks are retained locally with access controls and summarized centrally.

## 23.4 Metrics

### 23.4.1 Edge Health and Workload

- Camera connection, frame age, acquisition failures, exposure/configuration deviation, and reconnect count.
- Product windows opened/completed/aborted and ambiguous/multiple-product counts.
- Product detections, ROI failures, barcode reads/failures, and unusable frames.
- Decisions by `OK`, `NG`, optional `UNCERTAIN`, and reason code.
- Stage latency and total durable-decision latency distributions.
- CPU/GPU utilization, inference memory, temperature where available, process memory, disk space/inodes, database size, and file-descriptor use.
- Upload queue depth/bytes/oldest age, retry count, terminal failures, and receipt latency.
- Active application, model, rule, product-configuration versions and their checksums.

### 23.4.2 Central and Quality Metrics

- Ingestion request outcomes, duplicate receipts, checksum failures, and processing backlog.
- Device last seen, queue delay, clock offset estimate, and version compliance.
- NG recall, false-negative estimate, false-positive rate, and review correction rate where reviewed ground truth exists.
- Per-product, per-component, per-model, and per-rule segmentation.
- Review queue depth/age and reviewer turnaround.
- API latency/error rate, database saturation, object-store failures, and worker backlog.

Metric labels must avoid unbounded values such as inspection ID or barcode. Those belong in logs/traces.

## 23.5 Health Model

`/health/live` reports whether the process can answer. `/health/ready` reports whether its required local dependencies permit its function. A separate `/health/device` reports camera, model, rule, disk, database, clock, network, and central connectivity states.

The decision runtime inside `edge-service` is not ready when it cannot durably record decisions, has no compatible active model/rule, or has no usable camera. Central connectivity alone does not make it unready. The dashboard presents `healthy`, `degraded`, and `unavailable` with reason codes and timestamps rather than a single green indicator.

## 23.6 Events and Traceability

Device events are durable records for camera transitions, inspection pause/resume, disk thresholds, configuration activation, model/rule activation, upload failures, clock anomalies, startup/shutdown, and recovery. Central receipt preserves the source event time and central receive time.

Each inspection trace answers:

- Which physical window and barcode/product mapping was used?
- Which frames were accepted or rejected, and why?
- Which product box/ROI and component evidence led to the decision?
- Which application, model, rule, and configuration versions were active?
- Was evidence uploaded, reviewed, corrected, retained, or deleted?
- Which user or service changed relevant configuration?

## 23.7 Dashboards and Alerts

The edge dashboard prioritizes camera usability, latest decision, active versions, disk reserve, queue age, and central connection. The central dashboard prioritizes stale devices, quality trends, queue delays, version rollout, review backlog, and recurring component/barcode failures.

Alert thresholds are configured after baseline measurement. Required alert conditions include camera unavailable, no recent frames while production is expected, disk critical, database write failure, no active compatible release, repeated worker restarts, queue age/size growth, package signature failure, clock drift, central ingestion failure, and a statistically meaningful quality regression. Alerts need deduplication, severity, owner, runbook link, and recovery notification.

## 23.8 Diagnostic Bundle

An authorized support action may export a bounded, encrypted bundle containing manifest/version checksums, effective non-secret configuration, recent structured logs, health history, database integrity results, queue summary, selected inspection metadata, and explicitly selected evidence. The UI previews included sensitive data. Creation and download are audited; credentials and unrelated production media are excluded.

Remote shell access is not a default support mechanism. If customer policy permits it, access must be time-bounded, individually attributable, approved, and recorded outside the application as well as in audit logs.

## 23.9 Support Severity and Escalation

| Severity | Example | Immediate handling |
|---|---|---|
| Critical | Potential missed NG pattern; decisions cannot be durably stored | Pause/contain affected operation, preserve evidence, page quality and engineering owners |
| High | Camera unavailable, repeated crash, disk critical | Follow local recovery runbook and escalate promptly |
| Medium | Upload backlog while local inspection is healthy | Monitor capacity, restore connectivity, reconcile receipts |
| Low | Reporting defect or cosmetic dashboard issue | Record with versions/evidence and schedule correction |

Response and resolution times are contractual values to be agreed, not invented in this architecture.

## 23.10 Operational Runbooks

### 23.10.1 Potential Missed NG

1. Preserve the inspection, adjacent evidence, active versions, logs, and review record.
2. Determine affected product/component/version/time/device scope.
3. Increase review or temporarily pause automatic release of OK products according to customer procedure.
4. Re-evaluate retained evidence without overwriting the original decision.
5. Correct ground truth, add a locked regression case, and decide whether rule/configuration rollback or model remediation is needed.
6. Document containment, root cause, affected inspections, and release validation.

### 23.10.2 Growing Upload Queue

1. Confirm local inspection and durable queue health.
2. Check network, DNS, TLS, credentials, central API, object storage, and proxy limits.
3. Check oldest task, bytes pending, retry/error classes, and local free space.
4. Restore service and allow rate-limited draining; do not manually clone tasks.
5. Reconcile idempotency receipts and checksums; retry terminal tasks only after fixing their cause.

### 23.10.3 Repeated Process Restart

1. Keep the line in a safe unavailable/degraded state and preserve restart counters.
2. Inspect exit code, resource exhaustion, driver state, database integrity, and last event.
3. Disable automatic restart loops after the configured threshold.
4. Recover the failing dependency or roll back the release.
5. Run camera and known-sample checks before resuming.

### 23.10.4 Clock Drift

1. Compare edge wall time with the approved time source and central receive times.
2. Preserve monotonic sequence and source timestamps; do not rewrite historical records.
3. Restore time synchronization without unsafe abrupt changes where the platform supports gradual correction.
4. Mark affected records and verify product-window ordering and upload reconciliation.

## 23.11 Data Retention for Telemetry

Logs rotate by size and age and reserve disk for inspection records. Metrics use bounded local history, then aggregate centrally when connected. Audit records have a longer customer-approved retention and are not silently deleted by ordinary log cleanup. Telemetry cleanup follows the same safeguard as media cleanup: pending evidence and records needed for upload/reconciliation are protected.

## 23.12 Open Questions and Validation Required

- Customer monitoring platform, alert channels, support hours, severity definitions, and escalation contacts.
- Production schedule signal needed to distinguish expected idle time from missing frames.
- Metric/alert thresholds after hardware and production baseline measurement.
- Local and central log, metric, audit, and diagnostic-bundle retention periods.
- Barcode/image data classification, redaction rules, and permission to export diagnostic evidence.
- Time synchronization source and acceptable clock offset.
- Whether remote support is permitted and which access/audit controls are mandatory.
- Contractual response objectives and responsibility boundaries for camera, network, host, and application failures.

## 23.13 Related Documents

- [Deployment and Operations](20-deployment-and-operations.md)
- [Security and Source Distribution](21-security-and-source-distribution.md)
- [Testing and Quality Assurance](22-testing-and-quality-assurance.md)
- [Risks and Mitigations](27-risks-and-mitigations.md)
