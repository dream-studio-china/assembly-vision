# 05. Data, API, and Versioning Contracts

## 1. Immutable Inspection Fields

The following fields must not be modified after creation:

- `inspection_id`
- `device_id`
- `captured_at`
- `original_decision`
- `model_version`
- `rule_version`
- `product_config_version`
- Original media references

Human review must be stored separately.

## 2. Required Version Traceability

Each inspection must record:

- Application version
- Model version
- Rule version
- Product-configuration version
- Device ID

## 3. Database Migration Rules

- All schema changes must use Alembic.
- Production schemas must not be changed manually.
- Risky migrations must include migration notes.
- Fields must not be removed without a compatibility period.
- Migration history must remain auditable.

## 4. Required Indexes

At minimum, index:

- Barcode
- Inspection timestamp
- Decision
- Product type
- Device ID
- Model version
- Upload status

## 5. API Versioning

All public APIs must use versioned paths:

```text
/api/v1/...
```

## 6. Standard Error Response

```json
{
  "error": {
    "code": "PRODUCT_NOT_FOUND",
    "message": "Product could not be located",
    "trace_id": "..."
  }
}
```

The API must not expose:

- Python stack traces
- SQL statements
- Absolute filesystem paths
- Internal model paths
- Tokens
- Secrets

## 7. Configuration Rules

Do not hardcode:

- Model paths
- Component lists
- Product rules
- Confidence thresholds
- Upload URLs
- Retention periods
- Camera IDs

Use validated runtime configuration, preferably through Pydantic Settings.

Invalid configuration must prevent the service from entering the Ready state.

## 8. Version Binding

Every production inspection must bind to:

```text
Application Version
Model Version
Rule Version
Product Configuration Version
```

## Related Documents

- [Requirements](../design/02-requirements.md)
- [Data Model and Database](../design/14-data-model-and-database.md)
- [REST API and Events](../design/15-rest-api-and-events.md)
- [Appendices - traceability](../design/appendices.md#5-traceability-conventions)
- [ADR-006: REST Plus WebSocket](../design/decisions/ADR-006-rest-plus-websocket.md)
