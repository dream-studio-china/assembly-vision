"""AssemblyVision edge CLI (static-image MVP)."""

from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import Path
from uuid import UUID, uuid4

from assemblyvision_domain.errors import AssemblyVisionError, ConfigError
from assemblyvision_domain.models import BusinessResult
from assemblyvision_vision.manifests import load_model_manifest
from assemblyvision_vision.roi.roi_engine import ROIEngine
from assemblyvision_vision.sources.folder_source import FolderSource

from assemblyvision_edge import __version__
from assemblyvision_edge.config import (
    load_pipeline_config,
    load_rule_definition,
    validate_model_version_declaration,
)
from assemblyvision_edge.detection import ComponentDetector, ProductDetector
from assemblyvision_edge.output.writer import OutputWriter
from assemblyvision_edge.pipeline import InspectionPipeline
from assemblyvision_edge.rules.rule_engine import RuleEngine
from assemblyvision_edge.verify import format_per_image, format_report, load_expected, run_verify

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

    verify = sub.add_parser("verify", help="Inspect images and compare with expected OK/NG labels")
    verify.add_argument("paths", nargs="+", help="Input images or folders")
    verify.add_argument("--config", required=True, type=Path, help="Pipeline configuration file")
    verify.add_argument("--rule", required=True, type=Path, help="Product rule definition file")
    verify.add_argument(
        "--expected",
        type=Path,
        default=None,
        help="Expected-labels JSON (test-expected.json); filename fallback when omitted",
    )
    verify.add_argument(
        "--output",
        required=True,
        type=Path,
        help="Output directory for inspection records",
    )
    verify.add_argument(
        "--device-id",
        type=str,
        default=None,
        help="Stable device UUID; a random UUID is generated when omitted",
    )
    verify.add_argument("-q", "--quiet", action="store_true", help="Suppress INFO logs")

    serve = sub.add_parser("serve", help="Run the local edge API and dashboard")
    serve.add_argument("--output", required=True, type=Path, help="Inspection output root")
    serve.add_argument("--db", type=Path, default=None, help="SQLite database path")
    serve.add_argument("--config", type=Path, default=None, help="Pipeline configuration file")
    serve.add_argument("--rule", type=Path, default=None, help="Product rule definition file")
    serve.add_argument("--static", type=Path, default=None, help="Built frontend directory")
    serve.add_argument("--host", default="127.0.0.1", help="Bind host")
    serve.add_argument("--port", type=int, default=8000, help="Bind port")
    serve.add_argument("--device-id", type=str, default=None, help="Stable device UUID")
    serve.add_argument(
        "--api-token",
        type=str,
        default=None,
        help="Bearer token required by every read route except /health/live "
        "(falls back to AV_EDGE_API_TOKEN)",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command == "inspect":
        return _run_inspect(args)
    if args.command == "verify":
        return _run_verify(args)
    if args.command == "serve":
        return _run_serve(args)
    # Unreachable: argparse only accepts the three subcommands above.
    return 1  # pragma: no cover


def _build_pipeline(args: argparse.Namespace) -> InspectionPipeline:
    config = load_pipeline_config(args.config)
    rule = load_rule_definition(args.rule)
    product_manifest = load_model_manifest(config.product_manifest)
    component_manifest = load_model_manifest(config.component_manifest)
    validate_model_version_declaration(
        config.product_detection.model_version, product_manifest, "product_detection.model_version"
    )
    validate_model_version_declaration(
        config.component_detection.model_version,
        component_manifest,
        "component_detection.model_version",
    )
    product_detector = ProductDetector.from_manifest(
        product_manifest, config.product_detection, config.product_manifest
    )
    component_detector = ComponentDetector.from_manifest(
        component_manifest, config.component_detection, config.components, config.component_manifest
    )
    return InspectionPipeline(
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


def _run_inspect(args: argparse.Namespace) -> int:
    logging.basicConfig(
        level=logging.ERROR if args.quiet else logging.INFO,
        format="%(levelname)s %(name)s: %(message)s",
    )
    try:
        pipeline = _build_pipeline(args)
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


def _run_verify(args: argparse.Namespace) -> int:
    logging.basicConfig(
        level=logging.ERROR if args.quiet else logging.INFO,
        format="%(levelname)s %(name)s: %(message)s",
    )
    try:
        pipeline = _build_pipeline(args)
        expected = load_expected(args.expected) if args.expected is not None else {}
    except (ConfigError, ValueError) as exc:
        log.error("configuration error: %s", exc)
        return 2

    writer = OutputWriter(args.output)
    report = run_verify(pipeline, _collect_sources(args.paths), expected, writer)
    print(format_per_image(report))
    print()
    print(format_report(report))
    if report.false_negative > 0 or report.has_gaps:
        return 1
    return 0


def _run_serve(args: argparse.Namespace) -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    try:
        import uvicorn

        from assemblyvision_edge.api.app import create_app
        from assemblyvision_edge.api.settings import ServerSettings

        db_path = args.db or (args.output / "edge.sqlite3")
        api_token = args.api_token or os.environ.get("AV_EDGE_API_TOKEN")
        settings = ServerSettings(
            output_root=args.output,
            db_path=db_path,
            config_path=args.config,
            rule_path=args.rule,
            device_id=args.device_id,
            static_dir=args.static,
            api_token=api_token,
        )
        app = create_app(settings)
        uvicorn.run(app, host=args.host, port=args.port, log_level="info")
    except (ConfigError, ValueError) as exc:
        log.error("configuration error: %s", exc)
        return 2
    return 0


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


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
