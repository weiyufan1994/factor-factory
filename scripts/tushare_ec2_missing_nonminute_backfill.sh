#!/usr/bin/env bash
set -euo pipefail

ROOT="/home/ubuntu/.openclaw/workspace/repos/quant_self/tushare数据获取"
PYTHON_BIN="/home/ubuntu/miniconda3/envs/rdagent/bin/python"
LOG="/home/ubuntu/tushare_logs/nonminute_missing_backfill_20240101_20260421.log"
PID_FILE="/home/ubuntu/tushare_ec2_daily_self_update.pid"

mkdir -p /home/ubuntu/tushare_logs

if [ -s "$PID_FILE" ]; then
  DAILY_PID="$(cat "$PID_FILE")"
  while kill -0 "$DAILY_PID" 2>/dev/null; do
    echo "[$(date -Is)] waiting for daily catchup pid=$DAILY_PID" >> "$LOG"
    sleep 60
  done
fi

cd "$ROOT"
exec /usr/bin/flock -n /tmp/tushare_nonminute_missing_backfill.lock \
  "$PYTHON_BIN" ./22_tushare_nonminute_to_s3.py \
    --only moneyflow moneyflow_ths moneyflow_dc moneyflow_cnt_ths moneyflow_ind_ths moneyflow_ind_dc moneyflow_mkt_dc dc_concept_cons margin margin_detail \
    --start-date 20240101 --end-date 20260421 --overwrite-existing --max-per-minute 45 \
  >> "$LOG" 2>&1
