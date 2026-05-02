import os
from dataclasses import dataclass
from dotenv import load_dotenv

PROD_TARGET_DEFAULT = "invest-public-api.tbank.ru:443"
SANDBOX_TARGET_DEFAULT = "sandbox-invest-public-api.tbank.ru:443"


@dataclass(frozen=True)
class TBankSettings:
    env: str
    token: str
    target: str
    readonly_token_present: bool
    sandbox_token_present: bool


def load_tbank_settings(env: str = "prod") -> TBankSettings:
    load_dotenv()

    if env not in ("prod", "sandbox"):
        raise ValueError(f"Unknown env '{env}'. Allowed values: prod, sandbox")

    readonly_token = os.getenv("READONLY_TOKEN", "")
    sandbox_token = os.getenv("SANDBOX_TOKEN", "")

    if env == "prod":
        token = readonly_token
        target = os.getenv("TBANK_PROD_TARGET", PROD_TARGET_DEFAULT)
        if not token:
            raise ValueError(
                "READONLY_TOKEN is not set. Add it to your .env file.\n"
                "This token provides read-only access to market data."
            )
    else:
        token = sandbox_token
        target = os.getenv("TBANK_SANDBOX_TARGET", SANDBOX_TARGET_DEFAULT)
        if not token:
            raise ValueError(
                "SANDBOX_TOKEN is not set. Add it to your .env file."
            )

    return TBankSettings(
        env=env,
        token=token,
        target=target,
        readonly_token_present=bool(readonly_token),
        sandbox_token_present=bool(sandbox_token),
    )
