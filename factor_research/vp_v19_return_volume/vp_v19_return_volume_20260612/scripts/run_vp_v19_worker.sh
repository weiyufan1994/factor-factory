#!/usr/bin/env bash
set -euo pipefail

if [[ "${FACTORFORGE_ARCHIVED_MANUAL_ACK:-0}" != "1" ]]; then
  echo "BLOCK_FACTORFORGE_ARCHIVED_MANUAL_SCRIPT: this historical worker is not a formal Factor Forge entrypoint" >&2
  exit 64
fi

WORKSPACE="${WORKSPACE:?Set the explicit isolated VP V19 workspace}"
V19_SCRIPT_S3="${V19_SCRIPT_S3:-s3://yufan-data-lake/factorforge/tmp/vp_v19_20260612/research_vp_v19_return_volume_eval.py}"
V18_SCRIPT_S3="${V18_SCRIPT_S3:-s3://yufan-data-lake/factorforge/tmp/vp_v18_20260612/research_vp_v18_drift_persistence_eval.py}"
BASELINE_SCRIPT_S3="${BASELINE_SCRIPT_S3:-s3://yufan-data-lake/factorforge/tmp/vp_p0_baseline_20260612/research_vp_p0_baseline_eval.py}"
VP_S3="${VP_S3:-s3://yufan-data-lake/factorforge/datamart/intraday_value_occupation_state/v1}"
INDEX_UNIVERSE_S3="${INDEX_UNIVERSE_S3:-s3://yufan-data-lake/factorforge/datamart/index_weight_universe/v1}"
VP_ROOT="${VP_ROOT:-/tmp/factorforge_vp_p0_datamart_v1}"
INDEX_UNIVERSE_ROOT="${INDEX_UNIVERSE_ROOT:-/tmp/factorforge_index_weight_universe_v1}"
MINUTE_ROOT="${MINUTE_ROOT:-/home/ubuntu/factorforge_data_api_cache/s3_parquet/minute_bar-raw_v1-0b2b836c57d763c6}"
FLOW_FEATURE_ROOT="${FLOW_FEATURE_ROOT:-/tmp/factorforge_vp_v19_return_volume_features_20260612}"
FLOW_FEATURE_S3="${FLOW_FEATURE_S3:-s3://yufan-data-lake/factorforge/research_datamart/intraday_return_volume_state_research/v1}"
SKIP_FLOW_BUILD="${SKIP_FLOW_BUILD:-0}"
DAILY_CLEAN="${DAILY_CLEAN:-${WORKSPACE}/data/clean/daily_clean.parquet}"
DAILY_S3="${DAILY_S3:-s3://yufan-data-lake/factorforge/datamart/clean_daily_bar/v1/daily_clean.parquet}"
OUT_DIR="${OUT_DIR:-/tmp/factorforge_vp_v19_return_volume_full_20260612}"
UPLOAD_S3="${UPLOAD_S3:-}"
ALLOW_REMOTE_WRITE="${ALLOW_REMOTE_WRITE:-0}"
MINUTE_MIN_PARTITIONS="${MINUTE_MIN_PARTITIONS:-2312}"
MAX_DATES="${MAX_DATES:-}"
AVAILABLE_MINUTE_ONLY="${AVAILABLE_MINUTE_ONLY:-0}"
STREAM_BY_DATE="${STREAM_BY_DATE:-0}"
UNIVERSES="${UNIVERSES:-full,middle_20_90,largest_10,smallest_20,csi800,csi800_csi1000,csi2000,csi_all_share,fixed_small_20}"
SIGNALS="${SIGNALS:-}"
SIZE_NEUTRAL_SIGNALS="${SIZE_NEUTRAL_SIGNALS:-}"
SIZE_NEUTRAL_UNIVERSES="${SIZE_NEUTRAL_UNIVERSES:-}"
WRITE_MERGED_PANEL="${WRITE_MERGED_PANEL:-0}"

upload_artifacts() {
  if [[ "${ALLOW_REMOTE_WRITE}" != "1" ]]; then
    echo "[UPLOAD SKIPPED] ALLOW_REMOTE_WRITE is not 1"
    return 0
  fi
  if [[ -z "${UPLOAD_S3}" ]]; then
    echo "[ERROR] UPLOAD_S3 is required when ALLOW_REMOTE_WRITE=1" >&2
    return 64
  fi
  aws s3 cp --recursive "${OUT_DIR}" "${UPLOAD_S3}"
}

mkdir -p "${WORKSPACE}/scripts" "${WORKSPACE}/data/clean" "${VP_ROOT}" "${INDEX_UNIVERSE_ROOT}" "${OUT_DIR}" "${FLOW_FEATURE_ROOT}"
LOG_FILE="${OUT_DIR}/run.log"
exec > >(tee -a "${LOG_FILE}") 2>&1

date -u +"[START] %Y-%m-%dT%H:%M:%SZ"
echo "[WORKSPACE] ${WORKSPACE}"
df -h / /tmp "${WORKSPACE}" || true

echo "[SYNC] scripts"
aws s3 cp "${V19_SCRIPT_S3}" "${WORKSPACE}/scripts/research_vp_v19_return_volume_eval.py"
aws s3 cp "${V18_SCRIPT_S3}" "${WORKSPACE}/scripts/research_vp_v18_drift_persistence_eval.py"
aws s3 cp "${BASELINE_SCRIPT_S3}" "${WORKSPACE}/scripts/research_vp_p0_baseline_eval.py"
python3 -m py_compile "${WORKSPACE}/scripts/research_vp_v19_return_volume_eval.py"

if [[ ! -f "${DAILY_CLEAN}" ]]; then
  echo "[SYNC] daily_clean"
  aws s3 cp "${DAILY_S3}" "${DAILY_CLEAN}"
else
  echo "[SYNC] daily_clean exists"
fi

VP_PARTITIONS="$(find "${VP_ROOT}" -mindepth 1 -maxdepth 1 -type d -name 'trade_date=*' 2>/dev/null | wc -l | tr -d ' ')"
echo "[CHECK] existing_vp_partitions=${VP_PARTITIONS}"
if [[ "${VP_PARTITIONS}" -lt 2312 ]]; then
  echo "[SYNC] vp datamart"
  aws s3 cp --recursive "${VP_S3}" "${VP_ROOT}"
fi
echo "[CHECK] final_vp_partitions=$(find "${VP_ROOT}" -mindepth 1 -maxdepth 1 -type d -name 'trade_date=*' 2>/dev/null | wc -l | tr -d ' ')"
du -sh "${VP_ROOT}" || true

INDEX_PARTITIONS="$(find "${INDEX_UNIVERSE_ROOT}" -mindepth 1 -maxdepth 1 -type d -name 'trade_date=*' 2>/dev/null | wc -l | tr -d ' ')"
echo "[CHECK] existing_index_universe_partitions=${INDEX_PARTITIONS}"
if [[ "${INDEX_PARTITIONS}" -lt 2312 ]]; then
  echo "[SYNC] index weight universe"
  aws s3 cp --recursive "${INDEX_UNIVERSE_S3}" "${INDEX_UNIVERSE_ROOT}"
fi
echo "[CHECK] final_index_universe_partitions=$(find "${INDEX_UNIVERSE_ROOT}" -mindepth 1 -maxdepth 1 -type d -name 'trade_date=*' 2>/dev/null | wc -l | tr -d ' ')"
du -sh "${INDEX_UNIVERSE_ROOT}" || true

FLOW_PARTITIONS="$(find "${FLOW_FEATURE_ROOT}" -mindepth 1 -maxdepth 1 -type d -name 'trade_date=*' 2>/dev/null | wc -l | tr -d ' ')"
echo "[CHECK] existing_flow_feature_partitions=${FLOW_PARTITIONS}"
if [[ "${SKIP_FLOW_BUILD}" == "1" && "${FLOW_PARTITIONS}" -lt 2312 ]]; then
  echo "[SYNC] flow feature datamart"
  aws s3 cp --recursive "${FLOW_FEATURE_S3}" "${FLOW_FEATURE_ROOT}"
fi
echo "[CHECK] final_flow_feature_partitions=$(find "${FLOW_FEATURE_ROOT}" -mindepth 1 -maxdepth 1 -type d -name 'trade_date=*' 2>/dev/null | wc -l | tr -d ' ')"
du -sh "${FLOW_FEATURE_ROOT}" || true

if [[ "${SKIP_FLOW_BUILD}" != "1" ]]; then
  MINUTE_PARTITIONS="$(find "${MINUTE_ROOT}" -mindepth 1 -maxdepth 1 -type d -name 'trade_date=*' 2>/dev/null | wc -l | tr -d ' ')"
  echo "[CHECK] minute_root=${MINUTE_ROOT}"
  echo "[CHECK] minute_partitions=${MINUTE_PARTITIONS} required=${MINUTE_MIN_PARTITIONS}"
  if [[ "${MINUTE_PARTITIONS}" -lt "${MINUTE_MIN_PARTITIONS}" ]]; then
    echo "[ERROR] minute cache insufficient for requested V19 run"
    find "${MINUTE_ROOT}" -mindepth 1 -maxdepth 1 -type d -name 'trade_date=*' 2>/dev/null | head -20 || true
    upload_artifacts || true
    exit 42
  fi
else
  echo "[CHECK] SKIP_FLOW_BUILD=1; minute cache is not required"
fi

echo "[RUN] v19 return-volume"
set +e
EXTRA_ARGS=()
if [[ "${SKIP_FLOW_BUILD}" == "1" ]]; then
  EXTRA_ARGS+=(--skip-flow-build)
fi
if [[ "${AVAILABLE_MINUTE_ONLY}" == "1" ]]; then
  EXTRA_ARGS+=(--available-minute-only)
fi
if [[ "${STREAM_BY_DATE}" == "1" ]]; then
  EXTRA_ARGS+=(--stream-by-date)
fi
if [[ "${WRITE_MERGED_PANEL}" == "1" ]]; then
  EXTRA_ARGS+=(--write-merged-panel)
fi
if [[ -n "${SIGNALS}" ]]; then
  EXTRA_ARGS+=(--signals "${SIGNALS}")
fi
if [[ -n "${SIZE_NEUTRAL_SIGNALS}" ]]; then
  EXTRA_ARGS+=(--size-neutral-signals "${SIZE_NEUTRAL_SIGNALS}")
fi
if [[ -n "${SIZE_NEUTRAL_UNIVERSES}" ]]; then
  EXTRA_ARGS+=(--size-neutral-universes "${SIZE_NEUTRAL_UNIVERSES}")
fi
if [[ -n "${MAX_DATES}" ]]; then
  python3 "${WORKSPACE}/scripts/research_vp_v19_return_volume_eval.py" \
    --vp-root "${VP_ROOT}" \
    --daily-clean "${DAILY_CLEAN}" \
    --minute-root "${MINUTE_ROOT}" \
    --flow-feature-root "${FLOW_FEATURE_ROOT}" \
    --index-universe-root "${INDEX_UNIVERSE_ROOT}" \
    --output-dir "${OUT_DIR}" \
    --start-date 20160104 \
    --end-date 20250711 \
    --horizons 1,3,5 \
    --cost-bps 20 \
    --universes "${UNIVERSES}" \
    --max-dates "${MAX_DATES}" \
    "${EXTRA_ARGS[@]}"
else
  python3 "${WORKSPACE}/scripts/research_vp_v19_return_volume_eval.py" \
    --vp-root "${VP_ROOT}" \
    --daily-clean "${DAILY_CLEAN}" \
    --minute-root "${MINUTE_ROOT}" \
    --flow-feature-root "${FLOW_FEATURE_ROOT}" \
    --index-universe-root "${INDEX_UNIVERSE_ROOT}" \
    --output-dir "${OUT_DIR}" \
    --start-date 20160104 \
    --end-date 20250711 \
    --horizons 1,3,5 \
    --cost-bps 20 \
    --universes "${UNIVERSES}" \
    "${EXTRA_ARGS[@]}"
fi
STATUS=$?
set -e

echo "[ARTIFACTS]"
find "${OUT_DIR}" -maxdepth 2 -type f -print -exec ls -lh {} \;
upload_artifacts
date -u +"[DONE] %Y-%m-%dT%H:%M:%SZ status=${STATUS}"
exit "${STATUS}"
