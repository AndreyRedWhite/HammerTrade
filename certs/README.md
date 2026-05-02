# Certificates

This directory is for local runtime CA bundles only.

Do not commit real CA certificates or combined CA bundles.

On servers where T-Bank API is served via Russian Trusted Root CA, create a local combined
CA bundle and point **only the HammerTrade process** to it via environment variables:

```
GRPC_DEFAULT_SSL_ROOTS_FILE_PATH=/opt/hammertrade/certs/tbank-combined-ca.pem
SSL_CERT_FILE=/opt/hammertrade/certs/tbank-combined-ca.pem
REQUESTS_CA_BUNDLE=/opt/hammertrade/certs/tbank-combined-ca.pem
```

Build the bundle with:

```bash
bash scripts/build_tbank_ca_bundle.sh \
  --russian-root-ca /opt/hammertrade/certs/russian-trusted-root-ca.crt \
  --output /opt/hammertrade/certs/tbank-combined-ca.pem
```

Do not install Russian Trusted Root CA globally with `update-ca-certificates`.
Do not disable TLS verification.
Do not use this server for personal browsing or unrelated services.
