# 07. Deployment, Observability, and Operations

## 1. Container Requirements

- Run as a non-root user.
- Use explicit persistent volumes.
- Define health checks.
- Define restart policies.
- Use structured logs.
- Do not include the Git repository.
- Do not include training datasets.
- Do not include notebooks.
- Do not include development secrets.
- Use multi-stage builds.
- Keep runtime data outside the image.

## 2. Health Endpoints

The edge application should expose at least:

```text
/api/v1/health/live
/api/v1/health/ready
/api/v1/device/status
```

Definitions:

- `/api/v1/health/live`: the process is alive; it exposes no internal details.
- `/api/v1/health/ready`: decision-critical configuration, camera, models, and persistence permit
  valid inspections.
- `/api/v1/device/status`: authenticated detailed camera/model/storage/upload health, including
  separate `inspection_ready` and `sync_ready` flags.

Example:

```text
model unavailable:
/api/v1/health/live = healthy
/api/v1/health/ready = unhealthy
```

## 3. Startup Sequence

```text
1. Load configuration
2. Validate configuration
3. Initialize database
4. Validate storage directories
5. Load models
6. Initialize camera
7. Recover upload tasks
8. Enable inspection
```

The service must not accept production inspection work before readiness checks pass.

## 4. Structured Logging

```json
{
  "event": "inspection_completed",
  "inspection_id": "...",
  "device_id": "...",
  "business_result": "NG",
  "internal_decision": "UNCERTAIN",
  "latency_ms": 134,
  "product_model_version": "product-v1.0.0",
  "component_model_version": "component-v1.2.0"
}
```

## 5. Forbidden Log Content

Do not log:

- Passwords
- Tokens
- Authorization headers
- Database passwords
- Raw binary image payloads
- Sensitive customer data

## 6. Required Operational Metrics

- Inspections per minute
- OK and NG counts
- Average inference latency
- P95 inference latency
- Camera disconnect count
- Barcode failure rate
- ROI failure rate
- Disk utilization
- Upload queue length
- Age of oldest pending upload
- Model load status
- Database error count
- Edge-to-central connectivity state

## 7. Required Runbooks

Maintain runbooks for:

- Camera disconnection
- Model-loading failure
- Low disk space
- Upload backlog
- Database recovery
- Repeated container restart
- Synchronization after network recovery
- Model rollback
- Rule rollback

The indexed runbook set is under [docs/runbooks](../runbooks/README.md).

## Related Documents

- [Deployment and Operations](../design/20-deployment-and-operations.md)
- [Observability and Support](../design/23-observability-and-support.md)
- [Risks and Mitigations](../design/27-risks-and-mitigations.md)
- [ADR-008: Docker Deployment](../design/decisions/ADR-008-docker-deployment.md)
