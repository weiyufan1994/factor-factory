#!/usr/bin/env bash
set -euo pipefail

ROOT="/home/ubuntu/.openclaw/workspace/repos/quant_self/tushare数据获取"
PYTHON_BIN="/home/ubuntu/miniconda3/envs/rdagent/bin/python"
LOG_ROOT="/home/ubuntu/tushare_logs"
TODAY="$(TZ=Asia/Shanghai date +%Y%m%d)"
YEAR="$(TZ=Asia/Shanghai date +%Y)"
LAST_YEAR_START="$((YEAR - 1))0101"

mkdir -p "$LOG_ROOT"
cd "$ROOT"

run_with_lock() {
  local lock_name="$1"
  shift
  /usr/bin/flock -n "/tmp/${lock_name}.lock" "$@"
}

latest_open_trade_date() {
  "$PYTHON_BIN" - <<'PY'
import pandas as pd
from datetime import datetime
from pathlib import Path

root = Path("/home/ubuntu/.openclaw/workspace/repos/quant_self/tushare数据获取")
today = datetime.now().strftime("%Y%m%d")
cal = pd.read_csv(root / "trade_cal.csv", dtype=str)
open_days = cal[(cal["is_open"] == "1") & (cal["cal_date"] <= today)]["cal_date"]
if open_days.empty:
    raise SystemExit("no open trade date found")
print(open_days.max())
PY
}

case "${1:-}" in
  daily)
    run_with_lock tushare_daily_self_update \
      "$PYTHON_BIN" ./23_tushare_ec2_daily_self_update.py --end-date "$TODAY" \
      >> "$LOG_ROOT/daily_self_update.log" 2>&1
    ;;
  close-core)
    run_with_lock tushare_close_core \
      "$PYTHON_BIN" ./22_tushare_nonminute_to_s3.py \
        --only limit_list_d dc_concept ths_index ths_member dc_index dc_member dc_concept_cons \
          moneyflow moneyflow_ths moneyflow_dc moneyflow_cnt_ths moneyflow_ind_ths moneyflow_ind_dc moneyflow_mkt_dc \
          hm_list kpl_list kpl_concept_cons cyq_perf stk_factor_pro broker_recommend margin margin_detail \
        --end-date "$TODAY" --recent-days 3 --overwrite-existing --max-per-minute 60 \
      >> "$LOG_ROOT/close_core.log" 2>&1
    ;;
  hot)
    run_with_lock tushare_ths_hot \
      "$PYTHON_BIN" ./22_tushare_nonminute_to_s3.py \
        --only ths_hot --end-date "$TODAY" --recent-days 1 --overwrite-existing --max-per-minute 60 \
      >> "$LOG_ROOT/ths_hot.log" 2>&1
    ;;
  report-rc)
    run_with_lock tushare_report_rc \
      "$PYTHON_BIN" ./22_tushare_nonminute_to_s3.py \
        --only report_rc --end-date "$TODAY" --recent-days 3 --overwrite-existing --max-per-minute 2 \
      >> "$LOG_ROOT/report_rc.log" 2>&1
    ;;
  finance)
    run_with_lock tushare_finance \
      "$PYTHON_BIN" ./22_tushare_nonminute_to_s3.py \
        --only income_vip balancesheet_vip cashflow_vip forecast_vip express_vip fina_indicator_vip fina_mainbz_vip disclosure_date \
        --start-date "$LAST_YEAR_START" --end-date "$TODAY" --overwrite-existing --max-per-minute 60 \
      >> "$LOG_ROOT/finance.log" 2>&1
    ;;
  chips)
    run_with_lock tushare_chips \
      "$PYTHON_BIN" ./22_tushare_nonminute_to_s3.py \
        --only cyq_chips --end-date "$TODAY" --recent-days 1 --overwrite-existing --max-per-minute 30 \
      >> "$LOG_ROOT/chips.log" 2>&1
    ;;
  minute-daily)
    TRADE_DATE="$(latest_open_trade_date)"
    run_with_lock tushare_minute_daily \
      "$PYTHON_BIN" ./19_stk_mins_incremental_to_s3.py \
        --trade-date "$TRADE_DATE" --max-per-minute 380 --base-sleep 0.15 \
      >> "$LOG_ROOT/minute_daily.log" 2>&1
    ;;
  *)
    echo "usage: $0 {daily|close-core|hot|report-rc|finance|chips|minute-daily}" >&2
    exit 2
    ;;
esac
