# Task: Generate the Complete AssemblyVision Software Architecture Documentation

You are a principal software architect, industrial computer-vision engineer, MLOps engineer, and full-stack technical writer.

Your task is to generate a complete, internally consistent, implementation-oriented software architecture document set for an industrial AI inspection platform named **AssemblyVision**.

Do not produce a superficial README or generic AI-generated overview. Produce a practical engineering blueprint that a small software team can use to begin implementation immediately.

The documentation must describe both the initial MVP and the target production architecture.

---

# 1. Project Context

## 1.1 Project Name

**AssemblyVision**

Full title:

**AssemblyVision — Industrial Assembly Inspection System**

## 1.2 Business Purpose

AssemblyVision is an industrial computer-vision system used on a conveyor-based production line.

The system inspects completed products and verifies whether all required assembly components are present.

The inspection targets include:

- The complete product
- Several large assembly components
- Product manuals or instruction sheets
- Product barcodes
- Product model or product type

The primary business output is:

- `OK`: all required components are reliably detected
- `NG`: one or more required components are missing, uncertain, or cannot be reliably verified

## 1.3 Quality Priority

The system must prioritize reducing false negatives.

A false negative in this project means:

> A real defective or incomplete product is incorrectly classified as OK.

The business accepts a certain number of false NG results during the early production phases, because those products can be manually reviewed.

The engineering priority is therefore:

1. Minimize false negatives
2. Maintain traceability
3. Improve robustness
4. Gradually reduce false positives
5. Improve operational efficiency

Do not describe the system as guaranteeing 100% accuracy.

Use language such as:

- extremely low false-negative rate
- near-zero missed NG cases as an engineering objective
- production acceptance based on measured validation data
- high NG recall
- cautious rollout with human verification

---

# 2. Confirmed Production Conditions

The current physical environment has the following characteristics:

- Industrial camera with approximately four megapixels
- Fixed lighting
- Fixed camera during normal production
- Controlled inspection environment
- Products may shift slightly within the image
- Product position is not perfectly fixed
- Products do not normally undergo large uncontrolled rotations
- Inspection targets are large components
- No micro-component or tiny screw inspection is currently required
- The inspection task focuses primarily on component presence
- The system must implement camera capture itself
- The system must implement barcode recognition itself
- The system must implement image and video storage itself
- The system must implement inspection result storage itself
- The client machine must continue inspecting while disconnected from the central server

Do not state that image saving or barcode recording already exists.

These capabilities must be implemented as part of AssemblyVision.

---

# 3. Final Architecture Decision

AssemblyVision uses an **edge-client and central-server architecture**.

All production-critical image processing and inspection decisions must happen on the client-side industrial computer.

The central server must not be required for real-time inspection.

## 3.1 Edge Client Responsibilities

The edge client runs inside the customer’s factory and is responsible for:

- Industrial camera integration
- Video stream or frame capture
- Trigger handling
- Product-window management
- Barcode recognition
- Product-type resolution
- YOLO product detection
- ROI generation
- YOLO component detection
- Optional OpenCV inspection
- Multi-frame temporal aggregation
- Rule evaluation
- Final OK or NG decision
- Local inspection database
- Local image storage
- Local video or video-clip storage
- Upload queue
- Retry after network interruption
- Local device health monitoring
- Local FastAPI service
- Local Vue dashboard

The inspection pipeline must continue operating if the central server or network is unavailable.

## 3.2 Central Server Responsibilities

The central Web server is responsible for:

- Receiving uploaded inspection results
- Receiving selected key image frames
- Receiving optional NG video clips
- Centralized inspection history
- Cross-device and cross-line reporting
- Device management
- Product configuration management
- Rule configuration management
- Model version management
- User and permission management
- Manual NG review
- Data dashboards
- Statistical analysis
- Audit logs
- Remote configuration distribution
- Future model package distribution

## 3.3 Upload Strategy

Do not upload every video frame to the central server.

The edge client should retain the complete or rolling local video when required.

Recommended upload policy:

### For OK inspections

Upload:

- Inspection metadata
- Barcode
- Product type
- Final decision
- Detected components
- Confidence summary
- Model version
- Rule version
- Device ID
- Inspection timestamp
- One representative key frame

### For NG inspections

Upload:

- Full inspection metadata
- Missing components
- Low-confidence components
- Multiple key frames
- Annotated key frame
- Product ROI image
- Optional short video clip around the inspection event
- Relevant error logs

### For system exceptions

Upload:

- Exception type
- Device state
- Camera state
- Relevant image
- Relevant log excerpt
- Timestamp

The upload subsystem must support:

- Offline buffering
- Persistent upload queue
- Retry with backoff
- Idempotency
- Duplicate prevention
- Upload status tracking
- Checksum verification
- Local retention policies

---

# 4. Technology Decisions

## 4.1 Edge Backend

Use:

- Python 3.12
- FastAPI
- Uvicorn
- Ultralytics YOLO
- OpenCV
- Pydantic
- SQLAlchemy
- Alembic
- SQLite initially for local storage
- PostgreSQL optionally for larger edge installations
- Pytest
- Ruff
- MyPy
- structlog or standard structured logging

The first MVP may use SQLite locally.

## 4.2 Central Backend

Use:

- Python 3.12
- FastAPI
- Uvicorn or Gunicorn
- Pydantic
- SQLAlchemy
- Alembic
- PostgreSQL
- Redis where justified
- Celery, Dramatiq, RQ, or another background-job system where justified
- S3-compatible object storage or filesystem abstraction
- Pytest
- Ruff
- MyPy

Do not introduce background workers merely for architectural appearance. Explain which jobs require asynchronous execution.

## 4.3 Web Frontend

Both the local edge dashboard and the central administration dashboard use:

- Vue 3
- TypeScript
- Vite
- Vue Router
- Pinia
- Axios or a generated OpenAPI client
- Element Plus or Naive UI
- ECharts
- VueUse
- Vitest
- ESLint
- Prettier

Use Vue and TypeScript because the system requires:

- Complex administration pages
- Reusable tables
- Data dashboards
- Real-time status
- Image inspection views
- Detection-box overlays
- Rule configuration
- Device status
- Upload-queue visualization
- Manual review
- Typed API integration

The local edge dashboard must be a Web application served locally.

It may be opened through:

- A standard browser
- Browser kiosk mode
- A lightweight desktop wrapper such as Tauri in a future version

Do not recommend building the main dashboard with Tkinter, PyQt, or PySide unless discussing them as rejected alternatives.

## 4.4 Deployment

Use:

- Docker
- Docker Compose
- Nginx where appropriate
- Persistent volumes
- Multi-stage builds
- Non-root containers
- Environment-based configuration
- Health checks
- Restart policies

The edge deployment must not depend on Kubernetes.

The central server may support Kubernetes as a future option, but the initial design should remain Docker Compose friendly.

---

# 5. Detection Architecture

Use a two-stage detection pipeline.

## 5.1 Stage One: Product Detection

The first detector locates the complete product.

Input:

- Full camera frame

Output:

- Product class
- Bounding box
- Confidence
- Optional tracking information

Purpose:

- Handle slight product position changes
- Avoid relying on a hard-coded absolute ROI
- Normalize the input for component inspection

## 5.2 ROI Extraction

The ROI engine:

- Receives the product bounding box
- Expands it using configurable margins
- Clips the coordinates to image boundaries
- Crops the product region
- Records the mapping between full-frame and ROI coordinates
- Optionally normalizes orientation or perspective

Do not assume that the product location is perfectly fixed.

A hard-coded full-frame ROI may be available as a fallback or coarse capture zone, but the final product ROI should be generated from product detection.

## 5.3 Stage Two: Component Detection

The second detector processes the product ROI.

Possible classes include:

- `component_a`
- `component_b`
- `component_c`
- `manual`
- Other configured components

The specific required component list depends on product type.

The system should detect required components rather than train an abstract global `missing_component` class.

## 5.4 Barcode Recognition

Barcode recognition must be implemented as a separate capability.

It may use:

- Industrial scanner SDK
- OpenCV barcode APIs
- pyzbar or ZXing-compatible solutions
- A vendor-specific camera or scanner SDK

Barcode recognition must not be implemented as a YOLO classification task unless YOLO is only used to locate a barcode region.

The barcode identifies or helps resolve:

- Product identity
- Product type
- Required inspection rule
- Traceability record

## 5.5 Rule Engine

The rule engine must be deterministic and independent from the AI model.

Example:

```yaml
product_type: model_a
required_components:
  - component_a
  - component_b
  - manual
```

The rule engine evaluates the aggregated detection evidence and returns:

- `OK`
- `NG`
- `UNCERTAIN`, if such a state is adopted
- Missing component list
- Low-confidence component list
- Failure reason codes

The rule engine must store:

- Rule version
- Product configuration version
- Model version

---

# 6. Video and Temporal Aggregation

YOLO processes video as individual frames.

The business decision, however, is made per physical product.

Introduce a temporal aggregator between frame-level detection and final rule evaluation.

## 6.1 Product Inspection Window

The system must group frames belonging to the same physical product.

Possible mechanisms include:

- Hardware trigger
- Barcode event
- Product tracking
- Entry and exit detection zones
- Time-bounded inspection windows
- Conveyor sensor integration

Discuss the trade-offs.

## 6.2 Aggregation Policy

Do not use simple whole-product majority voting.

Aggregate evidence per required component.

Example:

```text
component_a:
frame 1: detected at 0.91
frame 2: not detected
frame 3: detected at 0.88
final state: present
```

```text
component_b:
frame 1: not detected
frame 2: not detected
frame 3: not detected
final state: missing
```

Support configurable policies such as:

- One high-confidence detection
- Two medium-confidence detections
- Detection in adjacent frames
- Minimum visible-area requirements
- Minimum frame-quality requirements
- Exclusion of blurred or unusable frames

Explain clearly:

> Temporal aggregation does not increase the underlying YOLO model’s single-frame accuracy. It increases system-level robustness by combining evidence across frames.

---

# 7. Local Storage Architecture

The edge client must maintain local persistent storage.

Store:

- Inspection metadata
- Barcode
- Product type
- Frame timestamps
- Final result
- Detected components
- Missing components
- Confidence values
- Product bounding box
- ROI metadata
- Model version
- Rule version
- Key-frame paths
- Annotated-image paths
- Video-clip paths
- Upload status
- Retry count
- Error information

The local system must support:

- Power-loss recovery
- Restart recovery
- Upload resume
- Disk-space monitoring
- Configurable data retention
- Safe cleanup
- Protection against deleting files still waiting for upload

Define a storage policy for:

- Full video
- Rolling video
- Key frames
- NG clips
- Annotated images
- ROI images
- Logs
- Database records

---

# 8. Frontend Architecture

## 8.1 Edge Dashboard

The local edge dashboard should include:

- Current camera preview
- Latest inspection result
- Current barcode
- Current product type
- Current detected components
- Missing components
- OK or NG indicator
- Inspection latency
- Camera connection state
- AI model state
- Local disk state
- Network state
- Central-server connectivity
- Upload-queue status
- Recent inspection records
- Local configuration
- Local service logs
- Manual retry for failed uploads
- Emergency inspection pause or resume if operationally appropriate

The dashboard must remain usable while offline.

## 8.2 Central Administration Dashboard

The central dashboard should include:

- Multi-device overview
- Multi-line overview
- Inspection statistics
- OK and NG trends
- Missing-component distribution
- Barcode failure rates
- Model-version performance
- Rule-version performance
- Device health
- Device last-seen state
- Upload delays
- Historical inspection queries
- Image and video review
- Manual NG verification
- Product configuration
- Rule management
- Model package management
- Users and roles
- Audit logs
- Export and reporting

## 8.3 Frontend Code Reuse

The Monorepo should support reusable frontend packages for:

- Shared UI components
- Image viewer
- Detection overlays
- Status badges
- Data tables
- Chart components
- TypeScript domain types
- API client
- Authentication helpers
- Validation schemas
- Formatting utilities

Clearly distinguish the edge Web application from the central administration Web application.

---

# 9. Monorepo Architecture

Use a Monorepo supporting Python and TypeScript.

Use a structure based on the following principles:

- `apps/` contains runnable applications
- `packages/python/` contains reusable Python packages
- `packages/typescript/` contains reusable frontend packages
- `training/` contains training and evaluation code
- `models/` contains local development model artifacts or metadata
- `deploy/` contains deployment definitions
- `docs/` contains architecture documentation
- `tests/` contains cross-application tests
- Runtime production data must not be stored inside the Git repository

Generate and explain a clear directory structure similar to:

```text
assembly-vision/
├── apps/
│   ├── edge-api/
│   ├── edge-web/
│   ├── edge-worker/
│   ├── edge-cli/
│   ├── server-api/
│   ├── server-worker/
│   └── admin-web/
│
├── packages/
│   ├── python/
│   │   ├── vision-core/
│   │   ├── image-sources/
│   │   ├── camera-adapters/
│   │   ├── barcode/
│   │   ├── product-detector/
│   │   ├── roi-engine/
│   │   ├── component-detector/
│   │   ├── temporal-aggregator/
│   │   ├── rule-engine/
│   │   ├── local-storage/
│   │   ├── upload-client/
│   │   ├── central-domain/
│   │   └── common/
│   │
│   └── typescript/
│       ├── ui/
│       ├── api-client/
│       ├── domain-types/
│       ├── detection-viewer/
│       ├── charts/
│       └── common/
│
├── training/
│   ├── product-detector/
│   ├── component-detector/
│   ├── datasets/
│   ├── evaluation/
│   └── shared/
│
├── models/
│   ├── product-detector/
│   ├── component-detector/
│   └── manifests/
│
├── deploy/
│   ├── edge/
│   ├── server/
│   ├── docker/
│   ├── compose/
│   └── nginx/
│
├── tests/
│   ├── integration/
│   ├── e2e/
│   ├── performance/
│   ├── resilience/
│   └── fixtures/
│
├── docs/
├── config/
├── scripts/
├── pyproject.toml
├── uv.lock
├── package.json
├── pnpm-workspace.yaml
├── docker-compose.yml
├── Makefile
└── README.md
```

Improve this structure when appropriate, but preserve clear architectural boundaries.

Do not create unnecessary package fragmentation.

Explain which packages are required for the MVP and which should be added later.

---

# 10. Source Distribution and Client Deployment

The complete edge application runs on customer-controlled hardware.

The goal is to avoid directly exposing readable source code, not to guarantee protection from advanced reverse engineering.

Document the following deployment approach:

- Compile Python modules into `.pyc`
- Remove original `.py` files from the final runtime image where practical
- Use multi-stage Docker builds
- Deploy only built frontend static assets
- Do not deploy the Git repository
- Do not deploy training datasets
- Do not deploy notebooks
- Do not deploy internal experiment configuration
- Do not embed long-term secrets in images
- Use a non-root runtime user
- Use read-only container filesystems where practical
- Store runtime data in explicit volumes

Clearly state:

- `.pyc` is not strong anti-reverse-engineering protection
- Docker is not a source-code security boundary
- This level is accepted because the immediate requirement is only to avoid direct casual source browsing

Do not over-engineer licensing or obfuscation in the MVP.

---

# 11. Training Strategy

## 11.1 Product Detector

Initial target:

- Approximately 300 to 800 real production images
- One primary `product` class
- Include slight position changes
- Include normal production variation
- Include background-only or empty-frame negatives
- Use actual production camera and lighting

## 11.2 Component Detector

Initial target:

- Approximately 300 to 500 labeled instances per component class
- Use product ROI images
- Include normal presence cases
- Intentionally create missing-manual and missing-component cases
- Start with approximately 100 images per missing-component scenario where practical

Do not assume these numbers guarantee a target accuracy.

Describe them as starting points that must be adjusted based on measured validation performance.

## 11.3 Data Splitting

Avoid leakage from adjacent video frames.

Split datasets by:

- Product batch
- Capture session
- Production date
- Physical product instance

Do not randomly split nearly identical adjacent frames across train and validation sets.

## 11.4 Camera Angle

The initial model should optimize for one fixed production angle.

Multi-angle data is not required for the first production line if the camera remains fixed.

If the camera angle changes significantly:

- Test the current model
- Collect data from the new angle
- Fine-tune the existing model
- Revalidate the complete system

A camera-angle change near 45 degrees should be treated as a meaningful domain change.

---

# 12. Human-in-the-Loop Strategy

Use a cautious rollout.

Initial production phase:

- AI performs automatic inspection
- All NG results are available for human review
- Low-confidence cases may be reviewed
- A sample of OK results may be audited
- Corrections are stored
- Misclassified cases are added to the training backlog

Later reduction of manual review must be based on production evidence, not a fixed calendar date.

Track:

- Manual review rate
- Manual correction rate
- False-positive rate
- Estimated false-negative rate
- Per-product performance
- Per-component performance
- Performance by model version
- Performance by rule version

---

# 13. MVP Scope

## 13.1 Two-Day Static Image MVP

The first MVP processes static images only.

Required workflow:

```text
Input folder
→ Read image
→ Detect product
→ Generate ROI
→ Detect components
→ Evaluate rules
→ Output OK or NG
→ Save JSON
→ Save annotated image
→ Save ROI
```

Day one:

- Initialize Monorepo
- Implement folder image source
- Load product detector
- Detect product bounding box
- Implement ROI extraction
- Save ROI images
- Save initial JSON output

Day two:

- Load component detector
- Detect required components
- Implement initial rule engine
- Produce OK or NG decision
- Save missing-component reasons
- Save annotated images
- Add CLI command
- Add minimal tests
- Add run instructions

Do not include in the two-day MVP:

- Camera SDK integration
- Real-time video
- Temporal aggregation
- Central server
- Complete edge dashboard
- Complete administration dashboard
- Authentication
- PLC integration
- MES integration
- Automated retraining

## 13.2 One-Month Target

Week 1:

- Static image pipeline
- Product detector
- ROI engine
- Component detector
- Rule engine
- Basic evaluation

Week 2:

- Camera integration
- Barcode recognition
- Local database
- Local file storage
- Edge API
- Basic edge dashboard

Week 3:

- Video-frame processing
- Product-window management
- Temporal aggregation
- Upload queue
- Central API
- Initial central database
- Initial administration dashboard

Week 4:

- Docker deployment
- Offline resilience
- Retry behavior
- Data retention
- Logs and health monitoring
- Customer-site testing
- Acceptance dataset evaluation
- Deployment documentation
- Operator documentation

Make the roadmap realistic and identify dependencies and risks.

---

# 14. Required Documentation Set

Generate the documentation as multiple Markdown files.

Use the following structure:

```text
docs/
├── 00-cover-and-status.md
├── 01-introduction.md
├── 02-requirements.md
├── 03-architecture-overview.md
├── 04-edge-client-architecture.md
├── 05-central-server-architecture.md
├── 06-ai-detection-pipeline.md
├── 07-camera-and-image-acquisition.md
├── 08-product-detection-and-roi.md
├── 09-component-detection.md
├── 10-temporal-aggregation.md
├── 11-rule-engine.md
├── 12-local-storage-and-retention.md
├── 13-upload-and-synchronization.md
├── 14-data-model-and-database.md
├── 15-rest-api-and-events.md
├── 16-edge-dashboard.md
├── 17-central-admin-dashboard.md
├── 18-monorepo-and-code-organization.md
├── 19-training-and-evaluation.md
├── 20-deployment-and-operations.md
├── 21-security-and-source-distribution.md
├── 22-testing-and-quality-assurance.md
├── 23-observability-and-support.md
├── 24-human-in-the-loop.md
├── 25-roadmap.md
├── 26-customer-acceptance.md
├── 27-risks-and-mitigations.md
└── appendices.md
```

Also generate:

```text
README.md
docs/README.md
docs/decisions/
```

Generate architecture decision records for important decisions such as:

- ADR-001: Edge-first inspection
- ADR-002: Python backend
- ADR-003: Vue 3 and TypeScript frontend
- ADR-004: Two-stage detection
- ADR-005: Local-first storage and delayed upload
- ADR-006: REST plus WebSocket
- ADR-007: Monorepo
- ADR-008: Docker deployment
- ADR-009: Static-image-first MVP
- ADR-010: Per-component temporal aggregation

---

# 15. Required Diagrams

Use Mermaid.

Include at minimum:

- System context diagram
- Edge and central-server deployment diagram
- Edge component diagram
- Central-server component diagram
- Static-image inspection sequence
- Real-time inspection sequence
- Temporal aggregation sequence
- Upload and retry sequence
- Offline operation sequence
- Manual review sequence
- Model update sequence
- Data-retention lifecycle
- Monorepo dependency diagram
- Database entity relationship diagram
- Device state diagram
- Inspection state diagram

Ensure Mermaid syntax is valid.

Do not put unsupported syntax inside diagrams.

---

# 16. Required Data Models

Provide concrete Pydantic examples for:

- BoundingBox
- Detection
- FrameQuality
- ProductDetection
- ROIResult
- ComponentDetection
- AggregatedComponentEvidence
- InspectionDecision
- InspectionRecord
- UploadTask
- DeviceStatus
- ProductConfiguration
- RuleConfiguration
- ModelManifest
- ReviewRecord

Provide matching TypeScript types or interfaces.

Explain how to keep Python and TypeScript API types synchronized.

Recommend OpenAPI-based TypeScript client generation where appropriate.

---

# 17. Required APIs

Define practical API endpoints for the edge and central systems.

## Edge APIs

Examples:

- Camera state
- Inspection state
- Recent inspections
- Local inspection details
- Local image retrieval
- Upload queue
- Retry upload
- Local configuration
- Device health
- WebSocket inspection events

## Central APIs

Examples:

- Authentication
- Devices
- Production lines
- Inspections
- Images
- NG reviews
- Products
- Required-component rules
- Models
- Rule versions
- Device configuration
- Dashboard
- Reports
- System events
- Audit logs

For each API group, include:

- Endpoint
- Method
- Purpose
- Request schema
- Response schema
- Error conditions
- Idempotency behavior where applicable
- Pagination where applicable
- Authorization requirements

---

# 18. Database Design

Design separate local edge and central database schemas.

## Edge Database

Possible tables:

- local_inspections
- local_detection_frames
- local_component_evidence
- local_media_files
- upload_tasks
- device_events
- local_configuration
- model_installations
- rule_installations

## Central Database

Possible tables:

- organizations
- sites
- production_lines
- devices
- users
- roles
- user_roles
- products
- product_components
- rules
- rule_versions
- model_packages
- model_versions
- inspections
- inspection_components
- inspection_media
- review_records
- device_events
- upload_receipts
- audit_logs

Explain:

- Primary keys
- Business identifiers
- Barcode indexing
- Time-based indexing
- Model and rule traceability
- Media metadata
- Soft deletion
- Retention
- Audit requirements

---

# 19. Testing Requirements

Define:

- Unit testing
- Integration testing
- End-to-end testing
- Model evaluation
- Camera adapter testing
- Offline resilience testing
- Upload retry testing
- Power-loss recovery testing
- Disk-full testing
- Database failure testing
- Performance testing
- Long-running stability testing
- Frontend component testing
- API contract testing
- Customer acceptance testing

Focus metrics on:

- NG recall
- False-negative rate
- False-positive rate
- Per-component recall
- Per-product recall
- Product-detection success
- ROI-generation success
- Barcode-read success
- Average latency
- P95 latency
- Throughput
- Upload delay
- Manual review rate
- Manual correction rate

Do not use overall accuracy as the only success metric.

---

# 20. Risk Requirements

Include a risk register covering:

- Camera shift
- Camera disconnection
- Incorrect exposure
- Motion blur
- Reflection
- Product occlusion
- Product-position variation
- Barcode-read failure
- Wrong product-type mapping
- Wrong rule configuration
- Model and rule version mismatch
- Multiple products in one inspection window
- Duplicate inspection
- Frame mixing between products
- Network outage
- Central-server outage
- Upload duplication
- Local disk full
- Local database corruption
- Container restart
- Client power loss
- Clock drift
- Model drift
- Insufficient NG samples
- Customer changing the camera angle
- Unauthorized configuration changes

For each risk provide:

- Cause
- Impact
- Detection method
- Prevention
- Recovery
- Residual risk

---

# 21. Customer Acceptance Requirements

The acceptance plan must use customer production data that was not used for model training.

Test separately by:

- Product type
- Missing component
- Missing manual
- Barcode failure
- Product-position shift
- Normal production variation
- Consecutive OK products
- Consecutive NG products
- Mixed product types
- Offline operation
- Network recovery
- Application restart
- Long-running operation

Each test must preserve:

- Inspection result
- Image evidence
- Model version
- Rule version
- Timestamp
- Device identifier
- Relevant logs

The primary acceptance metric is real NG recall.

Do not define an unvalidated numerical guarantee.

Instead, provide a framework for agreeing target values with the customer after baseline evaluation.

---

# 22. Writing and Quality Requirements

The generated documents must:

- Be written in professional technical English
- Use Markdown
- Use numbered sections
- Use consistent terminology
- Avoid contradictions
- Avoid unsupported claims
- Avoid vague phrases such as “use AI to improve accuracy”
- Explain every major architectural decision
- Separate current scope, MVP scope, production target, and future scope
- Clearly mark assumptions
- Clearly mark unresolved decisions
- Clearly mark optional components
- Include implementation-oriented examples
- Include pseudocode where useful
- Include configuration examples
- Include API examples
- Include Pydantic examples
- Include TypeScript examples
- Include SQL schema guidance
- Include Docker Compose examples
- Include Nginx examples
- Include test cases
- Include operational runbooks
- Include failure-handling behavior
- Include observability requirements
- Include retention and cleanup policies

Do not invent factory details that are not provided.

When information is unknown, create an explicit section named:

`Open Questions and Validation Required`

Do not silently assume:

- Conveyor speed
- Camera vendor
- Camera SDK
- GPU model
- Operating system
- Exact barcode standard
- Exact component classes
- Exact product count
- Exact retention period
- Exact central-server location
- Exact network reliability
- Exact customer acceptance threshold

---

# 23. Generation Workflow

Perform the task in this order:

1. Create the final documentation file tree.
2. Create a terminology and decision consistency checklist.
3. Generate the top-level README.
4. Generate the architecture overview.
5. Generate edge-client documents.
6. Generate central-server documents.
7. Generate AI-pipeline documents.
8. Generate data and API documents.
9. Generate frontend documents.
10. Generate deployment and operations documents.
11. Generate testing, acceptance, and risk documents.
12. Generate ADR files.
13. Review all generated documents for contradictions.
14. Fix inconsistent terminology.
15. Verify Mermaid syntax.
16. Verify links between Markdown files.
17. Verify that every file referenced in the documentation tree exists.
18. Produce a final summary of generated files and unresolved questions.

Do not stop after generating an outline.

Generate the complete content for every required file.

---

# 24. Repository Editing Instructions

If operating inside a repository:

- Inspect the existing repository before creating files.
- Preserve existing files unless replacement is clearly required.
- Do not delete user code.
- Create documentation under `docs/`.
- Update the root `README.md`.
- Use relative links between Markdown files.
- Add diagrams directly in Markdown using Mermaid.
- Do not create binary documents.
- Do not generate placeholder-only documents.
- Do not commit secrets.
- Do not add production data or model weights.
- At the end, list all created and modified files.
- Run available Markdown validation tools if present.
- Report any validation failures honestly.

---

# 25. Final Deliverables

The final repository must contain:

- A useful root `README.md`
- A `docs/README.md` documentation index
- All architecture documents listed above
- All required ADR documents
- Mermaid diagrams
- Edge and central API definitions
- Local and central data models
- Monorepo design
- MVP plan
- One-month implementation roadmap
- Testing strategy
- Deployment strategy
- Operations strategy
- Security statement
- Source-distribution statement
- Human-in-the-loop strategy
- Customer acceptance strategy
- Risk register
- Open questions list

The final output must be coherent enough that another engineering team can use it to begin implementation without reconstructing the architecture from the conversation
