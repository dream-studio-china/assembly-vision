"""AssemblyVision edge CLI (static-image MVP)."""

from __future__ import annotations

import argparse
import json
import logging
import os
import re
import sqlite3
import ssl
import sys
from datetime import timedelta
from pathlib import Path
from uuid import UUID, uuid4

from assemblyvision_domain.errors import AssemblyVisionError, ConfigError
from assemblyvision_domain.models import BusinessResult
from assemblyvision_vision.manifests import load_model_manifest
from assemblyvision_vision.roi.roi_engine import ROIEngine
from assemblyvision_vision.sources.folder_source import FolderSource

from assemblyvision_edge import __version__
from assemblyvision_edge.api.settings import (
    IntegrityScanSettings,
    RetentionSettings,
    StorageSettings,
    UploadSettings,
)
from assemblyvision_edge.config import (
    RuleIdentityRegistry,
    load_pipeline_config,
    load_rule_definition,
    validate_model_version_declaration,
    validate_rule_component_compatibility,
)
from assemblyvision_edge.detection import ComponentDetector, ProductDetector
from assemblyvision_edge.output.writer import OutputWriter
from assemblyvision_edge.persistence.repository import EdgeRepository, RepositoryError
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
    serve.add_argument(
        "--allow-dev-auth",
        action="store_true",
        help="Allow a non-loopback bind without an API token in explicit M1 "
        "development mode (not production authentication)",
    )
    serve.add_argument(
        "--enable-web-test",
        action="store_true",
        help="Enable the gated /api/v1/dev test endpoints (frame/video "
        "inspection); disabled by default (ADR-014)",
    )
    serve.add_argument(
        "--upload-base-url",
        type=str,
        default=None,
        help="HTTPS central upload endpoint (overrides AV_EDGE_UPLOAD_BASE_URL)",
    )
    serve.add_argument(
        "--upload-sink-dir",
        type=Path,
        default=None,
        help="Local development upload sink directory (overrides AV_EDGE_UPLOAD_SINK_DIR)",
    )
    serve.add_argument(
        "--upload-insecure-http",
        action="store_true",
        help="Development only: allow an http:// upload endpoint (design 13.8 "
        "requires TLS in production)",
    )
    serve.add_argument(
        "--tls-cert",
        type=Path,
        default=None,
        help="PEM certificate for local TLS on the edge API (or AV_EDGE_TLS_CERT)",
    )
    serve.add_argument(
        "--tls-key",
        type=Path,
        default=None,
        help="PEM private key for local TLS (or AV_EDGE_TLS_KEY); must be "
        "provided together with --tls-cert and not readable by group/others",
    )

    backup = sub.add_parser("backup", help="Create a consistent, checksummed edge backup bundle")
    backup.add_argument("--output", required=True, type=Path, help="Inspection output root")
    backup.add_argument("--db", type=Path, default=None, help="SQLite database path")
    backup.add_argument("--config", type=Path, default=None, help="Pipeline configuration file")
    backup.add_argument("--rule", type=Path, default=None, help="Product rule definition file")
    backup.add_argument(
        "--dest", required=True, type=Path, help="Destination .tar.gz backup bundle"
    )

    restore = sub.add_parser("restore", help="Restore a verified edge backup bundle")
    restore.add_argument("--backup", required=True, type=Path, help="Backup .tar.gz bundle")
    restore.add_argument("--output", required=True, type=Path, help="Inspection output root")
    restore.add_argument("--db", type=Path, default=None, help="SQLite database path")
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
    if args.command == "backup":
        return _run_backup(args)
    if args.command == "restore":
        return _run_restore(args)
    # Unreachable: argparse only accepts the five subcommands above.
    return 1  # pragma: no cover


def _build_pipeline(
    args: argparse.Namespace,
    rule_registry: RuleIdentityRegistry | None = None,
) -> InspectionPipeline:
    config = load_pipeline_config(args.config)
    rule = load_rule_definition(args.rule, registry=rule_registry)
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
    validate_rule_component_compatibility(rule, config, component_manifest)
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


def _open_durable_rule_registry(output: Path) -> EdgeRepository:
    """Open the durable rule-identity registry shared with ``serve``.

    The CLI and the API use the same SQLite registry (``<output>/edge.sqlite3``,
    the ``serve`` default) so a published ``(rule_id, rule_version)`` remains
    immutable across CLI invocations and service restarts. A registry that
    cannot be opened or migrated fails closed because the rule identity cannot
    be verified (gap 2).
    """
    output.mkdir(parents=True, exist_ok=True)
    try:
        return EdgeRepository.open(str(output / "edge.sqlite3"))
    except (OSError, RuntimeError, sqlite3.Error) as exc:
        raise ConfigError(f"cannot open the durable rule registry: {exc}") from exc


def _run_inspect(args: argparse.Namespace) -> int:
    logging.basicConfig(
        level=logging.ERROR if args.quiet else logging.INFO,
        format="%(levelname)s %(name)s: %(message)s",
    )
    try:
        registry = _open_durable_rule_registry(args.output)
        try:
            pipeline = _build_pipeline(args, rule_registry=registry.register_rule_identity)
        finally:
            registry.close()
    except (ConfigError, ValueError, RepositoryError) as exc:
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
        registry = _open_durable_rule_registry(args.output)
        try:
            pipeline = _build_pipeline(args, rule_registry=registry.register_rule_identity)
        finally:
            registry.close()
        expected = load_expected(args.expected) if args.expected is not None else {}
    except (ConfigError, ValueError, RepositoryError) as exc:
        log.error("configuration error: %s", exc)
        return 2

    writer = OutputWriter(args.output)
    report = run_verify(
        pipeline,
        _collect_sources(args.paths),
        expected,
        writer,
        filename_fallback=args.expected is None,
    )
    print(format_per_image(report))
    print()
    print(format_report(report))
    if report.false_negative > 0 or report.has_gaps:
        return 1
    return 0


def _is_loopback_host(host: str) -> bool:
    return host in ("127.0.0.1", "localhost", "::1", "::")


def _float_env(name: str, default: float) -> float:
    raw = os.environ.get(name)
    if raw is None:
        return default
    try:
        return float(raw)
    except ValueError as exc:
        raise ConfigError(f"{name} must be a number, got {raw!r}") from exc


def _optional_float_env(name: str) -> float | None:
    """Return a configured float without treating zero as an omitted value."""
    raw = os.environ.get(name)
    if raw is None:
        return None
    try:
        return float(raw)
    except ValueError as exc:
        raise ConfigError(f"{name} must be a number, got {raw!r}") from exc


def _int_env(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None:
        return default
    try:
        return int(raw)
    except ValueError as exc:
        raise ConfigError(f"{name} must be an integer, got {raw!r}") from exc


def _bool_env(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    if raw.lower() in ("1", "true", "yes", "on"):
        return True
    if raw.lower() in ("0", "false", "no", "off"):
        return False
    raise ConfigError(f"{name} must be a boolean, got {raw!r}")


def _build_upload_settings(args: argparse.Namespace) -> UploadSettings | None:
    """Assemble upload worker settings from CLI flags and AV_EDGE_UPLOAD_* env.

    Credentials are read from ``AV_EDGE_UPLOAD_TOKEN`` only, never from process
    arguments or committed files (design 13.8, PR-017 F6/F7). Returns ``None``
    when no destination is configured, leaving the scheduler explicitly
    disabled.
    """
    base_url = getattr(args, "upload_base_url", None) or os.environ.get("AV_EDGE_UPLOAD_BASE_URL")
    sink_dir = getattr(args, "upload_sink_dir", None) or os.environ.get("AV_EDGE_UPLOAD_SINK_DIR")
    if not base_url and not sink_dir:
        return None
    settings = UploadSettings(
        base_url=base_url,
        sink_dir=Path(sink_dir) if sink_dir else None,
        token=_secret_env("AV_EDGE_UPLOAD_TOKEN", "edge_upload_token"),
        connect_timeout_seconds=_float_env("AV_EDGE_UPLOAD_CONNECT_TIMEOUT_SECONDS", 5.0),
        request_timeout_seconds=_float_env("AV_EDGE_UPLOAD_REQUEST_TIMEOUT_SECONDS", 30.0),
        interval_seconds=_float_env("AV_EDGE_UPLOAD_INTERVAL_SECONDS", 1.0),
        batch_size=_int_env("AV_EDGE_UPLOAD_BATCH_SIZE", 4),
        lease_seconds=_int_env("AV_EDGE_UPLOAD_LEASE_SECONDS", 120),
        base_retry_seconds=_float_env("AV_EDGE_UPLOAD_BASE_RETRY_SECONDS", 2.0),
        maximum_retry_seconds=_float_env("AV_EDGE_UPLOAD_MAXIMUM_RETRY_SECONDS", 900.0),
        exponent_cap=_int_env("AV_EDGE_UPLOAD_EXPONENT_CAP", 8),
        maximum_bandwidth_mbps=_optional_float_env("AV_EDGE_UPLOAD_MAXIMUM_BANDWIDTH_MBPS"),
        allow_insecure_http=getattr(args, "upload_insecure_http", False)
        or _bool_env("AV_EDGE_UPLOAD_INSECURE_HTTP", False),
        circuit_failure_threshold=_int_env("AV_EDGE_UPLOAD_CIRCUIT_FAILURE_THRESHOLD", 5),
        circuit_open_seconds=_float_env("AV_EDGE_UPLOAD_CIRCUIT_OPEN_SECONDS", 60.0),
        media_chunk_bytes=_int_env("AV_EDGE_UPLOAD_MEDIA_CHUNK_BYTES", 8_388_608),
    )
    settings.validate()
    return settings


_DURATION_UNIT_SECONDS = {"s": 1, "m": 60, "h": 3600, "d": 86400}


def _parse_duration(raw: str) -> timedelta:
    """Parse a compact duration such as ``1d``, ``12h``, ``30m``, or ``90s``."""
    match = re.fullmatch(r"\s*(\d+)\s*([smhd])\s*", raw)
    if match is None:
        raise ConfigError(f"invalid duration {raw!r}; use e.g. 1d, 12h, 30m, 90s")
    value = int(match.group(1))
    return timedelta(seconds=value * _DURATION_UNIT_SECONDS[match.group(2)])


def _build_storage_settings() -> StorageSettings | None:
    """Assemble disk-pressure settings from AV_EDGE_STORAGE_* env (E2c)."""
    names = (
        "AV_EDGE_STORAGE_WARNING_FREE_PERCENT",
        "AV_EDGE_STORAGE_CRITICAL_FREE_PERCENT",
        "AV_EDGE_STORAGE_STOP_FREE_PERCENT",
    )
    if not any(os.environ.get(name) is not None for name in names):
        return None
    settings = StorageSettings(
        warning_free_percent=_float_env("AV_EDGE_STORAGE_WARNING_FREE_PERCENT", 20.0),
        critical_free_percent=_float_env("AV_EDGE_STORAGE_CRITICAL_FREE_PERCENT", 10.0),
        stop_free_percent=_float_env("AV_EDGE_STORAGE_STOP_FREE_PERCENT", 5.0),
    )
    settings.validate()
    return settings


def _build_retention_settings() -> RetentionSettings | None:
    """Assemble retention policy from AV_EDGE_RETENTION_* env (E2c).

    Cleanup is enabled only when ``AV_EDGE_RETENTION_ENABLED`` is true.
    ``AV_EDGE_RETENTION_DURATIONS`` maps media kinds to compact durations, e.g.
    ``{"KEY_FRAME": "1d", "NG_CLIP": "30d"}``; missing kinds are protected.
    """
    enabled = _bool_env("AV_EDGE_RETENTION_ENABLED", False)
    raw = os.environ.get("AV_EDGE_RETENTION_DURATIONS")
    if not enabled and raw is None:
        return None
    durations: dict[str, timedelta] = {}
    if raw is not None:
        try:
            parsed = json.loads(raw)
        except ValueError as exc:
            raise ConfigError("AV_EDGE_RETENTION_DURATIONS must be a JSON object") from exc
        if not isinstance(parsed, dict):
            raise ConfigError("AV_EDGE_RETENTION_DURATIONS must be a JSON object")
        durations = {str(kind): _parse_duration(str(value)) for kind, value in parsed.items()}
    settings = RetentionSettings(enabled=enabled, durations=durations)
    settings.validate()
    return settings


def _build_integrity_scan_settings() -> IntegrityScanSettings | None:
    """Assemble startup integrity-scan policy from AV_EDGE_STORAGE_INTEGRITY_* (F09)."""
    names = (
        "AV_EDGE_STORAGE_INTEGRITY_VERIFY_CHECKSUMS",
        "AV_EDGE_STORAGE_INTEGRITY_SAMPLE_LIMIT",
        "AV_EDGE_STORAGE_INTEGRITY_SAMPLE_MAX_BYTES",
    )
    if not any(os.environ.get(name) is not None for name in names):
        return None
    sample_limit = _optional_int_env("AV_EDGE_STORAGE_INTEGRITY_SAMPLE_LIMIT")
    sample_max_bytes = _optional_int_env("AV_EDGE_STORAGE_INTEGRITY_SAMPLE_MAX_BYTES")
    settings = IntegrityScanSettings(
        verify_checksums=_bool_env("AV_EDGE_STORAGE_INTEGRITY_VERIFY_CHECKSUMS", True),
        sample_limit=sample_limit,
        sample_max_bytes=sample_max_bytes,
    )
    settings.validate()
    return settings


def _optional_int_env(name: str) -> int | None:
    raw = os.environ.get(name)
    if raw is None:
        return None
    try:
        return int(raw)
    except ValueError as exc:
        raise ConfigError(f"{name} must be an integer, got {raw!r}") from exc


_SECRET_DIR = Path("/run/secrets")


def _secret_env(name: str, secret_file: str) -> str | None:
    """Return an environment secret, falling back to a Docker secret file.

    Docker secrets are mounted read-only under ``/run/secrets/<name>`` and
    never appear in image layers or process arguments (design 21.9, E5b).
    A secret file that exists but cannot be read fails closed instead of
    silently treating the secret as unset.
    """
    value = os.environ.get(name)
    if value:
        return value
    path = _SECRET_DIR / secret_file
    if not path.exists():
        return None
    try:
        content = path.read_text(encoding="utf-8").strip()
    except OSError as exc:
        raise ConfigError(f"cannot read secret file {path}: {exc}") from exc
    return content or None


def _optional_path_env(name: str) -> Path | None:
    raw = os.environ.get(name)
    if raw is None:
        return None
    return Path(raw)


def _validate_tls_files(cert: Path, key: Path) -> None:
    """Validate local TLS material before uvicorn starts (design 21.4, E5b).

    The private key must not be readable by group or others; the certificate
    and key must match, verified by loading them into a server TLS context.
    """
    if not cert.is_file() or not key.is_file():
        raise ConfigError("tls certificate and key must be existing files")
    key_mode = key.stat().st_mode & 0o777
    if key_mode & 0o044:
        raise ConfigError(
            f"tls private key {key} must not be readable by group or others "
            "(chmod 600 or mount as a Docker secret with mode 0400)"
        )
    try:
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.load_cert_chain(str(cert), str(key))
    except (ssl.SSLError, OSError, ValueError) as exc:
        raise ConfigError(f"tls certificate/key pair is invalid or mismatched: {exc}") from exc


def _validate_serve_bind(host: str, api_token: str | None, allow_dev_auth: bool) -> None:
    """Reject a non-loopback bind without authentication.

    Loopback binding is not authentication (design 15.2.1). Binding beyond
    loopback without a token disables auth entirely, so it requires either a
    token or an explicit development override (AUDIT-001 4.5).
    """
    if not _is_loopback_host(host) and not api_token and not allow_dev_auth:
        raise ConfigError(
            f"binding {host!r} without an API token disables authentication; "
            "set AV_EDGE_API_TOKEN / --api-token, or pass --allow-dev-auth for "
            "the documented M1 development mode"
        )


def _resolve_tls_files(args: argparse.Namespace) -> tuple[Path | None, Path | None]:
    """Resolve and validate the optional local TLS pair from flags/env (E5b)."""
    cert = args.tls_cert or _optional_path_env("AV_EDGE_TLS_CERT")
    key = args.tls_key or _optional_path_env("AV_EDGE_TLS_KEY")
    if (cert is None) != (key is None):
        raise ConfigError("tls certificate and key must be provided together")
    if cert is not None and key is not None:
        _validate_tls_files(cert, key)
    return cert, key


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
        api_token = args.api_token or _secret_env("AV_EDGE_API_TOKEN", "edge_api_token")
        _validate_serve_bind(args.host, api_token, args.allow_dev_auth)
        tls_cert, tls_key = _resolve_tls_files(args)
        settings = ServerSettings(
            output_root=args.output,
            db_path=db_path,
            config_path=args.config,
            rule_path=args.rule,
            device_id=args.device_id,
            static_dir=args.static,
            api_token=api_token,
            enable_web_test=args.enable_web_test,
            upload=_build_upload_settings(args),
            storage=_build_storage_settings(),
            retention=_build_retention_settings(),
            integrity_scan=_build_integrity_scan_settings(),
        )
        app = create_app(settings)
        uvicorn.run(
            app,
            host=args.host,
            port=args.port,
            log_level="info",
            ssl_certfile=str(tls_cert) if tls_cert is not None else None,
            ssl_keyfile=str(tls_key) if tls_key is not None else None,
        )
    except (ConfigError, ValueError) as exc:
        log.error("configuration error: %s", exc)
        return 2
    return 0


def _run_backup(args: argparse.Namespace) -> int:
    """Create a consistent backup bundle (design 20.10, E5c)."""
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    try:
        from assemblyvision_edge.backup import backup_edge

        report = backup_edge(
            output_root=args.output,
            db_path=args.db or (args.output / "edge.sqlite3"),
            dest=args.dest,
            config_path=args.config,
            rule_path=args.rule,
        )
        log.info(
            "backup written to %s: %d governed files, %d pending media, sha256=%s",
            report.bundle_path,
            report.governed_files,
            report.pending_media,
            report.bundle_sha256,
        )
        return 0
    except (ConfigError, ValueError, OSError) as exc:
        log.error("backup failed: %s", exc)
        return 2


def _run_restore(args: argparse.Namespace) -> int:
    """Restore a verified backup bundle (design 20.10, E5c)."""
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    try:
        from assemblyvision_edge.backup import restore_edge

        report = restore_edge(
            backup=args.backup,
            output_root=args.output,
            db_path=args.db or (args.output / "edge.sqlite3"),
        )
        log.info(
            "restore from %s: db=%s, media=%d, reconciled=%d",
            report.backup_path,
            report.restored_db,
            report.restored_media,
            report.reconciled,
        )
        return 0
    except (ConfigError, ValueError, OSError) as exc:
        log.error("restore failed: %s", exc)
        return 2


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
