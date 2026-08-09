#!/usr/bin/env bash
set -euo pipefail

ROOT="${ROOT:-/tmp/moneyflow_oos_feature_validation_full_v18a_20260614}"
DATA_API_REPO="${DATA_API_REPO:-/opt/factorforge/factorforge-data-api}"
WORKSPACE="${WORKSPACE:-/home/ubuntu/factorforge}"
SCRIPT_DIR="${SCRIPT_DIR:-/tmp/moneyflow_v18_scripts}"
CATALOG="${CATALOG:-/opt/factorforge/data-api-config/data_catalog.moneyflow_v9_v10_is.json}"
PRIOR_THRESHOLD_ROOT="${PRIOR_THRESHOLD_ROOT:-${ROOT}/intraday_flow_prior_thresholds_oos}"
MOMENTS_ROOT="${MOMENTS_ROOT:-${ROOT}/intraday_flow_distribution_moments_v1_oos}"
DAILY_BASIC_ROOT="${DAILY_BASIC_ROOT:-${ROOT}/daily_basic_backtest_base_oos}"
RESULT_DIR="${RESULT_DIR:-${ROOT}/results}"
CLEAN_LOCAL="${CLEAN_LOCAL:-/tmp/moneyflow_oos_feature_validation_pilot_20260614/daily_clean_latest.parquet}"
INDEX_ROOT="${INDEX_ROOT:-/tmp/factorforge_index_weight_universe_v1}"
RESULT_S3="${RESULT_S3:-s3://yufan-data-lake/factorforge/tmp/moneyflow_v18_20260613/oos_feature_validation_full_v18a_results}"

RESUME_START="${RESUME_START:-20260408}"
OOS_END="${OOS_END:-20260526}"
FULL_START="${FULL_START:-20250714}"
IS_END_DATE="${IS_END_DATE:-20250711}"
LAWS="${LAWS:-miller_flow_v18a_absolute_long_edge_gate_v1}"
UNIVERSES="${UNIVERSES:-full,middle_10_80,fixed_small_20}"
HORIZONS="${HORIZONS:-1}"
LOG_PATH="${LOG_PATH:-${ROOT}/moneyflow_oos_feature_validation_resume_worker.log}"

mkdir -p "${RESULT_DIR}"
exec > >(tee -a "${LOG_PATH}") 2>&1
trap 'rc=$?; echo "RESUME_FAILED_STAGE=${CURRENT_STAGE:-unknown} LINE=${LINENO} RC=${rc}"; exit ${rc}' ERR
stage() {
  CURRENT_STAGE="$1"
  date -u +"RESUME_STAGE_${CURRENT_STAGE}_%Y-%m-%dT%H:%M:%SZ"
}

stage build_remaining_distribution_moments
python3 "${DATA_API_REPO}/scripts/build_intraday_datamarts.py" \
  --catalog "${CATALOG}" \
  --output-root "${MOMENTS_ROOT}" \
  --start "${RESUME_START}" \
  --end "${OOS_END}" \
  --dataset intraday_flow_distribution_moments_v1 \
  --prior-threshold-root "${PRIOR_THRESHOLD_ROOT}" \
  --qa-output "${ROOT}/intraday_flow_distribution_moments_v1_oos.resume.qa.json" \
  --catalog-output "${ROOT}/intraday_flow_distribution_moments_v1_oos.resume.catalog.json" \
  --is-end-date "${IS_END_DATE}" \
  --chunk-days 1 \
  --overwrite

stage validate_full_oos_features
cd "${WORKSPACE}"
export PYTHONPATH="${WORKSPACE}:${SCRIPT_DIR}:${PYTHONPATH:-}"
python3 "${SCRIPT_DIR}/validate_moneyflow_feature_candidate.py" \
  --moments-root "${MOMENTS_ROOT}" \
  --daily-basic-root "${DAILY_BASIC_ROOT}" \
  --daily-clean "${CLEAN_LOCAL}" \
  --index-universe-root "${INDEX_ROOT}" \
  --output-dir "${RESULT_DIR}" \
  --start-date "${FULL_START}" \
  --end-date "${OOS_END}" \
  --cutoff-time 14:50 \
  --horizons "${HORIZONS}" \
  --laws "${LAWS}" \
  --universes "${UNIVERSES}"

stage write_resume_summary
python3 - "${ROOT}" "${RESULT_DIR}" "${RESUME_START}" "${OOS_END}" <<'PY'
import json
import sys
from pathlib import Path

root = Path(sys.argv[1])
result = Path(sys.argv[2])
payload = {
    "verdict": "ACCEPT",
    "scope": "research_side_oos_full_v18a_resume",
    "resume_start": sys.argv[3],
    "oos_end": sys.argv[4],
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
(root / "moneyflow_oos_feature_validation_full_v18a_resume_summary.json").write_text(
    json.dumps(payload, indent=2, sort_keys=True),
    encoding="utf-8",
)
print(json.dumps(payload, indent=2, sort_keys=True))
PY

stage upload_result_files
aws s3 cp --only-show-errors --recursive "${RESULT_DIR}" "${RESULT_S3}/results/"
aws s3 cp --only-show-errors "${ROOT}/moneyflow_oos_feature_validation_full_v18a_resume_summary.json" "${RESULT_S3}/"
aws s3 cp --only-show-errors "${ROOT}/intraday_flow_distribution_moments_v1_oos.resume.qa.json" "${RESULT_S3}/"
aws s3 cp --only-show-errors "${ROOT}/intraday_flow_distribution_moments_v1_oos.resume.catalog.json" "${RESULT_S3}/"
date -u +"RESUME_DONE_%Y-%m-%dT%H:%M:%SZ"
