"""E5b secrets and TLS tests: secret-file fallback and local TLS validation."""

from __future__ import annotations

import argparse
import shutil
import subprocess
from pathlib import Path

import pytest
from assemblyvision_domain.errors import ConfigError
from assemblyvision_edge import cli


class TestSecretFileFallback:
    def test_environment_wins_over_secret_file(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(cli, "_SECRET_DIR", tmp_path)
        (tmp_path / "edge_api_token").write_text("file-token", encoding="utf-8")
        monkeypatch.setenv("AV_EDGE_API_TOKEN", "env-token")
        assert cli._secret_env("AV_EDGE_API_TOKEN", "edge_api_token") == "env-token"

    def test_secret_file_is_used_when_env_is_unset(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(cli, "_SECRET_DIR", tmp_path)
        (tmp_path / "edge_upload_token").write_text("file-upload", encoding="utf-8")
        monkeypatch.delenv("AV_EDGE_UPLOAD_TOKEN", raising=False)
        assert cli._secret_env("AV_EDGE_UPLOAD_TOKEN", "edge_upload_token") == "file-upload"

    def test_missing_secret_returns_none(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(cli, "_SECRET_DIR", tmp_path)
        monkeypatch.delenv("AV_EDGE_API_TOKEN", raising=False)
        assert cli._secret_env("AV_EDGE_API_TOKEN", "edge_api_token") is None

    def test_unreadable_secret_fails_closed(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(cli, "_SECRET_DIR", tmp_path)
        secret = tmp_path / "edge_api_token"
        secret.write_text("token", encoding="utf-8")
        secret.chmod(0o000)
        monkeypatch.delenv("AV_EDGE_API_TOKEN", raising=False)
        try:
            with pytest.raises(ConfigError, match="cannot read secret file"):
                cli._secret_env("AV_EDGE_API_TOKEN", "edge_api_token")
        finally:
            secret.chmod(0o600)


class TestTlsValidation:
    def test_missing_pair_fails_closed(self, tmp_path: Path) -> None:
        cert = tmp_path / "cert.pem"
        cert.write_text("cert", encoding="utf-8")
        with pytest.raises(ConfigError, match="existing files"):
            cli._validate_tls_files(cert, tmp_path / "missing-key.pem")

    def test_world_readable_key_is_rejected(self, tmp_path: Path) -> None:
        cert = tmp_path / "cert.pem"
        key = tmp_path / "key.pem"
        cert.write_text("cert", encoding="utf-8")
        key.write_text("key", encoding="utf-8")
        key.chmod(0o644)
        with pytest.raises(ConfigError, match="not be readable by group or others"):
            cli._validate_tls_files(cert, key)

    @pytest.mark.skipif(
        subprocess.run(["openssl", "version"], capture_output=True).returncode != 0,
        reason="openssl is required to generate a real certificate pair",
    )
    def test_matching_pair_passes_and_mismatch_is_rejected(self, tmp_path: Path) -> None:
        cert = tmp_path / "cert.pem"
        key = tmp_path / "key.pem"
        other_key = tmp_path / "other-key.pem"
        subprocess.run(
            [
                "openssl",
                "req",
                "-new",
                "-newkey",
                "rsa:2048",
                "-nodes",
                "-x509",
                "-days",
                "1",
                "-subj",
                "/CN=edge-test",
                "-keyout",
                str(key),
                "-out",
                str(cert),
            ],
            check=True,
            capture_output=True,
        )
        subprocess.run(
            ["openssl", "genrsa", "-out", str(other_key), "2048"],
            check=True,
            capture_output=True,
        )
        key.chmod(0o600)
        other_key.chmod(0o600)
        # The matching pair validates.
        cli._validate_tls_files(cert, key)
        # A different private key is rejected.
        with pytest.raises(ConfigError, match="mismatched"):
            cli._validate_tls_files(cert, other_key)


class TestServeTlsPairing:
    def test_single_tls_flag_is_rejected(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("AV_EDGE_TLS_CERT", raising=False)
        monkeypatch.delenv("AV_EDGE_TLS_KEY", raising=False)
        args = argparse.Namespace(tls_cert=tmp_path / "cert.pem", tls_key=None)
        with pytest.raises(ConfigError, match="provided together"):
            cli._resolve_tls_files(args)

    def test_serve_parser_declares_both_tls_flags(self, tmp_path: Path) -> None:
        """The serve subparser must accept both --tls-cert and --tls-key."""
        parser = cli.build_parser()
        args = parser.parse_args(
            [
                "serve",
                "--output",
                str(tmp_path / "out"),
                "--tls-cert",
                "/run/secrets/cert.pem",
                "--tls-key",
                "/run/secrets/key.pem",
            ]
        )
        assert args.tls_cert == Path("/run/secrets/cert.pem")
        assert args.tls_key == Path("/run/secrets/key.pem")


class TestTlsServeIntegration:
    @pytest.mark.skipif(not shutil.which("openssl"), reason="openssl is required")
    def test_tls_serve_accepts_https_requests(self, tmp_path: Path) -> None:
        """A TLS-enabled serve must accept real HTTPS requests (E5b)."""
        import socket
        import ssl
        import threading
        import time
        import urllib.request

        import uvicorn
        from assemblyvision_edge.api.app import create_app
        from assemblyvision_edge.api.settings import ServerSettings

        cert = tmp_path / "cert.pem"
        key = tmp_path / "key.pem"
        subprocess.run(
            [
                "openssl",
                "req",
                "-new",
                "-newkey",
                "rsa:2048",
                "-nodes",
                "-x509",
                "-days",
                "1",
                "-subj",
                "/CN=edge-test",
                "-keyout",
                str(key),
                "-out",
                str(cert),
            ],
            check=True,
            capture_output=True,
        )
        key.chmod(0o600)

        output = tmp_path / "out"
        output.mkdir()
        settings = ServerSettings(
            output_root=output,
            db_path=output / "edge.sqlite3",
            api_token="dev-token",  # noqa: S106 - test fixture credential
        )
        app = create_app(settings)
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))
            port = int(probe.getsockname()[1])

        config = uvicorn.Config(
            app,
            host="127.0.0.1",
            port=port,
            log_level="error",
            ssl_certfile=str(cert),
            ssl_keyfile=str(key),
        )
        server = uvicorn.Server(config)
        thread = threading.Thread(target=server.run, daemon=True)
        thread.start()
        context = ssl.create_default_context()
        context.check_hostname = False
        context.verify_mode = ssl.CERT_NONE
        try:
            deadline = time.monotonic() + 20
            while time.monotonic() < deadline and not server.started:
                time.sleep(0.05)
            assert server.started, "TLS-enabled serve did not start"
            with urllib.request.urlopen(
                f"https://127.0.0.1:{port}/api/v1/health/live",
                timeout=5,
                context=context,
            ) as response:
                assert response.status == 200
            # The TLS port must not answer plaintext HTTP.
            with pytest.raises((OSError, ValueError)):
                urllib.request.urlopen(f"http://127.0.0.1:{port}/api/v1/health/live", timeout=2)
        finally:
            server.should_exit = True
            thread.join(timeout=10)
