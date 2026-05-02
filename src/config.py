import os
from dataclasses import dataclass
from typing import Optional

from dotenv import dotenv_values


@dataclass
class HammerParams:
    body_min_frac: float = 0.12
    body_max_frac: float = 0.33
    wick_mult: float = 2.3
    opp_wick_max_frac: float = 0.70
    wick_dom_ratio: float = 2.0
    ext_window: int = 5
    ext_eps_ticks: float = 1.0
    neighbor_mode: str = "left_or_right"
    neighbor_eps_ticks: float = 1.0
    min_range_ticks: float = 2.0
    min_wick_ticks: float = 1.5
    opp_wick_max_abs_ticks: float = 2.0
    close_pos_frac: float = 0.60
    silhouette_min_frac: float = 0.45
    min_excursion_ticks: float = 2.0
    excursion_horizon: int = 2
    fallback_tick: float = 0.5
    tick_size: Optional[float] = None
    tick_size_source: str = "fallback"
    clearing_enable: bool = True
    confirm_mode: str = "break"
    confirm_horizon: int = 1
    cooldown_bars: int = 3
    point_value_rub: float = 10.0
    commission_per_trade: float = 0.025
    commission_round_turn: float = 0.05
    clearing_block_before_min: int = 5
    clearing_block_after_min: int = 5
    timezone: str = "Europe/Moscow"

    @property
    def effective_tick_size(self) -> float:
        if self.tick_size is not None:
            return self.tick_size
        return self.fallback_tick


def load_params(env_path: str) -> HammerParams:
    if not os.path.exists(env_path):
        raise FileNotFoundError(f"Config file not found: {env_path}")

    raw = dotenv_values(env_path)

    def _f(key, default):
        return float(raw[key]) if key in raw else default

    def _i(key, default):
        return int(raw[key]) if key in raw else default

    def _s(key, default):
        return raw[key] if key in raw else default

    def _b(key, default):
        return bool(int(raw[key])) if key in raw else default

    return HammerParams(
        body_min_frac=_f("S_BODY_MIN_FRAC", 0.12),
        body_max_frac=_f("S_BODY_MAX_FRAC", 0.33),
        wick_mult=_f("S_WICK_MULT", 2.3),
        opp_wick_max_frac=_f("S_OPP_WICK_MAX_FRAC", 0.70),
        wick_dom_ratio=_f("S_WICK_DOM_RATIO", 2.0),
        ext_window=_i("S_EXT_WINDOW", 5),
        ext_eps_ticks=_f("S_EXT_EPS_TICKS", 1.0),
        neighbor_mode=_s("S_NEIGHBOR_MODE", "left_or_right"),
        neighbor_eps_ticks=_f("S_NEIGHBOR_EPS_TICKS", 1.0),
        min_range_ticks=_f("S_MIN_RANGE_TICKS", 2.0),
        min_wick_ticks=_f("S_MIN_WICK_TICKS", 1.5),
        opp_wick_max_abs_ticks=_f("S_OPP_WICK_MAX_ABS_TICKS", 2.0),
        close_pos_frac=_f("S_CLOSE_POS_FRAC", 0.60),
        silhouette_min_frac=_f("S_SILHOUETTE_MIN_FRAC", 0.45),
        min_excursion_ticks=_f("S_MIN_EXCURSION_TICKS", 2.0),
        excursion_horizon=_i("S_EXCURSION_HORIZON", 2),
        fallback_tick=_f("S_FALLBACK_TICK", 0.5),
        clearing_enable=_b("S_CLEARING_ENABLE", True),
        confirm_mode=_s("S_CONFIRM_MODE", "break"),
        confirm_horizon=_i("S_CONFIRM_HORIZON", 1),
        cooldown_bars=_i("S_COOLDOWN_BARS", 3),
        point_value_rub=_f("POINT_VALUE_RUB", 10.0),
        commission_per_trade=_f("COMMISSION_PER_TRADE", 0.025),
        commission_round_turn=_f("COMMISSION_ROUND_TURN", 0.05),
        clearing_block_before_min=_i("CLEARING_BLOCK_BEFORE_MIN", 5),
        clearing_block_after_min=_i("CLEARING_BLOCK_AFTER_MIN", 5),
        timezone=_s("TIMEZONE", "Europe/Moscow"),
    )
