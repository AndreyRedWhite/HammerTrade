#!/usr/bin/env bash
# Build an isolated CA bundle combining system CAs + Russian Trusted Root CA.
# Used only for the HammerTrade process — never modifies the system trust store.
set -euo pipefail

RUSSIAN_ROOT_CA=""
OUTPUT=""

usage() {
    cat <<EOF
Usage: bash scripts/build_tbank_ca_bundle.sh \\
         --russian-root-ca <path/to/russian-trusted-root-ca.crt> \\
         --output <path/to/tbank-combined-ca.pem>

Combines the system CA bundle with the supplied Russian Trusted Root CA file
into an isolated PEM bundle for use by the HammerTrade process only.

Does NOT modify the system trust store. Requires no sudo.

Options:
  --russian-root-ca PATH    Path to Russian Trusted Root CA certificate (.crt / .pem)
  --output PATH             Destination path for combined CA bundle (.pem)
  --help                    Show this help
EOF
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --russian-root-ca) RUSSIAN_ROOT_CA="$2"; shift 2 ;;
        --output)          OUTPUT="$2"; shift 2 ;;
        --help|-h)         usage; exit 0 ;;
        *) echo "Unknown argument: $1" >&2; usage; exit 1 ;;
    esac
done

if [[ -z "$RUSSIAN_ROOT_CA" || -z "$OUTPUT" ]]; then
    echo "ERROR: --russian-root-ca and --output are required." >&2
    usage
    exit 1
fi

# Find system CA bundle
SYSTEM_CA=""
for candidate in \
    /etc/ssl/certs/ca-certificates.crt \
    /etc/pki/tls/certs/ca-bundle.crt \
    /etc/ssl/cert.pem; do
    if [[ -f "$candidate" ]]; then
        SYSTEM_CA="$candidate"
        break
    fi
done

if [[ -z "$SYSTEM_CA" ]]; then
    echo "ERROR: System CA bundle not found. Tried:" >&2
    echo "  /etc/ssl/certs/ca-certificates.crt" >&2
    echo "  /etc/pki/tls/certs/ca-bundle.crt" >&2
    echo "  /etc/ssl/cert.pem" >&2
    exit 1
fi

if [[ ! -f "$RUSSIAN_ROOT_CA" ]]; then
    echo "ERROR: Russian Root CA file not found: $RUSSIAN_ROOT_CA" >&2
    exit 1
fi

OUTPUT_DIR="$(dirname "$OUTPUT")"
mkdir -p "$OUTPUT_DIR"

echo "System CA bundle : $SYSTEM_CA"
echo "Russian Root CA  : $RUSSIAN_ROOT_CA"
echo "Output           : $OUTPUT"

cat "$SYSTEM_CA" > "$OUTPUT"
echo "" >> "$OUTPUT"
cat "$RUSSIAN_ROOT_CA" >> "$OUTPUT"

chmod 640 "$OUTPUT"

echo "Done. Combined CA bundle written to: $OUTPUT"
echo ""
echo "To use only for HammerTrade process, add to .env:"
echo "  GRPC_DEFAULT_SSL_ROOTS_FILE_PATH=$OUTPUT"
echo "  SSL_CERT_FILE=$OUTPUT"
echo "  REQUESTS_CA_BUNDLE=$OUTPUT"
