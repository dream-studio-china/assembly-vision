"""Config tool editable-object schema.

Declarative field descriptions drive both the interactive editor and the
aggregate validator. Fields reference raw document keys so the tool edits the
source YAML/JSON/env documents directly (preserving comments and unknown
structure) instead of re-serializing the immutable dataclasses.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

FieldType = Literal["str", "int", "float", "bool", "choice"]


@dataclass(frozen=True)
class FieldSpec:
    """One editable field of a configuration object."""

    key: str
    label_key: str
    type: FieldType = "str"
    required: bool = False
    help_key: str | None = None
    choices: tuple[str, ...] = ()
    min_value: float | None = None
    max_value: float | None = None


@dataclass(frozen=True)
class ObjectSpec:
    """One editable object; ``doc_key`` locates it in the source document."""

    name_key: str
    doc_key: str
    fields: tuple[FieldSpec, ...] = field(default_factory=tuple)


# -- product / rule ---------------------------------------------------------

PRODUCT_RULE_FIELDS: tuple[FieldSpec, ...] = (
    FieldSpec("rule_id", "Rule id", "str", required=True),
    FieldSpec("rule_version", "Rule version", "int", required=True, min_value=1),
    FieldSpec("product_type", "Product type", "str", required=True),
    FieldSpec("barcode_required", "Barcode required", "bool"),
    FieldSpec(
        "compatible_component_model_versions",
        "Compatible component model versions",
        "str",
        required=True,
    ),
)

PRODUCT_RULE_SPEC = ObjectSpec("Product / rule", "", PRODUCT_RULE_FIELDS)

# -- camera sources ---------------------------------------------------------

CAMERA_SOURCE_CHOICES = ("folder", "video", "opencv-device", "rtsp", "http-image", "gige-vision")

CAMERA_COMMON_FIELDS: tuple[FieldSpec, ...] = (
    FieldSpec("source", "Camera source", "choice", required=True, choices=CAMERA_SOURCE_CHOICES),
    FieldSpec("fps", "FPS", "float", min_value=0.0),
    FieldSpec("loop", "Loop", "bool"),
)

CAMERA_SOURCE_FIELDS: dict[str, tuple[FieldSpec, ...]] = {
    "folder": CAMERA_COMMON_FIELDS
    + (FieldSpec("path", "Image folder path", "str", required=True),),
    "video": CAMERA_COMMON_FIELDS + (FieldSpec("path", "Video path", "str", required=True),),
    "opencv-device": CAMERA_COMMON_FIELDS
    + (FieldSpec("device", "Device index or path", "str", required=True),),
    "rtsp": CAMERA_COMMON_FIELDS + (FieldSpec("url", "RTSP URL", "str", required=True),),
    "http-image": CAMERA_COMMON_FIELDS
    + (FieldSpec("url", "HTTP image URL", "str", required=True),),
    "gige-vision": CAMERA_COMMON_FIELDS
    + (
        FieldSpec("serial", "Camera serial", "str", required=True),
        FieldSpec("gentl_producer", "GenTL producer (.cti)", "str", required=True),
        FieldSpec(
            "trigger_mode", "Trigger mode", "choice", choices=("continuous", "software", "hardware")
        ),
        FieldSpec("pixel_format", "Pixel format"),
        FieldSpec("exposure_us", "Exposure (us)", "float", min_value=0.0),
        FieldSpec("gain_db", "Gain (dB)", "float", min_value=0.0),
        FieldSpec("packet_size", "Packet size", "int", min_value=1),
    ),
}

# -- detection thresholds ----------------------------------------------------

DETECTION_FIELDS: tuple[FieldSpec, ...] = (
    FieldSpec(
        "product_detection.confidence_threshold",
        "Product confidence threshold",
        "float",
        min_value=0.0,
        max_value=1.0,
    ),
    FieldSpec(
        "product_detection.iou_threshold",
        "Product IOU threshold",
        "float",
        min_value=0.0,
        max_value=1.0,
    ),
    FieldSpec(
        "component_detection.iou_threshold",
        "Component IOU threshold",
        "float",
        min_value=0.0,
        max_value=1.0,
    ),
)

DETECTION_SPEC = ObjectSpec("Detection thresholds", "", DETECTION_FIELDS)

# -- ROI ---------------------------------------------------------------------

ROI_FIELDS: tuple[FieldSpec, ...] = (
    FieldSpec("margin_x_ratio", "ROI margin X ratio", "float", min_value=0.0, max_value=1.0),
    FieldSpec("margin_y_ratio", "ROI margin Y ratio", "float", min_value=0.0, max_value=1.0),
    FieldSpec("min_area_pixels", "ROI minimum area (pixels)", "int", min_value=1),
    FieldSpec(
        "min_expanded_area_retained",
        "ROI minimum expanded area retained",
        "float",
        min_value=0.0,
        max_value=1.0,
    ),
    FieldSpec("normalize_perspective", "ROI normalize perspective", "bool"),
)

ROI_SPEC = ObjectSpec("ROI", "roi", ROI_FIELDS)

# -- identity / barcode ------------------------------------------------------

IDENTITY_FIELDS: tuple[FieldSpec, ...] = (
    FieldSpec("enabled", "Barcode identity enabled", "bool"),
    FieldSpec("required", "Barcode identity required", "bool"),
    FieldSpec("allowed_symbologies", "Allowed symbologies", "str"),
    FieldSpec("mapping_file", "Barcode mapping file", "str"),
)

IDENTITY_SPEC = ObjectSpec("Identity / barcode", "identity.barcode", IDENTITY_FIELDS)

# -- model manifest ----------------------------------------------------------

MANIFEST_FIELDS: tuple[FieldSpec, ...] = (
    FieldSpec("model_version_label", "Model version label", "str", required=True),
    FieldSpec("class_names", "Class names (comma separated)", "str", required=True),
    FieldSpec("semantic_version", "Semantic version", "str", required=True),
    FieldSpec("artifacts.0.uri", "Artifact URI", "str", required=True),
    FieldSpec("artifacts.0.sha256", "Artifact SHA-256", "str", required=True),
    FieldSpec("artifacts.0.size_bytes", "Artifact size (bytes)", "int", required=True, min_value=0),
)

MANIFEST_SPEC = ObjectSpec("Model manifests", "", MANIFEST_FIELDS)

# -- central .env ------------------------------------------------------------

CENTRAL_ENV_FIELDS: tuple[FieldSpec, ...] = (
    FieldSpec("AV_CENTRAL_DATABASE_URL", "Database URL", "str", required=True),
    FieldSpec("AV_CENTRAL_MINIO_ENDPOINT", "MinIO endpoint", "str", required=True),
    FieldSpec("AV_CENTRAL_MINIO_ACCESS_KEY", "MinIO access key", "str", required=True),
    FieldSpec("AV_CENTRAL_MINIO_SECRET_KEY", "MinIO secret key", "str", required=True),
    FieldSpec("AV_CENTRAL_MINIO_BUCKET", "MinIO bucket", "str", required=True),
    FieldSpec("AV_CENTRAL_MINIO_SECURE", "MinIO secure (TLS)", "bool"),
    FieldSpec("AV_CENTRAL_ADMIN_TOKEN", "Administrator token", "str"),
    FieldSpec("AV_CENTRAL_DEVICE_UPLOAD_TOKEN", "Device upload token", "str"),
    FieldSpec("AV_CENTRAL_SECURE_COOKIES", "Secure session cookies", "bool"),
    FieldSpec(
        "AV_CENTRAL_RATE_LIMIT_REQUESTS_PER_MINUTE", "Rate limit per minute", "int", min_value=0
    ),
    FieldSpec(
        "AV_CENTRAL_ADMIN_SESSION_TTL_MINUTES", "Admin session TTL (minutes)", "int", min_value=1
    ),
    FieldSpec("POSTGRES_USER", "PostgreSQL user", "str"),
    FieldSpec("POSTGRES_PASSWORD", "PostgreSQL password", "str"),
    FieldSpec("POSTGRES_DB", "PostgreSQL database", "str"),
    FieldSpec("MINIO_ROOT_USER", "MinIO root user", "str"),
    FieldSpec("MINIO_ROOT_PASSWORD", "MinIO root password", "str"),
    FieldSpec("MINIO_BUCKET", "MinIO bucket (compose)", "str"),
)

CENTRAL_ENV_SPEC = ObjectSpec("Central server (.env)", "", CENTRAL_ENV_FIELDS)

ALL_OBJECTS: tuple[ObjectSpec, ...] = (
    PRODUCT_RULE_SPEC,
    ObjectSpec("Camera instances (devices)", "instances", ()),
    DETECTION_SPEC,
    ROI_SPEC,
    IDENTITY_SPEC,
    MANIFEST_SPEC,
    CENTRAL_ENV_SPEC,
)

# -- dev / production boundary ----------------------------------------------

# Edge pipeline dev-only markers that production mode rejects (mirrors the
# runtime fail-closed rules in config.py).
DEV_ONLY_EDGE: tuple[tuple[str, str], ...] = (
    ("temporal.window_strategy", "time"),
    ("trigger.source", "mock"),
)


def field_path(spec: FieldSpec, object_doc: dict[str, Any] | None = None) -> str:
    """Return the dotted document path for a field (used in reports/diffs)."""
    return spec.key


def parse_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        text = value.strip().lower()
        if text in ("true", "yes", "1", "on"):
            return True
        if text in ("false", "no", "0", "off"):
            return False
    raise ValueError(f"invalid boolean: {value!r}")


def parse_int(value: Any) -> int:
    return int(value)


def parse_float(value: Any) -> float:
    return float(value)
