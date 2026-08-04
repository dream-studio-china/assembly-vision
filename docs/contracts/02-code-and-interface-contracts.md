# 02. Code and Interface Contracts

## 1. Core Principle

Modules must communicate through explicit, stable, typed, testable, and serializable structures.

Do not use the following as core domain interfaces:

- Arbitrary dictionaries
- Unstable JSON payloads
- Raw YOLO result objects
- OpenCV internal objects
- SQLAlchemy ORM objects
- `dict[str, Any]`

## 2. Standard Domain Models

```python
from typing import Literal

from pydantic import BaseModel, Field


class BoundingBox(BaseModel):
    x_min: int
    y_min: int
    x_max: int
    y_max: int


class Detection(BaseModel):
    class_name: str
    confidence: float = Field(ge=0.0, le=1.0)
    bbox: BoundingBox
    frame_index: int | None = None


class InspectionDecision(BaseModel):
    decision: Literal["OK", "NG", "UNCERTAIN"]
    missing_components: list[str]
    low_confidence_components: list[str]
    model_version: str
    rule_version: str
```

## 3. Interface Constraints

- Public functions and classes must use explicit type annotations.
- External API contracts must use Pydantic models.
- Coordinates must state whether they belong to the original image, an ROI, or a normalized coordinate space.
- Timestamps must use timezone-aware UTC values.
- IDs must have clearly defined ownership and origin.
- Confidence values must use the range `0.0` to `1.0`.
- Python and TypeScript types must remain synchronized.

## 4. Detector Protocol

```python
from typing import Protocol

import numpy as np
from numpy.typing import NDArray


class Detector(Protocol):
    def detect(self, image: NDArray[np.uint8]) -> list[Detection]:
        ...
```

## 5. Compatibility Rules

- Adding an optional field is normally backward compatible.
- Removing a field is a breaking change.
- Renaming a field is a breaking change.
- Changing enum values is a breaking change.
- Breaking changes require an API version change.

## 6. Frontend and Backend Type Synchronization

Preferred flow:

```text
Pydantic models
→ OpenAPI schema
→ Generated TypeScript client
→ Vue applications
```

Do not maintain large duplicated sets of handwritten API types.

## 7. Minimum Quality Gates

```bash
ruff check .
ruff format --check .
mypy .
pytest
```

## Related Documents

- [Data Model and Database](../design/14-data-model-and-database.md)
- [REST API and Events](../design/15-rest-api-and-events.md)
- [Monorepo and Code Organization](../design/18-monorepo-and-code-organization.md)
- [Appendices - type and traceability conventions](../design/appendices.md)
- [ADR-002: Python Backend](../design/decisions/ADR-002-python-backend.md)
