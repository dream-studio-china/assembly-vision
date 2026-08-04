# 06. Testing, Quality, and CI Contracts

## 1. Minimum Tooling

The minimum required quality tools are:

- Ruff
- MyPy
- Pytest

## 2. Mandatory CI Commands

```bash
ruff check .
ruff format --check .
mypy .
pytest
```

A failure in any mandatory command blocks merge.

## 2.1 Applicability by Horizon

| Obligation | Static spike | Connected pilot | Production candidate |
|---|---:|---:|---:|
| Ruff, MyPy, Pytest and rule/ROI safety tests | Required | Required | Required |
| Temporal aggregation tests | Not applicable | Required when video/windowing enters scope | Required |
| Upload/idempotency/restart tests | Not applicable | Required when synchronization enters scope | Required |
| API/OpenAPI/TypeScript contract tests | Not applicable | Required for shipped APIs/Web apps | Required |
| Disk-full, power-loss, soak, customer acceptance | Design cases only | Targeted pilot subset | Full approved suite |

"Not applicable" means the subsystem is explicitly excluded; it never waives fail-safe decision
semantics for code that is in scope.

## 3. ROI Engine Required Tests

- Standard crop
- Left-boundary clipping
- Right-boundary clipping
- Top-boundary clipping
- Bottom-boundary clipping
- Zero-area box
- Invalid coordinates
- Margin expansion
- Original-image to ROI coordinate mapping

## 4. Rule Engine Required Tests

- All required components present
- One component missing
- Multiple components missing
- Low-confidence evidence
- Missing product rule
- Empty required-component list
- Invalid product type
- Rule-version mismatch

## 5. Temporal Aggregator Required Tests

- One high-confidence detection
- Repeated medium-confidence detections
- One low-confidence noise detection
- No detections across all frames
- No usable frames
- Frames from another product mixed into the window
- Adjacent-frame requirements
- Blurred-frame exclusion

## 6. Upload Queue Required Tests

- Successful upload
- Network interruption
- Retry
- Duplicate upload
- Process restart
- Missing file
- Checksum mismatch
- Server idempotency conflict
- Recovery of stale `IN_PROGRESS` tasks

## 7. Suggested Coverage Targets

```text
Rule Engine ≥ 95%
ROI Engine ≥ 95%
Temporal Aggregator ≥ 90%
Upload Queue ≥ 90%
API Layer ≥ 80%
```

Model quality must not be measured using code coverage.

## 8. Test Levels

- Unit tests
- Integration tests
- End-to-end tests
- API contract tests
- Model evaluation
- Performance tests
- Offline resilience tests
- Power-loss recovery tests
- Disk-full tests
- Long-running stability tests
- Customer acceptance tests

## 9. Key Quality Metrics

- NG Recall
- False Negative Rate
- False Positive Rate
- Per-component Recall
- Per-product Recall
- Product-detection success rate
- ROI success rate
- Barcode success rate
- Average latency
- P95 latency
- Throughput
- Manual review rate
- Manual correction rate

## Related Documents

- [Training and Evaluation](../design/19-training-and-evaluation.md)
- [Testing and Quality Assurance](../design/22-testing-and-quality-assurance.md)
- [Monorepo and Code Organization - CI](../design/18-monorepo-and-code-organization.md)
- [Customer Acceptance](../design/26-customer-acceptance.md)
