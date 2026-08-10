# 11. Rule Engine

## 11.1 Purpose and Independence

The rule engine converts resolved product identity, pipeline status, and per-component aggregate evidence into a deterministic inspection decision. It is independent of YOLO and contains no image inference. Inputs come from the [AI detection pipeline](06-ai-detection-pipeline.md) and [temporal aggregation](10-temporal-aggregation.md).

## 11.2 Decision Semantics

The external production result is `OK` or `NG`:

- `OK`: product type and rule are valid, every mandatory pipeline gate passed, and every required component independently has `PRESENT` evidence satisfying count and constraint rules.
- `NG`: any required component is `MISSING`, `UNCERTAIN`, or `UNVERIFIABLE`; or any mandatory pipeline/configuration gate failed.

An internal `UNCERTAIN` evidence state may be displayed and reported, but it maps to external `NG`. The engine has no permissive default. Unknown product, missing rule, malformed configuration, model/rule incompatibility, or evaluation exception is `NG` or prevents system readiness.

## 11.3 Versioned Rule Configuration

```yaml
schema_version: 1
rule_id: model-a-presence
rule_version: 3
product_type: model_a
compatible_component_model_versions:
  - component-yolo-1.0.0
barcode_required: true
required_components:
  component_a:
    expected_count: 1
  component_b:
    expected_count: 1
  manual:
    expected_count: 1
mandatory_gates:
  product_detected: true
  roi_valid: true
  minimum_valid_frames_met: true
```

Rules are immutable after publication. Editing creates a new version. The product window pins rule, product configuration, and model versions; the decision record stores all of them. Only signed or otherwise authenticated configuration packages should be installed in production, with local validation before activation.

## 11.4 Evaluation Algorithm

```python
def evaluate(context, rule):
    reasons = []
    if not compatible(context.versions, rule):
        reasons.append("VERSION_INCOMPATIBLE")
    if rule.barcode_required and not context.product_identity.verified:
        reasons.append("PRODUCT_IDENTITY_UNVERIFIED")
    for gate in rule.mandatory_gates:
        if not context.gates.get(gate, False):
            reasons.append(f"GATE_FAILED:{gate}")
    for key, requirement in rule.required_components.items():
        evidence = context.components.get(key)
        if evidence is None:
            reasons.append(f"COMPONENT_UNVERIFIABLE:{key}")
        elif evidence.state != "PRESENT":
            reasons.append(f"COMPONENT_{evidence.state}:{key}")
        elif not count_satisfied(evidence, requirement):
            reasons.append(f"COMPONENT_COUNT_INVALID:{key}")
    return InspectionDecision(result="NG" if reasons else "OK", reasons=sorted(reasons))
```

Sorting and stable component iteration produce reproducible reason ordering. The engine returns all applicable reasons rather than stopping at the first, except when input cannot be parsed safely.

## 11.5 Reason Codes

Reason codes are stable machine-readable identifiers grouped as:

- identity: `BARCODE_UNREADABLE`, `PRODUCT_TYPE_UNKNOWN`, `PRODUCT_MAPPING_AMBIGUOUS`, `PRODUCT_IDENTITY_UNVERIFIED`;
- pipeline: `CAMERA_DISCONNECTED`, `NO_PRODUCT`, `MULTIPLE_PRODUCTS`, `ROI_INVALID`, `INSUFFICIENT_VALID_FRAMES`, `INFERENCE_ERROR`, `IMAGE_READ_ERROR`, `PRODUCT_IDENTITY_MISSING`, `PRODUCT_IDENTITY_TRANSITION`, `WINDOW_MAX_DURATION_EXCEEDED`, `COMPONENT_POLICY_MISSING`, `GATE_FAILED:<gate>`;
- component: `COMPONENT_MISSING`, `COMPONENT_UNCERTAIN`, `COMPONENT_UNVERIFIABLE`, `COMPONENT_COUNT_INVALID`, `COMPONENT_SPATIAL_INVALID` with a component key;
- configuration: `RULE_NOT_FOUND`, `CONFIG_INVALID`, `VERSION_INCOMPATIBLE`;
- system: `INSPECTION_INTERRUPTED`, `DECISION_PERSISTENCE_FAILED`, `RULE_EVALUATION_ERROR`.

The canonical machine-readable set is implemented in
`packages/python/domain/src/assemblyvision_domain/reason_codes.py`; design 11.5
and that module must stay in sync (AUDIT-001).

Human-readable text is localized separately. Analytics use reason code plus structured parameters, not parsed display messages.

For the development upload path, barcode resolution supplies the identity
verification flag and the persisted barcode/product-resolution fields; rule
evaluation remains unchanged. Exact barcode mappings which resolve to a product
other than the active rule product type are unverified.

## 11.6 Configuration Lifecycle

Draft rules are schema-validated and simulated against a regression corpus. Publication requires authorization and an audit entry. Edge installation writes the package durably, validates checksums and compatibility, then activates it atomically between product windows. If activation fails, retain the last validated version and report the failure. If no valid rule exists for a product, that product is `NG`; a generic permissive rule is prohibited.

Rollback installs a previously published immutable version as a new activation event. Historical records always retain the version used at decision time.

## 11.7 Failure Handling

- Missing keys and unknown component states fail closed to `NG`.
- Unknown optional fields are rejected or handled according to an explicit schema-version policy, never silently interpreted.
- Evaluation exceptions are caught at the boundary, logged, and converted to `NG` with `RULE_EVALUATION_ERROR`.
- Duplicate component evidence with conflicting versions is invalid.
- Central-server outage does not prevent use of the last locally installed valid rule.
- A newly downloaded invalid rule cannot replace the active rule.

The edge dashboard may show a system-not-ready state for global configuration faults. It must not display an `OK` result when decision persistence fails.

## 11.8 Verification

- Use table-driven unit tests for every evidence state, gate, identity state, count, and reason code.
- Property-test: `OK` implies every required component is present and every mandatory gate is true.
- Property-test: adding a required component without evidence cannot preserve `OK`.
- Golden-test published rule versions against fixed inspection contexts.
- Test malformed YAML, unsupported schema versions, incompatible models, missing rules, and evaluation exceptions.
- Integration-test atomic activation during active and idle product windows.
- Audit a sample of `OK` results against persisted evidence during rollout.

## 11.9 Open Questions and Validation Required

- Confirm whether the customer-facing interface supports only `OK`/`NG` or also displays an internal uncertain category.
- Define exact product-to-barcode mapping and behavior when a barcode is readable but unknown.
- Define required component counts and any conditional requirements by product variant.
- Establish rule publication, approval, signing, and emergency rollback roles.
- Confirm downstream actuation semantics and timing; no PLC behavior is assumed here.
