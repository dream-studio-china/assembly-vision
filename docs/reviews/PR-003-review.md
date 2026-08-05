# PR-003 Follow-up Review

## Scope

This document records the actionable P1 and P2 findings remaining after the
P0 fixes committed as `677c094`, `c23d831`, and `1618efb`.

## P1 Findings

### Model manifest immutability is incomplete

`training/src/assemblyvision_training/artifact.py` permits an existing manifest
to be overwritten when the semantic version and first artifact checksum match.
The replacement can still change task, class order, input size, artifact URI,
provenance, or other decision-critical metadata while retaining the same model
version identity.

Require canonical immutable manifest content to match before accepting an
idempotent publication. Return the existing manifest without rewriting it when
it matches; otherwise reject publication and require a new version. Add tests
that retain the same weights while changing class order, task, and input size.

Relevant references: `docs/contracts/08-security-permissions-and-audit.md`,
`docs/contracts/10-model-rule-release-and-acceptance.md`, and
`docs/design/19-training-and-evaluation.md`.

### Runtime inference does not apply declared model settings

`apps/edge-service/src/assemblyvision_edge/detection/product_detector.py` and
`component_detector.py` call Ultralytics without the manifest input size or
configured IoU and confidence settings. Runtime therefore depends on library
defaults rather than the declared release configuration. In particular, default
NMS can suppress overlapping products or components before exact-count rules
run.

Pass validated `imgsz`, `iou`, confidence, and device parameters explicitly.
Persist the effective values as inference metadata and add adapter tests that
assert the exact model invocation arguments.

Relevant references: `docs/contracts/03-ai-rule-and-safety-contracts.md` and
`docs/design/08-product-detection-and-roi.md`.

### Component configuration, rule, and manifest sets are not cross-validated

`apps/edge-service/src/assemblyvision_edge/cli.py` validates configured
components against the manifest, but does not validate every rule-required
component against runtime settings. A class present in the rule and manifest
but absent from `config.components` reaches
`ComponentDetector.detect()` and raises `KeyError` while accessing its
threshold.

Validate compatible component sets at startup and prevent inspection readiness
for any mismatch. Add tests for each mismatch direction among the rule,
component configuration, and manifest.

Relevant references: `docs/contracts/03-ai-rule-and-safety-contracts.md` and
`docs/contracts/05-data-api-and-versioning-contracts.md`.

### Pipeline does not validate detection provenance

`apps/edge-service/src/assemblyvision_edge/pipeline.py` does not verify that
product and component detections belong to the current frame, the loaded model,
or the expected coordinate space before evidence is aggregated. The current
test suite accepts random, unrelated frame IDs in successful pipeline tests.

Validate frame IDs, model version IDs, image dimensions, and ROI/full-frame
coordinate metadata at the pipeline boundary. Any mismatch must invalidate the
inspection as `NG` and must not be converted into current-frame evidence.

Relevant references: `docs/contracts/03-ai-rule-and-safety-contracts.md` and
`docs/design/09-component-detection.md`.

### Roboflow adapter silently discards invalid source annotations

`scripts/adapt-roboflow-dataset.py` skips some invalid class IDs and allows
negative IDs to index from the end of the class-name list. It does not validate
field count, finite coordinates, positive box dimensions, or image bounds. A
dropped test annotation can be converted into fabricated missing-component
ground truth.

Parse every source label line once and require exactly five finite fields, a
non-negative in-range class ID, and an in-frame positive-area box. Reject the
entire adaptation before writing output when any source annotation is invalid.

Relevant references: `docs/design/19-training-and-evaluation.md` and
`docs/design/22-testing-and-quality-assurance.md`.

### Missing labels are still accepted as implicit negatives

`training/src/assemblyvision_training/dataset.py` only warns when an image has
no matching label file. Training can therefore treat an accidentally unpaired
product image as a background negative.

Require image/label basename pairing by default. Intentionally negative images
must have explicit empty label files. If legacy data needs missing labels,
provide a deliberate opt-in mode and record it in the dataset manifest.

Relevant references: `docs/design/19-training-and-evaluation.md` and
`docs/design/25-roadmap.md`.

### Product detector training drops explicit background negatives

`scripts/adapt-roboflow-dataset.py` excludes every image without a product box
from `dataset_product`, including explicitly empty-label conveyor/background
images. This removes useful product-detector negatives.

Keep explicit empty-label images in the product dataset with empty product
label files. Reject images that contain component labels but lack the required
independent product box instead of conflating them with backgrounds.

Relevant references: `docs/design/19-training-and-evaluation.md` and
`docs/design/22-testing-and-quality-assurance.md`.

### Expected-label verification still accepts unexpected filename-labeled files

`apps/edge-service/src/assemblyvision_edge/cli.py` calls `run_verify()` with
filename fallback enabled even when `--expected` is supplied. Extra stale files
named with `ok`, `ng`, or `missing` are silently assigned expected labels and
included in metrics.

Pass `filename_fallback=args.expected is None`. When an expected manifest is
provided, require exact one-to-one correspondence between its entries and the
input files, reporting both missing and unexpected files as verification gaps.

Relevant references: `docs/design/22-testing-and-quality-assurance.md`.

### Verification identifies samples only by basename

`apps/edge-service/src/assemblyvision_edge/verify.py` uses `path.name` as the
expected-result key. Same-named images supplied from different folders share
one label, and the `seen` set collapses them while metrics count both rows.

Use a manifest-relative path or immutable sample ID. Reject duplicate work
identities and require exactly one input for every expected entry.

Relevant references: `docs/design/19-training-and-evaluation.md` and
`docs/design/22-testing-and-quality-assurance.md`.

## P2 Findings

### Inspection evidence output is not bundle-atomic or power-loss durable

`apps/edge-service/src/assemblyvision_edge/output/writer.py` writes media and
JSON independently in the final inspection directory. A failure can leave
partial visible evidence; a retry can combine replaced media with an older JSON
record. Individual files and directories are not fsynced.

Build each inspection in a sibling staging directory, flush and fsync all files
and directories, then atomically publish the complete directory. Reject writes
to an already published inspection ID and add injected write-failure and
restart-recovery tests.

Relevant references: `docs/design/06-ai-detection-pipeline.md` and
`docs/design/23-observability-and-support.md`.

### Rule version identity is not bound to rule content

`rule_version_id()` in
`apps/edge-service/src/assemblyvision_edge/rules/rule_engine.py` hashes only
`rule_id` and `rule_version`. Changes to component requirements, gates,
spatial constraints, or compatible models can retain the same persisted UUID.

Persist a canonical rule checksum with the record, or derive the release
identity from canonical rule content. Reject reuse of the same rule ID/version
with different content.

Relevant references: `docs/contracts/05-data-api-and-versioning-contracts.md`
and `docs/design/11-rule-engine.md`.

### Dataset adaptation and preparation can retain stale output

`scripts/adapt-roboflow-dataset.py` and
`training/src/assemblyvision_training/prepare_components.py` write directly to
existing output directories. Re-running with fewer samples, different source
data, or a detector that skips a sample leaves old files in the new dataset.

Reject non-empty destinations or write a complete new dataset to a staging
directory, validate it, and atomically publish it. Record a file manifest so
dataset membership and lineage are auditable.

Relevant references: `docs/design/19-training-and-evaluation.md` and
`docs/design/25-roadmap.md`.

### Component dataset preparation does not share the production selection policy

`training/src/assemblyvision_training/prepare_components.py` loads unverified
weights, uses fixed confidence settings, and selects the largest product box
when multiple products are detected. This can crop labels against a different
object from the runtime pipeline.

Require a verified product manifest and reuse the runtime product-detector
selection policy, including exactly-one-product handling and manifest-derived
inference settings. Fail or produce an explicit exclusion manifest for
ambiguous samples.

Relevant references: `docs/design/19-training-and-evaluation.md`,
`docs/design/08-product-detection-and-roi.md`, and ADR-004.
