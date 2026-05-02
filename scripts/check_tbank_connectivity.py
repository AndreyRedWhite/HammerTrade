"""Check TLS/gRPC connectivity to T-Bank Invest API without live trading."""
import argparse
import os
import socket
import ssl
import sys
from pathlib import Path

HOST = "invest-public-api.tbank.ru"
PORT = 443


def _check_dns() -> tuple[bool, str]:
    try:
        addrs = socket.getaddrinfo(HOST, PORT, type=socket.SOCK_STREAM)
        ip = addrs[0][4][0]
        return True, ip
    except OSError as e:
        return False, str(e)


def _check_tls(ca_bundle: str | None) -> tuple[bool, str]:
    try:
        ctx = ssl.create_default_context(cafile=ca_bundle)
        with socket.create_connection((HOST, PORT), timeout=10) as raw:
            with ctx.wrap_socket(raw, server_hostname=HOST):
                pass
        return True, ""
    except ssl.SSLCertVerificationError as e:
        return False, str(e)
    except OSError as e:
        return False, str(e)


def _check_sdk(ca_bundle: str | None) -> tuple[bool, str]:
    token = os.environ.get("READONLY_TOKEN", "")
    if not token:
        return None, "READONLY_TOKEN not found, skipping SDK check."

    try:
        import t_tech.invest  # noqa: F401
    except ImportError:
        return None, (
            "t-tech-investments not installed, skipping SDK check. "
            "Install with: pip install t-tech-investments "
            "--extra-index-url https://opensource.tbank.ru/api/v4/projects/238/packages/pypi/simple"
        )

    try:
        from src.tbank.settings import load_tbank_settings
        from src.tbank.client import get_tbank_client

        settings = load_tbank_settings("prod")
        with get_tbank_client(settings) as client:
            resp = client.instruments.find_instrument(query="SiM6")
        found = len(resp.instruments) > 0
        detail = f"find_instrument('SiM6') → {len(resp.instruments)} result(s)"
        return found, detail
    except Exception as e:
        return False, str(e)


def main():
    p = argparse.ArgumentParser(description="Check T-Bank API connectivity")
    p.add_argument("--ca-bundle", default=None,
                   help="Path to combined CA bundle PEM file")
    args = p.parse_args()

    ca_bundle = args.ca_bundle or os.environ.get("GRPC_DEFAULT_SSL_ROOTS_FILE_PATH") or None

    print("T-Bank connectivity check")
    print("=========================")
    print()

    if ca_bundle:
        if not Path(ca_bundle).exists():
            print(f"ERROR: CA bundle not found: {ca_bundle}", file=sys.stderr)
            sys.exit(1)
        print(f"CA bundle: {ca_bundle}")
        print()

    overall = True

    # DNS
    ok, detail = _check_dns()
    if ok:
        print(f"DNS : PASS  {HOST} -> {detail}")
    else:
        print(f"DNS : FAIL  {detail}")
        overall = False

    # TLS
    ok, detail = _check_tls(ca_bundle)
    if ok:
        print("TLS : PASS")
    else:
        print(f"TLS : FAIL  {detail}")
        overall = False

    # SDK (optional)
    ok, detail = _check_sdk(ca_bundle)
    if ok is None:
        print(f"SDK : SKIP  {detail}")
    elif ok:
        print(f"SDK : PASS  {detail}")
    else:
        print(f"SDK : FAIL  {detail}")
        overall = False

    print()
    if overall:
        print("Result: PASS")
    else:
        print("Result: FAIL")
        sys.exit(1)


if __name__ == "__main__":
    main()
