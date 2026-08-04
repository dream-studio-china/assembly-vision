# AssemblyVision Requirements

## 1. Requirement Language and Priorities

`MUST` denotes a release obligation, `SHOULD` an expected behavior that may be waived with documented rationale, and `MAY` an option. Priorities are `P0` production-critical, `P1` required for the intended target, and `P2` future or conditional. Requirement IDs are stable and follow the conventions in [Appendices](appendices.md#5-traceability-conventions).

## 2. Business and Safety Requirements

| ID | Priority | Requirement | Verification |
|---|---:|---|---|
| BR-001 | P0 | The system MUST produce one traceable business result, `OK` or `NG`, per completed physical-product inspection. | End-to-end and acceptance tests |
| BR-002 | P0 | `OK` MUST require valid evidence for every component required by the resolved product rule. | Rule-engine tests |
| BR-003 | P0 | Missing, uncertain, invalid, unresolved, or incomplete inspection evidence MUST NOT produce `OK`. | Fault-injection tests |
| BR-004 | P0 | Evaluation MUST prioritize NG recall and false-negative reduction over early false-positive reduction. | Evaluation report review |
| BR-005 | P0 | Production acceptance MUST use measured customer production data excluded from training and MUST NOT rely on an unvalidated accuracy guarantee. | Dataset lineage and acceptance report |
| BR-006 | P1 | Early production MUST support human review of all NG results, low-confidence cases as configured, and sampled OK audits. | Workflow test |

## 3. Edge Functional Requirements

| ID | Priority | Requirement | Verification |
|---|---:|---|---|
| EDGE-001 | P0 | Production-critical capture, inference, aggregation, rules, and final decision MUST execute on the edge computer without a central round trip. | Network-disconnection test |
| EDGE-002 | P0 | The edge MUST integrate industrial camera capture and expose explicit connected, degraded, disconnected, and fault states. | Adapter and fault tests |
| EDGE-003 | P0 | The edge MUST delimit frames belonging to one physical product and prevent evidence mixing between products. | Sequence and boundary tests |
| EDGE-004 | P0 | Barcode decoding MUST be a separate capability; detection MAY locate its region but MUST NOT substitute for decoding. | Component/API tests |
| EDGE-005 | P0 | Product type resolution MUST be explicit and traceable; unresolved or conflicting identity MUST NOT produce `OK`. | Rule tests |
| EDGE-006 | P0 | Stage-one detection MUST locate the complete product in a full frame and report class, box, confidence, and optional tracking data. | Model contract tests |
| EDGE-007 | P0 | ROI generation MUST apply configurable margins, clip to image bounds, retain full-frame/ROI coordinate mapping, and reject invalid geometry. | Unit/property tests |
| EDGE-008 | P0 | Stage-two detection MUST identify configured required components in the generated product ROI. | Model evaluation |
| EDGE-009 | P0 | Temporal aggregation MUST combine evidence independently per required component and MUST NOT use whole-product majority voting. | Aggregator tests |
| EDGE-010 | P0 | The deterministic rule engine MUST emit decision, missing and low-confidence lists, reason codes, and active model/rule/product-configuration versions. | Golden tests |
| EDGE-011 | P0 | The edge MUST persist inspection metadata and required evidence atomically enough to recover after process restart or power loss. | Recovery test |
| EDGE-012 | P0 | The edge MUST persist upload work, retry with backoff, prevent duplicates through idempotency, verify media checksums, and resume after interruption. | Resilience test |
| EDGE-013 | P0 | Cleanup MUST protect records and files still required by pending uploads or active review policy. | Retention tests |
| EDGE-014 | P1 | The local FastAPI service and locally served Vue application SHOULD expose live status, recent results, evidence, storage/health state, queue state, logs, configuration, and manual retry while offline. | Local browser E2E |
| EDGE-015 | P1 | Inspection pause/resume MAY be exposed only after its operational authority and safe behavior are approved. | Acceptance procedure |

## 4. Central Functional Requirements

| ID | Priority | Requirement | Verification |
|---|---:|---|---|
| CENTRAL-001 | P1 | The central API MUST ingest inspection envelopes and selected media idempotently and return a durable receipt. | API/integration tests |
| CENTRAL-002 | P1 | Ingestion MUST detect payload conflicts for an already accepted idempotency key instead of silently replacing data. | Conflict tests |
| CENTRAL-003 | P1 | Central history MUST support time-, device-, line-, barcode-, product-, decision-, model-, rule-, and reason-based query with pagination. | API/query tests |
| CENTRAL-004 | P1 | The service MUST manage devices, products, product components, versioned rules, versioned model metadata, users, permissions, and audit records. | Authorization/E2E tests |
| CENTRAL-005 | P1 | Manual review MUST preserve the original automated result, reviewer outcome, reason, reviewer identity, and timestamps. | Audit tests |
| CENTRAL-006 | P1 | Dashboards MUST report device health, upload delay, OK/NG trends, missing components, barcode failures, and version-specific performance without presenting reviewed labels as raw predictions. | Data-quality tests |
| CENTRAL-007 | P1 | Configuration distribution MUST use immutable versioned packages, compatibility checks, staged activation, acknowledgement, and rollback. | Distribution tests |
| CENTRAL-008 | P1 | Media storage MUST use a filesystem abstraction or S3-compatible object storage with database metadata and integrity checks. | Storage integration tests |
| CENTRAL-009 | P0 | Central unavailability MUST NOT change or block an edge inspection decision. | Outage test |
| CENTRAL-010 | P2 | Future model package distribution MAY share the versioned distribution mechanism after signing/approval requirements are validated. | Release qualification |

## 5. Data and Upload Requirements

### 5.1 Common Inspection Record

Each inspection MUST include a globally unique inspection ID generated at the edge; device ID; inspection start/end timestamps; barcode value and read status where available; resolved product type and resolution source; final business result; internal decision state; detected, missing, and low-confidence components; per-component aggregate evidence; product box and ROI mapping; frame-quality summary; product-detector model, component-detector model, rule, and product-configuration versions; reason codes; media references and checksums; and upload status.

### 5.2 Upload Profile

| Outcome | Required central payload |
|---|---|
| `OK` | Metadata, barcode, product type, decision, component/confidence summary, versions, device/time, one representative key frame |
| `NG` | Full metadata, missing/low-confidence components, multiple key frames, annotated key frame, product ROI, optional event clip, relevant errors |
| System exception | Exception type, device/camera state, relevant image where available, bounded log excerpt, timestamp |

Every video frame MUST NOT be uploaded. Complete or rolling local video MAY be retained when required by an approved policy. Exact counts, formats, and retention periods are configuration decisions requiring validation.

## 6. Quality Attributes

| ID | Priority | Requirement | Verification |
|---|---:|---|---|
| QA-001 | P0 | Offline inspection MUST continue for the validated outage duration, bounded by local storage capacity. | Soak/outage test |
| QA-002 | P0 | Inspection and upload state MUST survive container restart and host reboot without duplicate business decisions. | Restart tests |
| QA-003 | P0 | All mutable operational configuration MUST be versioned, validated before activation, and attributable to an actor or source. | Audit tests |
| QA-004 | P0 | Logs MUST be structured and correlate by device ID, inspection ID, upload task ID, request ID, and active versions as applicable. | Observability tests |
| QA-005 | P0 | Disk monitoring MUST warn before exhaustion and apply safe, deterministic cleanup policy; disk-full MUST not yield `OK` when mandatory evidence cannot be committed. | Disk-full tests |
| QA-006 | P0 | Clock health and central receive time MUST be recorded so clock drift is detectable; ordering MUST not rely only on wall-clock time. | Clock-skew tests |
| QA-007 | P1 | APIs MUST use schema validation, bounded payloads, pagination, documented errors, and generated OpenAPI contracts. | Contract/security tests |
| QA-008 | P1 | Runtime services MUST use health checks, restart policies, persistent volumes, environment configuration, non-root containers, and read-only filesystems where practical. | Deployment inspection |
| QA-009 | P1 | Performance acceptance MUST measure average/P95 latency and throughput against observed line timing rather than an invented target. | Load/acceptance tests |
| QA-010 | P1 | Access to central administration, configuration, review, and evidence MUST be role-authorized and audited. | Authorization tests |
| QA-011 | P1 | Edge and central implementations MUST use Python 3.12 and the Web applications MUST use Vue 3 with TypeScript under the approved technology baseline. | Build inspection |
| QA-012 | P1 | Tests and evaluation MUST report NG recall, false-negative/positive rates, per-component/product recall, acquisition stages, barcode success, latency, throughput, upload delay, and review/correction rates. | Release report |

## 7. Scope Requirements by Horizon

### 7.1 Two-Day MVP

Applicable requirements are BR-002, BR-003, EDGE-005 through EDGE-008, EDGE-010, and the trace fields that can be populated for static images. The MVP uses folder input and output files; it does not claim EDGE-001 through EDGE-004 or operational durability.

### 7.2 One-Month Target

The target implements the remaining edge requirements, initial central requirements, local/central persistence, selected media upload, basic dashboards, Compose deployment, and resilience/evaluation tests. Features may remain demonstration-grade until their validation criteria are met.

### 7.3 Production Target

All P0 and applicable P1 requirements must have objective evidence. Release additionally requires customer-agreed thresholds, operational runbooks, security review, recovery/soak testing, accepted retention, package rollback, and cautious human-in-the-loop rollout.

### 7.4 Future

P2 requirements and integrations are separately approved. Kubernetes, automated retraining, Tauri packaging, PLC/MES integration, and edge PostgreSQL are not default production dependencies.

## 8. Constraints and Non-Requirements

- The edge deployment MUST NOT depend on Kubernetes; the central design remains Docker Compose friendly.
- AssemblyVision does not guarantee 100% accuracy or near-zero missed NG cases without measured evidence.
- The design does not assume exact camera/scanner vendors, GPU, OS, barcode standard, conveyor speed, network availability, component classes, retention period, server location, or acceptance threshold.
- The main dashboard will not use Tkinter, PyQt, or PySide. A future lightweight desktop wrapper may host the local Web application.
- `.pyc` files and Docker images reduce casual source browsing but are not anti-reverse-engineering or source-security boundaries.
- Training data, notebooks, production runtime data, and long-term secrets MUST NOT be included in client runtime images.

## 9. Open Questions and Validation Required

1. What exact thresholds, confidence policies, and required evidence qualify each component as present?
2. Is `UNCERTAIN` exposed to operators or only retained internally while business output remains `NG`?
3. Which edge operations require authentication in the one-month target?
4. Which metadata/media are mandatory for a locally committed result when storage is degraded?
5. What outage duration and disk reserve must the edge support?
6. What authorization, audit retention, encryption, and data residency obligations apply centrally?
7. What measurable performance and acceptance thresholds will be agreed from baseline data?
8. The authoritative unresolved list is [Global Open Questions](appendices.md#3-global-open-questions).
