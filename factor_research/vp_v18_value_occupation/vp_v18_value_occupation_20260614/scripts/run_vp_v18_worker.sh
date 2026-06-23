#!/usr/bin/env bash
set -euo pipefail

WORKSPACE="${WORKSPACE:-/home/ubuntu/.openclaw/workspace/factorforge}"
SCRIPT_S3="${SCRIPT_S3:-s3://yufan-data-lake/factorforge/tmp/vp_v18_20260612/research_vp_v18_drift_persistence_eval.py}"
BASELINE_SCRIPT_S3="${BASELINE_SCRIPT_S3:-s3://yufan-data-lake/factorforge/tmp/vp_p0_baseline_20260612/research_vp_p0_baseline_eval.py}"
VP_S3="${VP_S3:-s3://yufan-data-lake/factorforge/datamart/intraday_value_occupation_state/v1}"
VP_ROOT="${VP_ROOT:-/tmp/factorforge_vp_p0_datamart_v1}"
DAILY_CLEAN="${DAILY_CLEAN:-${WORKSPACE}/data/clean/daily_clean.parquet}"
DAILY_S3="${DAILY_S3:-s3://yufan-data-lake/factorforge/datamart/clean_daily_bar/v1/daily_clean.parquet}"
OUT_DIR="${OUT_DIR:-/tmp/factorforge_vp_v18_drift_persistence_full_20260612}"
UPLOAD_S3="${UPLOAD_S3:-s3://yufan-data-lake/factorforge/tmp/vp_v18_20260612/full}"

mkdir -p "${WORKSPACE}/scripts" "${WORKSPACE}/data/clean" "${VP_ROOT}" "${OUT_DIR}"
LOG_FILE="${OUT_DIR}/run.log"
exec > >(tee -a "${LOG_FILE}") 2>&1

date -u +"[START] %Y-%m-%dT%H:%M:%SZ"
echo "[WORKSPACE] ${WORKSPACE}"
df -h / /tmp "${WORKSPACE}" || true

echo "[SYNC] scripts"
aws s3 cp "${SCRIPT_S3}" "${WORKSPACE}/scripts/research_vp_v18_drift_persistence_eval.py"
aws s3 cp "${BASELINE_SCRIPT_S3}" "${WORKSPACE}/scripts/research_vp_p0_baseline_eval.py"
python3 -m py_compile "${WORKSPACE}/scripts/research_vp_v18_drift_persistence_eval.py"

if [[ ! -f "${DAILY_CLEAN}" ]]; then
  echo "[SYNC] daily_clean"
  aws s3 cp "${DAILY_S3}" "${DAILY_CLEAN}"
else
  echo "[SYNC] daily_clean exists"
fi

PARTITIONS="$(find "${VP_ROOT}" -mindepth 1 -maxdepth 1 -type d -name 'trade_date=*' 2>/dev/null | wc -l | tr -d ' ')"
echo "[CHECK] existing_vp_partitions=${PARTITIONS}"
if [[ "${PARTITIONS}" -lt 2312 ]]; then
  echo "[SYNC] vp datamart"
  aws s3 cp --recursive "${VP_S3}" "${VP_ROOT}"
fi
echo "[CHECK] final_vp_partitions=$(find "${VP_ROOT}" -mindepth 1 -maxdepth 1 -type d -name 'trade_date=*' 2>/dev/null | wc -l | tr -d ' ')"
du -sh "${VP_ROOT}" || true

echo "[RUN] v18 full"
set +e
python3 "${WORKSPACE}/scripts/research_vp_v18_drift_persistence_eval.py" \
  --vp-root "${VP_ROOT}" \
  --daily-clean "${DAILY_CLEAN}" \
  --output-dir "${OUT_DIR}" \
  --start-date 20160104 \
  --end-date 20250711 \
  --horizons 1,3,5 \
  --cost-bps 20
STATUS=$?
set -e

echo "[ARTIFACTS]"
find "${OUT_DIR}" -maxdepth 1 -type f -print -exec ls -lh {} \;
echo "[UPLOAD] ${UPLOAD_S3}"
aws s3 cp --recursive "${OUT_DIR}" "${UPLOAD_S3}"
date -u +"[DONE] %Y-%m-%dT%H:%M:%SZ status=${STATUS}"
exit "${STATUS}"
