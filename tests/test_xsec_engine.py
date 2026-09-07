"""Проверки кросс-секционного движка на синтетике.

Смысл этих тестов — не «код не падает», а доказательство трёх свойств, ошибка в
любом из которых даёт фантомный край, неотличимый на глаз от настоящего:

  1. движок СПОСОБЕН выразить край (иначе отрицательный результат ничего не
     доказывает — он мог бы быть артефактом сломанного движка);
  2. движок НЕ даёт края на информации, которая к моменту сделки уже устарела
     (off-by-one в исполнении);
  3. издержки считаются от фактического оборота.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from src.research.xsec.engine import Config, run
from src.research.xsec.panel import Panel

N_DAYS = 2000
N_NAMES = 30
SEED = 20260729


def _synthetic_panel(seed: int = SEED) -> Panel:
    """Синтетика, в которой open→open доходности НЕЗАВИСИМЫ между собой.

    Первичным рядом взято ОТКРЫТИЕ (чистое случайное блуждание), закрытие
    выведено из него внутридневным шумом. Порядок важен: если сделать наоборот
    (open = close[t-1]·(1+gap)), то ret_oo механически зависит от gap[t-1] с
    отрицательным знаком, и тесты начинают ловить артефакт генератора вместо
    свойств движка.
    """
    rng = np.random.default_rng(seed)
    dates = pd.bdate_range("2018-01-01", periods=N_DAYS)
    names = [f"S{i:02d}" for i in range(N_NAMES)]

    oo = pd.DataFrame(rng.normal(0.0, 0.02, (N_DAYS, N_NAMES)), index=dates, columns=names)
    open_ = 100.0 * (1.0 + oo).cumprod()
    intraday = pd.DataFrame(rng.normal(0.0, 0.01, (N_DAYS, N_NAMES)), index=dates, columns=names)
    close = open_ * (1.0 + intraday)

    value = pd.DataFrame(1e9, index=dates, columns=names)
    tradable = pd.DataFrame(True, index=dates, columns=names)
    div = pd.DataFrame(0.0, index=dates, columns=names)

    ret_cc = close / close.shift(1) - 1.0
    ret_oo = open_ / open_.shift(1) - 1.0
    bench = pd.DataFrame({"IMOEX": close.mean(axis=1)}, index=dates)

    return Panel(open=open_, close=close, value=value, tradable=tradable, div=div,
                 ret_cc=ret_cc, ret_oo=ret_oo, bench=bench)


def _sharpe(res) -> float:
    r = res.ret
    r = r[r.ne(0)]
    return float(r.mean() / r.std() * np.sqrt(252)) if len(r) > 2 and r.std() > 0 else 0.0


@pytest.fixture(scope="module")
def panel() -> Panel:
    return _synthetic_panel()


def test_null_signal_gives_no_edge(panel):
    """Шум обязан давать ~ноль. Движок, дающий край на шуме, не доказывает ничего."""
    rng = np.random.default_rng(1)
    sharpes = []
    for _ in range(5):
        noise = pd.DataFrame(rng.standard_normal(panel.close.shape),
                             index=panel.dates, columns=panel.tickers)
        sharpes.append(_sharpe(run(panel, noise, Config(cost_bps_per_side=0.0, short_q=0.2))))
    assert max(abs(s) for s in sharpes) < 1.0, f"край на шуме: {sharpes}"


def test_engine_can_express_an_edge(panel):
    """Сигнал, знающий доходность СВОЕГО интервала владения, обязан заработать.

    Веса, выставленные по сигналу дня r, зарабатывают ret_oo[r+delay+1].
    Ребаланс ежедневный: при месячном оракул угадывает только первый день из
    ~21, и его край размывается стоянием в устаревших весах — это свойство
    расписания, а не движка.

    Тест на дееспособность: без него отрицательный результат на реальных данных
    ничего не доказывает, потому что мог бы быть артефактом сломанного движка.
    """
    cfg = Config(cost_bps_per_side=0.0, short_q=0.2, exec_delay=1, rebalance="D")
    oracle = panel.ret_oo.shift(-(cfg.exec_delay + 1))
    assert _sharpe(run(panel, oracle, cfg)) > 5.0, "движок не способен выразить даже оракула"


def test_no_lookahead_on_stale_information(panel):
    """Сигнал, знающий уже ПРОШЕДШУЮ доходность, не должен давать края.

    ret_oo[r+1] на случайных данных к моменту установки весов (открытие r+1)
    уже реализован. Заметный Sharpe здесь означает off-by-one в исполнении.
    """
    cfg = Config(cost_bps_per_side=0.0, short_q=0.2, exec_delay=1, rebalance="D")
    stale = panel.ret_oo.shift(-1)
    s = _sharpe(run(panel, stale, cfg))
    assert abs(s) < 1.0, f"край на устаревшей информации — утечка будущего: Sharpe {s:.2f}"


def test_overnight_gap_is_not_capturable(panel):
    """Ключевой тест на исполнение по ОТКРЫТИЮ.

    Сигнал = гэп close(r) → open(r+1). Движок, исполняющий по закрытию дня r,
    забрал бы его целиком; исполняющий по открытию r+1 — не должен получить
    ничего, потому что к моменту сделки гэп уже случился.
    """
    cfg = Config(cost_bps_per_side=0.0, short_q=0.2, exec_delay=1, rebalance="D")
    gap = (panel.open.shift(-1) / panel.close - 1.0)
    s = _sharpe(run(panel, gap, cfg))
    assert abs(s) < 1.0, f"движок забирает овернайт-гэп — исполнение по закрытию: {s:.2f}"


def test_exec_delay_below_one_is_rejected(panel):
    with pytest.raises(ValueError, match="lookahead"):
        run(panel, panel.ret_oo * 0.0, Config(exec_delay=0))


def test_cost_scales_with_turnover(panel):
    """Издержки должны быть ровно turnover × bps, и расти линейно по ставке."""
    rng = np.random.default_rng(7)
    noise = pd.DataFrame(rng.standard_normal(panel.close.shape),
                         index=panel.dates, columns=panel.tickers)
    r10 = run(panel, noise, Config(cost_bps_per_side=10.0, short_q=0.2))
    r20 = run(panel, noise, Config(cost_bps_per_side=20.0, short_q=0.2))

    assert r10.cost.sum() > 0
    assert r20.cost.sum() == pytest.approx(2.0 * r10.cost.sum(), rel=1e-9)
    expected = r10.turnover.sum() * 10.0 / 1e4
    assert r10.cost.sum() == pytest.approx(expected, rel=1e-9)


def test_costs_reduce_return(panel):
    """Чистая доходность = валовая минус издержки, тождественно."""
    rng = np.random.default_rng(11)
    noise = pd.DataFrame(rng.standard_normal(panel.close.shape),
                         index=panel.dates, columns=panel.tickers)
    res = run(panel, noise, Config(cost_bps_per_side=10.0, short_q=0.2))
    assert np.allclose(res.ret.to_numpy(), (res.gross_ret - res.cost).to_numpy())


def test_untradable_position_is_not_sold(panel):
    """Бумагу, которой сегодня не торгуют, нельзя закрыть по несуществующей цене."""
    p = _synthetic_panel()
    frozen = p.tickers[0]
    p.tradable.loc[p.dates[200]:, frozen] = False

    # сигнал, который держит frozen в лонге до 200-го дня и выкидывает после
    s = pd.DataFrame(0.0, index=p.dates, columns=p.tickers)
    s.loc[:p.dates[199], frozen] = 10.0
    s.loc[p.dates[200]:, frozen] = -10.0

    res = run(p, s, Config(cost_bps_per_side=0.0, short_q=None, liq_min_value=0.0))
    held_after = res.weights.loc[p.dates[260]:, frozen].abs().sum()
    assert held_after > 0, "позиция в неторгуемой бумаге была закрыта — фиктивный выход"
