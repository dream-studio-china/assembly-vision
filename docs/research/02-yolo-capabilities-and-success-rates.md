# Research 2: YOLO Versions, Capabilities, and Published Success Rates for Industrial Inspection

> Status: Research synthesis for the AssemblyVision project (two-stage detection: stage-1 full-frame product detection, stage-2 component detection on the ROI).
> Date compiled: 2026-08-04
> Honesty convention: All mAP/AP numbers below are **COCO val or LVIS benchmark numbers published by the model authors or Ultralytics**, unless otherwise stated. Benchmark numbers are **lab results, not production results**. FPS/latency figures are vendor-reported on specific GPUs (noted per row). "As of 2025/2026" is respected: the newest model covered is Ultralytics YOLO26 (2026).

---

## 1. Scope

This document covers:

- YOLO versions relevant to industrial inspection: **YOLOv5, v8, v9, v10, v11, v12, YOLO-World, and YOLO26**.
- Published accuracy (AP/mAP) on generic and industrial benchmarks; speed vs accuracy trade-offs (FPS vs mAP, latency).
- Real-world industrial case reports of YOLO applied to defect detection, presence checking, and assembly verification, with achieved numbers.
- Guidance for choosing a YOLO version for AssemblyVision's small-scale, two-stage presence-detection task.

Primary sources: Ultralytics documentation pages (each model page states release date, architecture, and COCO metrics), arXiv papers for v9/v10/v11-world/YOLO26, and Roboflow engineering posts.

---

## 2. YOLO Family Overview and Relevance to Industrial Inspection

| Version | Released | Origin | Key architectural point | Industrial relevance |
|---|---|---|---|---|
| YOLOv5 | 2020 (v7.0 in 2022) | Ultralytics (community, de facto standard) | Anchor-based; huge ecosystem; mature; AGPL-3.0 | Most-published version in older industrial papers; enormous tutorial base |
| YOLOv8 | Jan 2023 | Ultralytics | Anchor-free split head; single unified package; tasks: detect/segment/classify/pose/OBB | The default baseline in 2023-2026 industrial literature |
| YOLOv9 | Feb 2024 | WongKinYiu (Academia Sinica) | PGI (programmable gradient information) + GELAN | High efficiency; official code is outside the Ultralytics package (separate repo) |
| YOLOv10 | May 2024 | Tsinghua THU-MIG + Ultralytics | **NMS-free end-to-end** (consistent dual assignments); holistic efficiency design | Removes NMS post-processing, lower latency; good for embedded pipelines |
| YOLO11 | Sep 2024 | Ultralytics | Improved backbone/neck; 22% fewer params than v8m at higher mAP; tasks: detect/segment/classify/pose/OBB | Strong default for production; used in Roboflow Train, widely deployed |
| YOLO12 | Early 2025 | University at Buffalo / UCAS (community) | Attention-centric (Area Attention, R-ELAN); **community-maintained, may be unstable for training; Ultralytics recommends YOLO11/YOLO26 for production** | Benchmarking/research; not recommended by Ultralytics for production workloads |
| YOLO-World | 2024 | Tencent AILab + Ultralytics port | Open-vocabulary detection (RepVL-PAN, region-text contrastive loss); zero-shot text prompts; offline vocabulary | Useful for fast prototyping product detection; needs fine-tuning for reliable fixed-class production use |
| YOLO26 | 2026 | Ultralytics | **Native NMS-free end-to-end**, DFL-free regression, MuSGD optimizer, STAL small-object label assignment; tasks incl. depth | Latest recommended default; best CPU/GPU efficiency per the vendor |

Sources: https://docs.ultralytics.com/models/yolov5/ ; https://docs.ultralytics.com/models/yolov8/ ; https://docs.ultralytics.com/models/yolov9/ ; https://docs.ultralytics.com/models/yolov10/ ; https://docs.ultralytics.com/models/yolo11/ ; https://docs.ultralytics.com/models/yolo12/ ; https://docs.ultralytics.com/models/yolo-world/ ; https://docs.ultralytics.com/models/yolo26/

---

## 3. Benchmark Performance (COCO val, 640px, detection)

### 3.1 mAP50-95 and model size

| Model | YOLOv5u | YOLOv8 | YOLOv9 | YOLOv10 | YOLO11 | YOLO12 | YOLO26 |
|---|---|---|---|---|---|---|---|
| nano | 34.3 | 37.3 | 38.3 (t) | 39.5 | 39.5 | 40.6 | 40.9 |
| small | 43.0 | 44.9 | 46.8 | 46.8 | 47.0 | 48.0 | 48.6 |
| medium | 49.0 | 50.2 | 51.4 | 51.3 (m) | 51.5 | 52.5 | 53.1 |
| large | 52.2 | 52.9 | 53.0 (c) | 53.4 (l) / 52.5 (b) | 53.4 | 53.7 | 55.0 |
| xlarge | 53.2 | 53.9 | 55.6 (e) | 54.4 | 54.7 | 55.2 | 57.5 |

Sources: https://docs.ultralytics.com/models/yolov5/ ; https://docs.ultralytics.com/models/yolov8/ ; https://docs.ultralytics.com/models/yolov9/ ; https://docs.ultralytics.com/models/yolov10/ ; https://docs.ultralytics.com/models/yolo11/ ; https://docs.ultralytics.com/models/yolo12/ ; https://docs.ultralytics.com/models/yolo26/

### 3.2 Parameters and FLOPs (smallest scales)

| Model | Params (M) | FLOPs (B) | Notes |
|---|---|---|---|
| YOLOv5nu | 2.6 | 7.7 | |
| YOLOv8n | 3.2 | 8.7 | |
| YOLOv10n | 2.3 | 6.7 | NMS-free |
| YOLO11n | 2.6 | 6.5 | |
| YOLO12n | 2.6 | 7.6 | Attention-based |
| YOLO26n | 2.4 | 5.4 | NMS-free, DFL-free |

Sources: model pages above.

### 3.3 Speed / latency (vendor-reported)

| Model | CPU ONNX (ms) | T4 TensorRT (ms) | A100 TensorRT (ms) | Notes |
|---|---|---|---|---|
| YOLOv8n | 80.4 | 6.16* | 0.99 | *T4 value from the v10 comparison table |
| YOLOv10n | - | 1.84 | - | NMS-free; T4 TRT FP16 |
| YOLO11n | 56.1 | 1.5 | - | T4 TRT |
| YOLO12n | - | 1.64 | - | T4 TRT |
| YOLO26n | 38.9 | 1.7 | - | "up to 43% faster CPU ONNX than YOLO11n" per Ultralytics |

Sources: https://docs.ultralytics.com/models/yolov8/ ; https://docs.ultralytics.com/models/yolov10/ ; https://docs.ultralytics.com/models/yolo11/ ; https://docs.ultralytics.com/models/yolo12/ ; https://docs.ultralytics.com/models/yolo26/

> **Reading the trade-off:** From v5u to v26 the nano-class models gained ~6.6 mAP (34.3 -> 40.9) while shrinking params (2.6 -> 2.4M) and speeding up CPU inference (~73.6 -> 38.9 ms). For an edge box running one or two small models at a few Hz, **any of v8/v10/v11/v26 nano or small is comfortably fast**; the binding constraint is more likely image decode/ROI crop and memory than model FLOPS. On a Jetson-class device (no NVIDIA data center GPU), expect lower FPS than the A100/T4 figures above; benchmark locally (see Section 7).

---

## 4. Speed vs Accuracy: FPS vs mAP Trade-off Summary

- **Generic COCO:** YOLO26 reaches 40.9-57.5 mAP at 1.7-11.8 ms T4 TensorRT (https://docs.ultralytics.com/models/yolo26/).
- **YOLOv10 paper:** YOLOv10-S is 1.8x faster than RT-DETR-R18 at similar AP; YOLOv10-B has 46% less latency and 25% fewer params than YOLOv9-C at the same performance; YOLOv10l/x beat YOLOv8l/x by 0.3/0.5 AP with 1.8x/2.3x fewer parameters (https://arxiv.org/abs/2405.14458).
- **YOLO-World (open-vocabulary):** 35.4 AP on LVIS at 52.0 FPS on a V100; zero-shot COCO mAP of the Ultralytics port ranges 37.4 (yolov8s-world) to 47.1 (yolov8x-worldv2) (https://arxiv.org/abs/2401.17270 ; https://docs.ultralytics.com/models/yolo-world/).
- **YOLOv9 paper:** PGI + GELAN enable train-from-scratch models to beat models pretrained on large datasets; YOLOv9c matches YOLOv7-AF accuracy with 42% fewer params and 21% less compute (https://arxiv.org/abs/2402.13616).

**Practical rule for industrial inspection:** a 4-10 mAP point difference between model families matters far less than (a) imaging quality, (b) label quality, and (c) operating-threshold choice. All modern YOLOs (v8+) are "good enough" accuracy-wise for simple presence detection; pick on deployment constraints and ecosystem maturity.

---

## 5. Real-World Industrial Case Reports (Published Numbers)

| Case | Method | Task / conditions | Achieved numbers | Lessons | Source |
|---|---|---|---|---|---|
| VR-YOLO, PCB defect detection | YOLOv8 + viewpoint robustness | PCB defects, original vs viewpoint-shifted test | mAP 98.9% (original), 94.7% (viewpoint shift) | Robustness augmentation buys ~4 pp under pose change; small cost added | https://arxiv.org/abs/2507.02963 |
| Multi-scale pruned YOLOv8, PCB | YOLOv8 + pruning/lightweight neck + MPDIoU loss | Public PCB defect dataset | mAP50 99.32%, mAP50-95 75.18% (+10.13 pp vs YOLOv8n) | mAP50 saturates; mAP50-95 is the honest quality bar; small defects dominate error | https://arxiv.org/abs/2507.17176 |
| Industrial-YOLO, steel + MVTec AD + automotive | Fine-tuned YOLOv8 + TensorRT/OpenVINO | NEU-DET, MVTec AD, custom automotive/battery; claims edge deployment | mAP 98.5%, >120 FPS Jetson Orin (preprint, unverified) | Treat as author-reported; useful only as an upper-bound existence claim | https://arxiv.org/abs/2606.07659 |
| YOLOv8 DSA semiconductor inspection | YOLOv8, data-centric labeling | SEM images of hexagonal contact-hole patterns | Defect detection precision >0.9 mAP | Labeling methodology matters as much as architecture | https://arxiv.org/abs/2307.15516 |
| ASDF assembly state detection | YOLOv8 + 6D pose late fusion | Assembly step/state detection (medical & industrial) | Beats pure-DL assembly state detection; stronger 6D pose on GBOT | Combining detection with geometric verification improves state classification | https://arxiv.org/abs/2403.16400 |
| Manual assembly tracking stand | YOLOv8, multicamera | 120 assemblies at varied speeds, manual assembly stages | High detection accuracy; stage-level timing deviations found | YOLOv8 reliably follows assembly stages in a controlled stand | https://arxiv.org/abs/2401.10777 |
| Roboflow real-time PCB inspection | RF-DETR Nano (YOLO alternative) | Forked Universe PCB dataset, 6 classes, conf 0.4 | mAP 0.99 on test | Managed training; confidence threshold 0.3-0.5 recommended range | https://blog.roboflow.com/pcb-defect-detection/ |
| Roboflow bottle-count missing item | YOLO counting | Top-down bottle packaging; 25-50 images for 1 class | Qualitative pass ("12 bottle tops counted") | Single-class presence/counting is feasible with tens of images | https://blog.roboflow.com/missing-item-inspection/ |
| Roboflow flange inspection | RF-DETR + workflow triage | Flange face scratches/cracks/dents/pinholes | PASS/REVIEW/FAIL triage; thresholds 0.4 (decision), 0.6 (fail) | Confidence-band triage (REVIEW) reduces wrong auto-decisions; REVIEW feeds retraining | https://blog.roboflow.com/flanges-uality-inspection/ |

**Cross-cutting lessons from the case reports:**

1. **Achieved mAP50 for well-defined, well-lit industrial classes is typically 0.90-0.99.** The spread comes from conditions (viewpoint, lighting) and evaluation strictness (mAP50 vs mAP50-95), not from which YOLO version was used.
2. **Robustness cost:** pose/lighting changes reliably cost several mAP points (VR-YOLO: -4 pp). Design the imaging station to minimize this, and monitor drift.
3. **Triage beats binary auto-decisions:** the flange and PCB workflows route mid-confidence detections to human review. This maps directly to AssemblyVision's `UNCERTAIN` handling (see `[docs/design/02-requirements.md](../design/02-requirements.md)`, BR-006).
4. **Detector + rules > detector alone:** assembly-state work and AssemblyVision's deterministic rule engine agree: never let the final OK/NG be decided by raw detections alone.

---

## 6. Choosing a YOLO Version for AssemblyVision (Two-Stage, Small-Scale Presence Detection)

### 6.1 Task profile (from the AssemblyVision design set)

- Stage 1: detect exactly one `product` in a full ~4MP frame (approx 2560x1440 or 2448x2048); ROI crop.
- Stage 2: detect `component_a`, `component_b`, ..., `manual` inside the ROI (fixed classes).
- Data budget: ~300-800 product images; ~300-500 labeled instances per component class (see `[docs/design/19-training-and-evaluation.md](../design/19-training-and-evaluation.md)`).
- Runtime: edge box (CPU or modest GPU); product-window latency budget around 2.5 s per inspection incl. multiple frames (see `[docs/design/06-ai-detection-pipeline.md](../design/06-ai-detection-pipeline.md)`).
- Priority: NG recall over throughput; fail-safe behavior.

### 6.2 Candidate choices and reasoning

| Choice | Fit for AssemblyVision | Caveats |
|---|---|---|
| **YOLO11n / YOLO11s** (default recommendation) | Mature, stable, officially maintained; nano=2.6M params is far under any edge budget; 39.5/47.0 COCO mAP is ample for simple classes; tasks/export coverage is the widest; the de facto standard for new projects | None significant; pick `s` over `n` if components are small or similar to each other |
| **YOLOv8n / YOLOv8s** | The most-published baseline; every industrial case report above uses v8; largest body of troubleshooting material | Slightly lower efficiency than v11/26; fine if you already have v8 expertise |
| **YOLOv10n/s** | NMS-free end-to-end: removes an entire post-processing stage and reduces latency; good for a fixed-class pipeline | Slightly smaller ecosystem; some export formats limited (e.g., PaddlePaddle/NCNN noted in docs); NMS removal matters little at 1-3 Hz |
| **YOLO26n/s** | Latest (2026), native NMS-free, best CPU ONNX latency (38.9 ms for n), STAL improves small-object label coverage (relevant to small components) | Newest = least battle-tested in the wild; ensure the toolchain (ONNX/TensorRT versions) you need is supported before committing |
| **YOLOv9** | Excellent accuracy/efficiency; good if you want an alternative research-grade model | Separate codebase; **training is slower and heavier than v8/v11** (explicitly noted by Ultralytics); v9c/v9e are the useful scales |
| **YOLO12** | Highest accuracy per FLOP in the 2025 batch | **Community-maintained; Ultralytics explicitly recommends YOLO11/YOLO26 for production**; training instability and memory reported; use only for benchmarking |
| **YOLO-World** | Zero-shot text-prompt detection for prototyping the `product` class before labeling | Zero-shot AP (37-47 mAP COCO) is below fine-tuned; use fine-tuning (worldv2 supports deterministic training and ONNX/TensorRT export) for production; requires label-free iteration discipline |

Sources: https://docs.ultralytics.com/models/yolo11/ ; https://docs.ultralytics.com/models/yolov8/ ; https://docs.ultralytics.com/models/yolov10/ ; https://docs.ultralytics.com/models/yolo12/ ; https://docs.ultralytics.com/models/yolo26/ ; https://docs.ultralytics.com/models/yolo-world/

### 6.3 Specific guidance for the two-stage design

1. **Use the same YOLO family for both stages** to keep one training/export/deploy pipeline (per `[docs/design/09-component-detection.md](../design/09-component-detection.md)`, Ultralytics YOLO is the initial implementation).
2. **Stage 1 needs very little capacity.** A single `product` class, large object, stable framing: YOLO11n is likely sufficient; keep confidence threshold validation (default starting config 0.70 in `[docs/design/08-product-detection-and-roi.md](../design/08-product-detection-and-roi.md)`).
3. **Stage 2 is where accuracy budget matters.** Components inside an ROI are smaller and may be visually similar. Prefer YOLO11s or a 1280-input run for stage 2 if mAP50-95 on validation is below target (PCB evidence: small-object localization is the hard part - https://arxiv.org/abs/2507.17176). 
4. **Input size trade-off:** 640px is the default and is fast; 1280px roughly quadruples compute but improves small-object recall. For a 4MP source, you almost always crop to a fixed resolution for stage 2 rather than run native 4MP.
5. **NMS-free (v10/26) is attractive but not required** at the pipeline's low frame rate. If you adopt it, keep the one-to-one head default and verify determinism for replay (AssemblyVision's `fail_on_multiple_products` and deterministic evidence require reproducible outputs).
6. **Fine-tune from COCO-pretrained weights**; Ultralytics and Roboflow both confirm transfer learning is the fastest, cheapest route for small datasets (https://docs.ultralytics.com/guides/model-training-tips/ ; https://blog.roboflow.com/missing-item-inspection/).
7. **Do not let mAP drive the decision.** Per `[docs/design/19-training-and-evaluation.md](../design/19-training-and-evaluation.md)`, promotion decisions hinge on product-level NG recall at frozen operating thresholds, not mAP.

---

## 7. Open Questions and Validation Required

- Confirm the actual edge hardware (CPU model/GPU/NPU) and benchmark YOLO11n/s and YOLO26n/s ONNX/TensorRT latency on that specific device; vendor T4/A100 figures are not representative of a conveyor-side box.
- Decide whether stage-2 input resolution (640 vs 1280 vs custom crop size) is required to hit per-component recall targets on the real components; the answer depends on smallest component pixel size in the ROI.
- Verify YOLO26 (2026) toolchain support (ONNX export, TensorRT version, PyTorch version) matches the AssemblyVision monorepo baseline before adopting it.
- Confirm whether deterministic/reproducible inference is achievable with the chosen runtime (required for replay and audit per `[docs/design/06-ai-detection-pipeline.md](../design/06-ai-detection-pipeline.md)`).
- Establish the operating confidence thresholds empirically from held-out production data for both stages; the design documents list starting values (0.70 product; 0.45-0.50 component observation) that are unvalidated.
- Resolve whether YOLO-World fine-tuning or a plain YOLO11 model is better for stage 1 given the small product dataset; no public comparison exists for this specific regime.
- Validate whether the Ultralytics "~1,500 images / 10,000 instances per class" recommendation conflicts with AssemblyVision's 300-800 image target for a single large, visually consistent product class - the guidance is for reliable generalization across diverse classes; a fixed station with one product type is a favorable case, but this needs empirical confirmation.
