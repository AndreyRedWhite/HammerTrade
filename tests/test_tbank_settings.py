import os
import pytest
from unittest.mock import patch


def _load(env, env_vars):
    with patch.dict(os.environ, env_vars, clear=False):
        from src.tbank.settings import load_tbank_settings
        return load_tbank_settings(env)


def test_prod_reads_readonly_token():
    settings = _load("prod", {"READONLY_TOKEN": "test_readonly", "SANDBOX_TOKEN": ""})
    assert settings.token == "test_readonly"
    assert settings.env == "prod"
    assert "invest-public-api.tbank.ru" in settings.target


def test_sandbox_reads_sandbox_token():
    settings = _load("sandbox", {"SANDBOX_TOKEN": "test_sandbox", "READONLY_TOKEN": ""})
    assert settings.token == "test_sandbox"
    assert settings.env == "sandbox"
    assert "sandbox" in settings.target


def test_prod_missing_token_raises():
    with patch.dict(os.environ, {"READONLY_TOKEN": ""}, clear=False):
        from src.tbank.settings import load_tbank_settings
        with pytest.raises(ValueError, match="READONLY_TOKEN"):
            load_tbank_settings("prod")


def test_sandbox_missing_token_raises():
    with patch.dict(os.environ, {"SANDBOX_TOKEN": ""}, clear=False):
        from src.tbank.settings import load_tbank_settings
        with pytest.raises(ValueError, match="SANDBOX_TOKEN"):
            load_tbank_settings("sandbox")


def test_unknown_env_raises():
    with patch.dict(os.environ, {"READONLY_TOKEN": "x"}, clear=False):
        from src.tbank.settings import load_tbank_settings
        with pytest.raises(ValueError, match="Unknown env"):
            load_tbank_settings("live")


def test_settings_frozen():
    settings = _load("prod", {"READONLY_TOKEN": "tok"})
    with pytest.raises(Exception):
        settings.token = "hacked"


def test_readonly_token_present_flag():
    settings = _load("prod", {"READONLY_TOKEN": "tok", "SANDBOX_TOKEN": "sb"})
    assert settings.readonly_token_present is True
    assert settings.sandbox_token_present is True
