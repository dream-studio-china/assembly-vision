# ADR-002: Python Backend

## 1. Status

Accepted

## 2. Context

The backend must integrate industrial cameras, OpenCV, Ultralytics YOLO, barcode libraries, numerical/image processing, APIs, persistence, and model evaluation. The implementation team needs a shared language between runtime vision code and training/evaluation code while retaining typed schemas and production-quality testing.

## 3. Decision

Use Python 3.12 for edge and central backend services. Use FastAPI, Pydantic, SQLAlchemy, Alembic, Uvicorn or an appropriate central process manager, Pytest, Ruff, and MyPy. Vision integration uses Ultralytics YOLO and OpenCV. SQLite is allowed initially at the edge; PostgreSQL is used centrally and is optional for larger edge installations after evidence demonstrates need.

Performance-sensitive work should first use optimized model runtimes, OpenCV/numerical libraries, batching only where latency allows, and profiling. Native extensions or separate services are introduced only for measured bottlenecks.

## 4. Scope

This decision covers application backends, the edge decision runtime, reusable vision packages, command-line tools, training, and evaluation. It does not require Python for the Vue frontend, Nginx, databases, camera firmware, or every future integration.

## 5. Consequences

### 5.1 Positive

- Strong ecosystem alignment with computer vision and machine learning.
- Shared schemas and algorithms across prototypes, tests, and runtime.
- Fast API implementation with generated OpenAPI contracts.
- Broad camera/vendor SDK integration options.

### 5.2 Negative and Trade-offs

- Python packaging, native dependencies, GPU drivers, and vendor SDKs require careful image construction.
- CPU-bound Python code can become a bottleneck if written outside optimized libraries.
- Bytecode distribution does not strongly protect source logic.
- Static typing is partial and depends on disciplined MyPy/Pydantic use.

## 6. Alternatives

- **C++ backend:** strong runtime control but slower application delivery and less direct integration with the selected Web stack; reserve for measured native needs.
- **C#/.NET:** viable for industrial integration but weaker alignment with the chosen training/vision workflow.
- **Node.js/TypeScript backend:** useful for Web APIs but not preferred for the primary YOLO/OpenCV pipeline.
- **Mixed-language services immediately:** rejected as unnecessary operational and contract complexity for the MVP.

## 7. Open Questions and Validation Required

- Camera SDK and GPU-runtime compatibility with Python 3.12 and the selected OS.
- Whether central CPU concurrency requires Gunicorn or another deployment pattern.
- Measured performance bottlenecks requiring native acceleration.

## 8. Links

- [Testing and Quality Assurance](../22-testing-and-quality-assurance.md)
- [Security and Source Distribution](../21-security-and-source-distribution.md)
- [ADR-009: Static-image-first MVP](ADR-009-static-image-first-mvp.md)
