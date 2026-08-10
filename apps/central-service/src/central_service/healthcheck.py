"""Container health check for the central service (design 05 section 10).

Usage::

    python -m central_service.healthcheck <url>

Exits 0 when the URL responds with a 2xx/3xx status, 1 on any failure, and 2
on misuse, so a Docker ``HEALTHCHECK`` can restart the container without the
check itself logging secrets or stack traces.
"""

from __future__ import annotations

import sys
import urllib.request
from collections.abc import Sequence
from urllib.error import URLError
from urllib.parse import urlsplit

_TIMEOUT_SECONDS = 5.0


def check(url: str) -> bool:
    """Return True when ``url`` responds with a 2xx/3xx status."""
    try:
        parts = urlsplit(url)
        if parts.scheme not in ("http", "https") or not parts.hostname:
            return False
        with urllib.request.urlopen(url, timeout=_TIMEOUT_SECONDS) as response:  # noqa: S310
            return 200 <= int(response.status) < 400
    except (URLError, OSError, ValueError):
        return False


def main(argv: Sequence[str] | None = None) -> int:
    args = list(argv) if argv is not None else sys.argv[1:]
    if len(args) != 1:
        print("usage: python -m central_service.healthcheck <url>", file=sys.stderr)
        return 2
    return 0 if check(args[0]) else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
