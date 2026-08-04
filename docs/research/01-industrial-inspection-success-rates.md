# Research 1: Achieved Detection Success Rates in Industrial Inspection (Horizontal Comparison)

> Status: Research synthesis for the AssemblyVision project (edge-first, two-stage industrial assembly inspection).
> Date compiled: 2026-08-04
> Purpose: Horizontal comparison of reported detection success rates (recall, precision, accuracy, F1, mAP) for industrial inspection tasks comparable to AssemblyVision, across industries, methods, and conditions.
> Honesty convention used throughout: **lab/benchmark numbers are clearly separated from production-line reports**; vendor- or dataset-reported numbers are flagged as such; estimates and contested figures are marked. When a number is not available, it is explicitly stated as unavailable rather than invented.

---

## 1. Scope and Definitions

This document compares **achieved detection success rates** for inspection tasks similar to AssemblyVision's task: **presence / completeness verification of components on an assembled product, imaged by a fixed industrial camera under controlled lighting**.

The most comparable published evidence comes from:

- **PCB / electronics defect detection** (dense, small features; fixed cameras)
- **Surface defect detection** on steel, metal, glass, wood, and textile (fixed-line scanning)
- **Assembly verification and state detection** (automotive and industrial manual assembly)
- **Packaging / food inspection** (counting and completeness checks)
- **Metal casting / welding inspection** (porosity, cracks, inclusions)
- **Pharmaceutical inspection** (direct published numbers are scarce; adjacent evidence only)

**Metric notes.** Industrial papers overwhelmingly report **mAP (mean Average Precision)** on a held-out test set, not production recall/precision at an operating threshold. mAP is an average over confidence thresholds and is **not** the same as the operational recall a production line achieves after a confidence threshold is fixed. Where papers report precision/recall/F1 at a threshold, this is stated. AssemblyVision's own safety metric (NG recall) is defined in `[docs/design/19-training-and-evaluation.md](../design/19-training-and-evaluation.md)`; no public benchmark measures exactly that quantity for assembly completeness, so AssemblyVision must establish its own baseline.

---

## 2. Reference Datasets and Benchmarks (Environment, Size, Ground Truth)

| Dataset | Domain | Images | Classes / defects | Environment & conditions | Ground truth | Link |
|---|---|---|---|---|---|---|
| **NEU-DET** | Hot-rolled steel strip surface defects | 1,800 grayscale, 200x200 px, 300/class | 6: crazing, inclusion, patches, pitted surface, rolled-in scale, scratches | Lab-acquired stills from a real steel mill; fixed illumination; single surface orientation | Bounding boxes | https://ieee-dataport.org/documents/neu-det ; Kaggle: https://www.kaggle.com/datasets/kaustubhdikshit/neu-surface-defect-database |
| **DAGM 2007** (industrial optical inspection challenge) | Textured industrial parts; weakly supervised defect detection | 10 datasets (6 development + 4 competition), each **1,000 defect-free + 150 defect** images | One defect class per dataset; multiple texture models | Artificially generated but "similar to real world problems"; images within a set very similar | Weak ellipse labels; loss matrix: false negative costs 20x a false positive; qualifying total loss <= 200 | https://conferences.mpi-inf.mpg.de/dagm/2007/prizes.html |
| **KolektorSDD** | Electrical commutator surface cracks (plastic embedding) | 399 images (52 defective, 347 OK) | 1 defect class | Real production items, "controlled industrial environment", real-world case | Pixel-level (original); later re-annotated | https://www.vicos.si/resources/kolektorsdd/ |
| **KolektorSDD2** | Same domain as above, larger | 3,336 images (356 defective, 2,979 OK) | 1 defect class, 394 labeled objects; multiple defect types | Real production items, controlled industrial environment; highly imbalanced | Pixel-precise instance annotations; train/test splits for detection and classification | https://www.vicos.si/resources/kolektorsdd2/ |
| **MVTec AD** | 15 object & texture categories incl. bottle, hazelnut, transistor, metal nut, cable, etc. | >5,000 high-resolution images | 73+ defect types; 5 texture + 10 object categories | "Simulates real-world industrial inspection scenarios"; unsupervised anomaly detection benchmark; per-category defect-free training set | Pixel-precise anomaly annotations; image-level and pixel-level evaluation | https://www.mvtec.com/research-teaching/datasets/mvtec-ad |
| **MVTec AD 2** | Advanced industrial anomaly detection | >8,000 high-resolution images, 8 scenarios | Transparent/overlapping objects, dark-field & back-light, high-variance normals, extremely small defects; **lighting-change test scenarios** | Stated to reflect real distribution shifts; SOTA methods remain **below 60% average AU-PRO** | Pixel-precise ground truth held on an evaluation server | https://arxiv.org/abs/2503.21622 |
| **Casting product dataset** (Kaggle, Ravirajsinh45) | Casting product surface quality (binary OK/defective) | Reported as ~7,348 images (~5,198 OK, ~2,150 defective), 512x512 | Binary classification (not localization) | Photographed cast parts; uncontrolled-ish studio conditions; dataset-reported figures, verify before citing | Folder-level binary labels | https://www.kaggle.com/datasets/ravirajsinh45/real-life-industrial-dataset-of-casting-product |
| **AITEX / TILDA** (textile) | Fabric defect detection | AITEX commonly cited with ~245 defect + 140 defect-free images (verify per distribution); TILDA 7 classes | Multiple textile defect types | Public textile databases; used in unsupervised fabric anomaly detection studies | Pixel/mask or image labels depending on release | See study using AITEX + TILDA + MVTec AD: https://arxiv.org/abs/2401.02287 |
| **PKU/DeepPCB-style public PCB defect datasets** | PCB fabrication defects (open, short, mouse-bite, spur, pinhole, spurious copper, missing hole) | Thousands of cropped defect patches in common releases (exact split varies by release) | 6 main defect classes | Reconstructed/imaged PCB micrographs; fixed scale | Bounding boxes | Referenced via papers: https://arxiv.org/abs/2507.02963 and https://arxiv.org/abs/2507.17176 |

> **Uncertainty flag:** Several of these numbers (especially casting image counts and AITEX image counts) vary between copies/mirrors. They are marked "reported/verify". The NEU-DET and KolektorSDD2 figures are consistent across the official sources listed above.

---

## 3. Reported Success Rates by Industry and Method

### 3.1 PCB / Electronics

| Project / benchmark | Method | Conditions | Dataset size (train) | Achieved metric | Cost / compute notes | Source |
|---|---|---|---|---|---|---|
| VR-YOLO (YOLOv8-based PCB defect detection) | One-stage YOLOv8 + scene diversity + key-object focus | Original test set | Not reported in abstract; PCB defect dataset | **mAP 98.9%** (original test); **94.7% mAP** with viewpoint shifts (shear ±0.06, rotation ±10 deg) | "Negligible additional computational cost" vs baseline YOLO | https://arxiv.org/abs/2507.02963 |
| Multi-scale YOLOv8 PCB (pruned, lightweight) | YOLOv8 + Ghost-HGNetv2 backbone, C2f-Faster neck, GCDetect head, Inner-MPDIoU loss | Public PCB defect dataset | Not reported in abstract | **mAP0.5 99.32%**, **mAP0.5:0.95 75.18%** (+10.13 pp over YOLOv8n) | Parameter-light; adaptive pruning; higher AP50 than AP50-95 indicates small-defect localization still hard | https://arxiv.org/abs/2507.17176 |
| Roboflow real-time PCB inspection walkthrough | RF-DETR Nano (transformer detector) | Forked Roboflow Universe PCB dataset (6 classes) | "Hundreds of annotated images" (as described in post) | **mAP 0.99** on test set | Confidence threshold 0.4; "training takes a few hours" on managed platform | https://blog.roboflow.com/pcb-defect-detection/ |
| YOLOv8 on semiconductor Directed Self-Assembly (DSA) defect inspection | YOLOv8 (data-centric labeling study) | SEM images of hexagonal contact-hole DSA patterns | Dataset built with novel labeling method | **Defect detection precision > 0.9 mAP** | Focus is labeling quality, not compute | https://arxiv.org/abs/2307.15516 |

**Read-across to AssemblyVision:** PCB results show that on a **single fixed imaging setup with consistent lighting, one-stage YOLO-family detectors routinely reach mAP50 ~0.98-0.99** for well-defined defect classes. But the VR-YOLO result (98.9 -> 94.7 mAP under mild viewpoint change) is the more honest figure for production robustness; small pose/light changes measurably cost accuracy.

### 3.2 Steel / Metal Surface Defects

| Project / benchmark | Method | Conditions | Dataset | Achieved metric | Notes | Source |
|---|---|---|---|---|---|---|
| Industrial-YOLO (fine-tuned YOLOv8, edge-optimized) | YOLOv8 + TensorRT/OpenVINO | **Benchmark on NEU-DET + MVTec AD + custom automotive/battery defect images; claims deployment on an active automotive assembly line** | NEU-DET, MVTec AD, custom extensions | **mAP 98.5%**; **>120 FPS on NVIDIA Jetson Orin** | **2026 preprint, single group, not peer-reviewed; treat as vendor/author-reported.** Typical YOLO papers on NEU-DET report lower mAP (~70-80%) depending on split; 98.5% is at the optimistic end and may include data curation effects | https://arxiv.org/abs/2606.07659 |
| Typical academic YOLO baselines on NEU-DET | YOLOv5/v8 variants | Standard 70/30-ish splits of the 1,800 images | 1,800 images (1,260 train in standard 70% split) | Reported mAP50 in the ~0.70-0.90 range across papers; **values vary widely with split and augmentation** (not reproduced here to avoid cherry-picking) | Small dataset; 200x200 inputs are low-resolution; results are lab results, not production | See NEU-DET hosting: https://ieee-dataport.org/documents/neu-det |
| Kaggle casting product (binary) | Classification CNNs (many public kernels) | Still images of cast products | ~7,348 images | Public kernels commonly report accuracy ~0.97-0.99 on the binary OK/defective split | Folder-label classification, not localization; accuracy is a poor metric here given class imbalance (~70/30); dataset figures are "reported" | https://www.kaggle.com/datasets/ravirajsinh45/real-life-industrial-dataset-of-casting-product |

> **Honest note:** The Industrial-YOLO abstract is included for completeness but is flagged as a non-peer-reviewed preprint with unusually high mAP; it should not be used as a planning anchor. For planning, expect NEU-DET-style benchmark mAP50 in the **0.75-0.90** range for YOLO-class models on small defect datasets, and verify with the actual split.

### 3.3 Automotive Parts Assembly / Assembly State

| Project | Method | Conditions | Dataset | Achieved metric | Notes | Source |
|---|---|---|---|---|---|---|
| ASDF - Assembly State Detection (YOLOv8 + 6D pose late fusion) | YOLOv8 object detection + pose refinement + Pose2State fusion | Medical/industrial assembly; occlusion and appearance dynamics | ASDF dataset + GBOT dataset | Outperforms "pure deep learning-based" assembly-state baselines; more robust 6D pose; on GBOT beats hybrid and pure tracking approaches | Demonstrates that combining detector + geometric verification beats detector alone - directly relevant to AssemblyVision's ROI + rules design | https://arxiv.org/abs/2403.16400 |
| Intelligent control of manual assembly operations | YOLOv8 detection, multicamera stand | Replicates real production; 120 assemblies at different speeds | 120 assemblies (multi-stage) | High segmentation/detection accuracy; stage-timing deviations identified; unified efficiency index proposed | Stage-level tracking rather than final OK/NG; shows YOLOv8 can follow assembly steps reliably in a controlled stand | https://arxiv.org/abs/2401.10777 |
| Industrial-YOLO automotive extensions | Fine-tuned YOLOv8 | Claims active assembly-line deployment | Custom automotive scratch/pit/inclusion images | (See 3.2; preprint-level claim) | Treat as unverified | https://arxiv.org/abs/2606.07659 |

**Read-across:** Published assembly-state work focuses on **detecting which assembly step is happening**, and consistently reports that adding geometric/pose verification improves state classification over detection alone. AssemblyVision's deterministic rule engine over per-component detections is the same design pattern.

### 3.4 Packaging / Food Inspection

| Project | Method | Conditions | Dataset | Achieved metric | Notes | Source |
|---|---|---|---|---|---|---|
| Roboflow missing-item (bottle counting) walkthrough | YOLO object detection, top-down | Packaged bottles, fixed camera; designed to run after a side camera cap-presence check | ~25-50 images recommended for a single object class (per the tutorial) | No formal mAP published; qualitative "correctly counted 12 bottle tops" | Demonstrates that **simple single-class counting tasks need very little data**; matches AssemblyVision's presence-checking pattern | https://blog.roboflow.com/missing-item-inspection/ |
| MVTec AD food categories (e.g., hazelnut, biscuit) | Unsupervised anomaly detection | Benchmark lab images | Part of 5,000+ MVTec AD images | MVTec AD image-level AU-ROC is high and saturating for SOTA methods (~high 90s), but AD2 shows the harder real-world gap (see 3.6) | Not a YOLO counting result; included for completeness | https://www.mvtec.com/research-teaching/datasets/mvtec-ad ; https://arxiv.org/abs/2503.21622 |

### 3.5 Textile / Fabric

| Project | Method | Conditions | Dataset | Achieved metric | Notes | Source |
|---|---|---|---|---|---|---|
| Reverse knowledge-distillation fabric anomaly detection | Teacher-student distillation (unsupervised) | Fabric anomaly detection, patterned textures | MVTec AD + AITEX + TILDA + a new textile-mill dataset | Metrics reported for each texture benchmark (see paper tables); no single headline number | Demonstrates the **unsupervised anomaly-detection route** used when defect labels are scarce; industrial fabric inspection frequently uses this rather than supervised YOLO | https://arxiv.org/abs/2401.02287 |

### 3.6 Pharmaceutical

**No reliable, citable public production recall/precision numbers were found for AI pharmaceutical visual inspection (vial/ampoule/syringe completeness or particle detection).** Adjacent evidence:

- MVTec AD 2 includes transparent-object scenarios (relevant to ampoules/vials) and reports SOTA anomaly detection below 60% AU-PRO (https://arxiv.org/abs/2503.21622).
- Pharmaceutical inspection is dominated by vendor AOI systems (Cognex, Omron, etc.) that do not publish recall numbers. https://www.cognex.com/what-is/machine-vision describes inspection capabilities without quantified accuracy.

**This is an explicit data gap.** AssemblyVision must not assume published pharmaceutical rates exist; plan to generate its own acceptance data.

### 3.7 General industry-level failure statistics (context)

- **~77% of vision AI implementations in manufacturing never make it past pilot** (practitioner interview summarized by Roboflow; attributed to integration/process issues, not model failure). https://blog.roboflow.com/scale-a-computer-vision-pilot-to-production/
- **50-70% of machine vision projects fail to meet expectations** due to preventable errors and technical oversights (industry survey cited by Cognex; vendor-published statistic, treat as directional). https://www.cognex.com/en/tools-and-resources/resource-center/machine-vision-considerations-implementation

---

## 4. Consolidated Comparison Table

| Industry / task | Method family | Conditions | Typical reported metric (test set) | Range observed | Key caveat | Sources |
|---|---|---|---|---|---|---|
| PCB defect detection | YOLOv8-family one-stage | Fixed imaging, benchmark dataset | mAP50 | **0.75 - 0.99** (75% at strict mAP50-95; 99% at mAP50) | mAP50-95 much lower than mAP50 (75% vs 99%) - localization of small defects is the binding constraint | https://arxiv.org/abs/2507.17176 ; https://arxiv.org/abs/2507.02963 |
| PCB defect detection, robustness | YOLOv8 + augmentation | Mild viewpoint shift | mAP | 98.9 -> 94.7 | Small pose/light changes cost ~4 pp | https://arxiv.org/abs/2507.02963 |
| Steel surface defects | YOLO-class on NEU-DET | Lab stills, small images | mAP50 | ~0.70 - 0.90 (typical papers) | Preprint claims 98.5% are not representative | https://ieee-dataport.org/documents/neu-det ; https://arxiv.org/abs/2606.07659 |
| Casting (binary) | CNN classification | Still images | Accuracy | ~0.97-0.99 (kernels) | Accuracy hides class imbalance; no localization | https://www.kaggle.com/datasets/ravirajsinh45/real-life-industrial-dataset-of-casting-product |
| Assembly state | YOLOv8 + pose fusion | Controlled assembly stand | Relative improvement vs pure DL | "better than pure DL baselines" | No public absolute recall; integration of geometric verification is the win | https://arxiv.org/abs/2403.16400 ; https://arxiv.org/abs/2401.10777 |
| Packaging completeness | YOLO counting | Fixed camera, simple class | Qualitative | "Correct count" demo | Very small data sufficient (25-50 images) | https://blog.roboflow.com/missing-item-inspection/ |
| Textile anomaly | Unsupervised distillation | Patterned textures | Per-benchmark metrics | See paper | Unsupervised route used when labels scarce | https://arxiv.org/abs/2401.02287 |
| Generic anomaly detection | SOTA anomaly methods | MVTec AD | AU-PRO | Saturating on MVTec AD; **<60% on MVTec AD2** | Harder, realistic scenarios reveal big gaps | https://arxiv.org/abs/2503.21622 |

---

## 5. What Real-World Success Rates Look Like: Good vs. Constrained Conditions

**Good conditions (typical lab-to-pilot results):**

- Fixed camera, fixed lighting, one product type, controlled pose, abundant well-labeled data, classes visually distinct.
- Published outcome for YOLO-class detectors on such setups: **mAP50 0.95-0.99** (PCB papers above; Roboflow PCB mAP 0.99).
- For **simple presence/counting** of a single visually-distinct object: usable models trained on **tens of images** (Roboflow missing-item tutorial: 25-50 images) and deployed successfully.

**Constrained conditions (production realism):**

- Mild viewpoint/pose variation: VR-YOLO drops from 98.9 to 94.7 mAP (https://arxiv.org/abs/2507.02963).
- Lighting and appearance shifts: MVTec AD 2 was explicitly built to test this and SOTA methods score **below 60% AU-PRO**, including on transparent objects and dark-field/back-light scenes (https://arxiv.org/abs/2503.21622).
- Severe class imbalance and rare defects: KolektorSDD2 has 356 defective vs 2,979 OK images (10.7% defect rate) (https://www.vicos.si/resources/kolektorsdd2/); rare-class recall is the metric that suffers, and small test sets make misses statistically unobservable.
- Weak/ambiguous labels: DAGM's competition design (FN cost 20x FP) encodes that in industry, a missed defect is much more expensive than a false alarm - and the winning threshold was a **total loss <= 200 across 4 test sets**, i.e., effectively near-zero tolerated misses with bounded false alarms (https://conferences.mpi-inf.mpg.de/dagm/2007/prizes.html).
- Small objects / tight localization: PCB mAP50-95 of 75.18% vs mAP50 99.32% shows that **detecting "something is wrong" is much easier than localizing it tightly** (https://arxiv.org/abs/2507.17176).

**Bottom line for AssemblyVision:** Published evidence supports high single-frame detection confidence (mAP50 ~0.95+) for presence checking under stable imaging, but **no public source reports production false-negative rates for assembly completeness**. AssemblyVision's fail-safe design (NG on any missing/uncertain evidence, temporal aggregation, human review) is the correct response to this uncertainty, and its acceptance thresholds must come from measured customer data, not from these benchmark numbers.

---

## 6. Implications and Caveats for AssemblyVision

1. **mAP is not production recall.** Every benchmark number above is a test-set average; AssemblyVision's acceptance metric (NG recall) must be measured with fixed thresholds on excluded production data.
2. **Small pose and lighting changes dominate error budgets.** Budget for them (VR-YOLO -4pp; MVTec AD2 <60% AU-PRO). AssemblyVision's fixed camera + fixed lighting are an advantage only if drift is monitored (see `[docs/design/07-camera-and-image-acquisition.md](../design/07-camera-and-image-acquisition.md)`).
3. **Rare-class and imbalance problems are the norm.** Expect NG cases to be a small minority; plan dedicated physically-captured missing-component datasets (see `[docs/design/19-training-and-evaluation.md](../design/19-training-and-evaluation.md)`).
4. **Benchmark datasets are NOT the target distribution.** NEU-DET, MVTec AD, etc. differ from a conveyor line (motion, vibration, reflection, barcode shadows). Treat them as method feasibility evidence only.
5. **Industry failure statistics** (77% pilots stall; 50-70% projects miss expectations) are about integration and process, not detector accuracy. AssemblyVision's edge-first, offline-capable design and human-in-the-loop plan address these specific failure modes.

---

## 7. Open Questions and Validation Required

- No public benchmark measures **NG recall / false-negative rate for component-presence (assembly completeness) inspection**. AssemblyVision must define its own acceptance dataset and confidence bounds (binomial bound for zero observed misses, per `[docs/design/19-training-and-evaluation.md](../design/19-training-and-evaluation.md)`).
- The Kaggle casting dataset figures (7,348 images; 5,198 OK / 2,150 defective) are dataset-page-reported and should be re-verified if used as a reference.
- Published PCB mAP numbers come from specific public datasets (splits vary); the exact dataset and split used by VR-YOLO and the multi-scale PCB papers should be confirmed before citing them as anchors.
- No reliable public numbers exist for pharmaceutical visual inspection; treat that industry as a data gap.
- The Industrial-YOLO 2026 preprint (mAP 98.5%, >120 FPS on Jetson Orin) is non-peer-reviewed; confirm or discard before relying on its throughput claims for edge hardware budgeting.
- Validate whether AssemblyVision's own target (300-800 product images; 300-500 instances/component) is sufficient by comparing against the "few hundred objects per class is enough to start, ~1,500 images / 10,000 instances per class for reliable real-world performance" guidance from Ultralytics (https://docs.ultralytics.com/guides/data-collection-and-annotation/).
