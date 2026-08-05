# Model Manifests

This directory holds model manifests and checksums for development references.

- `product-manifest.json` — stage-one product detector metadata.
- `component-manifest.json` — stage-two component detector metadata.

Model weights are external artifacts stored in a model/artifact registry and
must never be committed to Git. The example manifests reference placeholder
weights under `models/weights/` which do not exist in the repository; the
detector adapters currently reject inference until real artifacts are supplied.
