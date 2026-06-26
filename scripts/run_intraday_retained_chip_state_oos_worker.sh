#!/usr/bin/env bash
set -euo pipefail

REPO=${REPO:-/home/ubuntu/.openclaw/workspace/factorforge-data-api}
CACHE=${CACHE:-/home/ubuntu/factorforge_data_api_cache}
PYTHON_BIN=${PYTHON_BIN:-/home/ubuntu/.openclaw/workspace/.venvs/quant-research/bin/python}
PROOF=$CACHE/proofs/intraday_retained_chip_state_v1/oos_coverage_repair_20260619
TMP=$CACHE/tmp/intraday_retained_chip_state_v1_oos_coverage_repair_20260619
FINAL_S3=${FINAL_S3:-s3://yufan-data-lake/factorforge/datamart/intraday_retained_chip_state/v1}
OOS_ONLY_S3=${OOS_ONLY_S3:-s3://yufan-data-lake/factorforge/research_datamart/intraday_retained_chip_state_oos_repair_20260619/v1}
PROOF_S3=${PROOF_S3:-s3://yufan-data-lake/factorforge/proofs/intraday_retained_chip_state/v1/oos_coverage_repair_20260619}
MINUTE_S3=${MINUTE_S3:-s3://yufan-data-lake/tushares/分钟数据/raw/stk_mins_1min/}
DAILY_BASIC_S3=${DAILY_BASIC_S3:-s3://yufan-data-lake/tushares/行情数据/daily_basic_incremental/}
DAILY_ROOT=${DAILY_ROOT:-$CACHE/daily_basic/daily_basic_parquet_v1}
DAILY_BASIC_START=${DAILY_BASIC_START:-20250601}
OOS_START=${OOS_START:-20250714}
OOS_END=${OOS_END:-20260612}
BATCH_SIZE=${BATCH_SIZE:-20}

mkdir -p "$PROOF" "$TMP"
cd "$REPO"

aws s3 cp \
  s3://yufan-data-lake/factorforge/proofs/intraday_retained_chip_state/v1/factor_factory_data_api_full_bundle_20260618.tgz \
  /tmp/factor_factory_data_api_full_bundle.tgz \
  --only-show-errors
tar -xzf /tmp/factor_factory_data_api_full_bundle.tgz -C "$REPO"
aws s3 cp \
  "$PROOF_S3/closeout_intraday_retained_chip_state.py" \
  "$REPO/scripts/closeout_intraday_retained_chip_state.py" \
  --only-show-errors

"$PYTHON_BIN" -m py_compile \
  factor_factory/data_api/intraday_retained_chip_state.py \
  scripts/build_intraday_retained_chip_interval_base.py \
  scripts/build_intraday_retained_chip_state_from_interval_base.py \
  scripts/closeout_intraday_retained_chip_state.py

"$PYTHON_BIN" - <<'PY'
import os
import re
import subprocess
from pathlib import Path

import pandas as pd

daily_basic_s3 = os.environ.get('DAILY_BASIC_S3', 's3://yufan-data-lake/tushares/行情数据/daily_basic_incremental/')
daily_root = Path(os.environ.get('DAILY_ROOT', '/home/ubuntu/factorforge_data_api_cache/daily_basic/daily_basic_parquet_v1'))
daily_basic_start = os.environ.get('DAILY_BASIC_START', '20250601')
oos_end = os.environ.get('OOS_END', '20260612')
tmp_root = Path('/tmp/lcr_daily_basic_oos_csv')
tmp_root.mkdir(parents=True, exist_ok=True)
daily_root.mkdir(parents=True, exist_ok=True)

listing = subprocess.check_output(['aws', 's3', 'ls', daily_basic_s3], text=True)
dates = sorted(date for date in set(re.findall(r'trade_date=(\d{8})/', listing)) if daily_basic_start <= date <= oos_end)
if not dates:
    raise SystemExit('no OOS daily_basic_incremental partitions found on S3')

converted = []
skipped = []
for trade_date in dates:
    output_dir = daily_root / f'trade_date={trade_date}'
    output_file = output_dir / 'part.parquet'
    if output_file.exists():
        skipped.append(trade_date)
        continue
    csv_file = tmp_root / f'daily_basic_{trade_date}.csv'
    source = daily_basic_s3.rstrip('/') + f'/trade_date={trade_date}/daily_basic_{trade_date}.csv'
    subprocess.check_call(['aws', 's3', 'cp', source, str(csv_file), '--only-show-errors'])
    frame = pd.read_csv(csv_file)
    if 'trade_date' not in frame.columns:
        frame['trade_date'] = trade_date
    else:
        frame['trade_date'] = frame['trade_date'].astype(str).str.replace('-', '', regex=False).str.slice(0, 8)
    output_dir.mkdir(parents=True, exist_ok=True)
    frame.to_parquet(output_file, index=False)
    converted.append(trade_date)

print({
    'daily_basic_oos_partition_conversion': 'done',
    'date_count': len(dates),
    'converted_count': len(converted),
    'skipped_count': len(skipped),
    'start': dates[0],
    'end': dates[-1],
})
PY

"$PYTHON_BIN" - <<'PY' > /tmp/lcr_oos_target_dates.txt
import os
import re
import subprocess
from pathlib import Path
from factor_factory.data_api.intraday_retained_chip_state import normalize_trade_date

minute_root = os.environ.get('MINUTE_S3', 's3://yufan-data-lake/tushares/分钟数据/raw/stk_mins_1min/')
daily_root = Path(os.environ.get('DAILY_ROOT', '/home/ubuntu/factorforge_data_api_cache/daily_basic/daily_basic_parquet_v1'))
oos_start = os.environ.get('OOS_START', '20250714')
oos_end = os.environ.get('OOS_END', '20260612')

minute_listing = subprocess.check_output(['aws', 's3', 'ls', minute_root], text=True)
minute_dates = set(re.findall(r'trade_date=(\d{8})/', minute_listing))
daily_dates = {
    normalize_trade_date(path.name.split('=', 1)[1])
    for path in daily_root.glob('trade_date=*')
    if path.is_dir() and '=' in path.name
}
available = sorted(minute_dates & daily_dates)
Path('/tmp/lcr_available_dates.txt').write_text('\n'.join(available) + '\n', encoding='utf-8')
targets = [date for date in available if oos_start <= date <= oos_end]
if not targets:
    raise SystemExit('no OOS target dates in minute/daily intersection')
for date in targets:
    print(date)
PY

TOTAL=$(wc -l </tmp/lcr_oos_target_dates.txt)
echo "OOS_TOTAL_DATES=$TOTAL start=$OOS_START end=$OOS_END batch_size=$BATCH_SIZE" | tee "$PROOF/progress.log"
START_TS=$(date +%s)
BATCH_INDEX=0

while true; do
  mapfile -t BATCH < <("$PYTHON_BIN" - <<PY
from pathlib import Path
targets = Path('/tmp/lcr_oos_target_dates.txt').read_text().splitlines()
size = $BATCH_SIZE
idx = $BATCH_INDEX
for date in targets[idx * size:(idx + 1) * size]:
    print(date)
PY
)
  if [ ${#BATCH[@]} -eq 0 ]; then break; fi

  FIRST=${BATCH[0]}
  LAST=${BATCH[-1]}
  DATES=$(IFS=,; echo "${BATCH[*]}")
  mapfile -t SOURCE_BATCH < <("$PYTHON_BIN" - <<PY
from pathlib import Path
available = Path('/tmp/lcr_available_dates.txt').read_text().splitlines()
first = '$FIRST'
last = '$LAST'
positions = {date: idx for idx, date in enumerate(available)}
start = max(0, positions[first] - 19)
end = positions[last] + 1
for date in available[start:end]:
    print(date)
PY
)
  SOURCE_FIRST=${SOURCE_BATCH[0]}
  SOURCE_LAST=${SOURCE_BATCH[-1]}
  SOURCE_DATES=$(IFS=,; echo "${SOURCE_BATCH[*]}")
  BDIR=$TMP/batch_${BATCH_INDEX}_${FIRST}_${LAST}
  INTERVAL=$BDIR/interval
  STATE=$BDIR/state
  mkdir -p "$BDIR"

  echo "BATCH_START index=$BATCH_INDEX first=$FIRST last=$LAST count=${#BATCH[@]} source_first=$SOURCE_FIRST source_last=$SOURCE_LAST source_count=${#SOURCE_BATCH[@]} ts=$(date -u +%Y-%m-%dT%H:%M:%SZ)" | tee -a "$PROOF/progress.log"

  PYTHONPATH=. "$PYTHON_BIN" scripts/build_intraday_retained_chip_interval_base.py \
    --minute-s3-root "$MINUTE_S3" \
    --daily-basic-root "$DAILY_ROOT" \
    --start "$SOURCE_FIRST" \
    --end "$SOURCE_LAST" \
    --dates "$SOURCE_DATES" \
    --output-root "$INTERVAL" \
    --qa-output "$PROOF/batch_${BATCH_INDEX}_${FIRST}_${LAST}.interval.qa.json" \
    --max-dates 40 \
    --overwrite

  PYTHONPATH=. "$PYTHON_BIN" scripts/build_intraday_retained_chip_state_from_interval_base.py \
    --interval-root "$INTERVAL" \
    --start "$FIRST" \
    --end "$LAST" \
    --dates "$DATES" \
    --output-root "$STATE" \
    --qa-output "$PROOF/batch_${BATCH_INDEX}_${FIRST}_${LAST}.state.qa.json" \
    --catalog-output "$PROOF/batch_${BATCH_INDEX}_${FIRST}_${LAST}.catalog.json" \
    --max-target-dates 25 \
    --overwrite

  aws s3 sync "$STATE/" "$FINAL_S3/" --only-show-errors
  aws s3 sync "$STATE/" "$OOS_ONLY_S3/" --only-show-errors
  aws s3 cp "$PROOF/batch_${BATCH_INDEX}_${FIRST}_${LAST}.interval.qa.json" "$PROOF_S3/batch_${BATCH_INDEX}_${FIRST}_${LAST}.interval.qa.json" --only-show-errors
  aws s3 cp "$PROOF/batch_${BATCH_INDEX}_${FIRST}_${LAST}.state.qa.json" "$PROOF_S3/batch_${BATCH_INDEX}_${FIRST}_${LAST}.state.qa.json" --only-show-errors
  rm -rf "$BDIR"

  DONE=$(( (BATCH_INDEX + 1) * BATCH_SIZE ))
  if [ $DONE -gt $TOTAL ]; then DONE=$TOTAL; fi
  echo "BATCH_DONE index=$BATCH_INDEX done=$DONE total=$TOTAL ts=$(date -u +%Y-%m-%dT%H:%M:%SZ)" | tee -a "$PROOF/progress.log"
  aws s3 cp "$PROOF/progress.log" "$PROOF_S3/progress.log" --only-show-errors
  BATCH_INDEX=$((BATCH_INDEX + 1))
done

END_TS=$(date +%s)
"$PYTHON_BIN" - <<PY
import json
import pathlib
proof = pathlib.Path('$PROOF')
targets = pathlib.Path('/tmp/lcr_oos_target_dates.txt').read_text().splitlines()
summary = {
    'verdict': 'ACCEPT',
    'dataset_id': 'intraday_retained_chip_state_v1',
    'repair_mode': 'oos_coverage_repair',
    'start': targets[0] if targets else None,
    'end': targets[-1] if targets else None,
    'date_count': len(targets),
    'elapsed_seconds': $END_TS - $START_TS,
    'final_s3_root': '$FINAL_S3',
    'oos_only_s3_root': '$OOS_ONLY_S3',
    'proof_s3_root': '$PROOF_S3',
    'batch_size': $BATCH_SIZE,
    'lookback_overlap_trading_days': 19,
}
(proof / 'oos_backfill.summary.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
print(json.dumps(summary, ensure_ascii=False))
PY

PYTHONPATH=. "$PYTHON_BIN" scripts/closeout_intraday_retained_chip_state.py \
  --datamart-root "$OOS_ONLY_S3" \
  --daily-basic-root "$DAILY_ROOT" \
  --start "$OOS_START" \
  --end "$OOS_END" \
  --representative-dates "20250714,20251231,$OOS_END" \
  --qa-output "$PROOF/intraday_retained_chip_state_v1.oos.qa.json" \
  --catalog-output "$PROOF/intraday_retained_chip_state_v1.oos.catalog.json" \
  --read-smoke-output "$PROOF/intraday_retained_chip_state_v1.oos.read_smoke.json" \
  --closeout-output "$PROOF/intraday_retained_chip_state_v1.oos.closeout.json" \
  --qa-uri "$PROOF_S3/intraday_retained_chip_state_v1.oos.qa.json" \
  --research-window OOS

aws s3 cp "$PROOF/oos_backfill.summary.json" "$PROOF_S3/oos_backfill.summary.json" --only-show-errors
aws s3 cp "$PROOF/progress.log" "$PROOF_S3/progress.log" --only-show-errors
aws s3 cp "$PROOF/intraday_retained_chip_state_v1.oos.qa.json" "$PROOF_S3/intraday_retained_chip_state_v1.oos.qa.json" --only-show-errors
aws s3 cp "$PROOF/intraday_retained_chip_state_v1.oos.catalog.json" "$PROOF_S3/intraday_retained_chip_state_v1.oos.catalog.json" --only-show-errors
aws s3 cp "$PROOF/intraday_retained_chip_state_v1.oos.read_smoke.json" "$PROOF_S3/intraday_retained_chip_state_v1.oos.read_smoke.json" --only-show-errors
aws s3 cp "$PROOF/intraday_retained_chip_state_v1.oos.closeout.json" "$PROOF_S3/intraday_retained_chip_state_v1.oos.closeout.json" --only-show-errors
