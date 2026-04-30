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
  *)
    echo "usage: $0 {daily|close-core|hot|report-rc|finance|chips}" >&2
    exit 2
    ;;
esac
