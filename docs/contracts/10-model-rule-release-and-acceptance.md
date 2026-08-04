# 10. Model, Rule Release, and Acceptance

## 1. Model Manifest

Every model must include a manifest similar to:

```yaml
model_name: component-detector
model_version: 1.2.0
created_at: 2026-08-05
classes:
  - component_a
  - component_b
  - manual
input_size: 1280
dataset_version: component-dataset-v3
git_commit: abc123
checksum: sha256:...
```

## 2. Pre-Release Validation

Before release, validate:

- Offline evaluation
- Recall per component
- Recall per product type
- False-negative analysis
- Inference latency
- Site-camera behavior
- Manifest validity
- Checksum validity
- Rollback behavior

## 3. Rollback Contract

The edge client must retain:

- The currently active model
- The previous stable model

Rules must support rollback as well.

## 4. Rule Version Requirements

A rule release must record:

- Rule version
- Product type
- Required components
- Thresholds
- Creator
- Approver
- Activation timestamp
- Retirement timestamp

## 5. Human-in-the-Loop

During early rollout:

- All NG results should be reviewable.
- Low-confidence OK results may be sampled.
- A percentage of OK results may be audited.
- Human corrections must be stored separately.
- Original AI decisions must remain unchanged.
- Confirmed misclassifications must enter the training backlog.

## 6. Customer Acceptance

Acceptance data must not have been used for training.

Validate separately by:

- Product type
- Missing component
- Missing manual
- Barcode failure
- Product-position shift
- Consecutive OK products
- Consecutive NG products
- Mixed product types
- Offline operation
- Network recovery
- Application restart
- Long-running operation

Each acceptance record must retain:

- Result
- Image evidence
- Product-detector model version and checksum
- Component-detector model version and checksum
- Rule version
- Timestamp
- Device ID
- Relevant logs

Primary metrics:

- Real NG Recall
- False Negative Rate
- Per-component Recall
- System latency
- Stability

Do not make an absolute 100% guarantee without validated evidence.

## Related Documents

- [Training and Evaluation](../design/19-training-and-evaluation.md)
- [Deployment and Operations - release](../design/20-deployment-and-operations.md)
- [Customer Acceptance](../design/26-customer-acceptance.md)
- [Roadmap - delivery gates](../design/25-roadmap.md)
- [Appendices - model and dataset lineage](../design/appendices.md#54-model-and-dataset-lineage)
