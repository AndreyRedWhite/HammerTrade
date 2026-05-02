import os
from contextlib import contextmanager

_SDK_INSTALL_HINT = (
    "T-Bank SDK is not installed. Install it with:\n"
    "pip install t-tech-investments "
    "--index-url https://opensource.tbank.ru/api/v4/projects/238/packages/pypi/simple"
)


def _require_sdk():
    try:
        import t_tech.invest  # noqa: F401
    except ImportError:
        raise ImportError(_SDK_INSTALL_HINT)


def _build_ca_bundle() -> bytes:
    """Assemble root CA bundle: certifi defaults + optional TBANK_CA_BUNDLE."""
    parts = []

    # Base: certifi standard bundle (includes most public CAs)
    try:
        import certifi
        with open(certifi.where(), "rb") as f:
            parts.append(f.read())
    except Exception:
        pass  # certifi not available — grpc will use its own defaults

    # Extra: user-supplied CA bundle (e.g. Russian Минцифры cert)
    extra = os.getenv("TBANK_CA_BUNDLE", "").strip()
    if extra and os.path.exists(extra):
        with open(extra, "rb") as f:
            parts.append(f.read())

    return b"\n".join(parts) if parts else b""


def _patch_ssl() -> None:
    """Patch t_tech.invest.clients.create_channel to use a custom CA bundle.

    The SDK hardcodes grpc.ssl_channel_credentials() without root_certificates,
    which excludes the Russian CA used by invest-public-api.tbank.ru.
    We replace the local reference in the clients module before Client() is called.
    """
    import grpc
    import t_tech.invest.channels as _ch_module
    import t_tech.invest.clients as _cl_module

    root_certs = _build_ca_bundle()
    if not root_certs:
        return  # nothing we can do; grpc uses its own bundle

    # Capture required options from channels module
    _required_options = _ch_module._required_options
    _with_options = _ch_module._with_options
    INVEST_GRPC_API = _ch_module.INVEST_GRPC_API

    def _patched_create_channel(
        *,
        target=None,
        options=None,
        force_async=False,
        compression=None,
        interceptors=None,
    ):
        creds = grpc.ssl_channel_credentials(root_certificates=root_certs)
        target = target or INVEST_GRPC_API
        if options is None:
            options = []
        options = _with_options(options, _required_options)
        args = (target, creds, options, compression)
        if force_async:
            return grpc.aio.secure_channel(*args, interceptors=interceptors)
        return grpc.secure_channel(*args)

    # Patch both the module and the local binding in clients.py
    _ch_module.create_channel = _patched_create_channel
    _cl_module.create_channel = _patched_create_channel


@contextmanager
def get_tbank_client(settings):
    _require_sdk()
    _patch_ssl()

    from t_tech.invest import Client

    with Client(token=settings.token, target=settings.target) as client:
        yield client
