# 27. Risks and Mitigations

## 27.1 Purpose and Risk Method

This register identifies known threats to inspection integrity, traceability, availability, and operations. Every risk states cause, impact, detection, prevention, recovery, and residual risk. Owners and ratings are assigned during site planning because factory topology, hardware, throughput, and acceptance thresholds are not yet known.

## 27.2 Scope and Treatment Principles

- **MVP:** address risks affecting static decision correctness and evidence; document live-production risks as not yet mitigated.
- **One-month target:** implement core camera, identity, windowing, persistence, synchronization, health, and recovery controls.
- **Production target:** verify mitigations on customer hardware and independent data, assign owners, and accept residual risk explicitly.
- **Future scope:** hardware interlocks, PLC/MES integration, redundant infrastructure, and advanced drift automation where justified.

The default safe behavior is to avoid issuing `OK` when product identity, required evidence, configuration compatibility, or durable recording is uncertain. Human review and physical line procedures remain necessary controls during rollout.

## 27.3 Comprehensive Risk Register

| ID and risk | Cause | Impact | Detection method | Prevention | Recovery | Residual risk |
|---|---|---|---|---|---|---|
| R-01 Camera shift | Loose mount, vibration, maintenance, impact | ROI/domain shift can miss required components and create false OK or false NG | Reference-scene geometry, product-box distribution, calibration image, operator check, quality trend | Rigid/tamper-evident mount, startup checklist, detected product ROI, approved camera envelope | Pause, restore/alignment check, capture validation set, revalidate before resume | Small shifts may evade geometric alarms while changing appearance |
| R-02 Camera disconnection | Cable/power/driver/SDK/device failure | No inspectable frames; production may pass without a decision if external controls are weak | Frame-age watchdog, adapter errors, link state, reconnect count | Industrial cabling/power, strain relief, conformance tests, supervised adapter | Stop windows, alarm, reconnect adapter, verify framing with test product | Intermittent faults may recover before diagnosis; line interlock depends on customer integration |
| R-03 Incorrect exposure | Lighting/camera setting change, auto-exposure, contamination | Lost detail or confidence; false NG and possible false OK | Histogram/saturation/brightness metrics, config checksum, reference images | Lock validated exposure/gain, fixed lighting, change control, cleaning procedure | Correct settings/lighting, clean optics, rerun known samples | Local glare or gradual lamp aging may pass global metrics |
| R-04 Motion blur | Conveyor speed, exposure time, vibration, trigger timing | Components/barcodes become unreadable and detections fail | Blur score, frame-quality rejection, latency/timing logs, image review | Adequate lighting, short exposure, stable mount, trigger/window tuning, multiple usable frames | Route NG/uncertain, adjust optics/timing, recapture/reinspect | Blur metrics are imperfect; all frames may be blurred at some operating points |
| R-05 Reflection | Glossy surfaces, light/camera angle, environmental change | Occluded visual features and unstable confidence | Saturation/specular metrics, heatmaps/evidence review, scenario tests | Diffuse/polarized controlled lighting where validated, representative training data | Adjust lighting/angle under change control, collect data, revalidate | Reflection can vary by material batch and position |
| R-06 Product occlusion | Packaging, hands/tools, overlapping parts, incomplete field of view | Required component hidden; incorrect presence decision or excess NG | Visible-area/box checks, quality reasons, temporal consistency, review | Physical inspection zone, operator procedure, multiple frames, minimum visibility rules | Mark NG/uncertain and reinspect after clearing occlusion | Occlusion can resemble true absence and may not be separable from one view |
| R-07 Product-position variation | Conveyor guides/tolerances, product placement | Product crop truncation or unfamiliar viewpoint | Product-box position/size trends, ROI clipping flags, acceptance shift cases | Stage-one product detection, ROI margins, capture-zone guides, representative data | Reposition/reinspect, tune validated margins, collect/revalidate shifted cases | Movement beyond trained envelope can occur without a hard boundary |
| R-08 Barcode-read failure | Blur, damage, glare, unsupported symbology, decoder fault | Unknown product type/rule; loss of traceability | Decoder status, repeated attempts, checksum/format validation, mismatch rate | Dedicated decoder/ROI, multiple frames, validated standards, label quality process | Do not infer unverified OK; retry/reinspect or authorized manual resolution | Some labels remain unreadable; manual entry can introduce error |
| R-09 Wrong product-type mapping | Stale/incorrect master data, reused code, manual error | Wrong required-component rule can produce false OK | Barcode/product/config consistency checks, visual product class comparison, audits | Versioned authoritative mapping, approval workflow, test vectors | Pause affected mapping, restore last approved version, review affected inspections | Correctly formatted but semantically wrong source data may evade checks |
| R-10 Wrong rule configuration | Omitted component, wrong threshold/policy, editing error | Defective product may be classified OK or valid product NG | Schema/semantic validation, diff/approval, simulation on regression set, audit | Versioning, least privilege, two-person approval where feasible, staged activation | Roll back, identify affected version/time range, re-evaluate evidence | Regression set may not represent every production condition |
| R-11 Model and rule version mismatch | Partial update, manual file replacement, compatibility error | Rule expects classes/evidence model cannot supply | Signed manifest compatibility matrix, startup/readiness validation, inspection record versions | Atomic release set, read-only model/rule mounts, no ad hoc replacement | Refuse readiness, activate last known-good compatible set, report failure | Compatibility metadata itself may be authored incorrectly without end-to-end tests |
| R-12 Multiple products in one inspection window | Insufficient spacing, trigger overlap, tracking failure | Evidence combines products or misses one product | Product count/tracks, entry/exit events, window duration and geometry checks | Sensor/trigger design, spacing rules, explicit multi-product rejection | Abort as ambiguous/NG, clear zone, reinspect products individually | Occluded overlapping products may appear as one |
| R-13 Duplicate inspection | Trigger bounce, restart, repeated barcode event, tracking re-entry | Duplicate records/disposition and distorted statistics | Window identity state machine, product/barcode/time correlation, duplicate event metric | Trigger debounce, stable inspection IDs, explicit lifecycle and idempotency | Mark/link duplicate without deleting audit history; reconcile downstream action | Identical consecutive products can make heuristic deduplication unsafe |
| R-14 Frame mixing between products | Window overlap, stale buffers, async race, wrong timestamps | Components from another product can support false OK | Window/track IDs per frame, monotonic sequence checks, boundary tests, provenance audit | Single ownership of frames, flush/bound buffers, sensor/barcode boundaries, state-machine tests | Abort ambiguous windows, preserve evidence, fix boundary logic and retest | Weak physical separation can remain ambiguous without a sensor |
| R-15 Network outage | Factory WAN/LAN, DNS, firewall, proxy failure | Central history/review delayed; queue and disk grow | Connectivity state, queue depth/bytes/oldest age, retry classes | Edge-first design, persistent queue, capacity planning, backoff/jitter | Continue locally, restore network, rate-limit drain, reconcile receipts | Outage longer than local capacity requires degraded recording or production pause |
| R-16 Central-server outage | API/database/object storage/deployment failure | Upload/review/reporting unavailable across devices | Central health/alerts, edge 5xx/timeouts, backlog metrics | Decoupled edge, backups, tested central recovery, appropriate redundancy | Continue edge operation, recover service/data, drain queues idempotently | Extended outage delays human review and fleet-wide visibility |
| R-17 Upload duplication | Timeout after commit, retry, operator retry, queue replay | Duplicate central records/media and incorrect reporting | Idempotency key, unique source inspection constraint, receipt lookup, checksum | Idempotent API and durable receipt before acknowledgement | Return original receipt, merge/reject duplicate media by checksum, audit conflicts | Changed payload under reused key needs explicit conflict handling |
| R-18 Local disk full | Outage backlog, video/log growth, failed cleanup, undersizing | Cannot store evidence/database; crashes or traceability loss | Free bytes/inodes, growth forecast, media class/queue metrics, write errors | Quotas, bounded logs/video, tiered retention, capacity reserve, protect pending files | Safe cleanup uploaded expired data, disable optional recording, expand disk or pause | Sudden bursts/filesystem overhead can exhaust reserve before response |
| R-19 Local database corruption | Power loss, storage fault, unsafe copying, software defect | Lost decisions/queue state and inability to reconcile evidence | SQLite integrity checks, I/O errors, backup/restore tests, media reconciliation | Transactions/WAL as validated, atomic writes, reliable storage, online backups | Quarantine database, restore backup, reconstruct limited metadata from manifests/media, reconcile central receipts | Records after last valid backup may require manual reconstruction or remain lost |
| R-20 Container restart | Crash, OOM, host update, restart policy | Interrupted window, temporary inspection outage, duplicate work | Restart counters, exit codes, health gaps, incomplete-window state | Resource sizing/limits, health supervision, durable state boundaries, soak tests | Restart, mark ambiguous window aborted, reconcile queue/temp files, smoke test | Product present during restart may require physical reinspection |
| R-21 Client power loss | Facility/PSU failure or unsafe shutdown | Abrupt capture/database/media interruption and downtime | Boot reason, unclean shutdown flag, database/filesystem checks, UPS telemetry | UPS where justified, reliable power, transactional writes, atomic rename, shutdown procedure | Recover host, integrity/reconciliation checks, abort incomplete windows, verify known sample | Storage hardware can fail despite transactional design; physical product identity may be lost |
| R-22 Clock drift | NTP unavailable, bad RTC, manual time change | Misordered records, incorrect correlation/retention/audit times | Offset monitoring, central receive-time comparison, monotonic sequence checks | Approved time source, monotonic clocks for durations, store source and receive times | Restore synchronization, flag affected range, preserve original timestamps and sequence | Offline wall-clock accuracy remains bounded by hardware and outage duration |
| R-23 Model drift | Product/material/process/lighting changes over time | Rising false negatives/positives outside validation domain | OK audits, reviewed NG, per-version/product/component trends, input/box/quality distributions | Change control, representative monitoring, periodic sampling, locked baseline comparison | Increase review, contain affected scope, collect labels, retrain/tune and fully revalidate | Rare defects and delayed ground truth make drift detection statistically slow |
| R-24 Insufficient NG samples | Rare defects, inability to stage cases, biased collection | Unknown/weak NG recall and overconfident acceptance | Coverage matrix and sample counts by component/product/scenario, confidence intervals | Intentionally create authorized missing cases, collect production NG, conservative rules/review | Restrict acceptance scope, increase review, gather data before promotion | Staged defects may not reproduce natural failure appearance |
| R-25 Customer changing the camera angle | Maintenance, relocation, new line, mount adjustment | Significant domain change; product/component appearance and ROI behavior shift | Mount marks/calibration, reference image comparison, product-box trends, change audit | Physical lock/tamper evidence, operating envelope, customer change procedure | Treat significant change, including near 45 degrees, as new domain: test, collect, fine-tune if needed, revalidate system | Small undocumented angle changes may accumulate and evade threshold checks |
| R-26 Unauthorized configuration changes | Stolen account/device access, excessive role, direct volume edit | Disabled requirements, wrong mapping/thresholds, loss of audit trust | Authentication/audit logs, checksum/signature verification, file integrity and activation events | Least privilege, MFA centrally, signed artifacts, read-only mounts, approval separation | Revoke access, preserve evidence, restore approved version, assess/review affected inspections | Privileged host administrators can bypass container controls; physical/customer governance remains essential |

## 27.4 Cross-Risk Controls

Several controls reduce multiple risks:

1. A deterministic state machine binds each frame and decision to one product window.
2. Product detection generates the ROI; hard-coded full-frame regions are fallback/coarse zones only.
3. Per-component temporal aggregation excludes unusable frames and never claims to improve single-frame model accuracy.
4. Product identity, model, rule, configuration, and evidence versions are persisted with every decision.
5. The edge stores decisions and upload tasks transactionally and continues without the central server.
6. Signed, compatible release sets activate atomically between windows and support rollback.
7. Human review, OK auditing, and customer acceptance use independent evidence to detect quality failures.
8. Disk, camera, clock, process, queue, and quality health are observable locally and centrally.

## 27.5 Risk Review and Ownership

Before pilot deployment, each risk receives customer and supplier owners, likelihood/impact rating, planned treatment, target completion, verification evidence, and acceptance authority. Review occurs at design gates, after any incident or significant change, before each production release, and periodically during operation. Closed risks remain historically traceable; residual risks are accepted by an authorized customer representative.

## 27.6 Open Questions and Validation Required

- Customer risk-rating matrix, risk owners, escalation authority, and acceptable residual-risk process.
- Physical line controls when AssemblyVision is unavailable or returns NG/uncertain/system exception.
- Camera mount, lighting, trigger, spacing, power/UPS, storage, and time-source design.
- Expected outage duration and local capacity needed for media/upload buffering.
- Product/component criticality and consequences of missed defects.
- Availability of independent NG data and customer authority to stage missing-component cases.
- Identity provider, physical/host administrator controls, and configuration approval separation.
- Which changes mandate partial versus complete customer reacceptance.

## 27.7 Related Documents

- [Deployment and Operations](20-deployment-and-operations.md)
- [Security and Source Distribution](21-security-and-source-distribution.md)
- [Testing and Quality Assurance](22-testing-and-quality-assurance.md)
- [Observability and Support](23-observability-and-support.md)
- [Customer Acceptance](26-customer-acceptance.md)
