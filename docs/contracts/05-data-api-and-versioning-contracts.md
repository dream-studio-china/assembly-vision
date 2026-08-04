# 05. Data, API, and Versioning Contracts

## 1. Immutable Inspection Fields

The following fields must not be modified after creation:

- `inspection_id`
- `device_id`
- `captured_at`
- `original_internal_decision`
- `original_business_result`
- Product-detector model version and checksum
- Component-detector model version and checksum
- `rule_version`
- `product_config_version`
- Original media references

Human review must be stored separately.

## 2. Required Version Traceability

Each inspection must record:

- Application version
- Product-detector model version and checksum
- Component-detector model version and checksum
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

Use `application/problem+json`:

```json
{
  "type": "https://assemblyvision.example/problems/product-not-found",
  "title": "Product not found",
  "status": 422,
  "detail": "Product could not be located",
  "code": "PRODUCT_NOT_FOUND",
  "request_id": "...",
  "errors": []
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

Invalid decision-critical local configuration prevents `inspection_ready`. Missing upload URLs,
central credentials, or central connectivity prevents `sync_ready` but does not block otherwise
valid offline inspection. Product mapping, required components, thresholds, model/rule bindings,
and signed package fields cannot be overridden by environment variables or local UI overrides.

## 8. Version Binding

Every production inspection must bind to:

```text
Application Version
Product-Detector Model Version and Checksum
Component-Detector Model Version and Checksum
Rule Version
Product Configuration Version
```

## 9. Configuration Ownership

| Configuration class | Owner | Local/environment override |
|---|---|---|
| Product mapping, required components, thresholds, model/rule compatibility | Versioned governed package | Forbidden |
| Camera identity, exposure, geometry | Approved site configuration | Allowed only with audit and revalidation |
| Upload URL, proxy, timeouts, bandwidth | Deployment/site operations | Allowed; affects `sync_ready`, not decision rules |
| Secrets and device credentials | Deployment secret store | Runtime injection only; never persisted in packages |
| UI preferences and non-safety display options | Local user/device | Allowed |

## Related Documents

- [Requirements](../design/02-requirements.md)
- [Data Model and Database](../design/14-data-model-and-database.md)
- [REST API and Events](../design/15-rest-api-and-events.md)
- [Appendices - traceability](../design/appendices.md#5-traceability-conventions)
- [ADR-006: REST Plus WebSocket](../design/decisions/ADR-006-rest-plus-websocket.md)
