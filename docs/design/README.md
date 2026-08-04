# AssemblyVision Design Documentation

## 1. Core Architecture

| Document | Purpose |
|---|---|
| [00 - Cover and Status](00-cover-and-status.md) | Baseline, scope horizons, status, and quality position |
| [01 - Introduction](01-introduction.md) | Business context, boundaries, readers, and principles |
| [02 - Requirements](02-requirements.md) | Identified functional and quality requirements |
| [03 - Architecture Overview](03-architecture-overview.md) | Context, deployment, data flow, and technology baseline |
| [04 - Edge Client Architecture](04-edge-client-architecture.md) | Offline production decision plane |
| [05 - Central Server Architecture](05-central-server-architecture.md) | Ingestion, fleet management, review, and reporting |

## 2. Inspection Pipeline

| Document | Purpose |
|---|---|
| [06 - AI Detection Pipeline](06-ai-detection-pipeline.md) | End-to-end decision pipeline and static/real-time sequences |
| [07 - Camera and Image Acquisition](07-camera-and-image-acquisition.md) | Hardware adapters, capture, triggers, and frame quality |
| [08 - Product Detection and ROI](08-product-detection-and-roi.md) | Stage-one detection and coordinate-safe ROI generation |
| [09 - Component Detection](09-component-detection.md) | Stage-two required-component observations |
| [10 - Temporal Aggregation](10-temporal-aggregation.md) | Per-component multi-frame evidence |
| [11 - Rule Engine](11-rule-engine.md) | Deterministic conservative decision semantics |

## 3. Data and Interfaces

| Document | Purpose |
|---|---|
| [12 - Local Storage and Retention](12-local-storage-and-retention.md) | Durable edge records, media, cleanup, and recovery |
| [13 - Upload and Synchronization](13-upload-and-synchronization.md) | Persistent queue, retry, idempotency, and offline operation |
| [14 - Data Model and Database](14-data-model-and-database.md) | Pydantic/TypeScript contracts and edge/central schemas |
| [15 - REST API and Events](15-rest-api-and-events.md) | Edge and central APIs, authorization, and WebSocket events |

## 4. Applications and Delivery

| Document | Purpose |
|---|---|
| [16 - Edge Dashboard](16-edge-dashboard.md) | Local offline operator Web application |
| [17 - Central Admin Dashboard](17-central-admin-dashboard.md) | Fleet, history, review, configuration, and reporting UI |
| [18 - Monorepo and Code Organization](18-monorepo-and-code-organization.md) | Python/TypeScript boundaries and dependency rules |
| [19 - Training and Evaluation](19-training-and-evaluation.md) | Dataset strategy, leakage prevention, and metrics |
| [20 - Deployment and Operations](20-deployment-and-operations.md) | Compose, Nginx, upgrades, recovery, and runbooks |
| [21 - Security and Source Distribution](21-security-and-source-distribution.md) | Threat controls and client packaging limitations |

## 5. Assurance and Governance

| Document | Purpose |
|---|---|
| [22 - Testing and Quality Assurance](22-testing-and-quality-assurance.md) | Test layers, failure testing, and quality gates |
| [23 - Observability and Support](23-observability-and-support.md) | Logs, metrics, alerts, diagnostics, and support |
| [24 - Human in the Loop](24-human-in-the-loop.md) | Review, correction, audit, and training backlog |
| [25 - Roadmap](25-roadmap.md) | Two-day MVP, one-month target, dependencies, and gates |
| [26 - Customer Acceptance](26-customer-acceptance.md) | Independent production-data acceptance framework |
| [27 - Risks and Mitigations](27-risks-and-mitigations.md) | Complete risk register and treatments |
| [Appendices](appendices.md) | Terminology, consistency checklist, open questions, reason codes, and traceability |
| [Architecture Decisions](decisions/README.md) | Accepted ADR index |

## 6. Diagram Inventory

| Required diagram | Location |
|---|---|
| System context; edge/central deployment | [Architecture Overview](03-architecture-overview.md) |
| Edge component; inspection state; device state | [Edge Client Architecture](04-edge-client-architecture.md) |
| Central component | [Central Server Architecture](05-central-server-architecture.md) |
| Static-image and real-time sequences | [AI Detection Pipeline](06-ai-detection-pipeline.md) |
| Temporal aggregation sequence | [Temporal Aggregation](10-temporal-aggregation.md) |
| Upload/retry and offline sequences | [Upload and Synchronization](13-upload-and-synchronization.md) |
| Data-retention lifecycle | [Local Storage and Retention](12-local-storage-and-retention.md) |
| Database ER diagram | [Data Model and Database](14-data-model-and-database.md) |
| Monorepo dependency diagram | [Monorepo and Code Organization](18-monorepo-and-code-organization.md) |
| Model update sequence | [Deployment and Operations](20-deployment-and-operations.md) |
| Manual review sequence | [Human in the Loop](24-human-in-the-loop.md) |

## 7. Baseline Rules

1. Production-critical inspection runs entirely at the edge.
2. Central or network outage does not stop otherwise healthy local inspection.
3. Only complete valid evidence may produce business `OK`; internal `UNCERTAIN` always maps to business `NG`.
4. Product and component detector versions, rule version, and product-configuration version are pinned per inspection.
5. Runtime data, model weights, production media, datasets, and secrets remain outside Git.

Use the [decision consistency checklist](appendices.md#2-decision-consistency-checklist) for every architecture change.
