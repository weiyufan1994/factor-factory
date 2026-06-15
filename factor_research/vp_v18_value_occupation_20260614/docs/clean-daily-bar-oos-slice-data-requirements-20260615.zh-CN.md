# clean_daily_bar OOS Slice / Partitioned Access Data Requirement

Date: 2026-06-15

## Background

Research is evaluating the V18 value-occupation factor as a simple linear incremental feature for alpha-composite/optimizer use.

The intraday value-occupation OOS state is already available and validated:

- Dataset: `intraday_value_occupation_state_oos_stream/v1`
- S3: `s3://yufan-data-lake/factorforge/research_datamart/intraday_value_occupation_state_oos_stream/v1`
- Coverage: 2025-07-14 to 2026-06-12
- Rows: 1,209,358
- Dates: 222 / 222

Current blocker is daily data access:

- Mac local `daily_clean.parquet` is stale and only covers through 2026-04-24.
- S3 latest `daily_clean.parquet` covers through 2026-06-12, but it is a single 1.4 GiB parquet:
  `s3://yufan-data-lake/factorforge/datamart/clean_daily_bar/v1/daily_clean.parquet`
- S3 Select was attempted and failed with `MethodNotAllowed`.
- openclaw EC2 has the latest file, but default Python environments do not currently have a parquet reader available.

Research needs a small, reusable OOS daily slice or partitioned daily-clean access to complete full-window incremental tests without downloading the full monolithic parquet.

## Requested Deliverable

Please provide one of the following. Option A is preferred for future reuse.

### Option A: Partitioned clean_daily_bar datamart

Create a partitioned S3 parquet dataset:

```text
s3://yufan-data-lake/factorforge/datamart/clean_daily_bar_partitioned/v1/trade_date=YYYYMMDD/*.parquet
```

Register it in the Data API catalog as a production/read dataset:

```text
dataset_id = clean_daily_bar_partitioned
version = v1
partition_key = trade_date
unique_key = [trade_date, ts_code]
```

### Option B: Fast MVP fixed OOS slice

If Option A takes longer, please first deliver a fixed research slice:

```text
s3://yufan-data-lake/factorforge/research_datamart/clean_daily_bar_oos_slice/v1/trade_date=YYYYMMDD/*.parquet
```

or, if partitioning is inconvenient for MVP:

```text
s3://yufan-data-lake/factorforge/research_datamart/clean_daily_bar_oos_slice/v1/daily_clean_oos_20250601_20260612.parquet
```

Catalog dataset:

```text
dataset_id = clean_daily_bar_oos_slice
version = v1
date_range = 20250601-20260612
unique_key = [trade_date, ts_code]
```

## Required Date Range

Minimum required slice:

```text
2025-06-01 to 2026-06-12
```

Reason:

- OOS signal dates start at 2025-07-14.
- Research needs pre-OOS history for lagged close, 20D volatility, 5D/20D momentum-to-cutoff controls, and PIT universe/risk controls.
- Forward-return horizons are 1D, 3D, and 5D. Existing OOS convention drops the last horizon dates when forward return is unavailable.

If easy, please include through the latest available trade date after 2026-06-12 as well. That is not required for matching the existing OOS proof, but it improves future forward-return coverage.

## Required Columns

Minimum columns:

```text
ts_code
trade_date
open
high
low
close
pre_close
pct_chg
amount
vol
turnover_rate
turnover_rate_f
volume_ratio
total_mv
circ_mv
free_float_mcap
ln_mcap_free
ln_total_mv
ln_circ_mv
```

The V18 incremental test currently uses:

```text
ts_code
trade_date
close
pre_close
pct_chg
amount
turnover_rate
turnover_rate_f
volume_ratio
total_mv
circ_mv
ln_total_mv
ln_circ_mv
```

Please keep the wider minimum set above because other factor tests reuse daily-clean OHLCV and free-float size fields.

## Data Semantics

Please preserve the same semantics as the current latest `clean_daily_bar/v1/daily_clean.parquet`:

- adjusted price mode: current `clean_daily_bar` adjusted close/open/high/low/pre_close semantics;
- PIT filters unchanged:
  - drop BJ rows;
  - drop ST rows;
  - min listing days 60;
  - drop suspended rows;
  - drop limit-event rows;
  - drop abnormal pct move rows;
- `trade_date` should be normalized as `YYYYMMDD`;
- `ts_code` should retain Tushare code format;
- no alpha/factor composite columns should be added.

This request is data-access infrastructure only. Data group does not need to validate or opine on factor alpha.

## QA / Proof Requirements

Please deliver proof JSON files under:

```text
s3://yufan-data-lake/factorforge/proofs/clean_daily_bar_oos_slice/v1/
```

or the equivalent `clean_daily_bar_partitioned/v1` proof path if Option A is delivered.

Required proof fields:

```json
{
  "dataset_id": "clean_daily_bar_oos_slice",
  "schema_version": "clean_daily_bar_oos_slice_v1",
  "source_dataset": "clean_daily_bar/v1",
  "source_s3": "s3://yufan-data-lake/factorforge/datamart/clean_daily_bar/v1/daily_clean.parquet",
  "output_s3": "...",
  "requested_min_trade_date": "20250601",
  "requested_max_trade_date": "20260612",
  "output_min_trade_date": "...",
  "output_max_trade_date": "...",
  "date_count": 0,
  "row_count": 0,
  "ticker_count": 0,
  "duplicate_key_count": 0,
  "missing_required_columns": [],
  "null_ratio_by_required_column": {},
  "coverage_by_date_tail": {},
  "read_smoke": {
    "status": "PASS",
    "sample_dates": ["20260610", "20260611", "20260612"],
    "row_count": 0
  },
  "verdict": "ACCEPT"
}
```

Hard acceptance checks:

- output can be read by pandas/pyarrow from Mac after `aws s3 cp`;
- required columns are present;
- `duplicate_key_count == 0` on `(trade_date, ts_code)`;
- no missing dates inside the source trading calendar for the requested range, except documented non-trading days;
- `output_max_trade_date >= 20260612`;
- read smoke passes for `20260610-20260612`;
- catalog entry is available if this is promoted to Data API access.

## Research-Side Consumer

The current research script that will consume this deliverable:

```text
/Users/humphrey/projects/factor-factory/factor_research/vp_v18_value_occupation_20260614/scripts/research_vp_v18_incremental_linear_eval.py
```

Research will rerun:

```bash
python3 factor_research/vp_v18_value_occupation_20260614/scripts/research_vp_v18_incremental_linear_eval.py \
  --vp-root /tmp/vp18_oos_state_20260614 \
  --daily-clean <daily_slice_or_partitioned_local_path> \
  --output-dir /tmp/vp18_incremental_linear_full_oos_20260615 \
  --start-date 20250714 \
  --end-date 20260612 \
  --horizons 1,3,5
```

and then the stricter version:

```bash
python3 factor_research/vp_v18_value_occupation_20260614/scripts/research_vp_v18_incremental_linear_eval.py \
  --vp-root /tmp/vp18_oos_state_20260614 \
  --daily-clean <daily_slice_or_partitioned_local_path> \
  --output-dir /tmp/vp18_incremental_linear_full_oos_state_controls_20260615 \
  --start-date 20250714 \
  --end-date 20260612 \
  --horizons 1,3,5 \
  --use-state-controls
```

## Priority

P0 for current V18 OOS incremental research.

Preferred sequence:

1. Fast MVP fixed OOS slice if it can be delivered quickly.
2. Follow with partitioned `clean_daily_bar` datamart because many future factor tests need date-predicate daily reads.
