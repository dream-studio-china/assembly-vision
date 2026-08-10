"""Command-line interface for the central server.

Subcommands:
- ``serve``: run the FastAPI application (settings from ``AV_CENTRAL_*`` env).
- ``migrate``: apply pending schema migrations - a controlled release step
  that is never executed by the API process itself.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence

from central_service.api.app import create_app
from central_service.api.settings import CentralSettings
from central_service.persistence.migrate import migrate_to_head, schema_at_head


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

    args = parser.parse_args(list(argv) if argv is not None else None)
    try:
        if args.command == "migrate":
            return _run_migrate(args.database_url)
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


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
