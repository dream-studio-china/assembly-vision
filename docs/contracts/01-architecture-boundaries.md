# 01. Architecture Boundaries

## 1. Layer Model

AssemblyVision uses dependency inversion. Source-code dependencies point toward domain contracts;
infrastructure implements domain-owned protocols and is wired at the composition root:

```text
API / CLI / Scheduled Entry Points
                |
                v
Application / Orchestration
                |
                v
Domain Models and Protocols
                ^
                |
Infrastructure Adapters

Composition Root -> Application + Infrastructure
```

Initial repository mapping:

```text
apps/
  edge-service       # API, CLI entry point, inspection runtime, persistence, uploader
  edge-web
  central-api
  admin-web
  central-worker     # optional; only when long-running jobs justify it

packages/python/
  domain
  vision-core
  platform-common

packages/typescript/
  api-client
  ui                 # only proven shared presentation primitives
```

Product detection, ROI, component detection, temporal aggregation, and deterministic rules are
logical modules inside `vision-core`; they are not separate packages until reuse, native dependency
isolation, or independent release requirements are demonstrated. Edge persistence and upload
implementations remain in `edge-service` behind domain-facing protocols. In-process worker tasks or
a supervised inference subprocess are not separate deployment units.

## 2. Mandatory Rules

- `apps/` owns composition, transport, application orchestration, and app-specific infrastructure.
- Shared packages are created only for cohesive domain logic or demonstrated reuse by multiple applications.
- FastAPI routes must only validate requests, call services, and serialize responses.
- YOLO inference logic must not be implemented directly inside FastAPI routes.
- Database logic must not be implemented directly inside Vue components or FastAPI routes.
- The Rule Engine must remain independent from Web, database, and YOLO dependencies.
- Real-time inspection on the edge must not depend on the central server.

## 3. Forbidden Dependencies

The following dependencies are forbidden:

```text
rule-engine → FastAPI
rule-engine → SQLAlchemy
roi-engine → Vue
product-detector → database
component-detector → HTTP
persistence → YOLO
```

The following implementation style is forbidden:

```python
@router.post("/inspect")
def inspect(image: UploadFile):
    model = YOLO("best.pt")
    result = model(...)
    if "manual" not in result:
        return {"decision": "NG"}
```

## 4. Preferred Route Design

```python
@router.post("/inspect")
def inspect(
    request: InspectionRequest,
    service: InspectionService = Depends(get_inspection_service),
) -> InspectionResponse:
    return service.inspect(request)
```

## 5. Dependency Direction Rules

- Lower-level modules must not depend on application modules.
- Domain modules must not depend on FastAPI, Vue, or Docker.
- Detector modules must not produce final `OK` or `NG` decisions.
- The Rule Engine must not call YOLO.
- Persistence modules must not contain business decisions.
- The Upload Client must not modify local inspection results.

## 6. Enforcement

Recommended tools:

- Ruff
- MyPy
- Import Linter
- Semgrep
- Custom CI dependency checks

## Related Documents

- [Architecture Overview](../design/03-architecture-overview.md)
- [Edge Client Architecture](../design/04-edge-client-architecture.md)
- [Central Server Architecture](../design/05-central-server-architecture.md)
- [Monorepo and Code Organization](../design/18-monorepo-and-code-organization.md)
- [ADR-007: Monorepo](../design/decisions/ADR-007-monorepo.md)
