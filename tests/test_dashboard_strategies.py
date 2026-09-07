import base64

import pytest

pytest.importorskip("flask")

import src.dashboard.app as dashboard


def _auth(user="reader", password="secret"):
    token = base64.b64encode(f"{user}:{password}".encode()).decode()
    return {"Authorization": f"Basic {token}"}


def _client(monkeypatch):
    monkeypatch.setenv("DASHBOARD_USER", "reader")
    monkeypatch.setenv("DASHBOARD_PASS", "secret")
    return dashboard.create_app().test_client()


def test_strategy_catalog_is_protected_and_lists_all_descriptions(monkeypatch):
    client = _client(monkeypatch)
    assert client.get("/strategies").status_code == 401

    response = client.get("/strategies", headers=_auth())

    assert response.status_code == 200
    text = response.get_data(as_text=True)
    assert "Стратегии HammerTrade" in text
    assert "Perpetual funding carry" in text
    assert "Cross-sectional momentum 6–1" in text
    assert len(dashboard.STRATEGY_CATALOG) == 9


def test_strategy_detail_shows_explanation_and_related_service(monkeypatch):
    client = _client(monkeypatch)
    monkeypatch.setattr(
        dashboard,
        "_build_rows",
        lambda base, now: ([{
            "strategy_slug": "orb",
            "unit": "sandbox-orb-v2",
            "active": "active",
            "instr": "IMOEXF",
            "dir": "BOTH",
        }], []),
    )

    response = client.get("/strategies/orb", headers=_auth())

    assert response.status_code == 200
    text = response.get_data(as_text=True)
    assert "Как входит" in text
    assert "Где может сломаться" in text
    assert "sandbox-orb-v2 — active" in text
    assert client.get("/strategies/no-such-strategy", headers=_auth()).status_code == 404


def test_service_strategy_mapping_and_main_link():
    assert dashboard._strategy_slug("hammertrade-sandbox-xsec-momentum.service") == "xsec-momentum"
    assert dashboard._strategy_slug("hammertrade-paper-vwap-siu6.service") == "vwap-reversion"
    assert dashboard._strategy_slug("hammertrade-paper-orb-mxu6.service") == "orb"
    assert dashboard._strategy_slug("hammertrade-paper-long.service") == "hammer"
    assert dashboard._strategy_link("sandbox-orb-v2") == (
        "<a class='strategy-link' href='/strategies/orb'>sandbox-orb-v2</a>"
    )
