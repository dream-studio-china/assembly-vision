"""E5b secrets and TLS tests: secret-file fallback and local TLS validation."""

from __future__ import annotations

import argparse
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
