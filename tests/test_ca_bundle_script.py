import subprocess
from pathlib import Path

import pytest

SCRIPT = str(Path(__file__).resolve().parent.parent / "scripts" / "build_tbank_ca_bundle.sh")


def test_script_syntax_valid():
    result = subprocess.run(["bash", "-n", SCRIPT], capture_output=True, text=True)
    assert result.returncode == 0, f"Syntax error: {result.stderr}"


def test_help_exits_zero():
    result = subprocess.run(["bash", SCRIPT, "--help"], capture_output=True, text=True)
    assert result.returncode == 0
    assert "--russian-root-ca" in result.stdout
    assert "--output" in result.stdout


def test_missing_args_exits_nonzero():
    result = subprocess.run(["bash", SCRIPT], capture_output=True, text=True)
    assert result.returncode != 0
    assert "required" in result.stderr.lower() or "required" in result.stdout.lower()


def test_missing_russian_ca_file_exits_nonzero(tmp_path):
    result = subprocess.run(
        ["bash", SCRIPT,
         "--russian-root-ca", str(tmp_path / "nonexistent.crt"),
         "--output", str(tmp_path / "bundle.pem")],
        capture_output=True, text=True,
    )
    assert result.returncode != 0
    assert "not found" in result.stderr.lower() or "not found" in result.stdout.lower()


def test_builds_bundle_successfully(tmp_path):
    fake_ca = tmp_path / "fake-russian-root-ca.crt"
    fake_ca.write_text("-----BEGIN CERTIFICATE-----\nZmFrZQ==\n-----END CERTIFICATE-----\n")

    import platform
    system_ca_candidates = [
        "/etc/ssl/certs/ca-certificates.crt",
        "/etc/pki/tls/certs/ca-bundle.crt",
        "/etc/ssl/cert.pem",
    ]
    system_ca = next((p for p in system_ca_candidates if Path(p).exists()), None)
    if system_ca is None:
        pytest.skip("No system CA bundle found on this machine")

    output = tmp_path / "tbank-combined-ca.pem"
    result = subprocess.run(
        ["bash", SCRIPT,
         "--russian-root-ca", str(fake_ca),
         "--output", str(output)],
        capture_output=True, text=True,
    )
    assert result.returncode == 0, f"Script failed: {result.stderr}"
    assert output.exists()
    content = output.read_text()
    assert "BEGIN CERTIFICATE" in content
    assert "ZmFrZQ==" in content
