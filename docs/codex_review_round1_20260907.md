# Независимый adversarial review HammerTrade — раунд 1

Дата: 2026-09-07  
Роль: независимый quant/research reviewer  
Объект: `docs/claude_code_strategy_audit_20260907.md` и `docs/claude_code_arch_next_strategies_20260907.md`

## Резюме

Главный вывод Claude частично верен: издержки и исполнение действительно смоделированы плохо, а ORB не доказан как survivor. Но аудит пропустил дефекты опаснее большинства перечисленных им:

1. Sandbox-движки pairs и carry могут записать конструкцию как закрытую при нулевом или частичном исполнении выхода. Поэтому `REAL` PnL может быть фиктивным, а на счёте останется голая нога.
2. Исторический «edge» carry вообще не является backtest доходности конструкции. Это среднее модельного snapshot-показателя, построенного с look-ahead в определении экспирации.
3. Pairs выбрана по pooled OOS после перебора, а затем дополнительно откалибрована на выживших парах. Это не чистый OOS.
4. Гипотеза Claude о том, что S7 зарабатывает в основном на дивидендных гэпах ord/pref, кодом и доступными данными не подтверждена.
5. N4 в предложенном виде не является carry. Дивидендный гэп компенсируется дивидендным cashflow; после ex-date детерминированное движение уже произошло.

Точное пересечение 27 sandbox-сделок с ex-date и фактическую корреляцию carry/pairs проверить не удалось: локальной sandbox-БД с этими сделками в репозитории нет. Это отмечено как **не проверено**, а не заменено догадкой.

## 1. Проверка утверждений раздела 1.3, пункты A–K

### A. Комиссия занижена в 450 раз — UNDERSTATED

Дефолт действительно равен `0.05 RUB` round-trip:

- `src/config.py:33-35`;
- `src/backtest/engine.py:49,121-122`;
- `src/paper/engine.py:20-40,50`;
- `src/sandbox/engine.py:167-188,194-208,227`.

При позиции 90 тыс. RUB и минимальном тарифе 0.025% комиссия составляет примерно 22.5 RUB **за сторону**, то есть 45 RUB round-trip. Ошибка около **900 раз**, а не 450. Lead посчитал только одну сторону.

Есть ещё один дефект. ORB walk-forward config задаёт `commission=38` и `point_value=1` (`configs/research/orb_walkforward.yaml:28-30`), специализированный backtest читает эти значения в `src/strategies/opening_range_breakout/backtest.py:60-61`, но в расчёте затем хардкодит `point_value=10` и `commission=0.05` в `src/strategies/opening_range_breakout/backtest.py:141`. То есть конфиг создаёт видимость контролируемой экономики, но фактически не управляет PnL.

Дополнительные факты:

- `POINT_VALUE_RUB=10` зашит в ORB, momentum, VWAP, opening-range-fade и вспомогательных backtest-модулях;
- pairs research использует 2.5 bp commission плюс 1 bp slippage на сторону, то есть 3.5 bp, тогда как последующая реалистичная проверка использует 5 bp;
- slippage utility для ORB также пересчитывает результат post hoc с жёсткими `point_value=10` и `commission=0.05`, а не повторяет исполнение стратегии.

Итог: наличие ошибки подтверждено, её масштаб в аудите занижен.

### B. Stop/take исполняются по касанию — UNDERSTATED

Generic backtest исполняет вход точно по пробитому уровню даже при гэпе через этот уровень, а выход — точно по stop/take:

- `src/backtest/engine.py:166-174` — breakout entry;
- `src/backtest/engine.py:177-202` — stop/take exit.

ORB делает то же:

- `src/strategies/opening_range_breakout/backtest.py:90-121` — exit по точному stop/take;
- `src/strategies/opening_range_breakout/backtest.py:141` — PnL;
- `src/strategies/opening_range_breakout/strategy.py:266-300` — вход по точной границе диапазона.

Lead пропустил не только optimistic stop fills, но и невозможные entry fills при гэпе. Кроме того, несколько стратегий входят по тому же close, который породил сигнал:

- `src/strategies/momentum/strategy.py:203-216`;
- `src/strategies/vwap_reversion/strategy.py:199-228`;
- `src/strategies/opening_range_fade/strategy.py:200-233`.

Это прямой same-bar look-ahead на уровне исполнения: close можно узнать только после завершения бара, но сделка получает этот же close. Post-hoc добавление slippage не исправляет порядок событий, gap-through и доступный объём.

### C. Нет общего portfolio risk layer — CONFIRMED

В live-значимых pairs/carry runner нет общего лимита gross exposure, margin requirement, account equity или cross-strategy drawdown:

- `scripts/run_pairs_sandbox_trader.py:179-180,223-225,524-535` — локальная таблица pause и локальное чтение статуса;
- `scripts/run_carry_sandbox_trader.py:202-203,526-532` — отдельный локальный pause;
- `scripts/run_hammer_maxhold5_sandbox.py:59,340` — `RiskManager` подключён в другом runner, не в pairs/carry.

Используют ли carry и pairs фактически один и тот же sandbox account, по репозиторию **не проверено**: CLI-дефолты читают `SANDBOX_ACCOUNT_ID`, но example systemd units используют разные имена env-переменных. Центральное утверждение об отсутствии portfolio-level контроля подтверждено независимо от того, один счёт или два.

### D. Pair stop проверяется раз в час — CONFIRMED

Для развёрнутого v2-сервиса заданы:

- `--interval 1h`;
- `--poll-sec 300`;
- `--stop-loss-bp 300`.

См. `deploy/systemd/hammertrade-sandbox-pairs-v2.example.service:10-22`.

Runner получает и фильтрует часовые свечи в `scripts/run_pairs_sandbox_trader.py:479-496`, проходит новые закрытые бары с `scripts/run_pairs_sandbox_trader.py:527`, а stop проверяет по close в `scripts/run_pairs_sandbox_trader.py:556-568`.

Уточнение: CLI-дефолт `--stop-loss-bp` равен `None` (`scripts/run_pairs_sandbox_trader.py:60-64`). Следовательно, утверждение верно для указанного v2 deployment, а не для любого возможного запуска.

### E. Sandbox stop использует другую cost-базу — OVERSTATED

Несогласованность есть:

- paper `_bar_pnl` списывает полный round-trip: `src/paper/pairs/engine.py:30-39`;
- sandbox unrealized вычитает только entry commission: `scripts/run_pairs_sandbox_trader.py:361-372`;
- stop опирается на этот unrealized: `scripts/run_pairs_sandbox_trader.py:556-560`.

Но экономическая разница — ожидаемая exit-комиссия, примерно 10 bp при принятой модели, против stop 300 bp. Утверждение, что это «точно» объясняет расхождение `+21k` против `+9k`, из кода не следует. Для такого вывода нужна attribution по конкретным сделкам, fills и timestamps. Её нет.

### F. Paper exit имеет zero latency — OVERSTATED

Entry в режиме market моделируется по следующему open:

- теоретический signal close: `src/paper/pairs/engine.py:108-109`;
- market fill next-bar open: `src/paper/pairs/engine.py:124-127`.

Exit, напротив, возникает и считается по signal close: `src/paper/pairs/engine.py:158-173`. Это неисполняемо без задержки.

Но фраза «zero latency всегда в пользу paper» неверна. Следующая доступная цена может быть как хуже, так и лучше signal close. Корректный вердикт: execution bias есть, но знак по каждой сделке не детерминирован.

### G. Borrow cost отсутствует — CONFIRMED

В pairs borrow fee отсутствует и в paper PnL, и в sandbox accounting. В xsec поле существует, но дефолт равно нулю:

- `src/research/xsec/engine.py:29-39`;
- списание borrow cost: `src/research/xsec/engine.py:116,124-126`.

Приведённый lead диапазон `15-25%` для конкретных бумаг и дат **не проверен**. Сам дефект — отсутствие стоимости и доступности short — подтверждён.

### H. S7 в основном торгует дивидендные гэпы — OVERSTATED

Дивиденды действительно отсутствуют в live/paper pairs PnL. `compute_spread_z` использует только price series:

- `src/paper/pairs/engine.py:204-233`.

Но причинное утверждение «часть edge S7 — дивидендные гэпы из-за разных выплат» не доказано.

Доступные локальные dividend CSV показывают:

- TATN и TATNP имеют одинаковые даты и суммы выплат по доступной истории;
- RTKM и RTKMP преимущественно имеют одинаковые даты и суммы, с отдельными историческими исключениями;
- свежие price-файлы доходят до 2026 года, а dividend-файлы заканчиваются 2025 годом, поэтому календарь сам по себе устарел.

В 2026 году для RTKM/RTKMP объявлена одинаковая выплата 2.71 RUB на акцию. Различается dividend yield из-за разных цен, а не обязательно размер выплаты.

Главная экономическая ошибка lead: ожидаемый скачок ord/pref spread определяется **разницей dividend yields**, а не полным yield каждой бумаги. Для equal-notional long pref / short ord:

```text
price gap        ≈ -D / P_pref + D / P_ord
dividend cashflow ≈ +D / P_pref - D / P_ord
total             ≈ 0 до налогов, borrow и bid/ask
```

Локальная проверка ex-date 2026 дала:

- TATN/TATNP: изменение log-spread около -10 bp; price PnL equal-notional около -9.8 bp, дивидендная компенсация около +13.8 bp;
- RTKM/RTKMP: spread около -49 bp на фоне сильного общего движения; после dividend cashflow это не превращается в детерминированные +100-300 bp.

Были ли конкретные 27 sandbox-сделок S7 открыты через ex-date — **не проверено**, поскольку соответствующей БД нет.

### I. Candle loader не проверяет полноту — UNDERSTATED

После исчерпания retry loader предупреждает и возвращает то, что успел собрать:

- `src/tbank/candles.py:93-120`;
- цикл fetch: `src/tbank/candles.py:142-159`.

Карта ожидаемых timestamps не строится, gaps не маркируются, `is_complete` не контролируется:

- `src/paper/market_data.py:15-18,25-37`.

В pairs ноги загружаются раздельно и затем inner-joinятся:

- `src/paper/pairs/engine.py:210-213`.

Следствие хуже простого «может отсутствовать свеча»: окно rolling z-score означает последние N совпавших наблюдений, а не N последовательных рыночных интервалов. Пропуски одной ноги могут селективно удалять стрессовые интервалы и менять эффективную длительность окна без какого-либо warning.

### J. Carry reconcile не видит старый квартальный фьючерс — OVERSTATED

Если журнал всё ещё знает открытую старую ногу, caller специально подменяет UID текущего front на UID удерживаемого контракта:

- `scripts/run_carry_sandbox_trader.py:499-502`.

Следовательно, обычная открытая позиция в предыдущем quarterly не является невидимой. Утверждение lead в буквальном виде слишком широкое.

Но невидимым становится **unjournaled orphan** после частичного или ложного закрытия. Такой сценарий реален из-за отдельного критического дефекта exit accounting, который аудит не нашёл. После потери связи с journal reconcile действительно проверит только perp и текущий front, а старый orphan может остаться на счёте.

### K. Funding помечается `_REAL`, хотя он модельный — CONFIRMED

Funding берётся из ISS `SWAPRATE`:

- `scripts/run_carry_sandbox_trader.py:116-121`.

Затем он начисляется чистой расчётной функцией:

- `scripts/run_carry_sandbox_trader.py:169-171`;
- ledger update: `scripts/run_carry_sandbox_trader.py:509-524`.

В status эта величина попадает в колонку `_REAL`:

- `scripts/run_carry_sandbox_trader.py:583-605`.

Это не broker-reconciled cashflow. Более того, status смешивает price PnL только закрытых сделок с funding total, включающим начисления по открытым конструкциям. Даже как model PnL показатель внутренне неоднороден.

## 2. Что lead пропустил

### 2.1. Критический дефект: фиктивное закрытие двухногих позиций

Это опаснее всех пунктов A-K.

В pairs `_place()` возвращает цену и `filled_lots`:

- `scripts/run_pairs_sandbox_trader.py:294-306`.

На выходе `filled_lots` обеих ног выбрасываются, а при отсутствии fill используется fallback-цена бара:

- `scripts/run_pairs_sandbox_trader.py:385-390`;
- `scripts/run_pairs_sandbox_trader.py:391-392`;
- `scripts/run_pairs_sandbox_trader.py:407-410`.

Итог: сделка получает статус `CLOSED` и PnL по теоретической цене даже при нулевом или частичном fill. На счёте остаётся одна либо обе ноги. Следующий reconcile может попытаться ликвидировать остаток, но этот fill и его стоимость уже не попадут в PnL закрытой сделки.

Carry повторяет тот же дефект:

- order возвращает filled lots: `scripts/run_carry_sandbox_trader.py:272-302`;
- exit отбрасывает результат: `scripts/run_carry_sandbox_trader.py:363-380`;
- журнал всё равно закрывается: `scripts/run_carry_sandbox_trader.py:388-402`.

Дополнительно caller игнорирует failure `_close_construction`, локально обнуляет `open_t` и при `ROLL` может сразу открыть новую конструкцию:

- `scripts/run_carry_sandbox_trader.py:552-567`.

Это прямой путь к нескольким одновременным конструкциям и голым ногам. `db.open_trade()` возвращает только одну, самую новую открытую запись, поэтому более старая конструкция может выпасть из контроля.

«Реальные филлы» сами по себе ничего не доказывают, если accounting объявляет выход исполненным без проверки фактического объёма.

### 2.2. Carry research — не backtest carry

В `scripts/research_perp_funding.py:87-102` front-series строится без нормального liquidity filter, а экспирация контракта определяется как последняя торговая дата во всём датасете (`:91`). Это future information и не обязательно контрактная экспирация: неликвидный контракт может перестать торговаться раньше.

Далее рассчитывается:

```text
carry_bp_day = funding_bp - basis_bp / DTE
```

и усредняется:

- `scripts/research_perp_funding.py:105-132`;
- `scripts/research_perp_funding.py:134-149`.

Это не реализованная доходность:

- нет изменения basis между входом и выходом;
- нет позиции и размера collateral;
- нет bid/ask;
- нет variation margin;
- нет rolls;
- нет асинхронности spot/futures;
- нет forced liquidation;
- нет сравнения с RUONIA;
- нет реальных broker funding cashflows.

Поэтому `+4.76 bp/day` нельзя называть историческим PnL или доказанным edge. Это среднее модельной оценки ожидаемого carry.

### 2.3. Carry закрывает старый контракт по сигналу нового контракта

Runner сначала выбирает текущий front и считает его carry:

- `scripts/run_carry_sandbox_trader.py:476-490`.

Лишь затем он обнаруживает, что открытая сделка может держать предыдущий quarterly. При этом `CARRY_FLIP` принимается по carry **нового front**, хотя закрывается старый контракт:

- `scripts/run_carry_sandbox_trader.py:546-555`.

В журнал `exit_carry_bp` также записывается carry другого инструмента. Стратегия может закрыть старую конструкцию из-за смены знака basis у нового контракта, не имеющей отношения к economics удерживаемой позиции.

### 2.4. Pairs OOS использовался для выбора

Basket ограничен четырьмя заранее выбранными современными ord/pref-парами:

- `scripts/research_pairs_basket.py:25-31`.

Затем перебираются конфигурации, сортируются по pooled OOS, и primary configuration прямо названа выбранной как `best pooled-OOS`:

- `scripts/research_pairs_basket.py:193-210`;
- `scripts/research_pairs_basket.py:215-220`.

Это OOS только по имени. Он стал validation set.

При реалистичных 5 bp сохранённый отчёт показывает примерно:

- train PF `0.996`, net `-144 RUB`;
- OOS PF `1.042`, net `+396 RUB` на 60 сделках.

То есть edge практически нулевой. Затем stop калибруется только на оставшихся TATN и RTKM после отбрасывания SBER/SNGS. В stop-calibration OOS за май конфигурация со stop 300 bp показывает около `-783 RUB`, PF около `0.81`; сам stop ни разу не срабатывает.

Sandbox `+27` сделок — продолжение адаптивно выбранной конфигурации, а не независимое подтверждение.

### 2.5. Multiple comparisons недооценены на порядки

В `out/` лежат 12 `backtest_grid_results_*.csv` по 512 строк каждый: минимум **6144** сохранённых parameter runs только в одной серии.

Дополнительно обнаружены:

- ORB: 12 комбинаций (`scripts/research_orb_walkforward.py:84-95`);
- R2: 27 momentum + 12 opening-range-fade + 18 VWAP + 4 filters = 61 конфигурация;
- hammer calibration: 81 × 2 = 162;
- несколько pairs grids;
- 11 `scripts/research_*`;
- около 144 research reports.

Минимум — более **6300 видимых evaluation cells**. Реальное эффективное число гипотез неизвестно, потому что поиск адаптивный, результаты коррелированы, а неудачные ручные итерации не зарегистрированы.

Поэтому Monte Carlo максимум из 14 случайных стратегий не моделирует фактический процесс выбора. Он отвечает на другой, существенно более лёгкий вопрос.

### 2.6. Дивидендный календарь устарел

Downloader обновляет dividend-файл только если он отсутствует:

- `scripts/fetch_moex_daily_universe.py:177-186`.

`--refresh-universe` не означает refresh dividends:

- `scripts/fetch_moex_daily_universe.py:212-236`.

Локальные equity prices доходят до июля 2026, а dividend CSV TATN/RTKM заканчиваются 2025 годом. Следовательно, «total return» xsec за 2026 фактически частично является price return. Любые D1/N4/H-выводы на свежем периоде загрязнены.

### 2.7. `compute_spread_z`: прямого look-ahead нет, но hedge несогласован

Сам `compute_spread_z` использует текущие и прошлые наблюдения:

- `src/paper/pairs/engine.py:216-233`.

Прямого чтения будущего здесь не найдено. Включение текущего close в rolling mean/std причинно допустимо только при исполнении после close; sandbox именно это и должен моделировать.

Но при dynamic beta сигнал строится по beta-adjusted residual:

- `src/paper/pairs/engine.py:221-230`.

PnL при этом остаётся равным long/short RUB notional:

- `src/paper/pairs/engine.py:34-38`;
- sizing sandbox: `scripts/run_pairs_sandbox_trader.py:314-318`.

То есть сигнал исследует beta-hedged residual, а фактическая позиция beta-neutral не является. Backtest исследует одну конструкцию и исполняет другую.

### 2.8. Дополнительный look-ahead и индексная ошибка VWAP

Momentum, VWAP и opening-range-fade входят на том же close, который нужен для вычисления сигнала. Это не только optimistic execution, но и нарушение порядка доступности информации.

В VWAP есть дополнительная вероятная индексная ошибка:

- post-session candles получают reset index в `src/strategies/vwap_reversion/strategy.py:228`;
- `vwap_series` сохраняет прежний index в `:233`;
- simulator затем сопоставляет новый positional index со старым label index в `:52-61`.

В результате dynamic target может использовать несоответствующий или устаревший VWAP. Точный масштаб и частота эффекта требуют отдельного теста; сам риск следует из несовместимых индексов.

### 2.9. Скрытый leverage

Пример carry-сервиса разрешает две конструкции по 1 млн RUB на каждую ногу:

- `deploy/systemd/hammertrade-sandbox-carry.example.service:10-22`.

Pairs аналогично может держать две пары по 1 млн RUB на ногу:

- `deploy/systemd/hammertrade-sandbox-pairs-v2.example.service:10-24`.

При общем счёте это около 8 млн RUB gross exposure без общей проверки:

- доступной маржи;
- collateral;
- вариационной маржи;
- одновременного stress loss;
- новых заявок другой стратегии.

Экономически «нейтральная» конструкция не отменяет margin call. Рост ставки риска, price-limit одной ноги или variation-margin debit способны вызвать принудительное закрытие до ожидаемой конвергенции.

Факт использования одного физического sandbox account по репозиторию **не проверен**. Если счета разные, cross-strategy gross меньше, но отсутствие account-aware risk limit остаётся.

### 2.10. Независимость carry и pairs не доказана

Совместного ряда доходностей, covariance matrix или portfolio stress test нет. Фактическая корреляция — **не проверено**.

Заявление об их независимости не следует из разных формул сигналов. Обе стратегии имеют общий фактор риска:

- сжатие ликвидности;
- расширение basis/spread;
- margin tightening;
- остановка или планка одной ноги;
- forced deleveraging;
- последовательное исполнение ног.

В спокойном режиме корреляция может выглядеть низкой; в хвосте обе конструкции являются short liquidity.

### 2.11. Extreme events рынка РФ отсутствуют в risk model

Panel явно знает о закрытии MOEX в 2022 году:

- `src/research/xsec/panel.py:13-15`.

Но live engines не моделируют:

- планку на одной ноге;
- остановку торгов;
- отсутствие borrow;
- принудительное закрытие брокером;
- заморозку бумаги;
- изменение lot size;
- отмену или перенос корпоративного события.

Если одна нога pairs остановлена, inner join перестаёт выдавать новые общие бары. Stop не защищает позицию — он перестаёт вычисляться. После возобновления движок может перепрыгнуть накопившиеся интервалы и увидеть уже реализованный гэп. Последовательные market orders выхода дополнительно создают naked-leg exposure именно тогда, когда ликвидность хуже всего.

## 3. Атака на главные тезисы

### 3.1. ORB SHORT как survivor

Claude здесь **прав**, но формулирует проблему слишком мягко.

Процедура:

- один train/OOS split;
- 12 комбинаций, а не семь независимо проверенных гипотез (`scripts/research_orb_walkforward.py:84-95`);
- все варианты прогоняются на train и OOS (`:510-524`);
- победитель выбирается по максимальному train PF (`:547-563`);
- OOS содержит всего 13 сделок, не около 20;
- top-3 сделки дают примерно 144.5% результата;
- лучший день даёт около 53.6%;
- сам сохранённый отчёт выносит решение `NEEDS_MORE_DATA`, а не `SURVIVOR`.

Дополнительно OOS проверяется тем же backtest с невозможными price-level fills и игнорированием заявленных commission/point-value параметров. Slippage utility лишь пересчитывает PnL, но не повторяет path-dependent execution.

Итог: называть ORB SHORT survivor нельзя. Но это не доказательство отсутствия edge; это отсутствие достаточного доказательства его наличия.

### 3.2. S7 зарабатывает на дивидендных гэпах ord/pref

Вердикт: **не подтверждено**.

Claude прав только в одном: pairs PnL должен учитывать dividend receivable/payable, а сейчас не учитывает.

Но причинная история разваливается:

- в 2026 выплаты у RTKM/RTKMP одинаковы;
- у TATN/TATNP доступная история также показывает одинаковые суммы на акцию;
- различный dividend yield возникает главным образом из-за разных цен;
- ожидаемый скачок spread определяется разницей yield, а не полным yield `1-3%`;
- price gap должен быть скомпенсирован dividend cashflow.

Если позиция держится через ex-date, price-only PnL действительно неправильный. Но неправильность не означает, что стратегия получает прибыль от гэпа: полное total-return accounting может эту «прибыль» уничтожить или развернуть.

Точное попадание 27 sandbox-сделок на ex-date — **не проверено**.

### 3.3. N4: ex-date ord/pref spread trade

В изложенном виде кандидат должен быть **отклонён**.

Если позиция открыта до ex-date, ценовой гэп компенсируется правом или обязанностью по дивиденду. Это бухгалтерская идентичность, а не alpha.

Если позиция открывается после ex-date, детерминированное движение уже произошло. Остаётся лишь гипотеза о последующей mean reversion residual — обычная статистическая pairs-стратегия с corporate-event filter.

Величина `100-300 bp` не доказана и, вероятно, получена смешением полного dividend yield с гораздо меньшей разницей yield между классами.

Дополнительные потери:

- налоговая асимметрия;
- compensation payment по short;
- borrow fee;
- невозможность short;
- гэп bid/ask;
- разные даты расчётов и корпоративной обработки у брокера.

Это не carry и не бесплатный payer-funded edge.

### 3.4. N1: cash-and-carry до экспирации

Тезис «конвергенция гарантирована, значит edge устойчив» неверен.

Конвергенция гарантирует терминальную связь фьючерса со spot, но не excess return относительно:

- стоимости денег;
- ожидаемых дивидендов;
- bid/ask;
- комиссий;
- вариационной маржи;
- риска принудительного закрытия;
- стоимости collateral.

Формула должна оценивать зафиксированный IRR конструкции после всех cashflows и сравнивать его как минимум с RUONIA. Большой basis сам по себе не является прибылью.

Аргумент «держим дольше — 20 bp полностью амортизируются» также неверен. Фиксированные 20 bp не исчезают; уменьшается их annualized impact. Если basis уже отражает funding и дивиденды, дополнительного edge нет.

Дальние российские single-stock futures часто неликвидны. Даже экономически сходящаяся позиция может быть закрыта брокером раньше из-за роста risk rate или variation-margin deficit. Конвергенция к экспирации не защищает от path risk.

N1 имеет смысл только если до открытия доказано:

```text
locked return - RUONIA - all costs - stressed margin funding > threshold
```

и обе ноги реально исполнимы требуемым объёмом. Текущий research этого не делает.

### 3.5. R-1: «найди payer, иначе не исследуем»

Как эвристика — полезно. Как жёсткое правило — интеллектуально лениво.

«Кто payer?» заставляет сформулировать механизм и предотвращает бессодержательный mining. Но:

- наличие payer не гарантирует, что premium не арбитражирован;
- отсутствие очевидного payer не опровергает behavioural/statistical edge;
- историю про payer легко сочинить постфактум;
- «leveraged retail платит funding» в carry-кейсе в данных напрямую не идентифицировано;
- N4 имеет очевидный corporate cashflow, но экономического edge из этого не возникает.

R-1 должен быть prior и требованием к причинной интерпретации, а не veto. Настоящая защита — pre-registration, frozen outer OOS, realistic execution и корректировка за весь процесс поиска.

## 4. Проверка предложенной методологии

### 4.1. Классы C/S смешивают разные уровни доказательства

Разделение на структурные и статистические стратегии разумно, но Class C у Claude смешивает четыре разные проверки:

1. правильность арифметики формулы;
2. прогноз observable;
3. экономический PnL;
4. исполнимость hedge.

Высокая точность прогноза `SWAPRATE` может означать лишь persistence самого `SWAPRATE`. Это не доказывает доходность stock-perpetual конструкции.

Корректная проверка carry должна:

- на каждом `t` фиксировать только доступную информацию;
- прогнозировать cashflow `t+1...t+H`;
- сверять начисления с независимым broker ledger;
- включать basis MTM, реальные fills, rolls, commissions, spread и funding collateral;
- считать excess return над cash benchmark;
- использовать неперекрывающиеся горизонты либо HAC/block-bootstrap.

### 4.2. 20-30 наблюдений недостаточно

При горизонте 10 дней 20-30 дневных наблюдений дают лишь 2-3 почти независимых исхода. Формально строк больше, информации нет.

`R²` здесь плохая primary metric. Можно получить высокий `R²`, но неверный slope/intercept и отрицательный net PnL. Нужны:

- calibration slope/intercept;
- MAE cashflow;
- precision стратегии на входах;
- realised excess PnL;
- confidence intervals;
- sensitivity к costs и latency.

### 4.3. Walk-forward тоже можно переобучить

Требование «переоценивать параметры в каждом окне» не устраняет mining. Оно может создать adaptive curve fitting внутри каждого fold.

Нужны nested walk-forward и внешний untouched period. Использованный хотя бы раз OOS больше не является OOS.

### 4.4. Bootstrap отдельных сделок слаб

Перестановка отдельных сделок уничтожает:

- volatility clustering;
- correlation между стратегиями;
- liquidity regimes;
- серии гэпов;
- общие stress events.

Нужен calendar block-bootstrap совместного portfolio PnL, а не shuffle trade tickets.

### 4.5. Monte Carlo с N=14 нерелевантен

Реальный selection pipeline включает тысячи parameter cells и адаптивные решения о том, какую стратегию исследовать дальше. Генерировать максимум из 14 случайных сигналов — занижать multiple-comparison burden на порядки.

Если exact effective N нельзя восстановить, надо моделировать весь исследовательский pipeline либо явно признать результаты exploratory. Подстановка заведомо малого N создаёт ложную строгость.

### 4.6. Pre-registration не очищает уже просмотренную историю

Регистрация следующего эксперимента полезна, но старые данные уже загрязнены решениями исследователя. Подтверждение возможно только на новых будущих данных или на действительно не открывавшемся holdout.

### 4.7. Общий код research/execution не является независимой верификацией

Переиспользование одной функции уменьшает implementation drift, но создаёт common-mode error. Если формула неверна, и research, и live будут согласованно неверны.

Для cashflows, costs, order state и position reconciliation нужен независимый oracle: broker operations/positions и отдельный reconciliation calculation.

### 4.8. Market-neutral benchmark требует точного определения капитала

Для двухногой конструкции нельзя механически делить PnL на nominal одной ноги или весь gross. Нужны как минимум:

- initial и maintenance margin;
- фактически заблокированный collateral;
- использование или недоступность short proceeds;
- variation-margin path;
- капитал для stress buffer;
- opportunity cost этого капитала.

Без этого Sharpe и annualized return сравнивают стратегии на разных и произвольных capital denominators.

## 5. Приоритетный итог

### 5.1. Три главные опасности прямо сейчас

1. **Фиктивные закрытия и голые ноги.** Sandbox journal способен показать `CLOSED` и прибыль при частично либо вообще не исполненном выходе.
2. **Carry edge не измерен.** Исторический `bp/day` — не realised strategy return; live reporting при этом маркирует модельный funding как `_REAL` и может закрывать старый контракт по carry нового.
3. **Ни одна стратегия статистически не установлена.** ORB имеет 13 концентрированных OOS-сделок; pairs выбрана по OOS и survivor-парам; видимый поиск превышает 6300 конфигураций без корректного trial accounting.

### 5.2. Что следует остановить до дальнейшей оценки edge

До исправления accounting и reconciliation нельзя использовать sandbox PnL как доказательство:

- выход должен считаться завершённым только после подтверждения полного объёма обеих ног;
- partial fills должны создавать явное состояние `PARTIALLY_CLOSED`, а не fallback-price PnL;
- orphan liquidation должна попадать в PnL исходной конструкции;
- broker positions и operations должны быть источником истины, journal — только локальной проекцией;
- model funding нельзя маркировать как `_REAL` без reconciliation с broker operation;
- carry research должен быть заменён event-driven backtest полной конструкции;
- OOS, уже использованный для выбора, должен быть переименован в validation и больше не использоваться как доказательство.

### 5.3. Финальный вердикт раунда 1

Основной риск не в том, что edge окажется на 20-30% слабее. Риск в том, что отчёт покажет прибыльную закрытую сделку, которой на брокерском счёте физически не было, а затем исследователь примет accounting artifact за подтверждение стратегии.

В текущем состоянии:

- ORB SHORT — **не доказан**;
- S7 pairs — **не имеет чистого OOS-подтверждения**;
- carry — **не имеет исторического backtest realised construction PnL**;
- N4 — **экономически неверно сформулирован**;
- независимость carry/pairs — **не проверена**;
- 27 sandbox-сделок против ex-date — **не проверено**.

Разделы 1-5 завершены в объёме раунда 1. Репозиторий не изменялся, кроме создания этого файла.
