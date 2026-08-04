# Research 3: Imaging Workflow, Data Practices, and Training Cost for Fixed-Line Inspection

> Status: Research synthesis for the AssemblyVision project (fixed 4MP industrial camera, fixed lighting, presence checking of large components, 300-800 image target).
> Date compiled: 2026-08-04
> Honesty convention: Lighting/camera guidance is cited from published engineering references (Cognex, Wikipedia/MV literature). **Training-time and labeling-time figures that could not be pinned to a citable source are explicitly marked "practitioner estimate"**. Cost figures depend heavily on local hardware and are ranges, not guarantees.

---

## 1. Purpose

This document gives AssemblyVision (a) imaging specifications and best practices for fixed-line inspection, (b) standard data workflows (collection SOP, labeling standards, splits, quality gates), and (c) practitioner evidence on training cost, dataset size, and common failures - plus practical checklists that map directly onto the AssemblyVision design set.

---

## 2. Imaging Specifications and Best Practices for Fixed-Line Inspection

### 2.1 Lighting is the dominant factor

Vendor-engineering consensus is unambiguous: **"Poor lighting is the most common cause of poor machine vision performance. Even sophisticated cameras and software can't make up for inadequate lighting."** Good lighting maximizes contrast on the features of interest and minimizes it everywhere else, and it must be **consistent** so that normal part variation does not change image contrast (https://www.cognex.com/en/tools-and-resources/resource-center/machine-vision/the-importance-of-lighting).

### 2.2 Lighting families (and when to use them)

| Type | Geometry | Best for | Notes for AssemblyVision |
|---|---|---|---|
| **Ring / low-angle ring** | Circular LED around the lens | Uniform bright-field on flat, matte parts; general presence checks | Good default for matte plastic/metal assemblies viewed from above |
| **Bar lights** | Linear LED strips | Larger areas, wider FOV, or angled illumination of tall parts | Consider for a large product that fills the 4MP frame |
| **Dome (diffuse) lighting** | Diffuser over a ring, "cloudy-day" light | **Curved or shiny surfaces**; suppresses reflections | First choice if the product has glossy surfaces or visible reflections |
| **Coaxial (axial) lighting** | Light injected along the optical axis via beam splitter | Flat, specular surfaces; reading low-contrast features | Strong candidate for flat component faces; can introduce specular hotspots if alignment drifts |
| **Backlighting** | Diffuse light behind the target | Silhouette, edge/counting, dimensional checks | Not applicable to a product that sits on a conveyor with background visible unless the line allows a back panel |
| **Dark-field / low-angle** | Light from the side at a shallow angle | Surface texture, scratches, embossing, height changes | Useful for scratch/emboss detection on an otherwise flat surface |
| **Bright-field / full-illumination** | Light from above reflecting into the camera | Flat parts; high contrast on flat features | The most common default |
| **Multispectral / IR** | Color-specific or IR LEDs | Suppressing busy backgrounds or color noise; working through challenging ambient light | Possible fallback if visible-light reflections are unavoidable |

Sources: https://www.cognex.com/en/tools-and-resources/resource-center/machine-vision/the-importance-of-lighting ; https://en.wikipedia.org/wiki/Machine_vision (equipment and imaging sections).

### 2.3 Filters and glare control

- **Polarizing filters** (camera-side and/or light-side) "can eliminate glare from light being reflected into a camera" - the standard fix for specular reflections on metal or shiny plastic (https://www.cognex.com/en/tools-and-resources/resource-center/machine-vision/the-importance-of-lighting).
- **Color/IR/UV filters** can raise contrast or block unwanted ambient light. In a controlled station, an enclosure that excludes ambient light is usually simpler than relying on filters.
- Glass and reflective surfaces are called out in engineering guidance as a case where "controlled lighting is important because reflections may look similar to real defects" (https://blog.roboflow.com/surface-defects/).

### 2.4 Exposure, aperture, depth of field, and motion

- **Motion blur rule:** the image must freeze the product. With a moving conveyor, exposure time must be short enough that object displacement during exposure is a small fraction of a pixel (or use a strobe/global-shutter camera). Industrial cameras normally use **global shutters** for moving parts (Wikipedia's machine vision equipment section lists simultaneous-exposure ("suitable for moving processes") as a key differentiator: https://en.wikipedia.org/wiki/Machine_vision).
- **Aperture and DoF:** choose aperture (f-stop) so the whole product height range is in focus; smaller aperture increases depth of field but reduces light, requiring more illumination or longer exposure (which risks blur). There is a classic trade triangle: exposure time / aperture / lighting intensity.
- **ISO/gain:** keep analog gain/ISO low to minimize noise; add light rather than gain. (General imaging engineering practice; not tied to a single citation - treat as standard knowledge from the same MV literature above.)
- **Over-exposure/blooming:** specular highlights can saturate the sensor and wash out feature edges. Histogram checks (e.g., max mean brightness limits) belong in the quality gate (AssemblyVision already specifies min/max mean brightness and Laplacian variance in `[docs/design/06-ai-detection-pipeline.md](../design/06-ai-detection-pipeline.md)`).

### 2.5 Camera mounting, angle, and stationarity

- **Fixed, vibration-isolated mounting.** The environment section of engineering guidance flags vibration, temperature changes, and contaminants as the top environmental risks that break vision systems (https://www.cognex.com/en/tools-and-resources/resource-center/machine-vision-considerations-implementation).
- **Angle:** a single fixed angle is the right design (AssemblyVision `[docs/design/19-training-and-evaluation.md](../design/19-training-and-evaluation.md)` states a ~45-degree angle change is a domain change requiring revalidation). A near-perpendicular top-down view minimizes perspective distortion and makes ROI coordinates stable.
- **Field of view:** set the FOV so the product occupies a consistent fraction of the frame (AssemblyVision's stage-1 min box area ratio is 0.15 in `[docs/design/08-product-detection-and-roi.md](../design/08-product-detection-and-roi.md)`); verify the actual position band and clipping range from production captures.
- **Stationarity / trigger:** hardware photo-eye or PLC trigger is preferred over time windows (per `[docs/design/07-camera-and-image-acquisition.md](../design/07-camera-and-image-acquisition.md)`); ensure the product is stationary or the exposure is strobed at a deterministic point in the conveyor cycle so every frame is comparable.

### 2.6 AssemblyVision imaging checklist (applies directly)

1. Use a dome or coaxial diffuse setup for the specific product materials; test ring/bright-field as a baseline first (Cognex guidance: "there is no one best lighting setup for all applications").
2. Enclose or shield the station from ambient light; verify consistency over a full shift.
3. Add polarization if any component face is specular.
4. Set exposure to freeze motion (global shutter / strobe); target low ISO/gain; tune aperture for full-height DoF.
5. Mount camera rigidly; record applied settings and serial numbers (per `[docs/design/07-camera-and-image-acquisition.md](../design/07-camera-and-image-acquisition.md)`).
6. Calibrate frame-quality gates (blur, brightness, glare) from real production captures, including empty, blurred, dark, bright, and reflective scenes (per `[docs/design/07-camera-and-image-acquisition.md](../design/07-camera-and-image-acquisition.md)` Section 7.9).
7. Collect calibration and drift data over a normal shift before finalizing thresholds.

---

## 3. Standard Workflows and Procedures

### 3.1 Data collection SOP (synthesis of Ultralytics + Roboflow + AssemblyVision)

Ultralytics' official guidance stresses that **"the quality of this data directly determines model performance"** and covers class definition, sourcing, and bias avoidance (https://docs.ultralytics.com/guides/data-collection-and-annotation/). Roboflow's industrial walkthroughs add field-specific coverage rules (https://blog.roboflow.com/surface-defects/).

Recommended SOP:

1. **Define a versioned class ontology** (product + required components) with inclusion/exclusion rules and ambiguity policy (AssemblyVision `[docs/design/19-training-and-evaluation.md](../design/19-training-and-evaluation.md)` Section 19.5).
2. **Collect with the production camera/optics/mounting/lighting**, not a phone or a different camera. A fixed-angle setup should be kept for training and deployment.
3. **Coverage must include:** all products/components; real OK products across batches/dates; physically constructed NG products for each missing component (do NOT synthesize all NG by digital erasure - shadows, packaging deformation, and revealed backgrounds differ); empty frames; partial entries; blur; reflections; exposure variation; occlusion (AssemblyVision `[docs/design/19-training-and-evaluation.md](../design/19-training-and-evaluation.md)` Section 19.4; same coverage themes in https://blog.roboflow.com/surface-defects/).
4. **Include negative/background images** - "normal images are also important. They teach the model that ordinary grain, color changes, and harmless surface patterns should not always be classified as defects" (https://blog.roboflow.com/surface-defects/).
5. **Provenance per image:** site/line/camera/setup, capture session, product instance, deliberate defect scenario, and camera/lighting revision (AssemblyVision `[docs/design/19-training-and-evaluation.md](../design/19-training-and-evaluation.md)` Section 19.3).

### 3.2 Labeling standards and tooling

- **Annotation rules:** consistent class names; tight boxes around the visible feature ("Large boxes containing mostly normal surface can make it harder for the model to learn"); annotate every instance; decide and document connected/overlapping cases; second reviewer for all NG and ambiguous labels (https://blog.roboflow.com/surface-defects/ ; AssemblyVision `[docs/design/19-training-and-evaluation.md](../design/19-training-and-evaluation.md)` Section 19.5).
- **Annotation types/formats:** bounding boxes for detection; COCO/VOC/YOLO formats; YOLO format is `class x_center y_center width height` normalized (https://docs.ultralytics.com/guides/data-collection-and-annotation/).
- **Tools:**
  - **CVAT** - open-source, team workflow, auto-segmentation: https://github.com/cvat-ai/cvat
  - **Label Studio** - open-source, multi-task labeling: https://github.com/HumanSignal/label-studio
  - **LabelImg** - classic lightweight bounding-box tool: https://github.com/HumanSignal/labelImg
  - **Roboflow Annotate** - managed, model-assisted labeling, dataset versioning, export to YOLO/COCO: https://blog.roboflow.com/missing-item-inspection/ and https://blog.roboflow.com/roboflow-train-3-0/
  - **Ultralytics annotation editor** (platform) - SAM-powered smart annotation, native YOLO format: https://docs.ultralytics.com/guides/data-collection-and-annotation/
- **Labeling efficiency strategies:** clear guidelines, pre-annotation tools, active learning (label the most informative samples first), batch processing similar images, regular quality checks (https://docs.ultralytics.com/guides/data-collection-and-annotation/).

### 3.3 Dataset organization and train/validation/test splits

- **Version every dataset** (checksums, annotation hashes, ontology version) and treat raw data as immutable (AssemblyVision `[docs/design/19-training-and-evaluation.md](../design/19-training-and-evaluation.md)` Sections 19.3/19.5).
- **Leakage-safe splitting is the single most important split rule:** split by physical product instance, and preferably by capture session / batch / date; **never randomly split adjacent video frames** because near-identical frames leak and inflate metrics (AssemblyVision `[docs/design/19-training-and-evaluation.md](../design/19-training-and-evaluation.md)` Section 19.6). Planning start: 70/15/15 by grouped instances for train/validation/internal test, with the customer acceptance set held out entirely.
- **Run leakage checks:** exact SHA-256 duplicates, perceptual-hash nearest neighbors, group-ID overlap, derived-file lineage (AssemblyVision Section 19.6.3).

### 3.4 Quality gates

- **Frame-level gates at inference:** blur (Laplacian variance), brightness range, corruption, frame age; rejected frames contribute no positive evidence (AssemblyVision `[docs/design/06-ai-detection-pipeline.md](../design/06-ai-detection-pipeline.md)` and `[docs/design/07-camera-and-image-acquisition.md](../design/07-camera-and-image-acquisition.md)`).
- **Dataset-level gates:** automated checks for invalid boxes, unknown classes, duplicates; second-reviewer sampling; inter-annotator agreement (https://docs.ultralytics.com/guides/data-collection-and-annotation/).
- **Model-level gates:** evaluate precision, recall, mAP, confusion matrix, false positives/negatives, small-defect performance, and predictions on normal images; "For critical classes, recall may be more important than using a very high confidence threshold" (https://blog.roboflow.com/surface-defects/).

---

## 4. Training Cost and Practitioner Experience

### 4.1 How many images do people actually need?

The public guidance is intentionally wide because it depends on task difficulty:

- **Very simple single-class detection (presence/counting of a fixed object):** Roboflow's missing-item tutorial recommends **starting with 25-50 images for one object class** (https://blog.roboflow.com/missing-item-inspection/).
- **General guidance for starting experiments:** "A few hundred annotated objects per class is enough to start experimenting with transfer learning, but for reliable real-world performance Ultralytics recommends at least 1,500 images and 10,000 labeled instances per class" (https://docs.ultralytics.com/guides/data-collection-and-annotation/).
- **AssemblyVision's own target:** ~300-800 product images (one class) and ~300-500 labeled instances per component class plus physically-constructed missing-component scenarios (per `[docs/design/19-training-and-evaluation.md](../design/19-training-and-evaluation.md)`). This sits between the "few hundred to start" and the "1,500 / 10,000 for reliability" guidance. Given a fixed station, single product type, and large components, the lower end is plausible, but it must be validated empirically - the "reliable real-world" guidance is from a vendor generalizing across diverse custom datasets.

### 4.2 Training time and compute

- **Ultralytics reference schedule:** start around **300 epochs**; reduce if overfitting early, extend to 600-1200+ if not; use early stopping (patience), pretrained weights (transfer learning), mixed precision (AMP), and subset training for iteration (https://docs.ultralytics.com/guides/model-training-tips/).
- **Managed training:** Roboflow Train defaults to 100 epochs, supports training from a COCO checkpoint, and NAS automatically trains 10-100 candidate models (https://blog.roboflow.com/roboflow-train-3-0/). Roboflow's PCB walkthrough reports "training takes a few hours" for a forked dataset (https://blog.roboflow.com/pcb-defect-detection/).
- **Practitioner estimates (clearly marked, not from a single citable benchmark):**
  - A nano/small YOLO on **hundreds of images** on a single modern consumer/data-center GPU typically converges in **minutes to ~1 hour** for 100-300 epochs. Roboflow's "a few hours" is a safe planning figure for managed pipelines.
  - Labeling time for bounding boxes is commonly cited in practitioner forums at roughly **1-3 seconds per instance** for an experienced annotator (a few minutes per image with several instances). **This is an estimate; measure it on your own data.**
  - For AssemblyVision scale (a few hundred images, 3-5 classes), total human labeling effort is realistically on the order of **hours to 1-2 person-days**, and compute cost on cloud GPUs is small (tens of GPU-hours at most for the small models). Treat these as planning ranges, not promises.

### 4.3 Common failures and tips (synthesis of cited practitioner material)

1. **Poor/ inconsistent lighting is the #1 failure** (Cognex: "Poor lighting is the most common cause of poor machine vision performance" - https://www.cognex.com/en/tools-and-resources/resource-center/machine-vision/the-importance-of-lighting).
2. **Data leakage from video frames** inflates validation metrics and misleads threshold choice (AssemblyVision Section 19.6; this is a well-known pitfall across the community).
3. **Too few real NG examples** - synthetic digital erasure does not reproduce shadows/background changes (AssemblyVision Section 19.4).
4. **Label drift / inconsistent boxes** between annotators and across days; fix with frozen ontology versions, examples, review sampling, and adjudication (AssemblyVision Section 19.5; https://docs.ultralytics.com/guides/data-collection-and-annotation/).
5. **Over-trusting mAP** - choose thresholds for recall on validation and evaluate at frozen thresholds (https://blog.roboflow.com/surface-defects/ ; AssemblyVision Section 19.9).
6. **Integration failure is the real killer** - ~77% of manufacturing vision pilots stall on integration, not model quality (https://blog.roboflow.com/scale-a-computer-vision-pilot-to-production/). AssemblyVision's design (local-first, offline-capable, human review, evidence persistence) is structured to counter this.
7. **Starting augmentations too aggressively** can distort thin features (e.g., shear distorting scratches/cracks - https://blog.roboflow.com/flanges-uality-inspection/). Keep augmentations bounded to physically plausible variation (AssemblyVision Section 19.7).
8. **Confidence triage** (PASS / REVIEW / FAIL bands) reduces wrong automatic decisions and feeds the review stream back into training - directly applicable to AssemblyVision's low-confidence `UNCERTAIN` handling (https://blog.roboflow.com/flanges-uality-inspection/ ; AssemblyVision BR-006).

### 4.4 Iteration cycles

Practitioner material consistently describes **short, feedback-driven cycles**: run a first model on default settings, review false positives/negatives, add the most informative misclassified/uncertain images, relabel, retrain (https://blog.roboflow.com/surface-defects/ ; https://blog.roboflow.com/flanges-uality-inspection/). The active-learning loop (upload low-confidence predictions for review and retraining) is a standard production pattern and matches AssemblyVision's human-in-the-loop and production-monitoring requirements (`[docs/design/19-training-and-evaluation.md](../design/19-training-and-evaluation.md)` Section 19.14).

---

## 5. Practical Checklists for AssemblyVision

### 5.1 Imaging station checklist (pre-data-collection)

- [ ] Dome or coaxial diffuse lighting chosen and prototyped; ring/bright-field baseline tested
- [ ] Polarizers available/tested for specular component faces
- [ ] Ambient light excluded (enclosure/shroud)
- [ ] Global shutter / strobe configuration set; motion blur verified at max conveyor speed
- [ ] Aperture/DoF covers full product height band; gain/ISO kept low
- [ ] Camera rigidly mounted; applied settings + serial logged (per `[docs/design/07-camera-and-image-acquisition.md](../design/07-camera-and-image-acquisition.md)`)
- [ ] Frame-quality gates calibrated on real captures (blur, brightness, glare)
- [ ] Trigger (photo-eye/PLC) debounce and product-window boundaries validated
- [ ] FOV/position band verified against stage-1 min box area and ROI margins

### 5.2 Data collection checklist

- [ ] Collect with the exact production camera/optics/lighting/software
- [ ] Cover all products, all components, real OK across batches/dates
- [ ] Physically build NG cases for every missing component and missing manual
- [ ] Include empty frames, partial entries, blur, reflections, exposure variation, occlusion
- [ ] Record provenance per image (site, line, camera, session, product instance, scenario)
- [ ] Target: ~300-800 product images; ~300-500 instances/component; ~100 product instances per missing scenario to start (AssemblyVision Section 19.2)
- [ ] Freeze dataset version with checksums and ontology version

### 5.3 Annotation checklist

- [ ] Locked, versioned class ontology with inclusion/exclusion and ambiguity rules
- [ ] Consistent tight boxes; every instance annotated; connected/overlap rules documented
- [ ] Automated checks (invalid boxes, unknown classes, duplicates)
- [ ] Second reviewer on all NG and ambiguous labels; adjudication log
- [ ] Track per-class counts, product instances, sessions, batches (frame count alone overstates diversity)

### 5.4 Split & evaluation checklist

- [ ] Leakage-safe grouping by product instance / session / batch / date (never random frame splits)
- [ ] 70/15/15 planning split by grouped instances; customer acceptance set held out entirely
- [ ] Run SHA-256 + perceptual-hash + group-ID leakage checks
- [ ] Report NG recall, FN/FP rates, per-component recall, product-detection and ROI success, latency (AssemblyVision QA-012)
- [ ] Select thresholds on validation with missed-NG costed higher; freeze before test/acceptance

### 5.5 Training & cost planning checklist

- [ ] Start from COCO-pretrained weights; ~300 epochs default with early stopping
- [ ] Budget compute: small models on hundreds of images converge in minutes-hours (managed pipelines "a few hours" per Roboflow)
- [ ] Budget labeling: hours to 1-2 person-days at AssemblyVision scale (estimate - measure locally)
- [ ] Run subset training (e.g., 10% fraction) for quick iteration before full runs (Ultralytics)
- [ ] Track run provenance: source revision, container digest, seed, dataset version, hyperparameters, artifact checksums (AssemblyVision Section 19.8)

---

## 6. Open Questions and Validation Required

- Measure the **actual labeling rate** (seconds per box) for the real components before committing to a labeling budget; published/estimate rates vary widely.
- Confirm whether 300-800 product images is sufficient for stage-1 product detection on the actual product; compare against Ultralytics' "~1,500 images / 10,000 instances per class" reliability guidance on a fixed, single-product station.
- Select and prototype the lighting solution (dome vs coaxial vs ring + polarization) on real parts; no vendor source can choose it for a specific product finish.
- Verify motion-blur and exposure requirements against the actual conveyor speed and product dwell time; determine whether a strobe/global-shutter configuration is required.
- Confirm trigger availability (photo-eye/PLC/barcode timing) and stationarity before finalizing the product-window strategy.
- Determine whether quality-gate thresholds (Laplacian variance, brightness) chosen from the design defaults are correct for the real camera and lighting.
- Establish customer-acceptance sample sizes and binomial confidence bounds for NG recall with zero or few observed misses (per `[docs/design/19-training-and-evaluation.md](../design/19-training-and-evaluation.md)` Section 19.13).
- Validate GPU/CPU training time on the team's actual training hardware; cloud GPU-hour costs for this dataset size are expected to be small but are unmeasured here.
