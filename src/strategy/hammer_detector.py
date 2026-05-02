import pandas as pd
from typing import List

from src.config import HammerParams
from src.strategy.candle_geometry import compute_geometry
from src.risk.clearing import is_near_clearing


class HammerDetector:
    def __init__(self, params: HammerParams):
        self.p = params

    def detect_all(
        self,
        candles_df: pd.DataFrame,
        instrument: str = "",
        timeframe: str = "",
        profile: str = "",
    ) -> pd.DataFrame:
        df = compute_geometry(candles_df.copy())
        tick = self.p.effective_tick_size
        records = []
        last_signal_bar = -999

        for i in range(len(df)):
            row = df.iloc[i]
            result = self._evaluate_candle(df, i, tick, last_signal_bar)

            if result["is_signal"]:
                last_signal_bar = i

            records.append({
                "timestamp": row["timestamp"],
                "instrument": instrument,
                "timeframe": timeframe,
                "open": row["open"],
                "high": row["high"],
                "low": row["low"],
                "close": row["close"],
                "volume": row["volume"],
                "range": row["range"],
                "body": row["body"],
                "upper_shadow": row["upper_shadow"],
                "lower_shadow": row["lower_shadow"],
                "body_frac": row.get("body_frac"),
                "upper_frac": row.get("upper_frac"),
                "lower_frac": row.get("lower_frac"),
                "close_pos": row.get("close_pos"),
                "direction_candidate": result["direction_candidate"],
                "is_signal": result["is_signal"],
                "fail_reason": result["fail_reason"],
                "fail_reasons": result["fail_reasons"],
                "params_profile": profile,
                "tick_size": tick,
                "tick_size_source": self.p.tick_size_source,
            })

        return pd.DataFrame(records)

    def _evaluate_candle(self, df: pd.DataFrame, i: int, tick: float, last_signal_bar: int) -> dict:
        row = df.iloc[i]
        p = self.p

        def reject(direction, first_reason, all_reasons):
            return {
                "direction_candidate": direction,
                "is_signal": False,
                "fail_reason": first_reason,
                "fail_reasons": "|".join(all_reasons),
            }

        def accept(direction):
            return {
                "direction_candidate": direction,
                "is_signal": True,
                "fail_reason": "pass",
                "fail_reasons": "pass",
            }

        if not row.get("valid_candle", True):
            return reject("none", "invalid_range", ["invalid_range"])

        range_ = row["range"]
        body = row["body"]
        upper_shadow = row["upper_shadow"]
        lower_shadow = row["lower_shadow"]
        body_frac = row["body_frac"]
        close_pos = row["close_pos"]

        # Determine direction candidate
        # BUY hammer: long lower shadow
        # SELL inverted hammer / upper wick: long upper shadow
        if lower_shadow >= upper_shadow:
            direction = "BUY"
            working_wick = lower_shadow
            opposite_wick = upper_shadow
        else:
            direction = "SELL"
            working_wick = upper_shadow
            opposite_wick = lower_shadow

        all_reasons: List[str] = []

        # 1. range filter
        if range_ < p.min_range_ticks * tick:
            all_reasons.append("range")
            return reject(direction, "range", all_reasons)

        # 2. doji
        if body_frac < p.body_min_frac:
            all_reasons.append("doji")
            return reject(direction, "doji", all_reasons)

        # 3. body_big
        if body_frac > p.body_max_frac:
            all_reasons.append("body_big")
            return reject(direction, "body_big", all_reasons)

        # 4. wick_abs
        if working_wick < p.min_wick_ticks * tick:
            all_reasons.append("wick_abs")
            return reject(direction, "wick_abs", all_reasons)

        # 5. opp_abs
        if opposite_wick > p.opp_wick_max_abs_ticks * tick:
            all_reasons.append("opp_abs")
            return reject(direction, "opp_abs", all_reasons)

        # 6. dom_fail: working wick must dominate body and opposite wick
        dom_fail = False
        if working_wick < body * p.wick_mult:
            dom_fail = True
        if working_wick / max(opposite_wick, tick) < p.wick_dom_ratio:
            dom_fail = True
        if dom_fail:
            all_reasons.append("dom_fail")
            return reject(direction, "dom_fail", all_reasons)

        # 7. sil_fail: working wick fraction of candle range
        if working_wick / range_ < p.silhouette_min_frac:
            all_reasons.append("sil_fail")
            return reject(direction, "sil_fail", all_reasons)

        # 8. ext: local extremum check
        ext_window = p.ext_window
        eps = p.ext_eps_ticks * tick
        start = max(0, i - ext_window)
        end = min(len(df) - 1, i + ext_window)

        if direction == "BUY":
            local_lows = df.iloc[start:i]["low"].tolist() + df.iloc[i + 1:end + 1]["low"].tolist()
            if any(l < row["low"] - eps for l in local_lows):
                all_reasons.append("ext")
                return reject(direction, "ext", all_reasons)
        else:
            local_highs = df.iloc[start:i]["high"].tolist() + df.iloc[i + 1:end + 1]["high"].tolist()
            if any(h > row["high"] + eps for h in local_highs):
                all_reasons.append("ext")
                return reject(direction, "ext", all_reasons)

        # 9. neighbors: check immediate neighbors (left or right) are not at the same extremum
        neighbor_eps = p.neighbor_eps_ticks * tick
        if p.neighbor_mode == "left_or_right":
            neighbors = []
            if i > 0:
                neighbors.append(df.iloc[i - 1])
            if i < len(df) - 1:
                neighbors.append(df.iloc[i + 1])

            if direction == "BUY":
                if any(n["low"] <= row["low"] + neighbor_eps and n["low"] < row["low"] for n in neighbors):
                    all_reasons.append("neighbors")
                    return reject(direction, "neighbors", all_reasons)
            else:
                if any(n["high"] >= row["high"] - neighbor_eps and n["high"] > row["high"] for n in neighbors):
                    all_reasons.append("neighbors")
                    return reject(direction, "neighbors", all_reasons)

        # 10. close_pos
        if direction == "BUY":
            if close_pos < p.close_pos_frac:
                all_reasons.append("close_pos")
                return reject(direction, "close_pos", all_reasons)
        else:
            if close_pos > (1 - p.close_pos_frac):
                all_reasons.append("close_pos")
                return reject(direction, "close_pos", all_reasons)

        # 11. excursion: next bars move enough
        excursion_end = min(len(df), i + 1 + p.excursion_horizon)
        future_bars = df.iloc[i + 1:excursion_end]
        if len(future_bars) == 0:
            all_reasons.append("excursion")
            return reject(direction, "excursion", all_reasons)

        if direction == "BUY":
            excursion = future_bars["high"].max() - row["close"]
        else:
            excursion = row["close"] - future_bars["low"].min()

        if excursion < p.min_excursion_ticks * tick:
            all_reasons.append("excursion")
            return reject(direction, "excursion", all_reasons)

        # 12. confirm: next bar breaks signal high/low
        confirm_end = min(len(df), i + 1 + p.confirm_horizon)
        confirm_bars = df.iloc[i + 1:confirm_end]
        if len(confirm_bars) == 0:
            all_reasons.append("confirm")
            return reject(direction, "confirm", all_reasons)

        if direction == "BUY":
            confirmed = confirm_bars["high"].max() > row["high"]
        else:
            confirmed = confirm_bars["low"].min() < row["low"]

        if not confirmed:
            all_reasons.append("confirm")
            return reject(direction, "confirm", all_reasons)

        # 13. clearing filter
        if p.clearing_enable:
            if is_near_clearing(row["timestamp"], p.clearing_block_before_min, p.clearing_block_after_min):
                all_reasons.append("clearing")
                return reject(direction, "clearing", all_reasons)

        # 14. cooldown
        if (i - last_signal_bar) < p.cooldown_bars:
            all_reasons.append("cooldown")
            return reject(direction, "cooldown", all_reasons)

        return accept(direction)
