# Next Paper Candidates Decision

Создан: 2026-06-02  
Контекст: по итогам MVP-R2 Multi-Strategy Research Pack  
Статус текущих сервисов: hammer-baseline, hammer-maxhold5, orb-paper (все active, liveness OK)

---

## Current running paper services

| Сервис | Стратегия | Ticker | Dir | Статус | Decision |
|--------|-----------|--------|-----|--------|---------|
| hammer-baseline | Hammer Reversal | SiM6 | SELL | active | control group |
| hammer-maxhold5 | Hammer maxhold5 | SiM6 | SELL | active | **CONTINUE** (PF 1.396, 61 trades) |
| orb-paper | ORB or60_short2r | SiM6 | SHORT | active | accumulating (0 trades) |

---

## Candidate comparison

| Кандидат | OOS PF | OOS trades | Slippage robustness | Концентрация | Execution complexity | Приоритет |
|----------|--------|------------|---------------------|-------------|----------------------|-----------|
| Momentum MC_atr2.0_vol2.0_r2.0 | **2.883** | 20 | ✅ Высокая (PF 1.15 @ 10pt) | ⚠ HIGH (top-3 = 79%) | Низкая (маркет ОК) | **1 — первый** |
| VWAP Reversion VR_d1.0_s1.0_1.5R | 1.475 | **55** | ❌ Низкая (PF 1.08 @ 2pt) | ✅ Нет | Высокая (нужен limit) | **2 — второй** |
| ORB or60_short2r | 1.683* | 13* | ✅ Высокая (PF 1.50 @ 10pt) | ⚠ HIGH (top-3 = 144%) | Низкая | уже запущен |

*данные MVP-R1a, May OOS

---

## Momentum Continuation — анализ

**Сильные стороны:**
- Лучший OOS PF (2.883) из всех R2-кандидатов
- Slippage не убивает: маркет-ордер приемлем
- Простая execution: вход по Close, стоп по High свечи
- Работает в HIGH_VOL и NEWS_SHOCK режимах — дополняет hammer (reversal)

**Слабые стороны:**
- Только 20 OOS trades — статистически тонко
- Концентрация: 79% прибыли в топ-3 сделках
- Январь убыточен (PF 0.498) — режимная зависимость
- Нет paper engine — требует разработки `run_momentum_paper_trader.py`

**Предварительный вывод**: первый кандидат для запуска после роллирования. Высокий OOS PF
перевешивает малость выборки — нужна более длинная paper-история для подтверждения.

---

## VWAP Reversion — анализ

**Сильные стороны:**
- Наиболее статистически устойчивая (180 train, 55 OOS trades)
- Все 4 train-месяца прибыльны — лучшая временна́я стабильность
- PF 1.475 на OOS подтверждает train
- Нет концентрации

**Слабые стороны:**
- **Edge destroyed at 2pt slippage** — маркет-ордер неприемлем
- Требует dual-fill paper engine или limit-order simulation
- 3 сделки/день → больше рисков slippage и заполнения
- Сложнее в реализации daemon (инкрементальная VWAP в реальном времени)

**Предварительный вывод**: второй кандидат, запускать только после:
1) Momentum уже работает >= 2 недель
2) Реализован dual-fill tracking
3) Проверен типичный slippage < 1.5pt на реальных данных

---

## Recommendation

### Launch order after rollover

```
1. Rollover SiM6 → SiU6 (deadline ~2026-06-10)
   - Перезапустить hammer-maxhold5 на SiU6
   - Перезапустить ORB на SiU6
   - Отдельные DB для SiU6

2. Запустить Momentum paper (SiU6)
   - После rollover + стабилизации hammer/ORB на SiU6
   - Критерий: hammer и ORB без ошибок >= 3 торговых дня
   - Требует: run_momentum_paper_trader.py + тесты

3. Запустить VWAP Reversion paper (SiU6)
   - После того как Momentum >= 2 недели и >= 20 trades
   - Требует: dual-fill engine, проверка slippage
   - Это наиболее технически сложный paper engine
```

---

## What to prepare before launch

### Для Momentum (приоритет HIGH):
- [ ] `src/paper/momentum/` — paper engine, аналогичный `src/paper/orb/`
- [ ] `scripts/run_momentum_paper_trader.py`
- [ ] Тесты (аналог `tests/test_orb_paper_engine.py`)
- [ ] `deploy/systemd/hammertrade-paper-momentum.example.service`
- [ ] Smoke test с `--once`

### Для VWAP Reversion (приоритет MEDIUM):
- [ ] Проектирование dual-fill model
- [ ] `src/paper/vwap_reversion/` — paper engine
- [ ] `scripts/run_vwap_reversion_paper_trader.py`
- [ ] Dual-fill diagnostics column
- [ ] Тесты + smoke test

---

## What NOT to launch yet

- **OR Fade**: развалился на OOS (PF 0.68). Отклонён.
- **Volatility Breakout**: не реализован в R2, нет данных.
- **VWAP Hammer Filter**: helper, не standalone стратегия.
- **Sandbox/live**: не раньше чем 30+ paper trades на каждой стратегии.

---

## Final summary

| | Что делаем сейчас | Что готовим | Когда запускаем |
|--|---|---|---|
| hammer-maxhold5 | продолжает работать | rollover SiU6 | ~10 июня |
| ORB paper | продолжает работать | rollover SiU6 | ~10 июня |
| **Momentum** | spec готова | paper engine | после rollover |
| **VWAP Reversion** | spec готова | dual-fill engine | после Momentum |
| OR Fade | отклонена | — | никогда (пока) |
