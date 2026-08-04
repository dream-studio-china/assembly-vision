# 09. Industrial Site and Change Control

## 1. Equipment Baseline

Record at least:

- Camera model
- Resolution
- Lens
- Exposure
- Gain
- Light position
- Light intensity
- Camera angle
- Camera height
- Inspection area
- Edge hardware
- CPU or GPU
- Operating system
- Camera SDK version

## 2. Changes Requiring Revalidation

- Camera-position change
- Camera-angle change
- Lens change
- Exposure change
- Lighting change
- Background change
- Packaging change
- Component appearance change
- New product type
- Camera SDK upgrade
- Inference-framework upgrade
- GPU-driver upgrade

A large viewpoint change, such as approximately 45 degrees, must be treated as domain shift.

## 3. Change Process

```text
Site change
→ Capture new data
→ Run baseline evaluation
→ Decide whether fine-tuning is required
→ Validate on a holdout dataset
→ Limited rollout
→ Production release
```

## 4. Forbidden Practices

- Moving the camera without revalidation
- Changing exposure without revalidation
- Replacing the lens without revalidation
- Publishing a new model without validation
- Changing production thresholds without validation
- Using the training set as the final acceptance set

## 5. Industrial Exception Policy

The following conditions should produce `NG` or `UNCERTAIN`:

- Camera disconnected
- Missing image
- Severe blur
- Product not found
- Invalid ROI
- Barcode failure
- Unknown product type
- Missing rule
- Model unavailable
- No valid frame

## Related Documents

- [Camera and Image Acquisition](../design/07-camera-and-image-acquisition.md)
- [Deployment and Operations](../design/20-deployment-and-operations.md)
- [Risks and Mitigations](../design/27-risks-and-mitigations.md)
- [Customer Acceptance](../design/26-customer-acceptance.md)
- [Roadmap](../design/25-roadmap.md)
