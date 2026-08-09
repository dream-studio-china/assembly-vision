"""E5a deployment packaging tests: health check and compose template.

Covers the healthcheck module exit codes and the compose deployment template
contract (non-root user, read-only root filesystem, restart policy, health
check, explicit persistent volumes, loopback port binding).
"""

from __future__ import annotations

import http.server
import socketserver
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from assemblyvision_edge.healthcheck import check, main


class _Handler(http.server.BaseHTTPRequestHandler):
    """One-shot responder: 200 for /ok, 500 for /fail."""

    def do_GET(self) -> None:  # noqa: N802 - stdlib handler naming
        status = 200 if self.path == "/ok" else 500
        self.send_response(status)
        self.end_headers()

    def log_message(self, format: str, *args: object) -> None:  # noqa: A002
        pass


@contextmanager
def _http_server() -> Iterator[tuple[str, int]]:
    """Serve the test responder on an ephemeral loopback port."""

    class _Server(socketserver.TCPServer):
        allow_reuse_address = True
        daemon_threads = True

    server = _Server(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield "127.0.0.1", int(server.server_address[1])
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


class TestHealthcheck:
    def test_ok_url_returns_success(self) -> None:
        with _http_server() as (host, port):
            assert check(f"http://{host}:{port}/ok") is True
            assert main([f"http://{host}:{port}/ok"]) == 0

    def test_error_status_is_failure(self) -> None:
        with _http_server() as (host, port):
            assert check(f"http://{host}:{port}/fail") is False
            assert main([f"http://{host}:{port}/fail"]) == 1

    def test_unreachable_url_is_failure(self) -> None:
        assert check("http://127.0.0.1:1/unreachable") is False
        assert main(["http://127.0.0.1:1/unreachable"]) == 1

    def test_missing_url_argument_is_misuse(self) -> None:
        assert main([]) == 2


class TestComposeTemplate:
    def test_template_renders_with_required_contract(self) -> None:
        import yaml

        root = Path(__file__).resolve().parents[3]
        compose = yaml.safe_load((root / "compose.yaml").read_text(encoding="utf-8"))
        service = compose["services"]["edge-service"]
        # Contract 07 §1: non-root, restart policy, explicit volumes.
        assert service["user"] == "10001:10001"
        assert service["read_only"] is True
        assert service["restart"] == "unless-stopped"
        assert service["build"]["dockerfile"] == "apps/edge-service/Dockerfile"
        # Loopback binding and a token are the safe defaults.
        assert service["ports"] == ["127.0.0.1:8000:8000"]
        health = service["healthcheck"]["test"]
        assert any("assemblyvision_edge.healthcheck" in item for item in health)
        volumes = {volume.split(":")[0] for volume in service["volumes"]}
        assert {
            "edge-db",
            "edge-media",
            "edge-config",
            "edge-models",
            "edge-web",
            "edge-tmp",
        } <= volumes
        # The container must not depend on central DNS at startup.
        assert "AV_CENTRAL_URL" not in service.get("environment", {})
