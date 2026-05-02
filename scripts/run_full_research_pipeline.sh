#!/usr/bin/env bash

set -euo pipefail

# ============================================================
# Defaults
# ============================================================
TICKER=""
CLASS_CODE="SPBFUT"
TIMEFRAME="1m"
START_DATE=""
END_DATE=""
ENVIRONMENT="prod"
PROFILE="balanced"
PARAMS_FILE=""

POINT_VALUE_RUB="auto"
FALLBACK_POINT_VALUE_RUB="10"
TICK_SIZE="auto"
FALLBACK_TICK_SIZE="0.5"
TICK_SIZE_SOURCE="fallback"
AUTO_SPECS=true
SPECS_CACHE="data/instruments/futures_specs.csv"
COMMISSION_PER_TRADE="0.025"
CONTRACTS="1"
DIRECTION_FILTER="all"

ENTRY_MODE="breakout"
ENTRY_HORIZON_BARS="3"
MAX_HOLD_BARS="30"
TAKE_R="1.0"
STOP_BUFFER_POINTS="0"
SLIPPAGE_POINTS="0"

SLIPPAGE_TICKS=""

GRID_ENTRY_MODES="breakout,close"
GRID_TAKE_R_VALUES="0.5,1.0,1.5,2.0"
GRID_MAX_HOLD_BARS_VALUES="5,10,30,60"
GRID_STOP_BUFFER_POINTS_VALUES="0,1,2,5"
GRID_SLIPPAGE_POINTS_VALUES="0,1,2,5"
GRID_SLIPPAGE_TICKS_VALUES="0,1,2,5"

SKIP_LOAD=false
SKIP_GRID=false
SKIP_WALKFORWARD_GRID=false
ARCHIVE=true

# ============================================================
# Help
# ============================================================
show_help() {
  cat <<EOF
MOEXF Hammer Research Pipeline

Usage:
  ./scripts/run_full_research_pipeline.sh --ticker SiM6 --from 2026-03-01 --to 2026-04-10 [options]

Required:
  --ticker VALUE                      Futures ticker, e.g. SiM6
  --from YYYY-MM-DD                   Start date
  --to YYYY-MM-DD                     End date

Common options:
  --class-code VALUE                  Default: SPBFUT
  --timeframe VALUE                   Default: 1m
  --profile VALUE                     Default: balanced
  --env VALUE                         prod or sandbox, default: prod
  --params-file PATH                  Default: configs/hammer_detector_<profile>.env

Financial options:
  --point-value-rub VALUE             'auto' (from specs) or numeric. Default: auto
  --fallback-point-value-rub VALUE    Fallback if auto fails. Default: 10
  --tick-size VALUE                   'auto' (from specs) or numeric. Default: auto
  --fallback-tick-size VALUE          Fallback tick size if auto fails. Default: 0.5
  --auto-specs true|false             Fetch specs from T-Bank if not cached. Default: true
  --specs-cache PATH                  Specs cache CSV. Default: data/instruments/futures_specs.csv
  --commission-per-trade VALUE        Default: 0.025
  --contracts VALUE                   Default: 1

Backtest options:
  --entry-mode VALUE                  breakout or close, default: breakout
  --entry-horizon-bars VALUE          Default: 3
  --take-r VALUE                      Default: 1.0
  --max-hold-bars VALUE               Default: 30
  --stop-buffer-points VALUE          Default: 0
  --slippage-points VALUE             Default: 0
  --slippage-ticks VALUE              Single-backtest slippage in ticks (optional)
  --direction-filter VALUE            all|BUY|SELL. Default: all

Grid options:
  --grid-entry-modes VALUE            Default: breakout,close
  --grid-take-r-values VALUE          Default: 0.5,1.0,1.5,2.0
  --grid-max-hold-bars-values VALUE   Default: 5,10,30,60
  --grid-stop-buffer-points-values VALUE  Default: 0,1,2,5
  --grid-slippage-points-values VALUE Default: 0,1,2,5
  --grid-slippage-ticks-values VALUE  Grid slippage in ticks. Default: 0,1,2,5 (used by default)

Flags:
  --skip-load                 Do not call T-Bank API, use existing raw CSV
  --skip-grid                 Skip grid backtest (step 6)
  --skip-walkforward-grid     Skip daily/weekly walk-forward grid (steps 8-9)
  --no-archive                Do not create zip archive
  --help                      Show this help

Examples:
  # Full run (auto point_value_rub from specs)
  ./scripts/run_full_research_pipeline.sh \\
    --ticker SiM6 --from 2026-03-01 --to 2026-04-10

  # SELL-only, skip heavy grids
  ./scripts/run_full_research_pipeline.sh \\
    --ticker SiM6 --from 2026-03-01 --to 2026-04-10 \\
    --skip-load --direction-filter SELL --skip-walkforward-grid

  # Re-run without T-Bank API call
  ./scripts/run_full_research_pipeline.sh \\
    --ticker SiM6 --from 2026-03-01 --to 2026-04-10 --skip-load
EOF
}

# ============================================================
# Argument parsing
# ============================================================
while [[ $# -gt 0 ]]; do
  case "$1" in
    --ticker)                         TICKER="$2";                         shift 2 ;;
    --class-code)                     CLASS_CODE="$2";                     shift 2 ;;
    --point-value-rub)                POINT_VALUE_RUB="$2";                shift 2 ;;
    --fallback-point-value-rub)       FALLBACK_POINT_VALUE_RUB="$2";       shift 2 ;;
    --tick-size)                      TICK_SIZE="$2";                      shift 2 ;;
    --fallback-tick-size)             FALLBACK_TICK_SIZE="$2";             shift 2 ;;
    --auto-specs)                     AUTO_SPECS="$2";                     shift 2 ;;
    --specs-cache)                    SPECS_CACHE="$2";                    shift 2 ;;
    --direction-filter)               DIRECTION_FILTER="$2";               shift 2 ;;
    --from)                           START_DATE="$2";                     shift 2 ;;
    --to)                             END_DATE="$2";                       shift 2 ;;
    --timeframe)                      TIMEFRAME="$2";                      shift 2 ;;
    --profile)                        PROFILE="$2";                        shift 2 ;;
    --env)                            ENVIRONMENT="$2";                    shift 2 ;;
    --params-file)                    PARAMS_FILE="$2";                    shift 2 ;;
    --commission-per-trade)           COMMISSION_PER_TRADE="$2";           shift 2 ;;
    --contracts)                      CONTRACTS="$2";                      shift 2 ;;
    --entry-mode)                     ENTRY_MODE="$2";                     shift 2 ;;
    --entry-horizon-bars)             ENTRY_HORIZON_BARS="$2";             shift 2 ;;
    --max-hold-bars)                  MAX_HOLD_BARS="$2";                  shift 2 ;;
    --take-r)                         TAKE_R="$2";                         shift 2 ;;
    --stop-buffer-points)             STOP_BUFFER_POINTS="$2";             shift 2 ;;
    --slippage-points)                SLIPPAGE_POINTS="$2";                shift 2 ;;
    --slippage-ticks)                 SLIPPAGE_TICKS="$2";                 shift 2 ;;
    --grid-entry-modes)               GRID_ENTRY_MODES="$2";               shift 2 ;;
    --grid-take-r-values)             GRID_TAKE_R_VALUES="$2";             shift 2 ;;
    --grid-max-hold-bars-values)      GRID_MAX_HOLD_BARS_VALUES="$2";      shift 2 ;;
    --grid-stop-buffer-points-values) GRID_STOP_BUFFER_POINTS_VALUES="$2"; shift 2 ;;
    --grid-slippage-points-values)    GRID_SLIPPAGE_POINTS_VALUES="$2";    shift 2 ;;
    --grid-slippage-ticks-values)     GRID_SLIPPAGE_TICKS_VALUES="$2";     shift 2 ;;
    --skip-load)                      SKIP_LOAD=true;                      shift ;;
    --skip-grid)                      SKIP_GRID=true;                      shift ;;
    --skip-walkforward-grid)          SKIP_WALKFORWARD_GRID=true;          shift ;;
    --no-archive)                     ARCHIVE=false;                       shift ;;
    --help|-h)                        show_help; exit 0 ;;
    *)
      echo "Error: unknown argument: $1" >&2
      echo "Use --help for usage." >&2
      exit 1
      ;;
  esac
done

# ============================================================
# Validation
# ============================================================
if [[ -z "${TICKER}" ]]; then
  echo "Error: --ticker is required." >&2
  echo "Use --help for usage." >&2
  exit 1
fi
if [[ -z "${START_DATE}" ]]; then
  echo "Error: --from is required." >&2
  echo "Use --help for usage." >&2
  exit 1
fi
if [[ -z "${END_DATE}" ]]; then
  echo "Error: --to is required." >&2
  echo "Use --help for usage." >&2
  exit 1
fi

if [[ -z "${PARAMS_FILE}" ]]; then
  PARAMS_FILE="configs/hammer_detector_${PROFILE}.env"
fi

if [[ ! -f "${PARAMS_FILE}" ]]; then
  echo "Error: params file not found: ${PARAMS_FILE}" >&2
  exit 1
fi

if [[ "${ARCHIVE}" == "true" ]] && ! command -v zip &>/dev/null; then
  echo "Error: 'zip' is not installed. Install it or use --no-archive." >&2
  exit 1
fi

if [[ "${DIRECTION_FILTER}" != "all" && "${DIRECTION_FILTER}" != "BUY" && "${DIRECTION_FILTER}" != "SELL" ]]; then
  echo "Error: --direction-filter must be 'all', 'BUY', or 'SELL'." >&2
  exit 1
fi

# ============================================================
# Resolve point_value_rub (auto / numeric)
# ============================================================
_resolve_point_value_rub() {
  if [[ "${POINT_VALUE_RUB}" != "auto" ]]; then
    echo "Point value RUB: ${POINT_VALUE_RUB} (user-specified)"
    echo "WARNING: Overriding point_value_rub with user-provided value=${POINT_VALUE_RUB}." >&2
    return
  fi

  # Try local cache first
  local cached
  cached=$(python scripts/fetch_future_specs.py \
    --ticker "${TICKER}" --class-code "${CLASS_CODE}" \
    --output "${SPECS_CACHE}" \
    --cache-only --print-point-value 2>/dev/null || true)

  if [[ -n "${cached}" && "${cached}" != "None" ]]; then
    POINT_VALUE_RUB="${cached}"
    echo "Point value RUB: ${POINT_VALUE_RUB} (from specs cache)"
    return
  fi

  # Try T-Bank API if auto-specs enabled and not skip-load context
  if [[ "${AUTO_SPECS}" == "true" ]]; then
    echo "Fetching instrument specs from T-Bank for ${TICKER}..."
    if python scripts/fetch_future_specs.py \
        --ticker "${TICKER}" --class-code "${CLASS_CODE}" \
        --env "${ENVIRONMENT}" \
        --output "${SPECS_CACHE}" 2>/dev/null; then
      cached=$(python scripts/fetch_future_specs.py \
        --ticker "${TICKER}" --class-code "${CLASS_CODE}" \
        --output "${SPECS_CACHE}" \
        --cache-only --print-point-value 2>/dev/null || true)
      if [[ -n "${cached}" && "${cached}" != "None" ]]; then
        POINT_VALUE_RUB="${cached}"
        echo "Point value RUB: ${POINT_VALUE_RUB} (from T-Bank API)"
        return
      fi
    fi
  fi

  # Fallback
  POINT_VALUE_RUB="${FALLBACK_POINT_VALUE_RUB}"
  echo "WARNING: Could not determine point_value_rub from instrument specs." >&2
  echo "WARNING: Using fallback_point_value_rub=${POINT_VALUE_RUB}." >&2
  echo "WARNING: PnL may be invalid for this instrument." >&2
}

# ============================================================
# Resolve tick_size (auto / numeric)
# ============================================================
_resolve_tick_size() {
  if [[ "${TICK_SIZE}" != "auto" ]]; then
    TICK_SIZE_SOURCE="user"
    echo "Tick size: ${TICK_SIZE} (user-specified)"
    echo "WARNING: Overriding tick_size with user-provided value=${TICK_SIZE}." >&2
    return
  fi

  # Try local cache first
  local cached
  cached=$(python scripts/fetch_future_specs.py \
    --ticker "${TICKER}" --class-code "${CLASS_CODE}" \
    --output "${SPECS_CACHE}" \
    --cache-only --print-tick-size 2>/dev/null || true)

  if [[ -n "${cached}" && "${cached}" != "None" ]]; then
    TICK_SIZE="${cached}"
    TICK_SIZE_SOURCE="specs"
    echo "Tick size: ${TICK_SIZE} (from specs cache)"
    return
  fi

  # Try T-Bank API if auto-specs enabled
  if [[ "${AUTO_SPECS}" == "true" ]]; then
    echo "Fetching instrument specs from T-Bank for ${TICKER} (tick size)..."
    if python scripts/fetch_future_specs.py \
        --ticker "${TICKER}" --class-code "${CLASS_CODE}" \
        --env "${ENVIRONMENT}" \
        --output "${SPECS_CACHE}" 2>/dev/null; then
      cached=$(python scripts/fetch_future_specs.py \
        --ticker "${TICKER}" --class-code "${CLASS_CODE}" \
        --output "${SPECS_CACHE}" \
        --cache-only --print-tick-size 2>/dev/null || true)
      if [[ -n "${cached}" && "${cached}" != "None" ]]; then
        TICK_SIZE="${cached}"
        TICK_SIZE_SOURCE="specs"
        echo "Tick size: ${TICK_SIZE} (from T-Bank API)"
        return
      fi
    fi
  fi

  # Fallback
  TICK_SIZE="${FALLBACK_TICK_SIZE}"
  TICK_SIZE_SOURCE="fallback"
  echo "WARNING: Could not determine tick_size from instrument specs." >&2
  echo "WARNING: Using fallback_tick_size=${TICK_SIZE}." >&2
  echo "WARNING: Detector filters may be invalid for this instrument." >&2
}

# ============================================================
# Derived paths
# ============================================================
if [[ "${DIRECTION_FILTER}" != "all" ]]; then
  RUN_ID="${TICKER}_${TIMEFRAME}_${START_DATE}_${END_DATE}_${PROFILE}_${DIRECTION_FILTER}"
else
  RUN_ID="${TICKER}_${TIMEFRAME}_${START_DATE}_${END_DATE}_${PROFILE}"
fi

RAW_CANDLES="data/raw/tbank/${RUN_ID}.csv"

DATA_QUALITY_REPORT="reports/data_quality_${RUN_ID}.md"

DEBUG_CSV="out/debug_simple_all.csv"
DEBUG_CSV_RUN="out/debug_simple_all_${RUN_ID}.csv"
DEBUG_REPORT="reports/debug_report_${RUN_ID}.md"

BACKTEST_TRADES="out/backtest_trades_${RUN_ID}.csv"
BACKTEST_REPORT="reports/backtest_report_${RUN_ID}.md"

GRID_RESULTS="out/backtest_grid_results_${RUN_ID}.csv"
GRID_REPORT="reports/backtest_grid_report_${RUN_ID}.md"

WALKFORWARD_PERIOD_RESULTS_WEEK="out/walkforward_period_results_${RUN_ID}_week.csv"
WALKFORWARD_TRADES_WEEK="out/walkforward_trades_${RUN_ID}_week.csv"
WALKFORWARD_REPORT_WEEK="reports/walkforward_report_${RUN_ID}_week.md"

WALKFORWARD_GRID_RESULTS_DAY="out/walkforward_grid_results_${RUN_ID}_day.csv"
WALKFORWARD_GRID_REPORT_DAY="reports/walkforward_grid_report_${RUN_ID}_day.md"

WALKFORWARD_GRID_RESULTS_WEEK="out/walkforward_grid_results_${RUN_ID}_week.csv"
WALKFORWARD_GRID_REPORT_WEEK="reports/walkforward_grid_report_${RUN_ID}_week.md"

ARCHIVE_TS="$(date '+%Y%m%d_%H%M%S')"

ACTUAL_ARCHIVE="archives/latest/Actual_${RUN_ID}.zip"
ACTUAL_MANIFEST="archives/latest/Actual_${RUN_ID}.manifest.txt"

OLD_ARCHIVE="archives/old/research_${RUN_ID}_${ARCHIVE_TS}.zip"
OLD_MANIFEST="archives/old/research_${RUN_ID}_${ARCHIVE_TS}.manifest.txt"

# ============================================================
# Validate skip-load
# ============================================================
if [[ "${SKIP_LOAD}" == "true" ]] && [[ ! -f "${RAW_CANDLES}" ]]; then
  echo "Error: --skip-load was provided, but raw candles file does not exist:" >&2
  echo "  ${RAW_CANDLES}" >&2
  exit 1
fi

# ============================================================
# Create directories
# ============================================================
mkdir -p data/raw/tbank out reports archives/latest archives/old

# Resolve point_value_rub and tick_size (before header so it prints resolved values)
_resolve_point_value_rub
_resolve_tick_size

# ============================================================
# Header
# ============================================================
echo
echo "============================================================"
echo "MOEXF Hammer Research Pipeline"
echo "============================================================"
echo "Ticker:              ${TICKER}"
echo "Class code:          ${CLASS_CODE}"
echo "Timeframe:           ${TIMEFRAME}"
echo "Period:              ${START_DATE} -> ${END_DATE}"
echo "Profile:             ${PROFILE}"
echo "Run ID:              ${RUN_ID}"
echo "Point value RUB:     ${POINT_VALUE_RUB}"
echo "Tick size:           ${TICK_SIZE} (source: ${TICK_SIZE_SOURCE})"
echo "Slippage points:     ${SLIPPAGE_POINTS}"
[[ -n "${SLIPPAGE_TICKS}" ]] && echo "Slippage ticks:      ${SLIPPAGE_TICKS}"
echo "Grid slippage ticks: ${GRID_SLIPPAGE_TICKS_VALUES}"
echo "Direction filter:    ${DIRECTION_FILTER}"
echo "Skip load:           ${SKIP_LOAD}"
echo "Skip grid:           ${SKIP_GRID}"
echo "Skip walkfwd grid:   ${SKIP_WALKFORWARD_GRID}"
echo "Archive:             ${ARCHIVE}"
echo "============================================================"
echo

# ============================================================
# Step 1: Load candles
# ============================================================
if [[ "${SKIP_LOAD}" == "true" ]]; then
  echo
  echo "Step 1/9: Loading candles — SKIPPED (--skip-load)"
  echo "------------------------------------------------------------"
  echo "Using existing file: ${RAW_CANDLES}"
else
  echo
  echo "Step 1/9: Loading candles from T-Bank..."
  echo "------------------------------------------------------------"

  python scripts/load_tbank_candles.py \
    --ticker "${TICKER}" \
    --class-code "${CLASS_CODE}" \
    --from "${START_DATE}" \
    --to "${END_DATE}" \
    --timeframe "${TIMEFRAME}" \
    --env "${ENVIRONMENT}" \
    --output "${RAW_CANDLES}"
fi

# ============================================================
# Step 2: Data quality report
# ============================================================
echo
echo "Step 2/9: Generating data quality report..."
echo "------------------------------------------------------------"

python -m src.analytics.data_quality_report \
  --input "${RAW_CANDLES}" \
  --output "${DATA_QUALITY_REPORT}" \
  --timeframe "${TIMEFRAME}"

# ============================================================
# Step 3: HammerDetector
# ============================================================
echo
echo "Step 3/9: Running HammerDetector..."
echo "------------------------------------------------------------"

python -m src.main \
  --input "${RAW_CANDLES}" \
  --output "${DEBUG_CSV}" \
  --params "${PARAMS_FILE}" \
  --instrument "${TICKER}" \
  --timeframe "${TIMEFRAME}" \
  --profile "${PROFILE}" \
  --tick-size "${TICK_SIZE}" \
  --tick-size-source "${TICK_SIZE_SOURCE}"

cp "${DEBUG_CSV}" "${DEBUG_CSV_RUN}"

# ============================================================
# Step 4: Debug report
# ============================================================
echo
echo "Step 4/9: Generating debug report..."
echo "------------------------------------------------------------"

python -m src.analytics.debug_report \
  --input "${DEBUG_CSV_RUN}" \
  --output "${DEBUG_REPORT}"

# ============================================================
# Step 5: Single backtest
# ============================================================
echo
echo "Step 5/9: Running single backtest..."
echo "------------------------------------------------------------"

_slip_args=("--slippage-points" "${SLIPPAGE_POINTS}")
if [[ -n "${SLIPPAGE_TICKS}" ]]; then
  _slip_args+=("--slippage-ticks" "${SLIPPAGE_TICKS}" "--tick-size" "${TICK_SIZE}")
fi

python scripts/run_backtest.py \
  --input "${DEBUG_CSV_RUN}" \
  --trades-output "${BACKTEST_TRADES}" \
  --report-output "${BACKTEST_REPORT}" \
  --entry-mode "${ENTRY_MODE}" \
  --entry-horizon-bars "${ENTRY_HORIZON_BARS}" \
  --max-hold-bars "${MAX_HOLD_BARS}" \
  --take-r "${TAKE_R}" \
  --stop-buffer-points "${STOP_BUFFER_POINTS}" \
  "${_slip_args[@]}" \
  --point-value-rub "${POINT_VALUE_RUB}" \
  --commission-per-trade "${COMMISSION_PER_TRADE}" \
  --contracts "${CONTRACTS}" \
  --direction-filter "${DIRECTION_FILTER}"

# ============================================================
# Step 6: Grid backtest
# ============================================================
if [[ "${SKIP_GRID}" == "true" ]]; then
  echo
  echo "Step 6/9: Grid backtest — SKIPPED (--skip-grid)"
  echo "------------------------------------------------------------"
else
  echo
  echo "Step 6/9: Running grid backtest..."
  echo "------------------------------------------------------------"

  python scripts/run_backtest_grid.py \
    --input "${DEBUG_CSV_RUN}" \
    --output "${GRID_RESULTS}" \
    --report-output "${GRID_REPORT}" \
    --entry-modes "${GRID_ENTRY_MODES}" \
    --take-r-values "${GRID_TAKE_R_VALUES}" \
    --max-hold-bars-values "${GRID_MAX_HOLD_BARS_VALUES}" \
    --stop-buffer-points-values "${GRID_STOP_BUFFER_POINTS_VALUES}" \
    --slippage-ticks-values "${GRID_SLIPPAGE_TICKS_VALUES}" \
    --tick-size "${TICK_SIZE}" \
    --entry-horizon-bars "${ENTRY_HORIZON_BARS}" \
    --point-value-rub "${POINT_VALUE_RUB}" \
    --commission-per-trade "${COMMISSION_PER_TRADE}" \
    --contracts "${CONTRACTS}" \
    --direction-filter "${DIRECTION_FILTER}"
fi

# ============================================================
# Step 7: Weekly walk-forward
# ============================================================
echo
echo "Step 7/9: Running weekly walk-forward..."
echo "------------------------------------------------------------"

python scripts/run_walkforward.py \
  --input "${DEBUG_CSV_RUN}" \
  --period week \
  --period-results-output "${WALKFORWARD_PERIOD_RESULTS_WEEK}" \
  --trades-output "${WALKFORWARD_TRADES_WEEK}" \
  --report-output "${WALKFORWARD_REPORT_WEEK}" \
  --entry-mode "${ENTRY_MODE}" \
  --entry-horizon-bars "${ENTRY_HORIZON_BARS}" \
  --max-hold-bars "${MAX_HOLD_BARS}" \
  --take-r "${TAKE_R}" \
  --stop-buffer-points "${STOP_BUFFER_POINTS}" \
  "${_slip_args[@]}" \
  --point-value-rub "${POINT_VALUE_RUB}" \
  --commission-per-trade "${COMMISSION_PER_TRADE}" \
  --contracts "${CONTRACTS}" \
  --direction-filter "${DIRECTION_FILTER}"

# ============================================================
# Steps 8-9: Walk-forward grid
# ============================================================
if [[ "${SKIP_WALKFORWARD_GRID}" == "true" ]]; then
  echo
  echo "Step 8/9: Daily walk-forward grid — SKIPPED (--skip-walkforward-grid)"
  echo "------------------------------------------------------------"
  echo
  echo "Step 9/9: Weekly walk-forward grid — SKIPPED (--skip-walkforward-grid)"
  echo "------------------------------------------------------------"
else
  echo
  echo "Step 8/9: Running daily walk-forward grid..."
  echo "------------------------------------------------------------"

  python scripts/run_walkforward_grid.py \
    --input "${DEBUG_CSV_RUN}" \
    --period day \
    --output "${WALKFORWARD_GRID_RESULTS_DAY}" \
    --report-output "${WALKFORWARD_GRID_REPORT_DAY}" \
    --entry-modes "${GRID_ENTRY_MODES}" \
    --take-r-values "${GRID_TAKE_R_VALUES}" \
    --max-hold-bars-values "${GRID_MAX_HOLD_BARS_VALUES}" \
    --stop-buffer-points-values "${GRID_STOP_BUFFER_POINTS_VALUES}" \
    --slippage-ticks-values "${GRID_SLIPPAGE_TICKS_VALUES}" \
    --tick-size "${TICK_SIZE}" \
    --entry-horizon-bars "${ENTRY_HORIZON_BARS}" \
    --point-value-rub "${POINT_VALUE_RUB}" \
    --commission-per-trade "${COMMISSION_PER_TRADE}" \
    --contracts "${CONTRACTS}" \
    --direction-filter "${DIRECTION_FILTER}"

  echo
  echo "Step 9/9: Running weekly walk-forward grid..."
  echo "------------------------------------------------------------"

  python scripts/run_walkforward_grid.py \
    --input "${DEBUG_CSV_RUN}" \
    --period week \
    --output "${WALKFORWARD_GRID_RESULTS_WEEK}" \
    --report-output "${WALKFORWARD_GRID_REPORT_WEEK}" \
    --entry-modes "${GRID_ENTRY_MODES}" \
    --take-r-values "${GRID_TAKE_R_VALUES}" \
    --max-hold-bars-values "${GRID_MAX_HOLD_BARS_VALUES}" \
    --stop-buffer-points-values "${GRID_STOP_BUFFER_POINTS_VALUES}" \
    --slippage-ticks-values "${GRID_SLIPPAGE_TICKS_VALUES}" \
    --tick-size "${TICK_SIZE}" \
    --entry-horizon-bars "${ENTRY_HORIZON_BARS}" \
    --point-value-rub "${POINT_VALUE_RUB}" \
    --commission-per-trade "${COMMISSION_PER_TRADE}" \
    --contracts "${CONTRACTS}" \
    --direction-filter "${DIRECTION_FILTER}"
fi

# ============================================================
# Summary
# ============================================================
echo
echo "============================================================"
echo "Pipeline completed successfully"
echo "============================================================"
echo
echo "Generated files:"
echo
echo "Raw candles:"
echo "  ${RAW_CANDLES}"
echo
echo "Data quality:"
echo "  ${DATA_QUALITY_REPORT}"
echo
echo "Debug:"
echo "  ${DEBUG_CSV}"
echo "  ${DEBUG_CSV_RUN}"
echo "  ${DEBUG_REPORT}"
echo
echo "Backtest:"
echo "  ${BACKTEST_TRADES}"
echo "  ${BACKTEST_REPORT}"
echo

if [[ "${SKIP_GRID}" == "false" ]]; then
  echo "Grid:"
  echo "  ${GRID_RESULTS}"
  echo "  ${GRID_REPORT}"
  echo
fi

echo "Walk-forward:"
echo "  ${WALKFORWARD_PERIOD_RESULTS_WEEK}"
echo "  ${WALKFORWARD_TRADES_WEEK}"
echo "  ${WALKFORWARD_REPORT_WEEK}"
echo

if [[ "${SKIP_WALKFORWARD_GRID}" == "false" ]]; then
  echo "Walk-forward grid:"
  echo "  ${WALKFORWARD_GRID_RESULTS_DAY}"
  echo "  ${WALKFORWARD_GRID_REPORT_DAY}"
  echo "  ${WALKFORWARD_GRID_RESULTS_WEEK}"
  echo "  ${WALKFORWARD_GRID_REPORT_WEEK}"
  echo
fi

echo "Next recommended files to inspect:"
echo "  ${DATA_QUALITY_REPORT}"
echo "  ${DEBUG_REPORT}"
echo "  ${BACKTEST_REPORT}"
[[ "${SKIP_GRID}" == "false" ]]              && echo "  ${GRID_REPORT}"
echo "  ${WALKFORWARD_REPORT_WEEK}"
[[ "${SKIP_WALKFORWARD_GRID}" == "false" ]] && echo "  ${WALKFORWARD_GRID_REPORT_DAY}"
[[ "${SKIP_WALKFORWARD_GRID}" == "false" ]] && echo "  ${WALKFORWARD_GRID_REPORT_WEEK}"
[[ "${ARCHIVE}" == "true" ]]                && echo "  ${ACTUAL_ARCHIVE}  (latest archive)"
echo

# ============================================================
# Archive
# ============================================================
if [[ "${ARCHIVE}" == "true" ]]; then
  echo "------------------------------------------------------------"
  echo "Creating archive..."
  echo "------------------------------------------------------------"

  ARCHIVE_CANDIDATES=(
    "${RAW_CANDLES}"
    "${DEBUG_CSV_RUN}"
    "${BACKTEST_TRADES}"
    "${BACKTEST_REPORT}"
    "${DATA_QUALITY_REPORT}"
    "${DEBUG_REPORT}"
    "${GRID_RESULTS}"
    "${GRID_REPORT}"
    "${WALKFORWARD_PERIOD_RESULTS_WEEK}"
    "${WALKFORWARD_TRADES_WEEK}"
    "${WALKFORWARD_REPORT_WEEK}"
    "${WALKFORWARD_GRID_RESULTS_DAY}"
    "${WALKFORWARD_GRID_REPORT_DAY}"
    "${WALKFORWARD_GRID_RESULTS_WEEK}"
    "${WALKFORWARD_GRID_REPORT_WEEK}"
  )

  ARCHIVE_FILES=()
  for f in "${ARCHIVE_CANDIDATES[@]}"; do
    [[ -f "${f}" ]] && ARCHIVE_FILES+=("${f}")
  done

  if [[ ${#ARCHIVE_FILES[@]} -eq 0 ]]; then
    echo "Warning: no output files found to archive." >&2
  else
    # Create manifest
    {
      echo "Run ID: ${RUN_ID}"
      echo "Created at: $(date '+%Y-%m-%dT%H:%M:%S%z')"
      echo "Ticker: ${TICKER}"
      echo "Class code: ${CLASS_CODE}"
      echo "Timeframe: ${TIMEFRAME}"
      echo "Period: ${START_DATE} -> ${END_DATE}"
      echo "Profile: ${PROFILE}"
      echo "Direction filter: ${DIRECTION_FILTER}"
      echo "Point value RUB: ${POINT_VALUE_RUB}"
      echo "Tick size: ${TICK_SIZE}"
      echo "Tick size source: ${TICK_SIZE_SOURCE}"
      echo "Slippage points: ${SLIPPAGE_POINTS}"
      [[ -n "${SLIPPAGE_TICKS}" ]] && echo "Slippage ticks: ${SLIPPAGE_TICKS}"
      echo "Grid slippage ticks values: ${GRID_SLIPPAGE_TICKS_VALUES}"
      echo "Skip load: ${SKIP_LOAD}"
      echo "Skip grid: ${SKIP_GRID}"
      echo "Skip walkforward grid: ${SKIP_WALKFORWARD_GRID}"
      echo ""
      echo "Files included:"
      for f in "${ARCHIVE_FILES[@]}"; do
        echo "- ${f}"
      done
    } > "${OLD_MANIFEST}"

    zip "${OLD_ARCHIVE}" "${ARCHIVE_FILES[@]}"

    cp "${OLD_ARCHIVE}"   "${ACTUAL_ARCHIVE}"
    cp "${OLD_MANIFEST}"  "${ACTUAL_MANIFEST}"

    echo
    echo "Archive created:"
    echo "  Latest:      ${ACTUAL_ARCHIVE}"
    echo "  Timestamped: ${OLD_ARCHIVE}"
    echo
    echo "Manifest:"
    echo "  Latest:      ${ACTUAL_MANIFEST}"
    echo "  Timestamped: ${OLD_MANIFEST}"
    echo
    echo "Files included: ${#ARCHIVE_FILES[@]}"
  fi
else
  echo "(Archive skipped: --no-archive)"
fi

echo
