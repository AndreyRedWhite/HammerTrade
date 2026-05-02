from src.pipeline.run_id import build_run_id


def test_run_id_all_no_suffix():
    rid = build_run_id("SiM6", "1m", "2026-03-01", "2026-04-10", "balanced", direction_filter="all")
    assert rid == "SiM6_1m_2026-03-01_2026-04-10_balanced"


def test_run_id_default_direction_no_suffix():
    rid = build_run_id("SiM6", "1m", "2026-03-01", "2026-04-10", "balanced")
    assert rid == "SiM6_1m_2026-03-01_2026-04-10_balanced"


def test_run_id_sell_adds_suffix():
    rid = build_run_id("SiM6", "1m", "2026-03-01", "2026-04-10", "balanced", direction_filter="SELL")
    assert rid == "SiM6_1m_2026-03-01_2026-04-10_balanced_SELL"


def test_run_id_buy_adds_suffix():
    rid = build_run_id("SiM6", "1m", "2026-03-01", "2026-04-10", "balanced", direction_filter="BUY")
    assert rid == "SiM6_1m_2026-03-01_2026-04-10_balanced_BUY"


def test_run_id_sell_different_from_all():
    all_id = build_run_id("BRM6", "1m", "2026-03-01", "2026-04-10", "balanced", direction_filter="all")
    sell_id = build_run_id("BRM6", "1m", "2026-03-01", "2026-04-10", "balanced", direction_filter="SELL")
    assert all_id != sell_id


def test_run_id_buy_different_from_sell():
    buy_id = build_run_id("SiM6", "1m", "2026-03-01", "2026-04-10", "balanced", direction_filter="BUY")
    sell_id = build_run_id("SiM6", "1m", "2026-03-01", "2026-04-10", "balanced", direction_filter="SELL")
    assert buy_id != sell_id
