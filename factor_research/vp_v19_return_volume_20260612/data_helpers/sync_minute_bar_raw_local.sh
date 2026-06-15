#!/usr/bin/env bash
set -euo pipefail

S3_PREFIX="${S3_PREFIX:-s3://yufan-data-lake/tushares/分钟数据/raw/stk_mins_1min/}"
S3_BUCKET="${S3_BUCKET:-yufan-data-lake}"
LOCAL_ROOT="${LOCAL_ROOT:-/Users/humphrey/projects/factorforge-data-api-cache/s3_parquet/minute_bar-raw_v1-0b2b836c57d763c6}"
START_DATE="${START_DATE:-20160104}"
END_DATE="${END_DATE:-20250711}"
JOBS="${JOBS:-8}"
REFRESH_LIST="${REFRESH_LIST:-0}"

mkdir -p "${LOCAL_ROOT}/_sync"
LISTING_FILE="${LOCAL_ROOT}/_sync/s3_listing_${START_DATE}_${END_DATE}.txt"
TARGETS_FILE="${LOCAL_ROOT}/_sync/targets_${START_DATE}_${END_DATE}.tsv"

if [[ ! -s "${LISTING_FILE}" || "${REFRESH_LIST}" == "1" ]]; then
  echo "[LIST] ${S3_PREFIX}"
  aws s3 ls "${S3_PREFIX}" --recursive > "${LISTING_FILE}"
fi

awk -v start="${START_DATE}" -v end="${END_DATE}" '
  {
    key=$4
    if (key ~ /trade_date=/ && key ~ /\.parquet$/) {
      d=key
      sub(/^.*trade_date=/, "", d)
      sub(/\/.*$/, "", d)
      if (d >= start && d <= end) {
        print d "\t" $3 "\t" key
      }
    }
  }
' "${LISTING_FILE}" | sort > "${TARGETS_FILE}"

target_count="$(wc -l < "${TARGETS_FILE}" | tr -d ' ')"
target_bytes="$(awk '{sum += $2} END {printf "%.0f", sum}' "${TARGETS_FILE}")"
target_gib="$(awk -v b="${target_bytes}" 'BEGIN {printf "%.3f", b/1024/1024/1024}')"
echo "[TARGETS] count=${target_count} bytes=${target_bytes} gib=${target_gib} jobs=${JOBS}"

download_one() {
  local date="$1"
  local size="$2"
  local key="$3"
  local dest_dir="${LOCAL_ROOT}/trade_date=${date}"
  local dest="${dest_dir}/$(basename "${key}")"
  local tmp="${dest}.download.$$"
  mkdir -p "${dest_dir}"
  if [[ -f "${dest}" ]]; then
    local have
    have="$(stat -f '%z' "${dest}" 2>/dev/null || stat -c '%s' "${dest}")"
    if [[ "${have}" == "${size}" ]]; then
      echo "[SKIP] ${date}"
      return 0
    fi
  fi
  if aws s3api get-object --bucket "${S3_BUCKET}" --key "${key}" "${tmp}" --cli-connect-timeout 60 --cli-read-timeout 300 >/dev/null && mv "${tmp}" "${dest}"; then
    echo "[DONE] ${date}"
  else
    echo "[FAIL] ${date}" >&2
    return 1
  fi
}
export -f download_one
export LOCAL_ROOT
export S3_BUCKET

awk -F '\t' '{print $1, $2, $3}' "${TARGETS_FILE}" | xargs -P "${JOBS}" -n 3 bash -c 'download_one "$1" "$2" "$3"' _

local_count="$(find "${LOCAL_ROOT}" -mindepth 2 -maxdepth 2 -type f -name 'part-000.parquet' | wc -l | tr -d ' ')"
local_size="$(du -sh "${LOCAL_ROOT}" | awk '{print $1}')"
echo "[LOCAL] parquet_count=${local_count} size=${local_size} root=${LOCAL_ROOT}"
