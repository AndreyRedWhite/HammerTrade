import pytest
from src.config import HammerParams


def test_effective_tick_uses_tick_size():
    p = HammerParams(tick_size=0.01)
    assert p.effective_tick_size == pytest.approx(0.01)


def test_effective_tick_fallback_when_none():
    p = HammerParams(fallback_tick=0.5, tick_size=None)
    assert p.effective_tick_size == pytest.approx(0.5)


def test_effective_tick_custom_fallback():
    p = HammerParams(fallback_tick=1.0, tick_size=None)
    assert p.effective_tick_size == pytest.approx(1.0)


def test_tick_size_overrides_fallback():
    p = HammerParams(fallback_tick=0.5, tick_size=0.01)
    assert p.effective_tick_size == pytest.approx(0.01)


def test_tick_size_source_default():
    p = HammerParams()
    assert p.tick_size_source == "fallback"


def test_tick_size_source_can_be_set():
    p = HammerParams(tick_size=0.01, tick_size_source="specs")
    assert p.tick_size_source == "specs"


def test_min_range_abs_uses_effective_tick():
    p = HammerParams(min_range_ticks=2.0, tick_size=0.01)
    expected = 2.0 * 0.01
    assert p.min_range_ticks * p.effective_tick_size == pytest.approx(expected)


def test_min_range_abs_with_fallback():
    p = HammerParams(min_range_ticks=2.0, fallback_tick=0.5, tick_size=None)
    expected = 2.0 * 0.5
    assert p.min_range_ticks * p.effective_tick_size == pytest.approx(expected)
