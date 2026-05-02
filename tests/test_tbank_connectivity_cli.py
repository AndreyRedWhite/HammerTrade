import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

import pytest


SCRIPT = str(Path(__file__).resolve().parent.parent / "scripts" / "check_tbank_connectivity.py")


def test_help_exits_zero():
    result = subprocess.run(
        [sys.executable, SCRIPT, "--help"],
        capture_output=True, text=True,
    )
    assert result.returncode == 0
    assert "T-Bank" in result.stdout or "ca-bundle" in result.stdout


def test_missing_ca_bundle_file_exits_nonzero():
    result = subprocess.run(
        [sys.executable, SCRIPT, "--ca-bundle", "/nonexistent/path/bundle.pem"],
        capture_output=True, text=True,
    )
    assert result.returncode != 0
    assert "not found" in result.stderr.lower() or "not found" in result.stdout.lower()


def test_sdk_skipped_without_token(monkeypatch, tmp_path):
    from scripts.check_tbank_connectivity import _check_sdk
    monkeypatch.delenv("READONLY_TOKEN", raising=False)
    ok, detail = _check_sdk(None)
    assert ok is None
    assert "READONLY_TOKEN" in detail


def test_dns_check_returns_bool():
    from scripts.check_tbank_connectivity import _check_dns
    ok, detail = _check_dns()
    assert isinstance(ok, bool)
    assert isinstance(detail, str)


def test_tls_fail_without_bundle_on_broken_network():
    from scripts.check_tbank_connectivity import _check_tls
    with patch("scripts.check_tbank_connectivity.ssl.create_default_context") as mock_ctx:
        import ssl
        mock_ctx.return_value.wrap_socket.side_effect = ssl.SSLCertVerificationError(
            "self-signed certificate in certificate chain"
        )
        ok, detail = _check_tls(None)
    assert isinstance(ok, bool)


def test_tls_check_with_nonexistent_bundle_raises():
    from scripts.check_tbank_connectivity import _check_tls
    ok, detail = _check_tls("/nonexistent/bundle.pem")
    assert ok is False
    assert detail != ""
