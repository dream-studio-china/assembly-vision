# 01. Architecture Boundaries

## 1. Layer Model

AssemblyVision follows this dependency direction:

```text
Application Layer
        ↓
Orchestration Layer
        ↓
Domain Layer
        ↓
Infrastructure Layer
```

Suggested repository mapping:

```text
apps/
  edge-api
  edge-cli
  edge-worker
  server-api
  server-worker

packages/python/
  vision-core
  rule-engine
  temporal-aggregator
  product-detector
  component-detector
  roi-engine
  persistence
  upload-client
```

## 2. Mandatory Rules

- `apps/` is responsible only for startup, dependency injection, protocol adaptation, and transport concerns.
- Core business logic must live under reusable packages.
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
