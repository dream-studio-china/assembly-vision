# AssemblyVision Architecture Appendices

## 1. Terminology

| Term | Canonical meaning |
|---|---|
| AssemblyVision | The complete edge-client and central-server inspection platform. |
| Physical product | One real item moving through the inspection area; the unit of business decision. |
| Frame | One timestamped image from a camera or static-image source. |
| Inspection window | The bounded set of identity events and frames attributed to one physical product. |
| Inspection | The traceable processing record and decision for one physical product window. |
| Product detection | Stage-one inference on the full frame to locate/classify the complete product. |
| Product ROI | A crop generated from a detected product box, with margins, clipping, and coordinate mapping. |
| Component detection | Stage-two inference on the product ROI to find configured component classes. |
| Required component | A component that a versioned rule requires for a resolved product type. |
| Barcode decoding | Reading barcode data with a decoder/SDK; YOLO may locate a barcode region but is not the decoder. |
| Product-type resolution | Deterministic selection of product configuration from barcode and other approved evidence. |
| Frame quality | Typed evidence describing whether a frame is usable, blurred, clipped, exposed inadequately, or otherwise invalid. |
| Temporal aggregation | Combining valid frame-level evidence independently for each required component. It does not change single-frame model accuracy. |
| Rule engine | Versioned deterministic logic that turns aggregated evidence and product requirements into a decision. |
| Internal decision | `OK`, `NG`, or `UNCERTAIN` from rule evaluation. |
| Business result | `OK` or `NG`; internal `UNCERTAIN` always maps to `NG`. |
| False negative | A defective or incomplete real product incorrectly classified as `OK`. |
| False positive / false NG | A complete product classified as `NG`. |
| NG recall | Proportion of real defective/incomplete products classified as `NG`; primary acceptance metric. |
| Key frame | A selected frame retained/uploaded as representative inspection evidence. |
| Annotated image | A derived image with detections/results rendered; original evidence remains separately identifiable. |
| Edge client / device | The factory industrial computer and software that make local decisions. |
| Central server | The non-real-time management, ingestion, history, review, and reporting system. |
| Model version | Immutable identity of a model artifact and manifest; product and component detectors are identified separately. |
| Rule version | Immutable identity of deterministic decision and aggregation policy. |
| Product-configuration version | Immutable identity of product identity mapping and required component set. |
| Upload task | Durable edge work item for synchronizing metadata or media. |
| Durable receipt | Central acknowledgement that specified content was persistently accepted. |
| Review outcome | Human assessment linked to, but not replacing, the original automated result. |
| Acceptance dataset | Customer production data excluded from training and used for agreed validation. |

## 2. Decision Consistency Checklist

Use this checklist for every architecture, API, schema, UI, and operational change.

- [ ] Production-critical decisions remain entirely executable at the edge.
- [ ] Network or central failure cannot turn incomplete evidence into `OK` or stop otherwise healthy local inspection.
- [ ] The business output remains `OK`/`NG`; any `UNCERTAIN` state is explicit and conservative.
- [ ] Product detection uses the full frame and creates the final product ROI; no perfect product position is assumed.
- [ ] Component detection runs on the generated ROI and detects present required classes, not an abstract global missing class.
- [ ] Barcode decoding remains separate from YOLO detection/classification.
- [ ] Temporal aggregation is per required component, excludes unusable evidence, and is not described as improving single-frame accuracy.
- [ ] The deterministic rule engine remains independent from model implementation.
- [ ] Each inspection pins immutable product-detector, component-detector, rule, and product-configuration versions.
- [ ] Identity, coordinate space, timestamps, evidence lineage, and reason codes remain traceable.
- [ ] Edge records/media/upload tasks survive restart and protect pending evidence from cleanup.
- [ ] Synchronization is at-least-once with stable idempotency and content/checksum conflict detection.
- [ ] The server never overwrites an original edge decision with a review outcome.
- [ ] OK uploads remain selective; all frames are not sent centrally by default.
- [ ] Thresholds, timing, retention, hardware, hosting, and acceptance claims are measured or marked unresolved.
- [ ] Two-day MVP, one-month target, production target, and future scope are not conflated.
- [ ] Docker Compose remains sufficient for edge and initial central deployment; edge has no Kubernetes dependency.
- [ ] Optional Redis, brokers, PostgreSQL at edge, Kubernetes, and desktop wrapping have a concrete justification before adoption.
- [ ] Source packaging is not represented as strong reverse-engineering protection.
- [ ] Training data, production media/data, notebooks, secrets, and runtime artifacts remain outside Git/client images as applicable.
- [ ] New requirements and decisions have trace links and objective verification evidence.

## 3. Global Open Questions

### 3.1 Product and Process

| ID | Question | Affects | Needed by |
|---|---|---|---|
| OQ-001 | Which product types, exact required component classes, and variants are in scope? | Data, models, rules, UI | Two-day MVP configuration; production validation |
| OQ-002 | What physical event opens/closes a product window, and can products overlap or appear in multiples? | Acquisition, aggregation, duplicate prevention | One-month target |
| OQ-003 | What is the measured conveyor cycle/line rate and required decision deadline? | Hardware sizing, buffering, acceptance | One-month target |
| OQ-004 | How is `NG` consumed, and are PLC/MES/diverter integrations in scope? | External interface, safe states | Production target |
| OQ-005 | Who can pause/resume inspection and what must the physical process do while paused/faulted? | Operations, authorization | Production target |

### 3.2 Hardware and Environment

| ID | Question | Affects | Needed by |
|---|---|---|---|
| OQ-006 | What camera vendor/model, SDK, interface, trigger mode, lens, pixel format, and frame rate apply? | Adapter, image quality, deployment | One-month target |
| OQ-007 | What barcode standard, location, reader/SDK, and read-rate expectation apply? | Decoder, product resolution | One-month target |
| OQ-008 | What OS, CPU, GPU/accelerator, memory, disk, and container runtime are supported? | Packaging, performance, capacity | One-month target |
| OQ-009 | What measured shift, rotation, blur, exposure, reflection, and occlusion ranges define normal operation? | Data collection, quality gates, acceptance | Production target |
| OQ-010 | What constitutes a meaningful camera move and how is recalibration/revalidation initiated? | Health, operations, model validity | Production target |

### 3.3 Decision and Validation

| ID | Question | Affects | Needed by |
|---|---|---|---|
| OQ-011 | What per-model/product confidence, visible-area, frame-quality, aggregation, and timeout thresholds are validated? | Rules, model acceptance | Production target |
| OQ-012 | Is internal `UNCERTAIN` visible in UI/API, and what review routing does it receive? | Domain/API/UI | One-month target |
| OQ-013 | What customer-agreed NG recall, false-negative, false-positive, latency, and throughput criteria follow baseline evaluation? | Release acceptance | Production target |
| OQ-014 | How many independent production samples and missing-component cases are feasible and statistically sufficient? | Dataset/evaluation | Production target |
| OQ-015 | Who approves labels, models, rules, package promotion, and retraining candidates? | Governance/audit | Production target |

### 3.4 Storage, Network, and Hosting

| ID | Question | Affects | Needed by |
|---|---|---|---|
| OQ-016 | What local retention periods, media profiles, outage duration, disk reserve, and evidence holds apply? | Disk sizing, cleanup | One-month target |
| OQ-017 | What central retention, deletion, backup, recovery, residency, and legal requirements apply? | Storage/security/operations | Production target |
| OQ-018 | What network reliability, bandwidth, proxy/firewall, TLS, inbound/outbound, and maintenance constraints apply? | Synchronization/distribution | One-month target |
| OQ-019 | Where is the central server hosted and what availability/recovery objectives apply? | Deployment/DR | Production target |
| OQ-020 | What expected inspection/media volume, device count, query concurrency, and growth determine capacity? | Database/object store/jobs | Production target |

### 3.5 Security and Operations

| ID | Question | Affects | Needed by |
|---|---|---|---|
| OQ-021 | Is tenancy required, and what organization/site/line hierarchy and isolation apply? | Central domain/auth | One-month target |
| OQ-022 | Which human identity provider, roles, device credential/PKI, signing, and rotation policies apply? | Authentication/distribution | Production target |
| OQ-023 | How are barcode and image data classified; what encryption, export, and access-audit controls apply? | Security/storage/UI | Production target |
| OQ-024 | Who operates edge/central services, receives alerts, and owns incident/recovery runbooks? | Observability/support | Production target |
| OQ-025 | Is casual source-browsing deterrence sufficient contractually, or are stronger controls required? | Edge packaging/commercial risk | Before client delivery |

## 4. Reason-Code Glossary

Reason codes are stable machine-readable identifiers. A record may contain several codes; `primary_reason_code` selects the principal explanation. Message text is localized/presentational and must not replace the code. New codes require schema documentation, tests, severity/default mapping, and backward-compatible central display.

| Code | Meaning | Default internal state | Typical action |
|---|---|---|---|
| `OK_ALL_REQUIRED_PRESENT` | All required components meet the pinned rule using valid evidence. | `OK` | Record and apply normal OK upload policy |
| `NG_COMPONENT_MISSING` | A required component has sufficient valid evidence of absence under the rule. | `NG` | Review component evidence |
| `UNCERTAIN_COMPONENT_LOW_CONFIDENCE` | A required component has evidence below its validated presence criterion. | `UNCERTAIN` | Business `NG`; review and evaluate threshold/model |
| `UNCERTAIN_INSUFFICIENT_VALID_FRAMES` | Too few usable frames were available for the aggregation policy. | `UNCERTAIN` | Business `NG`; inspect acquisition/quality |
| `UNCERTAIN_PRODUCT_NOT_DETECTED` | No valid product detection supports ROI generation. | `UNCERTAIN` | Business `NG`; inspect frame and product model |
| `UNCERTAIN_MULTIPLE_PRODUCTS` | More than one product candidate makes attribution ambiguous. | `UNCERTAIN` | Business `NG`; inspect window/spacing |
| `UNCERTAIN_ROI_INVALID` | Product ROI geometry is empty, excessively clipped, or otherwise invalid. | `UNCERTAIN` | Business `NG`; inspect product detection/ROI config |
| `UNCERTAIN_BARCODE_NOT_READ` | Required barcode decoding did not produce an accepted value. | `UNCERTAIN` | Business `NG`; inspect reader/image |
| `UNCERTAIN_BARCODE_CONFLICT` | Multiple identity observations conflict. | `UNCERTAIN` | Business `NG`; review identity events |
| `UNCERTAIN_PRODUCT_TYPE_UNKNOWN` | Identity cannot map to an installed product configuration. | `UNCERTAIN` | Business `NG`; correct mapping/package |
| `UNCERTAIN_FRAME_QUALITY` | Frames fail blur, exposure, visibility, or other validated quality gates. | `UNCERTAIN` | Business `NG`; inspect environment/camera |
| `UNCERTAIN_WINDOW_TIMEOUT` | The inspection window ended by timeout without complete evidence. | `UNCERTAIN` | Business `NG`; inspect trigger/timing |
| `ERROR_CAMERA_UNAVAILABLE` | Camera is disconnected or cannot supply valid frames. | Fault | Stop decision path safely; reconnect/repair |
| `ERROR_CAPTURE_FAILED` | Frame acquisition failed within a window. | Fault or `UNCERTAIN` | Preserve exception; recover adapter |
| `ERROR_MODEL_LOAD_FAILED` | A required model cannot load or pass health checks. | Fault | Keep/restore last known-good package |
| `ERROR_MODEL_RULE_INCOMPATIBLE` | Active model classes/manifest are incompatible with rule/configuration. | Fault | Reject activation; rollback |
| `ERROR_INFERENCE_FAILED` | A required inference operation failed. | `UNCERTAIN` or Fault | Business `NG`; log bounded diagnostics |
| `ERROR_PERSISTENCE_FAILED` | Mandatory inspection metadata cannot be committed. | Fault | Do not report unjustified `OK`; recover storage |
| `ERROR_MEDIA_COMMIT_FAILED` | Mandatory evidence media cannot be finalized. | Fault or `UNCERTAIN` | Apply approved minimum-evidence policy |
| `ERROR_DISK_CRITICAL` | Free space crossed the critical watermark or mandatory writes are unsafe. | Fault | Safe cleanup; operator intervention |
| `ERROR_CONFIGURATION_INVALID` | Installed or requested configuration fails schema/invariant checks. | Fault | Reject package; retain known-good version |
| `INFO_NETWORK_OFFLINE` | Central network path is unavailable while local inspection remains viable. | Degraded | Buffer uploads and retry |
| `INFO_CENTRAL_UNAVAILABLE` | Central endpoint is unavailable. | Degraded | Continue local inspection and retry |
| `WARN_UPLOAD_RETRYING` | A transient synchronization failure is scheduled for retry. | Degraded | Observe queue age/attempts |
| `ERROR_UPLOAD_PERMANENT` | Upload failed validation/authentication or exceeded approved handling policy. | Degraded | Operator/support resolution; preserve evidence |
| `ERROR_UPLOAD_CONFLICT` | Central detected the same identity/idempotency key with different content. | Degraded | Quarantine task and investigate integrity |
| `WARN_CLOCK_DRIFT` | Device wall clock differs beyond the validated tolerance. | Degraded | Correct clock; use receive/monotonic evidence |
| `CANCELLED_OPERATOR_REQUEST` | An authorized operator cancelled an active inspection under approved policy. | `UNCERTAIN` | Business `NG`; audit actor and reason |

Fault-versus-uncertain behavior for capture/media failures depends on whether recovery within the current window is validated. It must be configured explicitly and can never default to `OK`.

## 5. Traceability Conventions

### 5.1 Identifier Namespaces

| Prefix | Artifact | Example |
|---|---|---|
| `BR-` | Business requirement | `BR-003` |
| `EDGE-` | Edge functional requirement | `EDGE-009` |
| `CENTRAL-` | Central functional requirement | `CENTRAL-001` |
| `QA-` | Quality attribute requirement | `QA-005` |
| `OQ-` | Open question | `OQ-016` |
| `ADR-` | Architecture decision record | `ADR-001` |
| `TC-` | Test case | `TC-EDGE-009-01` |
| `EV-` | Evaluation/acceptance evidence | `EV-MODEL-2026-001` |

IDs are never reused after publication. Changed meaning receives a new ID or an explicit supersession link.

### 5.2 Inspection Correlation

Use globally unique opaque `device_id` and edge-generated `inspection_id`. `frame_id`, `media_id`, and `upload_task_id` are unique and reference the inspection. Every frame/evidence item records capture sequence/time and coordinate space (`FULL_FRAME`, `PRODUCT_ROI`, or derived space) plus the transform needed for overlays.

At window start, pin and persist:

- Product-detector model ID/version/checksum.
- Component-detector model ID/version/checksum.
- Rule ID/version.
- Product-configuration ID/version.
- Aggregation and frame-quality policy versions if not fully contained by the rule version.
- Application/build version and relevant adapter/configuration versions.

Wall-clock timestamps use RFC 3339 UTC. Preserve original device time, monotonic sequence/duration where available, timezone/clock-health metadata, and central receive time; never silently rewrite an edge timestamp.

### 5.3 Requirement-to-Evidence Matrix

Each implementation pull request or release record should identify affected requirement IDs. Tests name the requirement in metadata or docstrings, and release evidence links requirements to code/module, test case, result, environment, dataset version where relevant, and approving role.

| Requirement | Design owner | Verification artifact | Release evidence |
|---|---|---|---|
| `BR-003` | Rule and failure semantics | Conservative-path golden tests | Test report plus reviewed exception samples |
| `EDGE-009` | Per-component aggregator | Unit/sequence tests | Evaluation report by component |
| `EDGE-012` | Upload scheduler/ingestion | Retry, conflict, outage tests | Resilience run log and receipts |
| `CENTRAL-005` | Review/audit domain | API and concurrency tests | Audit export from acceptance run |
| `QA-005` | Storage/retention | Disk watermark/full tests | Recovery and no-data-loss report |

The table is illustrative, not a substitute for a complete generated trace matrix.

### 5.4 Model and Dataset Lineage

A model manifest links artifact checksum, architecture/runtime requirements, class map, training dataset version, split strategy, code/configuration revision, evaluation dataset(s), metrics by product/component, limitations, approval, and superseded version. Dataset splits group by batch, capture session/date, and physical product so adjacent frames do not leak across train and validation sets.

Starting data targets are approximately 300-800 real images for a primary product class and approximately 300-500 labeled instances per component class, including practical intentionally missing scenarios (initially around 100 images per missing scenario where feasible). These are planning starts, not guarantees; measured validation determines additional collection.

### 5.5 Review Lineage

A review record references the immutable inspection, original business/internal result, selected evidence, reviewer identity, review outcome, reason, timestamps, and revision/concurrency token. Corrected cases enter a training backlog by reference. Dataset inclusion requires a separate approved labeling action; a review does not automatically retrain or relabel historical model metrics.

## 6. Scope-Language Convention

- **Two-day MVP** means the static-image vertical slice and excludes camera/video/central/UI/authentication/integrations.
- **One-month target** means an implementation target subject to hardware, data, and site dependencies; it is not automatically production-ready after one month.
- **Production target** means behavior required after measured validation, acceptance, security/operational hardening, and runbook approval.
- **Future** means optional scope with no current delivery commitment.

## 7. Open Questions and Validation Required

The authoritative unresolved decisions are listed in [Section 3](#3-global-open-questions). Document owners must add new unknowns there, link the affected requirement/decision, assign an owner and due horizon in the project tracker, and record the evidence used to close them. Closing an open question may require updates to reason-code defaults, diagrams, tests, and acceptance evidence; a meeting decision without recorded rationale and validation is insufficient.
