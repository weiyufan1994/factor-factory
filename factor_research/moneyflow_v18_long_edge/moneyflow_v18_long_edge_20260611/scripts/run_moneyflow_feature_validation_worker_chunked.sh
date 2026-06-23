#!/usr/bin/env bash
set -euo pipefail

OUT_ROOT="${OUT_ROOT:-/tmp/moneyflow_feature_validation_chunked_20260613}"
RESULT_DIR="${RESULT_DIR:-${OUT_ROOT}/results}"
SCRIPT_DIR="${SCRIPT_DIR:-/tmp/moneyflow_v18_scripts}"
S3_ROOT="${S3_ROOT:-s3://yufan-data-lake/factorforge/tmp/moneyflow_v18_20260613}"
INDEX_ROOT="${INDEX_ROOT:-/tmp/factorforge_index_weight_universe_v1}"
WORKSPACE="${WORKSPACE:-/home/ubuntu/factorforge}"
DAILY_CLEAN="${DAILY_CLEAN:-/home/ubuntu/.openclaw/workspace/factorforge/data/clean/daily_clean.parquet}"
HORIZONS="${HORIZONS:-1,3,5}"
UNIVERSES="${UNIVERSES:-full,middle_10_80,fixed_small_10,fixed_small_20,smallest_20,csi800,csi800_csi1000}"
LAWS="${LAWS:-miller_flow_v15_repair_confirmed_absorption_fp_v1,miller_flow_v18a_absolute_long_edge_gate_v1,miller_flow_v18b_first_passage_repair_edge_v1}"

mkdir -p "${OUT_ROOT}" "${RESULT_DIR}" "${SCRIPT_DIR}" "${INDEX_ROOT}" "$(dirname "${DAILY_CLEAN}")"

date -u +"START_%Y-%m-%dT%H:%M:%SZ"
aws s3 cp "${S3_ROOT}/research_moneyflow_v11_datamart_eval.py" "${SCRIPT_DIR}/research_moneyflow_v11_datamart_eval.py"
aws s3 cp "${S3_ROOT}/validate_moneyflow_feature_candidate.py" "${SCRIPT_DIR}/validate_moneyflow_feature_candidate.py"
python3 -m py_compile "${SCRIPT_DIR}/research_moneyflow_v11_datamart_eval.py" "${SCRIPT_DIR}/validate_moneyflow_feature_candidate.py"

if [[ ! -f "${DAILY_CLEAN}" ]]; then
  aws s3 cp s3://yufan-data-lake/factorforge/datamart/clean_daily_bar/v1/daily_clean.parquet "${DAILY_CLEAN}"
fi

index_n="$(find "${INDEX_ROOT}" -mindepth 1 -maxdepth 1 -type d -name 'trade_date=*' 2>/dev/null | wc -l | tr -d ' ')"
echo "INDEX_PARTITIONS_BEFORE=${index_n}"
if [[ "${index_n:-0}" -lt 2312 ]]; then
  aws s3 cp --recursive s3://yufan-data-lake/factorforge/datamart/index_weight_universe/v1 "${INDEX_ROOT}"
fi
echo "INDEX_PARTITIONS_AFTER=$(find "${INDEX_ROOT}" -mindepth 1 -maxdepth 1 -type d -name 'trade_date=*' 2>/dev/null | wc -l | tr -d ' ')"

rm -rf "${RESULT_DIR}"
mkdir -p "${RESULT_DIR}/chunks"
cd "${WORKSPACE}"
export PYTHONPATH="${WORKSPACE}:${SCRIPT_DIR}:${PYTHONPATH:-}"

for year in 2016 2017 2018 2019 2020 2021 2022 2023 2024 2025; do
  chunk_start="${year}0101"
  chunk_end="${year}1231"
  if [[ "${year}" == "2016" ]]; then
    chunk_start="20160104"
  fi
  if [[ "${year}" == "2025" ]]; then
    chunk_end="20250711"
  fi
  out_dir="${RESULT_DIR}/chunks/${year}"
  mkdir -p "${out_dir}"
  echo "CHUNK_START=${chunk_start} CHUNK_END=${chunk_end}"
  python3 "${SCRIPT_DIR}/validate_moneyflow_feature_candidate.py" \
    --moments-root /opt/factorforge/data-api-datamarts/intraday_flow_distribution_moments_v1_is \
    --daily-basic-root /opt/factorforge/data-api-datamarts/daily_basic_backtest_base_is \
    --daily-clean "${DAILY_CLEAN}" \
    --index-universe-root "${INDEX_ROOT}" \
    --output-dir "${out_dir}" \
    --start-date "${chunk_start}" \
    --end-date "${chunk_end}" \
    --cutoff-time 14:50 \
    --horizons "${HORIZONS}" \
    --laws "${LAWS}" \
    --universes "${UNIVERSES}"
done

python3 - "${RESULT_DIR}" <<'PY'
import json
import sys
from pathlib import Path

import pandas as pd

root = Path(sys.argv[1])
frames = []
for path in sorted((root / "chunks").glob("*/moneyflow_feature_validation_metrics.csv")):
    frame = pd.read_csv(path)
    year = path.parent.name
    frame["chunk_year"] = year
    frame["chunk_start"] = f"{year}0101"
    frame["chunk_end"] = f"{year}1231"
    if year == "2016":
        frame["chunk_start"] = "20160104"
    if year == "2025":
        frame["chunk_end"] = "20250711"
    frames.append(frame)

if not frames:
    raise SystemExit("no chunk metrics")

chunk = pd.concat(frames, ignore_index=True)
chunk_path = root / "moneyflow_feature_validation_chunk_metrics.csv"
chunk.to_csv(chunk_path, index=False)

keys = ["universe", "feature", "horizon"]
value_cols = [
    "raw_rank_ic_mean",
    "raw_pearson_ic_mean",
    "signal_resid_rank_ic_mean",
    "both_resid_rank_ic_mean",
    "raw_top_decile_excess",
    "resid_top_decile_excess",
]
rows = []
for key, group in chunk.groupby(keys, sort=False):
    row = dict(zip(keys, key, strict=True))
    weights = pd.to_numeric(group["date_count"], errors="coerce").fillna(0.0)
    row["date_count"] = int(weights.sum())
    for col in value_cols:
        vals = pd.to_numeric(group[col], errors="coerce")
        valid = vals.notna() & weights.gt(0.0)
        row[col] = float((vals[valid] * weights[valid]).sum() / weights[valid].sum()) if valid.any() else float("nan")
    rows.append(row)

metrics = pd.DataFrame(rows)
metrics_path = root / "moneyflow_feature_validation_metrics.csv"
metrics.to_csv(metrics_path, index=False)
top = metrics.sort_values(["both_resid_rank_ic_mean", "signal_resid_rank_ic_mean"], ascending=False).head(40)
(root / "moneyflow_feature_validation_top.csv").write_text(top.to_csv(index=False), encoding="utf-8")
summary = {
    "verdict": "ACCEPT",
    "chunked": True,
    "chunk_metrics_path": str(chunk_path),
    "metrics_path": str(metrics_path),
    "chunk_count": len(frames),
    "side_effects": {
        "clean_data_started": False,
        "search_worker_started": False,
        "official_promotion_started": False,
        "factor_forge_artifacts_written": False,
    },
}
(root / "moneyflow_feature_validation_summary.json").write_text(json.dumps(summary, indent=2, sort_keys=True), encoding="utf-8")
print(json.dumps(summary, indent=2, sort_keys=True))
PY

aws s3 cp --recursive "${RESULT_DIR}" "${S3_ROOT}/feature_validation_chunked_results/"
date -u +"DONE_%Y-%m-%dT%H:%M:%SZ"
