# ADR-011: Labeled Train-and-Inspect MVP

## 1. Status

Accepted

## 2. Context

ADR-009 establishes a static-image-first implementation sequence and excludes model training from its two-day scope. The current MVP objective requires a developer to train from a labeled static-image set and then inspect a separate image set one image at a time with traceable `OK` or `NG` results.

The selected annotation tool is X-AnyLabeling. It exports product and component bounding boxes in Ultralytics YOLO text format. Filename `OK` or `NG` labels remain useful for held-out verification, but cannot train a bounding-box detector by themselves.

The MVP runs on a developer-controlled Apple Silicon Mac with 16 GB memory. It must preserve the final two-stage architecture: product detection on the full frame, generated product ROI, component detection in that ROI, and deterministic rule evaluation. Training must remain separate from the edge runtime so it is not distributed with a customer runtime package.

## 3. Decision

Replace the training exclusion in ADR-009 for the MVP only. The labeled train-and-inspect MVP shall:

1. Use X-AnyLabeling to create full-frame product and component bounding-box labels in standard YOLO format.
2. Provide a developer-only `training/` workspace and `av-train` CLI that is separate from `edge-service`; runtime code must not import training code.
3. Train the product detector from full-frame images and labels.
4. Prepare the component dataset by generating product ROIs, cropping images, and mapping component boxes from full-frame coordinates into ROI coordinates before training the component detector.
5. Write versioned model weights outside Git and produce checksummed model manifests consumed by `assemblyvision inspect`.
6. Run the existing static inspection pipeline with real two-stage Ultralytics YOLO adapters, deterministic rules, JSON evidence, ROI images, and annotated images.
7. Provide `assemblyvision verify` to compare inspection results with expected `OK` or `NG` labels parsed from a configured filename convention and report false negatives, false positives, and NG recall.

This MVP uses small models and measured input sizes appropriate for the developer hardware. It demonstrates a reproducible training-to-inspection flow, not production accuracy or production readiness.

Model encryption and `.pyc`-only runtime packaging are deferred. The immediate protection boundary is that training code, datasets, notebooks, and experiment configuration are never included in a customer runtime distribution.

## 4. Consequences

### 4.1 Positive

- Exercises the same two-stage detection path intended for production instead of introducing a classification-only alternate path.
- Uses standard YOLO labels and training tooling, minimizing custom model-training behavior.
- Produces model manifests, checksums, and held-out verification evidence before camera, timing, and network complexity are introduced.
- Preserves the runtime/training separation required by the monorepo architecture.

### 4.2 Negative and Trade-offs

- Requires initial manual or model-assisted box annotation rather than filename labels alone.
- Component training requires an explicit ROI preparation step and coordinate-transform tests.
- Apple Silicon developer hardware constrains model size, batch size, and training duration.
- Plain model weights and Python source remain development artifacts in this MVP; they are not a distribution-security control.
- The resulting metrics are valid only for the labeled and held-out static-image sets, not a production acceptance claim.

## 5. Supersession

This ADR supersedes only ADR-009's two-day scope and its exclusion of model training. ADR-009 remains in force for static-image-first sequencing, for exclusion of camera/video/central/dashboard work, and for the requirement that static artifacts remain deterministic regression fixtures.

## 6. Links

- [ADR-009: Static-Image-First MVP](ADR-009-static-image-first-mvp.md)
- [ADR-004: Two-stage detection](ADR-004-two-stage-detection.md)
- [Training and Evaluation](../19-training-and-evaluation.md)
- [Monorepo and Code Organization](../18-monorepo-and-code-organization.md)
- [Implementation Roadmap](../25-roadmap.md)
