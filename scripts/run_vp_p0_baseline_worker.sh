#!/usr/bin/env bash
set -euo pipefail

RUN_ID="${RUN_ID:-vp_p0_baseline_20260612_full}"
WORKSPACE="${WORKSPACE:-/home/ubuntu/.openclaw/workspace/factorforge}"
SCRIPT_S3="${SCRIPT_S3:-s3://yufan-data-lake/factorforge/tmp/vp_p0_baseline_20260612/research_vp_p0_baseline_eval.py}"
DAILY_S3="${DAILY_S3:-s3://yufan-data-lake/factorforge/datamart/clean_daily_bar/v1/daily_clean.parquet}"
VP_S3="${VP_S3:-s3://yufan-data-lake/factorforge/datamart/intraday_value_occupation_state/v1}"
UPLOAD_S3="${UPLOAD_S3:-s3://yufan-data-lake/factorforge/tmp/vp_p0_baseline_20260612/full}"
VP_ROOT="${VP_ROOT:-/tmp/factorforge_vp_p0_datamart_v1}"
OUT_DIR="${OUT_DIR:-/tmp/factorforge_vp_p0_baseline_full_20260612}"
DAILY_CLEAN="${DAILY_CLEAN:-${WORKSPACE}/data/clean/daily_clean.parquet}"

mkdir -p "${WORKSPACE}/scripts" "${WORKSPACE}/data/clean" "${VP_ROOT}" "${OUT_DIR}"
LOG_FILE="${OUT_DIR}/run.log"
exec > >(tee -a "${LOG_FILE}") 2>&1

date -u +"[START] %Y-%m-%dT%H:%M:%SZ"
echo "[RUN_ID] ${RUN_ID}"
echo "[WORKSPACE] ${WORKSPACE}"
echo "[DISK_BEFORE]"
df -h / /tmp "${WORKSPACE}" || true

echo "[SYNC] script"
aws s3 cp "${SCRIPT_S3}" "${WORKSPACE}/scripts/research_vp_p0_baseline_eval.py"
python3 -m py_compile "${WORKSPACE}/scripts/research_vp_p0_baseline_eval.py"

if [[ ! -f "${DAILY_CLEAN}" ]]; then
  echo "[SYNC] daily_clean"
  aws s3 cp "${DAILY_S3}" "${DAILY_CLEAN}"
else
  echo "[SYNC] daily_clean exists: ${DAILY_CLEAN}"
fi

echo "[SYNC] vp datamart"
aws s3 cp --recursive "${VP_S3}" "${VP_ROOT}"

echo "[RUN] baseline"
cd "${WORKSPACE}"
python3 scripts/research_vp_p0_baseline_eval.py \
  --vp-root "${VP_ROOT}" \
  --daily-clean "${DAILY_CLEAN}" \
  --output-dir "${OUT_DIR}" \
  --start-date 20160104 \
  --end-date 20250711 \
  --horizons 1,3,5 \
  --cost-bps 20

echo "[ARTIFACTS]"
find "${OUT_DIR}" -maxdepth 1 -type f -print -exec ls -lh {} \;

echo "[UPLOAD] ${UPLOAD_S3}"
aws s3 cp --recursive "${OUT_DIR}" "${UPLOAD_S3}"

echo "[DISK_AFTER]"
df -h / /tmp "${WORKSPACE}" || true
date -u +"[DONE] %Y-%m-%dT%H:%M:%SZ"
