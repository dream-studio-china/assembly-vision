"""AssemblyVision developer-only training CLI (av-train)."""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

import yaml
from assemblyvision_domain.errors import ConfigError
from assemblyvision_vision.roi.roi_engine import ROIConfig

from assemblyvision_training import __version__
from assemblyvision_training.artifact import place_weights, write_manifest
from assemblyvision_training.dataset import validate_dataset
from assemblyvision_training.prepare_components import prepare_component_dataset
from assemblyvision_training.train import train_detector

log = logging.getLogger("assemblyvision.training")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="av-train",
        description="AssemblyVision developer-only training CLI",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    product = sub.add_parser("product", help="Train a full-frame product detector")
    product.add_argument("dataset", type=Path, help="YOLO dataset directory")
    product.add_argument("--semver", required=True, help="Semantic version for the artifact")
    product.add_argument("--epochs", type=int, default=50, help="Training epochs")
    product.add_argument("--imgsz", type=int, default=640, help="Model input size")
    product.add_argument("--model-size", default="n", help="YOLO model scale (n/s/m/l)")
    product.add_argument("--device", default="cpu", help="torch device (cpu/mps/cuda)")
    product.add_argument(
        "--seed", type=int, default=0, help="Training random seed (reproducibility)"
    )
    product.add_argument(
        "--no-augment",
        action="store_true",
        help="Disable heavy augmentation (stable for small datasets)",
    )
    product.add_argument(
        "--out-weights",
        type=Path,
        default=Path("models/weights/product-yolo.pt"),
        help="Output weights path",
    )
    product.add_argument(
        "--out-manifest",
        type=Path,
        default=Path("models/manifests/product-manifest.json"),
        help="Output manifest path",
    )
    product.add_argument(
        "--rule",
        type=Path,
        default=None,
        help="Optional product-rule.yaml to suggest the required version bump",
    )

    prepare = sub.add_parser("prepare-components", help="Prepare ROI-cropped component dataset")
    prepare.add_argument("dataset", type=Path, help="YOLO dataset with full-frame component labels")
    prepare.add_argument(
        "--product-weights", required=True, type=Path, help="Trained product detector weights"
    )
    prepare.add_argument("--margin-x", type=float, default=0.05, help="ROI X margin ratio")
    prepare.add_argument("--margin-y", type=float, default=0.05, help="ROI Y margin ratio")
    prepare.add_argument("--min-area", type=int, default=10_000, help="Minimum ROI area (pixels)")
    prepare.add_argument(
        "--min-retention", type=float, default=0.80, help="Minimum clip retention ratio"
    )
    prepare.add_argument("--out-dir", type=Path, required=True, help="Output dataset directory")

    component = sub.add_parser("component", help="Train a component detector on ROI images")
    component.add_argument("dataset", type=Path, help="Prepared ROI-cropped YOLO dataset")
    component.add_argument("--semver", required=True, help="Semantic version for the artifact")
    component.add_argument("--epochs", type=int, default=50, help="Training epochs")
    component.add_argument("--imgsz", type=int, default=320, help="Model input size")
    component.add_argument("--model-size", default="n", help="YOLO model scale (n/s/m/l)")
    component.add_argument("--device", default="cpu", help="torch device (cpu/mps/cuda)")
    component.add_argument(
        "--seed", type=int, default=0, help="Training random seed (reproducibility)"
    )
    component.add_argument(
        "--no-augment",
        action="store_true",
        help="Disable heavy augmentation (stable for small datasets)",
    )
    component.add_argument(
        "--out-weights",
        type=Path,
        default=Path("models/weights/component-yolo.pt"),
        help="Output weights path",
    )
    component.add_argument(
        "--out-manifest",
        type=Path,
        default=Path("models/manifests/component-manifest.json"),
        help="Output manifest path",
    )
    component.add_argument(
        "--rule",
        type=Path,
        default=None,
        help="Optional product-rule.yaml to suggest the required version bump",
    )

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    logging.basicConfig(
        level=logging.INFO,
        format="%(levelname)s %(name)s: %(message)s",
    )

    cmd = args.command
    if cmd == "product":
        return _run_product(args)
    if cmd == "prepare-components":
        return _run_prepare(args)
    if cmd == "component":
        return _run_component(args)
    parser.error(f"unknown command: {cmd}")


def _print_improvement_hints(task: str, weights_path: Path, rule_path: Path | None) -> None:
    tag = weights_path.stem
    print("\n=== Next steps: model improved ===")
    if task == "COMPONENT_DETECTION":
        print(f"1. pipeline.yaml: set component_detection.model_version: {tag!r}")
        print(f"2. product-rule.yaml: add {tag!r} to compatible_component_model_versions")
        if rule_path is not None and rule_path.is_file():
            try:
                raw = yaml.safe_load(rule_path.read_text(encoding="utf-8"))
                current = int(raw.get("rule_version", 0))
                comp = list(raw.get("compatible_component_model_versions", []))
                print(f"   suggested: rule_version {current} -> {current + 1}")
                print(f"   suggested compatible: {comp} -> {comp + [tag]}")
            except (OSError, yaml.YAMLError, TypeError, ValueError) as exc:
                print(f"   (could not read rule {rule_path} for suggestions: {exc})")
    else:
        print(f"1. pipeline.yaml: set product_detection.model_version: {tag!r}")
        print("2. regenerate the component ROI dataset with prepare-components")
        print("   using the new product weights, then retrain the component detector")
    print(
        "3. re-run: assemblyvision verify <test> --config <pipeline.yaml> --rule <rule.yaml> --output out/"
    )
    print("   see docs/runbooks/10-model-improvement.md")


def _run_product(args: argparse.Namespace) -> int:
    try:
        info = validate_dataset(args.dataset)
    except ConfigError as exc:
        log.error("invalid dataset: %s", exc)
        return 2
    log.info(
        "dataset validated: %d classes, %d train / %d val images",
        len(info.class_names),
        info.train_images,
        info.val_images,
    )
    semver = args.semver
    weights_path: Path = args.out_weights
    manifest_path: Path = args.out_manifest

    log.info(
        "training product detector (semver=%s epochs=%d imgsz=%d device=%s)",
        semver,
        args.epochs,
        args.imgsz,
        args.device,
    )
    best = train_detector(
        dataset_dir=args.dataset,
        model_size=args.model_size,
        epochs=args.epochs,
        imgsz=args.imgsz,
        device=args.device,
        project_dir=weights_path.parent / ".train-runs",
        run_name="product",
        seed=args.seed,
        no_augment=args.no_augment,
    )
    log.info("best weights: %s", best)
    place_weights(best, weights_path)
    log.info("weights saved: %s", weights_path)

    manifest = write_manifest(
        task="PRODUCT_DETECTION",
        semantic_version=semver,
        class_names=info.class_names,
        weights_path=weights_path,
        imgsz=args.imgsz,
        output_path=manifest_path,
    )
    log.info("manifest written: %s (version_id=%s)", manifest_path, manifest.model_version_id)
    _print_improvement_hints("PRODUCT_DETECTION", weights_path, args.rule)
    return 0


def _run_prepare(args: argparse.Namespace) -> int:
    try:
        validate_dataset(args.dataset)
    except ConfigError as exc:
        log.error("invalid dataset: %s", exc)
        return 2

    product_weights: Path = args.product_weights
    if not product_weights.is_file():
        log.error("product weights not found: %s", product_weights)
        return 2

    roi_config = ROIConfig(
        margin_x_ratio=args.margin_x,
        margin_y_ratio=args.margin_y,
        min_area_pixels=args.min_area,
        min_expanded_area_retained=args.min_retention,
    )
    log.info("preparing component dataset -> %s", args.out_dir)
    prepare_component_dataset(
        dataset_dir=args.dataset,
        product_weights=product_weights,
        roi_config=roi_config,
        output_dir=args.out_dir,
    )
    log.info("component dataset prepared at %s", args.out_dir)
    return 0


def _run_component(args: argparse.Namespace) -> int:
    try:
        info = validate_dataset(args.dataset)
    except ConfigError as exc:
        log.error("invalid dataset: %s", exc)
        return 2
    log.info(
        "dataset validated: %d classes, %d train / %d val images",
        len(info.class_names),
        info.train_images,
        info.val_images,
    )
    semver = args.semver
    weights_path: Path = args.out_weights
    manifest_path: Path = args.out_manifest

    log.info(
        "training component detector (semver=%s epochs=%d imgsz=%d device=%s)",
        semver,
        args.epochs,
        args.imgsz,
        args.device,
    )
    best = train_detector(
        dataset_dir=args.dataset,
        model_size=args.model_size,
        epochs=args.epochs,
        imgsz=args.imgsz,
        device=args.device,
        project_dir=weights_path.parent / ".train-runs",
        run_name="component",
        seed=args.seed,
        no_augment=args.no_augment,
    )
    log.info("best weights: %s", best)
    place_weights(best, weights_path)
    log.info("weights saved: %s", weights_path)

    manifest = write_manifest(
        task="COMPONENT_DETECTION",
        semantic_version=semver,
        class_names=info.class_names,
        weights_path=weights_path,
        imgsz=args.imgsz,
        output_path=manifest_path,
    )
    log.info("manifest written: %s (version_id=%s)", manifest_path, manifest.model_version_id)
    _print_improvement_hints("COMPONENT_DETECTION", weights_path, args.rule)
    return 0


if __name__ == "__main__":
    sys.exit(main())
