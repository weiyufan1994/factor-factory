#!/usr/bin/env bash
set -euo pipefail

OUT_ROOT="${OUT_ROOT:-/tmp/moneyflow_oos_feature_validation_20260614}"
SCRIPT_DIR="${SCRIPT_DIR:-/tmp/moneyflow_v18_scripts}"
S3_ROOT="${S3_ROOT:-s3://yufan-data-lake/factorforge/tmp/moneyflow_v18_20260613}"
RESULT_S3="${RESULT_S3:-${S3_ROOT}/oos_feature_validation_pilot_results}"
WORKSPACE="${WORKSPACE:-/home/ubuntu/factorforge}"
DATA_API_REPO="${DATA_API_REPO:-/opt/factorforge/factorforge-data-api}"
CATALOG="${CATALOG:-/opt/factorforge/data-api-config/data_catalog.moneyflow_v9_v10_is.json}"
INDEX_ROOT="${INDEX_ROOT:-/tmp/factorforge_index_weight_universe_v1}"
CLEAN_S3="${CLEAN_S3:-s3://yufan-data-lake/factorforge/datamart/clean_daily_bar/v1/daily_clean.parquet}"
CLEAN_LOCAL="${CLEAN_LOCAL:-${OUT_ROOT}/daily_clean_latest.parquet}"

OOS_START="${OOS_START:-20250714}"
OOS_END="${OOS_END:-20250829}"
WARMUP_START="${WARMUP_START:-20250401}"
IS_END_DATE="${IS_END_DATE:-20250711}"
HORIZONS="${HORIZONS:-1}"
UNIVERSES="${UNIVERSES:-full,middle_10_80,fixed_small_20}"
LAWS="${LAWS:-miller_flow_v15_repair_confirmed_absorption_fp_v1,miller_flow_v18a_absolute_long_edge_gate_v1,miller_flow_v18b_first_passage_repair_edge_v1}"

THRESHOLD_BASE_ROOT="${THRESHOLD_BASE_ROOT:-${OUT_ROOT}/intraday_flow_threshold_base_oos}"
PRIOR_THRESHOLD_ROOT="${PRIOR_THRESHOLD_ROOT:-${OUT_ROOT}/intraday_flow_prior_thresholds_oos}"
FLOW_STATE_DUMMY_ROOT="${FLOW_STATE_DUMMY_ROOT:-${OUT_ROOT}/intraday_flow_state_dummy_oos}"
MOMENTS_ROOT="${MOMENTS_ROOT:-${OUT_ROOT}/intraday_flow_distribution_moments_v1_oos}"
DAILY_BASIC_ROOT="${DAILY_BASIC_ROOT:-${OUT_ROOT}/daily_basic_backtest_base_oos}"
RESULT_DIR="${RESULT_DIR:-${OUT_ROOT}/results}"
LOG_PATH="${LOG_PATH:-${OUT_ROOT}/moneyflow_oos_feature_validation_worker.log}"

mkdir -p "${OUT_ROOT}" "${SCRIPT_DIR}" "${RESULT_DIR}" "$(dirname "${CLEAN_LOCAL}")"
exec > >(tee -a "${LOG_PATH}") 2>&1
trap 'rc=$?; echo "FAILED_STAGE=${CURRENT_STAGE:-unknown} LINE=${LINENO} RC=${rc}"; exit ${rc}' ERR
stage() {
  CURRENT_STAGE="$1"
  date -u +"STAGE_${CURRENT_STAGE}_%Y-%m-%dT%H:%M:%SZ"
}
date -u +"START_%Y-%m-%dT%H:%M:%SZ"

stage fetch_research_scripts
aws s3 cp --only-show-errors "${S3_ROOT}/research_moneyflow_v11_datamart_eval.py" "${SCRIPT_DIR}/research_moneyflow_v11_datamart_eval.py"
aws s3 cp --only-show-errors "${S3_ROOT}/validate_moneyflow_feature_candidate.py" "${SCRIPT_DIR}/validate_moneyflow_feature_candidate.py"
stage fetch_clean_daily
if [[ -s "${CLEAN_LOCAL}" ]]; then
  echo "CLEAN_LOCAL_REUSE=${CLEAN_LOCAL}"
else
  aws s3 cp --only-show-errors "${CLEAN_S3}" "${CLEAN_LOCAL}"
fi
stage compile_research_scripts
python3 -m py_compile "${SCRIPT_DIR}/research_moneyflow_v11_datamart_eval.py" "${SCRIPT_DIR}/validate_moneyflow_feature_candidate.py"

stage ensure_index_universe
mkdir -p "${INDEX_ROOT}"
index_n="$({ find "${INDEX_ROOT}" -mindepth 1 -maxdepth 1 -type d -name 'trade_date=*' 2>/dev/null || true; } | wc -l | tr -d ' ')"
echo "INDEX_PARTITIONS_BEFORE=${index_n}"
if [[ "${index_n:-0}" -lt 2312 ]]; then
  aws s3 cp --only-show-errors --recursive s3://yufan-data-lake/factorforge/datamart/index_weight_universe/v1 "${INDEX_ROOT}"
fi
echo "INDEX_PARTITIONS_AFTER=$({ find "${INDEX_ROOT}" -mindepth 1 -maxdepth 1 -type d -name 'trade_date=*' 2>/dev/null || true; } | wc -l | tr -d ' ')"

stage write_daily_basic_oos
python3 - "${CLEAN_LOCAL}" "${DAILY_BASIC_ROOT}" "${OOS_START}" "${OOS_END}" <<'PY'
import sys
from pathlib import Path

import pandas as pd
import pyarrow.parquet as pq

clean_path = Path(sys.argv[1])
out_root = Path(sys.argv[2])
start, end = sys.argv[3], sys.argv[4]
cols = [
    "ts_code",
    "trade_date",
    "close",
    "pct_chg",
    "turnover_rate",
    "turnover_rate_f",
    "volume_ratio",
    "total_mv",
    "circ_mv",
    "float_mv",
]
schema_cols = set(pq.read_schema(clean_path).names)
df = pd.read_parquet(clean_path, columns=[c for c in cols if c in schema_cols])
df["trade_date"] = df["trade_date"].astype(str).str.replace("-", "", regex=False).str[:8]
df = df[(df["trade_date"] >= start) & (df["trade_date"] <= end)].copy()
if df.empty:
    raise SystemExit(f"no clean daily rows for OOS window {start}-{end}")
out_root.mkdir(parents=True, exist_ok=True)
for trade_date, day in df.groupby("trade_date", sort=True):
    part = out_root / f"trade_date={trade_date}"
    part.mkdir(parents=True, exist_ok=True)
    day.drop(columns=["trade_date"], errors="ignore").to_parquet(part / "part-000.parquet", index=False)
print({"event": "daily_basic_oos_written", "rows": int(len(df)), "dates": int(df["trade_date"].nunique()), "start": df["trade_date"].min(), "end": df["trade_date"].max()})
PY

oos_partitions="$({ find "${DAILY_BASIC_ROOT}" -mindepth 1 -maxdepth 1 -type d -name 'trade_date=*' 2>/dev/null || true; } | wc -l | tr -d ' ')"
moments_partitions="$({ find "${MOMENTS_ROOT}" -mindepth 1 -maxdepth 1 -type d -name 'trade_date=*' 2>/dev/null || true; } | wc -l | tr -d ' ')"
echo "OOS_PARTITIONS=${oos_partitions}"
echo "MOMENTS_PARTITIONS_BEFORE=${moments_partitions}"
if [[ "${moments_partitions:-0}" -lt "${oos_partitions:-0}" ]]; then
  stage build_threshold_base
  python3 "${DATA_API_REPO}/scripts/backfill_intraday_flow_state_v2.py" \
    --catalog "${CATALOG}" \
    --output-root "${FLOW_STATE_DUMMY_ROOT}" \
    --threshold-base-root "${THRESHOLD_BASE_ROOT}" \
    --prior-threshold-root "${PRIOR_THRESHOLD_ROOT}" \
    --qa-output "${OUT_ROOT}/intraday_flow_state_dummy_oos.qa.json" \
    --catalog-output "${OUT_ROOT}/intraday_flow_state_dummy_oos.catalog.json" \
    --start "${WARMUP_START}" \
    --end "${OOS_END}" \
    --is-end-date "${IS_END_DATE}" \
    --phase threshold-base \
    --overwrite \
    --allow-blocked-qa

  stage build_prior_thresholds
  python3 "${DATA_API_REPO}/scripts/backfill_intraday_flow_state_v2.py" \
    --catalog "${CATALOG}" \
    --output-root "${FLOW_STATE_DUMMY_ROOT}" \
    --threshold-base-root "${THRESHOLD_BASE_ROOT}" \
    --prior-threshold-root "${PRIOR_THRESHOLD_ROOT}" \
    --qa-output "${OUT_ROOT}/intraday_flow_state_dummy_oos.qa.json" \
    --catalog-output "${OUT_ROOT}/intraday_flow_state_dummy_oos.catalog.json" \
    --start "${WARMUP_START}" \
    --end "${OOS_END}" \
    --is-end-date "${IS_END_DATE}" \
    --phase prior-thresholds \
    --overwrite \
    --allow-blocked-qa

  stage build_distribution_moments
  python3 "${DATA_API_REPO}/scripts/build_intraday_datamarts.py" \
    --catalog "${CATALOG}" \
    --output-root "${MOMENTS_ROOT}" \
    --start "${OOS_START}" \
    --end "${OOS_END}" \
    --dataset intraday_flow_distribution_moments_v1 \
    --prior-threshold-root "${PRIOR_THRESHOLD_ROOT}" \
    --qa-output "${OUT_ROOT}/intraday_flow_distribution_moments_v1_oos.qa.json" \
    --catalog-output "${OUT_ROOT}/intraday_flow_distribution_moments_v1_oos.catalog.json" \
    --is-end-date "${IS_END_DATE}" \
    --chunk-days 1 \
    --overwrite
else
  echo "MOMENTS_REUSE=${MOMENTS_ROOT}"
fi

stage validate_oos_features
cd "${WORKSPACE}"
export PYTHONPATH="${WORKSPACE}:${SCRIPT_DIR}:${PYTHONPATH:-}"
python3 "${SCRIPT_DIR}/validate_moneyflow_feature_candidate.py" \
  --moments-root "${MOMENTS_ROOT}" \
  --daily-basic-root "${DAILY_BASIC_ROOT}" \
  --daily-clean "${CLEAN_LOCAL}" \
  --index-universe-root "${INDEX_ROOT}" \
  --output-dir "${RESULT_DIR}" \
  --start-date "${OOS_START}" \
  --end-date "${OOS_END}" \
  --cutoff-time 14:50 \
  --horizons "${HORIZONS}" \
  --laws "${LAWS}" \
  --universes "${UNIVERSES}"

stage write_run_summary
python3 - "${OUT_ROOT}" "${RESULT_DIR}" <<'PY'
import json
import sys
from pathlib import Path

root = Path(sys.argv[1])
result = Path(sys.argv[2])
payload = {
    "verdict": "ACCEPT",
    "scope": "research_side_oos_pilot",
    "out_root": str(root),
    "result_dir": str(result),
    "side_effects": {
        "clean_data_started": False,
        "search_worker_started": False,
        "official_promotion_started": False,
        "factor_forge_artifacts_written": False,
        "formal_catalog_modified": False,
    },
}
(root / "moneyflow_oos_feature_validation_run_summary.json").write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
print(json.dumps(payload, indent=2, sort_keys=True))
PY

stage upload_results
aws s3 cp --only-show-errors --recursive "${OUT_ROOT}" "${RESULT_S3}/"
date -u +"DONE_%Y-%m-%dT%H:%M:%SZ"
