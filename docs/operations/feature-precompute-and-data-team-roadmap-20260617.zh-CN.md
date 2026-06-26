# Feature Precompute And Data Team Roadmap

Date: 2026-06-17

Scope: Data API / datamart / operator acceleration. This document does not authorize clean data, search_worker, official promotion, Factor Forge production loop execution, or production backend replacement.

## Current Position

Minute-factor acceleration should not be treated as one CPV-specific patch. The durable target is:

```text
raw source -> prepared cache -> reusable operator/state datamart -> research consumption
```

The current local direction is correct:

- keep finished datamarts parquet-first and partitioned
- use projection and warm cache for IO
- move repeated time-series math into shared kernels
- require bounded proof, worker proof, and separate production approval before changing defaults

The missing next layer is a formal feature/state menu: what should Data API precompute daily, what should remain on-demand, and what should never be materialized globally.

Machine-readable registry:

```text
docs/operations/feature-precompute-registry.v1.json
docs/operations/feature-family-registry.v1.json
docs/operations/data-team-daily-ops-checklist.v1.json
```

Validation command:

```bash
PYTHONPATH=. python3 scripts/validate_feature_precompute_registry.py \
  docs/operations/feature-precompute-registry.v1.json

PYTHONPATH=. python3 scripts/validate_feature_family_registry.py \
  docs/operations/feature-family-registry.v1.json

PYTHONPATH=. python3 scripts/validate_data_team_ops_registry.py \
  docs/operations/data-team-daily-ops-checklist.v1.json

PYTHONPATH=. python3 scripts/validate_registry_crosslinks.py \
  --output /tmp/registry_crosslinks.validation.json

PYTHONPATH=. python3 scripts/build_data_api_status_report.py \
  --output /tmp/data_api_status_report.json \
  --markdown-output /tmp/data_api_status_report.md
```

The feature-family registry answers "which indicators or time-series state families should be precomputed?" The feature-precompute registry answers "which concrete Data API datasets are available or planned?" The data-team ops checklist answers "what should the data group verify every day or before publication?" None of these registries is the active production catalog. A dataset listed as `production_candidate` still needs its own full-window worker proof, QA, catalog candidate, and true worker read smoke before active catalog registration. A dataset listed as `planned` or `exploratory` must not be used as formal production evidence.

The status-report script combines all three registries into one JSON/Markdown handoff for researchers and architects. It also validates crosslinks: feature-family `recommended_dataset` values must point to known datasets, P0/P1 candidate datasets must be referenced by a feature family, and ops checklist dataset references must be known:

```text
/tmp/data_api_status_report.json
/tmp/data_api_status_report.md
```

Current P0 worker-plan proof, 2026-06-17:

```text
dataset=intraday_flow_distribution_moments_v1
bundle=/tmp/intraday_flow_distribution_moments_v1.full_is.worker_bundle.json
validation=/tmp/intraday_flow_distribution_moments_v1.full_is.worker_bundle.validation.json
validation_verdict=ACCEPT
input_dataset=prepared_minute_bar_v1
operator_backend=vectorized
window=20160104..20250711
execution_policy=plan_only
```

This is a worker command bundle and safety validation, not a completed backfill. The flow-distribution builder now supports date-partition resume controls (`--skip-existing`, `--max-dates`, `--manifest-output`) and the bundle uses a two-step resume plan: batch1 processes a bounded number of pending dates, batch2 skips existing partitions and continues the remaining window. The bundle also ends with:

```text
scripts/closeout_intraday_flow_distribution_moments.py
```

The closeout script converts final QA, catalog, worker read smoke, and batch manifests into a standard `datamart_closeout_v1` ACCEPT/BLOCK artifact. The next engineering step is to run the worker proof under explicit approval, then review the closeout before any active catalog registration.

## Alpha360 Lesson

Qlib's Alpha360 is useful as a design reference, not as a formula library to copy blindly.

Official Qlib code describes Alpha360 as original price and volume data over the last 60 days, normalized by the latest price/volume. Its feature config expands 60 lags for close, open, high, low, vwap, and volume, producing 360 raw time-series features. Qlib docs also list Alpha360 and Alpha158 as off-the-shelf datasets, and benchmark docs compare models on Alpha360/Alpha158 workflows.

Sources:

- https://github.com/microsoft/qlib/blob/main/qlib/contrib/data/loader.py
- https://qlib.readthedocs.io/en/latest/component/data.html
- https://github.com/microsoft/qlib/blob/main/examples/benchmarks/README.md

Implication for Factor Forge:

- For **daily data**, Alpha360-style rolling windows are cheap enough and stable enough to precompute broadly.
- For **minute data**, a full Alpha360-style tensor for every stock/date/cutoff can become very large. Precompute state families and compressed sufficient statistics first; materialize raw lag tensors only for fixed model pipelines that repeatedly reuse them.
- Alpha360's core value is not that every feature is individually brilliant. Its value is standardized, model-ready temporal context with consistent normalization and no ad hoc IO.

## Daily Features Worth Precomputing

These should be parquet/datamart candidates because they are cheap, reused often, and stable.

### Daily Alpha360-Lite

Dataset candidate:

```text
daily_alpha360_lite_v1
```

Current implementation status:

```text
module=factor_factory/data_api/daily_alpha360_lite.py
script=scripts/build_daily_alpha360_lite.py
validator=scripts/validate_daily_alpha360_lite.py
status=read_only_local_builder_available
production_catalog_status=not_registered
```

Keys:

```text
ts_code + trade_date
```

Fields:

- lag windows for close/open/high/low/vwap/volume over 0..59 trading days
- price fields normalized by current close
- volume normalized by current volume or rolling median volume
- optional return-space version: log close returns, open-close return, high-low range, vwap-close spread

Recommended policy:

- Build daily first, not minute.
- Keep raw normalized lags and a smaller engineered set.
- Use IS-fitted normalization only for model training processors; raw feature datamart itself should stay factual and no-future.
- Treat the current builder as a proof-producing artifact generator. Production acceptance still requires full-window backfill, catalog registration, QA summary, warm read proof, and true worker read smoke.

Local proof command:

```bash
PYTHONPATH=. python3 scripts/build_daily_alpha360_lite.py \
  --input-parquet /path/to/clean_daily_bar.parquet \
  --output-parquet /tmp/daily_alpha360_lite_v1.parquet \
  --qa-output /tmp/daily_alpha360_lite_v1.qa.json \
  --lookback 60
```

The script writes only the requested parquet and QA JSON. It does not write a catalog, datamart registry, production backend config, or Factor Forge artifact.

Validation and warm-read proof command:

```bash
PYTHONPATH=. python3 scripts/validate_daily_alpha360_lite.py \
  --feature-parquet /tmp/daily_alpha360_lite_v1.parquet \
  --qa-path /tmp/daily_alpha360_lite_v1.qa.json \
  --output-path /tmp/daily_alpha360_lite_v1.validation.json \
  --lookback 60 \
  --min-row-count 100000 \
  --max-warm-read-seconds 5
```

The validator rereads the parquet, rebuilds QA, compares it with the source QA, checks expected feature columns, checks duplicate keys, records `warm_read_seconds`, and emits a `catalog_candidate` object. It still does not register the dataset. Formal catalog registration requires a separate production step after full-window proof and true-worker read smoke.

Required production acceptance chain:

```text
build_daily_alpha360_lite.py full-window output
  -> validate_daily_alpha360_lite.py ACCEPT
  -> catalog candidate review
  -> DataApiClient read smoke on true research worker
  -> active catalog registration
```

Local real-data bounded proof, 2026-06-17:

```text
source=/Users/humphrey/projects/factor-factory-data-api/data/clean/daily_clean.parquet
source_rows=11612429
source_dates=20100104..20260507
source_tickers=5178
proof_window=20240102..20240131
lookback=60
output=/tmp/daily_alpha360_lite_202401.parquet
qa=/tmp/daily_alpha360_lite_202401.qa.json
validation=/tmp/daily_alpha360_lite_202401.validation.json
verdict=ACCEPT
rows=99758
dates=22
tickers=4592
features=360
duplicate_key_count=0
warm_read_seconds=0.105
output_size_mb=316.59
```

Production implication:

- The bounded proof confirms the feature contract is executable on real `clean_daily_bar`.
- The file size is already large for one month. Full-window production should use partitioned parquet by `trade_date`, not one monolithic wide file.
- Readers should project only required feature columns. Do not load all 360 columns unless the model pipeline requires the full Alpha360-lite tensor.
- True production acceptance still needs full-window or explicitly bounded production-scale build, catalog registration, and true worker DataApiClient smoke.

Partitioned bounded proof, 2026-06-17:

```text
source=/Users/humphrey/projects/factor-factory-data-api/data/clean/daily_clean.parquet
proof_window=20240102..20240131
lookback=60
output_root=/tmp/daily_alpha360_lite_202401_partitioned
qa=/tmp/daily_alpha360_lite_202401_partitioned.qa.json
validation=/tmp/daily_alpha360_lite_202401_partitioned.validation.json
catalog_candidate=/tmp/daily_alpha360_lite_202401_partitioned.catalog.json
read_smoke=/tmp/daily_alpha360_lite_202401_partitioned.read_smoke.json
verdict=ACCEPT
rows=99758
dates=22
tickers=4592
features=360
duplicate_key_count=0
partition_column=trade_date
partition_count=22
warm_read_seconds=0.163
partitioned_size_mb=327.44
DataApiClient_projection_smoke=ACCEPT
projection_fields=CLOSE0,CLOSE59,VOLUME1
projection_rows_on_20240110=4546
```

Implementation note:

- Partition files drop the physical `trade_date` column and rely on hive path `trade_date=YYYYMMDD`; this avoids pyarrow schema conflicts between file columns and partition columns.
- The Data API local parquet backend can read the partitioned candidate with `partition_columns=["trade_date"]` and project only requested feature columns.
- The partitioned proof is mechanically ready for catalog review, but not production accepted because it is still a one-month bounded proof on Mac, not a full-window or true-worker proof.

### Daily Technical State Pack

Dataset candidate:

```text
daily_technical_state_v1
```

Current implementation status:

```text
module=factor_factory/data_api/daily_technical_state.py
script=scripts/build_daily_technical_state.py
validator=scripts/validate_daily_technical_state.py
status=read_only_partitioned_builder_available
production_catalog_status=not_registered
```

Fields:

- returns: 1d, 2d, 5d, 10d, 20d, 60d
- volatility: rolling std, downside std, realized range
- trend: moving-average ratios, slope, distance to high/low
- volume/liquidity: turnover, amount, volume ratio, Amihud-style illiquidity
- distribution: return skewness, excess kurtosis, tail asymmetry
- cross-section-ready values: optional date-level rank/zscore outputs if clearly labeled

Implemented v1 fields:

```text
ret_1d
ret_5d
ret_20d
range_pct
open_close_ret
vwap_close_spread
ma5_close_ratio
ma20_close_ratio
volatility_20d
downside_volatility_20d
ret_skew_20d
ret_excess_kurtosis_20d
ret_tail_asymmetry_20d
amount_mean_20d
volume_ratio_20d
amihud_20d
```

Local partitioned bounded proof, 2026-06-17:

```text
source=/Users/humphrey/projects/factor-factory-data-api/data/clean/daily_clean.parquet
proof_window=20240102..20240131
output_root=/tmp/daily_technical_state_202401_partitioned
qa=/tmp/daily_technical_state_202401_partitioned.qa.json
validation=/tmp/daily_technical_state_202401_partitioned.validation.json
catalog_candidate=/tmp/daily_technical_state_202401_partitioned.catalog.json
read_smoke=/tmp/daily_technical_state_202401_partitioned.read_smoke.json
verdict=ACCEPT
rows=99758
dates=22
tickers=4592
features=16
duplicate_key_count=0
partition_column=trade_date
partition_count=22
warm_read_seconds=0.038
partitioned_size_mb=15.38
DataApiClient_projection_smoke=ACCEPT
projection_fields=ret_1d,volatility_20d,amihud_20d
projection_rows_on_20240110=4546
```

Production implication:

- `daily_technical_state_v1` is much lighter than `daily_alpha360_lite_v1` and should be the first daily feature-state candidate to productionize.
- It is suitable for factor prototypes, tree models, neutralization controls, and data feasibility checks.
- Full-window production still requires true-worker read smoke before active catalog registration.

Resume/batch proof, 2026-06-17:

Current worker-plan closeout chain, 2026-06-17:

```text
dataset=daily_technical_state_v1
bundle=/tmp/daily_feature_worker/daily_technical_state_full_is.resume_bundle.json
validation=/tmp/daily_feature_worker/daily_technical_state_full_is.resume_bundle.validation.json
validation_verdict=ACCEPT
worker_command_count=5
has_closeout=true
closeout_script=scripts/closeout_daily_technical_state.py
```

The closeout script converts the final validator output, catalog candidate, worker read smoke, and batch manifests into a standard `datamart_closeout_v1` ACCEPT/BLOCK artifact. It keeps active catalog registration as a separate explicit step.

```text
source=/Users/humphrey/projects/factor-factory-data-api/data/clean/daily_clean.parquet
proof_window=20240102..20240628
output_root=/tmp/daily_technical_state_2024h1_partitioned
batch1_manifest=/tmp/daily_technical_state_2024h1.batch1.manifest.json
batch2_manifest=/tmp/daily_technical_state_2024h1.batch2.manifest.json
validation=/tmp/daily_technical_state_2024h1.validation.json
read_smoke=/tmp/daily_technical_state_2024h1.read_smoke.json
batch1_processed_dates=40
batch1_remaining_dates=77
batch2_skipped_dates=40
batch2_processed_dates=77
batch2_remaining_dates=0
verdict=ACCEPT
rows=528570
dates=117
tickers=4636
features=16
duplicate_key_count=0
partition_count=117
warm_read_seconds=0.075
partitioned_size_mb=81.50
DataApiClient_projection_smoke=ACCEPT
projection_fields=ret_1d,volatility_20d,amihud_20d
projection_rows_on_20240410=4576
```

Resume contract:

- `build_daily_technical_state.py --max-dates N` processes only the first N pending output dates.
- `--skip-existing` keeps existing `trade_date=YYYYMMDD` partitions and processes only missing dates.
- `validate_daily_technical_state.py --allow-partial-source-qa` is required when the latest QA describes only the final resumed batch; the validator then rebuilds full-output QA from the whole partition root.

Resource estimate:

- 2024H1 proof is 81.5MB for 117 trading days, roughly 0.70MB per trade date.
- A 2016-2025 IS build is expected to be low-single-digit GB for this 16-feature pack, materially smaller than Alpha360-lite.
- Full-window production should run on the true research worker or batch worker, then return catalog/QA/read-smoke artifacts for review.

True-worker plan-only bundle, 2026-06-17:

```text
builder=scripts/build_daily_feature_worker_resume_bundle.py
validator=scripts/validate_daily_feature_worker_resume_bundle.py
bundle=/tmp/daily_feature_worker/daily_technical_state_full_is.resume_bundle.json
bundle_validation=/tmp/daily_feature_worker/daily_technical_state_full_is.resume_bundle.validation.json
verdict=ACCEPT
dataset_id=daily_technical_state_v1
instance_id=i-02cc0b6e93856fbb4
repo=/home/ubuntu/.openclaw/workspace/factorforge-data-api
input_parquet=/home/ubuntu/factorforge_data_api_cache/data/clean/daily_clean.parquet
output_root=/home/ubuntu/factorforge_data_api_cache/datamarts/daily_technical_state_v1
window=20160104..20250711
max_dates_per_batch=80
min_row_count=1000000
smoke_date=20240110
```

The bundle is deliberately plan-only:

- It includes local EC2/SSM readiness inspection commands.
- It includes worker-side batch1, resume batch2, validator, and DataApiClient read-smoke commands.
- It does **not** start the instance, send SSM commands, run worker commands, write active catalog, write Factor Forge artifacts, or start any production loop.
- After explicit approval to execute on the true worker, expected return artifacts are:
  - `daily_technical_state_full_is.batch1.qa.json`
  - `daily_technical_state_full_is.batch1.manifest.json`
  - `daily_technical_state_full_is.batch2.qa.json`
  - `daily_technical_state_full_is.batch2.manifest.json`
  - `daily_technical_state_full_is.validation.json`
  - `daily_technical_state_full_is.catalog.json`
  - `daily_technical_state_full_is.read_smoke.json`

### Investability And Universe State

Already important and should remain mandatory for official backtests:

```text
tradability_risk_flags_daily
standard_full_market_universe
microcap_universe
index_weight_universe
daily_basic_backtest_base
```

Rule:

```text
official backtest universe = requested universe joined with tradability_risk_flags_daily on trade_date + ts_code
```

## Minute Features Worth Precomputing

Minute features should be split into state families. Do not precompute every possible factor. Precompute reusable states and sufficient statistics that many factors can consume.

### Cutoff Intraday State Pack

Dataset candidate:

```text
intraday_cutoff_state_pack_v1
```

Keys:

```text
ts_code + trade_date + cutoff_time
```

Cutoffs:

```text
10:30 / 11:30 / 14:00 / 14:30 / 14:50 / 14:55
```

Fields:

- open-to-cutoff return
- cutoff VWAP / TWAP / VWAP-minus-TWAP
- amount, volume, turnover to cutoff
- minute return realized volatility
- high-low range to cutoff
- close-location / value-occupation location
- last-N-minute momentum and reversal states
- amount concentration by time bucket

### Intraday Distribution Moments

Dataset candidate:

```text
intraday_flow_distribution_moments_v1
```

This remains a high-priority blocker for Moneyflow V20-like reuse.

Fields:

- return skewness / excess kurtosis / tail asymmetry
- amount skewness / excess kurtosis / tail asymmetry
- signed-flow skewness / excess kurtosis / tail asymmetry
- HHI, entropy, top-share concentration
- large/small proxy states
- no-future proof per cutoff

### Terminal Correlation And Recurrence State

Dataset candidates:

```text
intraday_terminal_corr_state_v1
intraday_ema_slow_state_v1
```

Use cases:

- CPV: terminal price-volume correlation per stock/date/cutoff
- Moneyflow slow state: group-wise recurrence such as `H_t = lambda H_{t-1} + (1-lambda) S_t`
- cutoff-specific recurrences that do not need full minute vectors

Important implementation rule:

- If downstream only uses the cutoff terminal value, do not materialize all minute rows.
- Use `terminal_rolling_corr_by_group` or `terminal_ema_state_by_group`.
- If chunking by date, explicitly pass prior state across chunks; do not reset yearly and claim full-window continuity.

### Pseudo Dollar And Event Buckets

Dataset candidates:

```text
intraday_pseudo_dollar_bar_v1
intraday_event_bucket_state_v1
```

Policy:

- Label pseudo dollar bars clearly as built from 1-minute bars, not tick dollar bars.
- Use them as compressed market activity states.
- True tick dollar bars require tick source coverage and a separate contract.

## What Should Stay On-Demand

Do not globally precompute features when:

- the formula is a one-off branch with unclear reuse
- it requires too many parameter combinations
- it depends on labels, future returns, model residuals, or revision-specific fitting
- it uses OOS data for anything other than evaluation
- it generates very wide tensors that most research branches will not consume

For these, Data API should provide:

- fast prepared minute cache
- shared operator kernels
- bounded worker benchmark gate
- optional one-branch datamart after reuse is likely

## Data Team Daily Work

A serious buy-side data group is not only cleaning data. Cleaning is the floor. The daily loop is closer to this:

Machine-readable checklist:

```text
docs/operations/data-team-daily-ops-checklist.v1.json
```

Researcher handoff package:

```bash
PYTHONPATH=. python3 scripts/build_data_api_handoff_package.py \
  --output-dir /tmp/data_api_handoff_package
```

This package is read-only. It bundles the status report, registry validation proof, crosslink proof, and a README for Factor Forge architects/researchers. It does not publish active catalog entries, start workers, or write Factor Forge artifacts.

Feature precompute decision report:

```bash
PYTHONPATH=. python3 scripts/build_feature_precompute_decision_report.py \
  --output /tmp/feature_precompute_decision_report.json \
  --markdown-output /tmp/feature_precompute_decision_report.md
```

Use this report to decide whether a feature family belongs in a production datamart, requires source readiness first, should remain model-specific like Alpha360, or should stay on the research side because it depends on the final universe and neutralization controls.

Datamart readiness report:

```bash
PYTHONPATH=. python3 scripts/build_datamart_readiness_report.py \
  --output /tmp/datamart_readiness_report.json \
  --markdown-output /tmp/datamart_readiness_report.md
```

Use this report to inspect proof-path existence, ACCEPT/BLOCK proof status, remaining registration blockers, and the next action for each planned or candidate datamart.

1. Source freshness and coverage
   - ingest daily/minute/fundamental/index/universe/risk-flag updates
   - detect missing trade dates, partial days, duplicate keys, vendor drift
   - reconcile calendars and corporate actions

2. Data product publishing
   - write parquet/qlib/datamart partitions
   - update catalog metadata and coverage summaries
   - keep versioned schemas and producer versions
   - maintain warm caches on research machines

3. Quality and legality proof
   - duplicate key checks
   - null ratio and outlier checks
   - no-future / cutoff legality checks
   - IS/OOS window labeling
   - representative read smoke on the true research worker

4. Reusable feature/state production
   - daily technical states
   - universe and investability tables
   - minute cutoff states
   - distribution moments
   - factor-family states with high reuse probability

5. Performance engineering
   - projection and partition pruning
   - prepared caches
   - direct-array / vectorized / numba kernels
   - worker/batch resource sizing
   - resume/retry/shard plans
   - performance regression dashboards

6. Research handoff
   - catalog-first usage docs
   - sample commands
   - latency/row-count proof
   - explicit BLOCK tokens when data contracts are not ready

## Priority Queue

P0:

- finish direct-array benchmark gate and worker-scale proof path
- produce `intraday_flow_distribution_moments_v1`
- keep `daily_basic_backtest_base` and investability filters current

P1:

- build `daily_alpha360_lite_v1`
- build `daily_technical_state_v1`
- build `intraday_cutoff_state_pack_v1`

P2:

- build CPV terminal state datamart if multiple branches reuse it
- build pseudo dollar/event bucket states after production size estimate
- evaluate whether Qlib `.bin` materialization is worth keeping in parallel with parquet for model pipelines

## Acceptance For Any New Precomputed Feature Dataset

Every accepted datamart must ship:

```text
catalog.json
qa.json
schema_version
producer_version
partition_column
unique_key
coverage summary
missing dates
duplicate key count
null ratio summary
warm read timing
true worker read smoke
information-set legality notes
```

Read smoke should use the shared Data API smoke runner:

```bash
PYTHONPATH=. python3 scripts/run_data_api_read_smoke.py \
  --catalog /path/to/catalog.json \
  --dataset-id <dataset_id> \
  --start-date <yyyymmdd> \
  --end-date <yyyymmdd> \
  --fields <comma-separated-fields> \
  --output-path /tmp/<dataset_id>.read_smoke.json
```

This keeps closeout proof comparable across daily technical state, Alpha360-style tensors, intraday moments, cutoff states, and future datamarts.

Production feature datasets must not be accepted from local Mac-only proof if the intended consumer is the true research worker.
