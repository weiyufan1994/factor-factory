#!/usr/bin/env bash
set -euo pipefail

OUT_ROOT=/tmp/moneyflow_v18a_other_universes_20260613
RESULT_DIR=${OUT_ROOT}/results
SCRIPT_DIR=/tmp/moneyflow_v18_scripts
S3_ROOT=s3://yufan-data-lake/factorforge/tmp/moneyflow_v18_20260613
INDEX_ROOT=/tmp/factorforge_index_weight_universe_v1
WORKSPACE=/home/ubuntu/factorforge
DAILY_CLEAN=/home/ubuntu/.openclaw/workspace/factorforge/data/clean/daily_clean.parquet

mkdir -p "$OUT_ROOT" "$RESULT_DIR" "$SCRIPT_DIR" "$INDEX_ROOT" "$(dirname "$DAILY_CLEAN")"

aws s3 cp "${S3_ROOT}/research_moneyflow_v11_datamart_eval.py" "${SCRIPT_DIR}/research_moneyflow_v11_datamart_eval.py"
python3 -m py_compile "${SCRIPT_DIR}/research_moneyflow_v11_datamart_eval.py"

if [[ ! -f "$DAILY_CLEAN" ]]; then
  aws s3 cp s3://yufan-data-lake/factorforge/datamart/clean_daily_bar/v1/daily_clean.parquet "$DAILY_CLEAN"
fi

index_n="$(find "$INDEX_ROOT" -mindepth 1 -maxdepth 1 -type d -name 'trade_date=*' 2>/dev/null | wc -l | tr -d ' ')"
echo "INDEX_PARTITIONS_BEFORE=${index_n}"
if [[ "${index_n:-0}" -lt 2312 ]]; then
  aws s3 cp --recursive s3://yufan-data-lake/factorforge/datamart/index_weight_universe/v1 "$INDEX_ROOT"
fi
echo "INDEX_PARTITIONS_AFTER=$(find "$INDEX_ROOT" -mindepth 1 -maxdepth 1 -type d -name 'trade_date=*' 2>/dev/null | wc -l | tr -d ' ')"

export PYTHONPATH=/home/ubuntu/factorforge:/home/ubuntu/.openclaw/workspace/factorforge:${PYTHONPATH:-}

rm -rf "$RESULT_DIR"
mkdir -p "$RESULT_DIR"
cd "$WORKSPACE"

python3 "${SCRIPT_DIR}/research_moneyflow_v11_datamart_eval.py" \
  --chunk-by-year \
  --moments-root /opt/factorforge/data-api-datamarts/intraday_flow_distribution_moments_v1_is \
  --flow-root /opt/factorforge/data-api-datamarts/intraday_flow_state_v2_is \
  --daily-basic-root /opt/factorforge/data-api-datamarts/daily_basic_backtest_base_is \
  --daily-clean "$DAILY_CLEAN" \
  --index-universe-root "$INDEX_ROOT" \
  --output-dir "$RESULT_DIR" \
  --start-date 20160104 \
  --end-date 20250711 \
  --cutoff-time 14:50 \
  --horizons 1,3,5 \
  --portfolio-horizons 1 \
  --cost-bps 20 \
  --laws miller_flow_v18a_absolute_long_edge_gate_v1 \
  --portfolio-policies daily_top10_equal,rebalance5_top10_equal,top10_dropout30_rebalance5_equal \
  --universes csi800,csi800_csi1000,largest_10

aws s3 cp --recursive "$RESULT_DIR" "${S3_ROOT}/v18a_other_universes_results/"
echo "DONE_$(date -u +%Y-%m-%dT%H:%M:%SZ)"
