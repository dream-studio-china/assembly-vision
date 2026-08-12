"""Command-line interface for the central server.

Subcommands:
- ``serve``: run the FastAPI application (settings from ``AV_CENTRAL_*`` env).
- ``migrate``: apply pending schema migrations - a controlled release step
  that is never executed by the API process itself.
- ``bootstrap``: idempotently create the pilot organization, site, line,
  registered device, and administrator (C1b) - an explicit operator step that
  upload requests can never trigger implicitly.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence

from central_service.api.app import create_app
from central_service.api.settings import CentralSettings
from central_service.persistence.bootstrap import (
    BootstrapError,
    resolve_plan,
    run_bootstrap,
)
from central_service.persistence.engine import create_database_engine
from central_service.persistence.migrate import migrate_to_head, schema_at_head
from central_service.persistence.repository import CentralRepository
from central_service.storage.object_store import (
    MinioObjectStorage,
    ObjectStorageSettings,
    reconcile_media,
)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="central-service")
    subparsers = parser.add_subparsers(dest="command", required=True)

    serve = subparsers.add_parser("serve", help="run the FastAPI application")
    serve.add_argument("--host", default=None, help="bind address (default: settings host)")
    serve.add_argument("--port", type=int, default=None, help="bind port (default: settings port)")

    migrate = subparsers.add_parser(
        "migrate", help="apply pending schema migrations (controlled release step)"
    )
    migrate.add_argument("--database-url", default=None, help="override AV_CENTRAL_DATABASE_URL")

    bootstrap = subparsers.add_parser(
        "bootstrap",
        help="idempotently create the pilot organization/device/administrator",
    )
    bootstrap.add_argument("--database-url", default=None, help="override AV_CENTRAL_DATABASE_URL")
    bootstrap.add_argument("--organization-name", default=None)
    bootstrap.add_argument("--site-name", default=None)
    bootstrap.add_argument("--line-name", default=None)
    bootstrap.add_argument("--device-id", default=None)
    bootstrap.add_argument("--device-name", default=None)
    bootstrap.add_argument("--device-upload-token", default=None)
    bootstrap.add_argument("--admin-username", default=None)
    bootstrap.add_argument("--admin-token", default=None)

    reconcile = subparsers.add_parser(
        "reconcile-media",
        help="idempotent integrity check of media bindings vs object store (C2b)",
    )
    reconcile.add_argument("--database-url", default=None, help="override AV_CENTRAL_DATABASE_URL")
    reconcile.add_argument(
        "--remove-orphans",
        action="store_true",
        help="remove object-store objects that have no persisted binding",
    )

    args = parser.parse_args(list(argv) if argv is not None else None)
    try:
        if args.command == "migrate":
            return _run_migrate(args.database_url)
        if args.command == "bootstrap":
            return _run_bootstrap(args)
        if args.command == "reconcile-media":
            return _run_reconcile_media(args)
        return _run_serve(args.host, args.port)
    except SystemExit:
        raise
    except Exception as exc:  # noqa: BLE001 - CLI entry point reports and exits
        print(f"central-service: {exc}", file=sys.stderr)
        return 1


def _run_serve(host: str | None, port: int | None) -> int:
    import uvicorn

    settings = CentralSettings()
    settings.validate_settings()
    app = create_app(settings)
    uvicorn.run(
        app,
        host=host if host is not None else settings.host,
        port=port if port is not None else settings.port,
    )
    return 0


def _run_migrate(database_url: str | None) -> int:
    settings = CentralSettings()
    if database_url is not None:
        settings.database_url = database_url
    if not settings.database_url:
        print(
            "central-service: database_url is required (AV_CENTRAL_DATABASE_URL)", file=sys.stderr
        )
        return 1
    migrate_to_head(settings.database_url)
    if not schema_at_head(settings.database_url):
        print("central-service: migration did not reach the schema head", file=sys.stderr)
        return 1
    print("central-service: schema migrations applied and verified")
    return 0


def _run_bootstrap(args: argparse.Namespace) -> int:
    settings = CentralSettings()
    if args.database_url is not None:
        settings.database_url = args.database_url
    if not settings.database_url:
        print(
            "central-service: database_url is required (AV_CENTRAL_DATABASE_URL)", file=sys.stderr
        )
        return 1
    try:
        plan = resolve_plan(
            settings,
            organization_name=args.organization_name,
            site_name=args.site_name,
            line_name=args.line_name,
            device_id=args.device_id,
            device_name=args.device_name,
            device_upload_token=args.device_upload_token,
            admin_username=args.admin_username,
            admin_token=args.admin_token,
        )
    except BootstrapError as exc:
        print(f"central-service: {exc}", file=sys.stderr)
        return 1
    engine = create_database_engine(settings.database_url)
    try:
        outcome = run_bootstrap(CentralRepository(engine), plan)
    finally:
        engine.dispose()
    result = outcome.result
    print("central-service: pilot bootstrap complete")
    print(f"  organization: {plan.organization_name} (id {result.organization_id})")
    print(f"  site: {plan.site_name} (id {result.site_id})")
    print(f"  line: {plan.line_name} (id {result.production_line_id})")
    print(f"  device: {plan.device_id} (row id {result.device_row_id})")
    print(f"  administrator: {plan.admin_username} (id {result.administrator_id})")
    print(f"  created: {', '.join(result.created) or 'none (all rows already existed)'}")
    print("  note: credentials are never printed; provision them via environment or CLI options")
    return 0


def _run_reconcile_media(args: argparse.Namespace) -> int:
    """Compare persisted media bindings against the object store (C2b).

    M1 maintenance command, not a continuous worker: it reports bindings whose
    object is missing and object-store objects without a binding, and
    optionally removes the orphans. Idempotent by design.
    """
    settings = CentralSettings()
    if args.database_url is not None:
        settings.database_url = args.database_url
    if not settings.database_url:
        print(
            "central-service: database_url is required (AV_CENTRAL_DATABASE_URL)", file=sys.stderr
        )
        return 1
    engine = create_database_engine(settings.database_url)
    storage = MinioObjectStorage(
        ObjectStorageSettings(
            endpoint=settings.minio_endpoint,
            access_key=settings.minio_access_key,
            secret_key=settings.minio_secret_key,
            bucket=settings.minio_bucket,
            secure=settings.minio_secure,
        )
    )
    try:
        bindings = CentralRepository(engine).list_media_bindings()
    finally:
        engine.dispose()
    report = reconcile_media(bindings, storage)
    for key in report.missing_objects:
        print(f"missing-object: {key}")
    for key in report.orphan_objects:
        print(f"orphan-object: {key}")
    if args.remove_orphans:
        for key in report.orphan_objects:
            storage.remove_object(key)
            print(f"removed-orphan: {key}")
    print(
        f"reconcile-media: {report.binding_count} bindings, "
        f"{len(report.missing_objects)} missing objects, "
        f"{len(report.orphan_objects)} orphan objects"
    )
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
