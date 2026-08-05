"""Product and component detector adapters.

Detector interfaces and manifest validation follow the architecture design
(docs/design/08-product-detection-and-roi.md and 09-component-detection.md).
Concrete implementations are scaffold stubs that raise DetectionError until
trained YOLO artifacts and weights are supplied (see models/manifests); the
pipeline converts those failures into deterministic NG results.
"""

from assemblyvision_edge.detection.component_detector import ComponentDetector
from assemblyvision_edge.detection.product_detector import (
    ProductDetectionOutcome,
    ProductDetector,
)

__all__ = ["ComponentDetector", "ProductDetectionOutcome", "ProductDetector"]
