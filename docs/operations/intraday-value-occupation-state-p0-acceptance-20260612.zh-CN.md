# Intraday Value Occupation State P0 Acceptance

日期：2026-06-12

验收对象：

```text
dataset_id = intraday_value_occupation_state_v1
scope = P0 data contract acceptance only
alpha_review = not performed
```

## 结论

研究侧验收结论：

```text
data_acceptance = ACCEPT_WITH_MINOR_METADATA_FIX
blocking_issue = none
ready_for_research_test = yes
```

本次只验收数据口径、coverage、catalog、QA/read smoke 和信息集边界；不评价任何因子有效性。

## Proof Artifacts

```text
final_delivery_proof = s3://yufan-data-lake/factorforge/proofs/intraday_value_occupation_state/v1/final_delivery_proof.json
final_catalog = s3://yufan-data-lake/factorforge/proofs/intraday_value_occupation_state/v1/final_catalog.json
source_coverage = s3://yufan-data-lake/factorforge/proofs/intraday_value_occupation_state/v1/final_source_coverage.json
output_coverage = s3://yufan-data-lake/factorforge/proofs/intraday_value_occupation_state/v1/final_output_coverage.json
read_smoke = s3://yufan-data-lake/factorforge/proofs/intraday_value_occupation_state/v1/final_read_smoke.json
datamart = s3://yufan-data-lake/factorforge/datamart/intraday_value_occupation_state/v1
```

Local acceptance copies:

```text
/tmp/intraday_value_occupation_final_delivery_proof.json
/tmp/intraday_value_occupation_final_catalog.json
/tmp/intraday_value_occupation_final_source_coverage.json
/tmp/intraday_value_occupation_final_output_coverage.json
/tmp/intraday_value_occupation_final_read_smoke.json
/tmp/intraday_value_occupation_20250711.parquet
```

## Contract Checks

### State-only boundary

PASS.

Catalog columns contain P0 state variables only. The following research-side composite scores are not present:

```text
support_minus_overhang
support_absorption_minus_overhang
below_cost_guarded_support
support_with_below_cost_cap
vp_below_cost_repair_v1
vp_support_defense_repair_v1
```

Catalog metadata also states:

```text
field_boundary = state_variables_only_no_alpha_scores
research_p0_confirmed_scope = P0 state variables only; research side computes composite scores and alpha evaluation downstream.
```

### MVP parameters

PASS.

```text
cutoff_times = ["14:50:00"]
lookback_days = [20]
bin_width_bps = 20
value_area_mass = 0.7
near_band_bps = 300
source_dataset = minute_bar
no_future_intraday_minutes = true
```

### Unique key

PASS.

```text
unique_key = ts_code + trade_date + cutoff_time + lookback_days
duplicate_key_count = 0
```

Note: in the sampled physical parquet file, `trade_date` is supplied by the Hive partition path rather than stored as an in-file column. Data API read smoke returns `trade_date` correctly, so this is acceptable as long as Data API/catalog treats `trade_date` as a partition column.

### Required P0 fields

PASS.

Required field groups are present in catalog:

```text
key / metadata
price-axis core
support / overhang
below-cost / repair diagnostics
```

Sample physical partition:

```text
s3://yufan-data-lake/factorforge/datamart/intraday_value_occupation_state/v1/trade_date=20250711/part-000.parquet
rows = 5,393
forbidden composite fields = []
duplicate keys with partition trade_date = 0
cutoff_times = ["14:50:00"]
lookback_days = [20]
schema_version = intraday_value_occupation_state_v1_p0
producer_version = factorforge_data_api_value_occupation_20260610
no_future_intraday_minutes = [true]
```

Sample field sanity:

```text
lower_support_ratio: null=0, min=0.0, max=0.96700627
upper_overhang_ratio: null=0, min=0.0, max=0.87683221
below_mass_ratio: null=0, min=0.0, max=0.99922468
above_mass_ratio: null=0, min=0.0, max=0.99963083
below_cost_depth: null=0, min=0.0, max=0.47955977
amount_total: null=0, min=172,434,809.0, max=204,390,186,673.3
reference_price: null=0, min=1.4, max=1,435.78
vwap_cost: null=0, min=1.3563383, max=1,422.5550406
```

## Coverage / QA

### Source coverage

PASS.

```text
source = catalog:minute_bar
expected_date_count = 2313
available_date_count = 2534
covered_date_count = 2313
missing_date_count = 0
coverage_ratio = 1.0
min_available_date = 20160104
max_available_date = 20260611
missing_dates = []
```

### Output coverage

PASS, with known missing date.

```text
expected_date_count = 2313
target_date_count_from_shards = 2313
output_partition_count = 2312
output_date_count = 2312
missing_dates = ["20160107"]
extra_dates = []
row_count = 9,105,107
output_min_trade_date = 20160104
output_max_trade_date = 20250711
duplicate_key_count = 0
```

`20160107` is accepted as the known circuit-breaker short trading day under the delivered missing-date policy.

Output hard checks all pass, including:

```text
duplicate_key_count_zero = true
duplicate_key_count_zero_global = true
no_future_intraday_minutes_true = true
expected_dates_2313 = true
target_date_count_2313 = true
s3_output_partition_count_matches_missing_policy = true
output_missing_dates_known = true
extra_output_dates_empty = true
all_shard_verdicts_accept = true
```

Null / finite checks:

```text
null_ratio_by_field = 0.0 for all reported fields
finite_ratio_by_numeric_field = 1.0 for all reported numeric fields
```

### Read smoke

PASS.

```text
verdict = ACCEPT
status = ready
validation_result = PASS
query = 20250709 through 20250711
row_count = 16,171
date_count = 3
ticker_count = 5,395
duplicate_key_count = 0
source_backend = s3_file
source_uri = s3://yufan-data-lake/factorforge/datamart/intraday_value_occupation_state/v1
elapsed_seconds = 1.4134663639999872
```

Read smoke returned helper keys:

```text
ts_code
trade_date
cutoff_time
lookback_days
```

## Minor Metadata Issue

Non-blocking WARN:

```text
catalog.metadata.qa_summary_path = s3:/yufan-data-lake/factorforge/proofs/intraday_value_occupation_state/v1/final_output_coverage.json
```

This should be:

```text
s3://yufan-data-lake/factorforge/proofs/intraday_value_occupation_state/v1/final_output_coverage.json
```

This is a metadata typo only. The primary dataset URI and proof URIs are correct, and the read smoke passes. Ask Data group to patch catalog metadata before or alongside the next catalog sync, but do not block research testing on this issue.

## Acceptance Decision

```text
ACCEPT_WITH_MINOR_METADATA_FIX
```

The P0 datamart is accepted for research-side testing. Next research step can consume `intraday_value_occupation_state_v1` and test:

```text
1. static support-overhang baseline
2. drift / momentum confirmed support
3. below-cost as penalty/control
4. momentum/reversal/Barra-neutral incremental IC
```

Do not promote any factor from this data acceptance step. Alpha evaluation starts only after the research-side factor tests run.
