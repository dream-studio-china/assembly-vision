"""AssemblyVision edge CLI (static-image MVP)."""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path
from uuid import UUID, uuid4

from assemblyvision_domain.errors import AssemblyVisionError, ConfigError
from assemblyvision_domain.models import BusinessResult
from assemblyvision_vision.manifests import load_model_manifest
from assemblyvision_vision.roi.roi_engine import ROIEngine
from assemblyvision_vision.sources.folder_source import FolderSource

from assemblyvision_edge import __version__
from assemblyvision_edge.config import load_pipeline_config, load_rule_definition
from assemblyvision_edge.detection import ComponentDetector, ProductDetector
from assemblyvision_edge.output.writer import OutputWriter
from assemblyvision_edge.pipeline import InspectionPipeline
from assemblyvision_edge.rules.rule_engine import RuleEngine

log = logging.getLogger("assemblyvision")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="assemblyvision",
        description="AssemblyVision static-image inspection CLI (MVP)",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    inspect = sub.add_parser("inspect", help="Run the static-image inspection pipeline")
    inspect.add_argument("paths", nargs="+", help="Input images or folders")
    inspect.add_argument("--config", required=True, type=Path, help="Pipeline configuration file")
    inspect.add_argument("--rule", required=True, type=Path, help="Product rule definition file")
    inspect.add_argument("--output", required=True, type=Path, help="Output directory")
    inspect.add_argument(
        "--device-id",
        type=str,
        default=None,
        help="Stable device UUID; a random UUID is generated when omitted",
    )
    inspect.add_argument("-q", "--quiet", action="store_true", help="Suppress INFO logs")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command != "inspect":
        parser.error("unknown command")
    return _run_inspect(args)


def _run_inspect(args: argparse.Namespace) -> int:
    logging.basicConfig(
        level=logging.ERROR if args.quiet else logging.INFO,
        format="%(levelname)s %(name)s: %(message)s",
    )
    try:
        config = load_pipeline_config(args.config)
        rule = load_rule_definition(args.rule)
        product_manifest = load_model_manifest(config.product_manifest)
        component_manifest = load_model_manifest(config.component_manifest)
        product_detector = ProductDetector.from_manifest(
            product_manifest, config.product_detection, config.product_manifest
        )
        component_detector = ComponentDetector.from_manifest(
            component_manifest, config.component_detection, config.components, config.component_manifest
        )
        pipeline = InspectionPipeline(
            product_detector=product_detector,
            component_detector=component_detector,
            roi_engine=ROIEngine(config.roi),
            rule_engine=RuleEngine(),
            rule=rule,
            product_manifest=product_manifest,
            component_manifest=component_manifest,
            config=config,
            device_id=uuid4() if args.device_id is None else UUID(args.device_id),
        )
    except (ConfigError, ValueError) as exc:
        log.error("configuration error: %s", exc)
        return 2

    writer = OutputWriter(args.output)
    work = _collect_sources(args.paths)
    ok_count = 0
    ng_count = 0
    error_count = 0
    for source, path in work:
        try:
            record = pipeline.inspect_image(source, path, writer)
        except AssemblyVisionError as exc:
            error_count += 1
            log.error("inspection failed for %s: %s", path, exc)
            continue
        if record.decision.business_result is BusinessResult.NG:
            ng_count += 1
        else:
            ok_count += 1
        reasons = ",".join(record.decision.reason_codes) or "-"
        print(f"{path}\t{record.decision.business_result.value}\t{reasons}\t{record.inspection_id}")
    log.info("summary: %d OK, %d NG, %d errors", ok_count, ng_count, error_count)
    return 0 if error_count == 0 else 1


def _collect_sources(paths: list[str]) -> list[tuple[FolderSource, Path]]:
    work: list[tuple[FolderSource, Path]] = []
    for raw in paths:
        path = Path(raw)
        if path.is_dir():
            source = FolderSource(path)
            work.extend((source, p) for p in source.iter_paths())
        else:
            work.append((FolderSource(path.parent), path))
    return work


if __name__ == "__main__":
    sys.exit(main())
