# intraday_flow_distribution_moments_v1 Production Runbook

Date: 2026-06-16

Scope: Data API production datamart only. Do not start clean data, search_worker, official promotion, or Factor Forge production loop.

## Dataset

`intraday_flow_distribution_moments_v1`

Source:

- `minute_bar`

Unique key:

```text
ts_code + trade_date + cutoff_time
```

Supported cutoffs:

```text
10:30:00, 11:30:00, 14:00:00, 14:30:00, 14:50:00, 14:55:00
```

Information-set rules:

- `no_future_intraday_minutes=true`
- every row uses only `trade_time <= cutoff_time`
- large/small proxy thresholds use prior trade dates only
- signed-flow is an explicit 1m proxy: `sign(close-open) * amount`, not true order flow
- default production operator: `operator_backend=vectorized`
- tail asymmetry method: exact per-group 10%/90% quantile tail absolute-mass asymmetry

## Builder

Module:

```text
factor_factory/data_api/flow_distribution_moments.py
```

CLI:

```text
scripts/build_intraday_flow_distribution_moments.py
```

Production runs must keep:

```text
--operator-backend vectorized
```

`operator_backend=reference` is only for regression testing because it uses Python group loops and is too slow for production backfill.

`operator_backend=polars` is implemented and contract-tested, but should not replace the default unless a bounded proof shows material speedup on the true worker.

## Local Bounded Smoke

Already verified locally with a synthetic parquet sample:

```text
verdict=ACCEPT
rows=4
dates=1
tickers=2
duplicate_key_count=0
read_seconds=0.0905
compute_seconds=0.0053
write_seconds=0.0038
```

PyArrow emitted sandbox-only CPU info warnings on macOS, but the datamart/QA/catalog outputs were written and accepted.

## Worker Bounded Proof

True factor research worker:

```text
instance_id=i-02cc0b6e93856fbb4
python=/usr/bin/python3
workspace=/home/ubuntu/.openclaw/workspace/factorforge
operator_backend=vectorized
```

Bounded full-market date:

```text
target_date=20240110
lookback_source_dates=20240102,20240103,20240104,20240105,20240108,20240109
```

Exact vectorized proof:

```text
verdict=ACCEPT
output_path=/opt/factorforge/data-api-datamarts/intraday_flow_distribution_moments_v1_bounded_vectorized_20240110_20260616T024616
qa_output=/opt/factorforge/data-api-proofs/intraday_flow_distribution_moments_v1_bounded_vectorized_20240110_20260616T024616.qa.json
catalog_output=/opt/factorforge/data-api-catalog/intraday_flow_distribution_moments_v1_bounded_vectorized_20240110_20260616T024616.catalog.json
rows=31482
dates=1
tickers=5247
duplicate_key_count=0
missing_dates=[]
read_seconds=1.5999
compute_seconds=44.4855
write_seconds=0.0862
```

Consumer IO warm read proof on the same schema/cardinality:

```text
verdict=ACCEPT
path=/opt/factorforge/data-api-datamarts/intraday_flow_distribution_moments_v1_bounded_fastvec_20240110_20260616T024850
rows=31482
dates=1
tickers=5247
duplicate_key_count=0
warm_read_seconds=0.0310
```

Note: the later `bounded_fastvec` run was useful as a consumer-IO and performance experiment, but production default remains exact `vectorized`; do not publish the approximate fast-tail definition as the production contract.

Polars backend proof on the same worker/date:

```text
verdict=ACCEPT
operator_backend=polars
output_path=/opt/factorforge/data-api-datamarts/intraday_flow_distribution_moments_v1_bounded_polars_20240110_20260616T030453
qa_output=/opt/factorforge/data-api-proofs/intraday_flow_distribution_moments_v1_bounded_polars_20240110_20260616T030453.qa.json
catalog_output=/opt/factorforge/data-api-catalog/intraday_flow_distribution_moments_v1_bounded_polars_20240110_20260616T030453.catalog.json
rows=31482
dates=1
tickers=5247
duplicate_key_count=0
missing_dates=[]
read_seconds=1.5579
compute_seconds=43.9362
write_seconds=0.0783
warm_read_seconds=0.0293
```

Conclusion: Polars preserves the contract but does not materially improve this workload versus exact pandas vectorized. The remaining bottleneck is the current algorithm shape: all six cutoffs rescan the same intraday rows and run exact tail-quantile grouping. The next production-speed operator should compute cutoff states from cumulative sufficient statistics per `ts_code + trade_date`, or move the grouped window computation into a query engine designed for sorted intraday state.

Map-reduce operator proof on the same worker/date:

```text
verdict=ACCEPT
operator_backend=mapreduce
output_path=/opt/factorforge/data-api-datamarts/intraday_flow_distribution_moments_v1_bounded_mapreduce_20240110_20260616T031751
rows=31482
dates=1
tickers=5247
duplicate_key_count=0
missing_dates=[]
read_seconds=1.6449
compute_seconds=46.7151
write_seconds=0.0912
```

Threaded map-reduce operator proof:

```text
verdict=ACCEPT
operator_backend=mapreduce_threaded
output_path=/opt/factorforge/data-api-datamarts/intraday_flow_distribution_moments_v1_bounded_mapreduce_threaded_20240110_20260616T032103
rows=31482
dates=1
tickers=5247
duplicate_key_count=0
missing_dates=[]
read_seconds=1.5129
compute_seconds=54.7251
write_seconds=0.0775
warm_read_seconds=0.0326
```

Conclusion: Python-level map-reduce preserves the contract but is not production-fast. Threading did not scale because the workload remains mostly Python/GIL-bound; health probe showed the main thread carrying almost all CPU. The map-reduce design should be kept, but the worker implementation should move to process-level date/shard parallelism, Numba/Rust, or a sorted columnar engine rather than Python ThreadPool.

Process-sharded map-reduce proof:

```text
verdict=ACCEPT
operator_backend=process_sharded_mapreduce
output_path=/opt/factorforge/data-api-datamarts/intraday_flow_distribution_moments_v1_bounded_process_sharded_20240110_20260616T033745
rows=31482
dates=1
tickers=5247
duplicate_key_count=0
missing_dates=[]
read_seconds=1.6337
compute_seconds=41.5452
write_seconds=0.0891
warm_read_seconds=0.0302
```

Decision: process sharding is correct as an execution mode, but this bounded proof is only about 7% faster than exact vectorized. Keep it experimental until the Python group-loop and exact-tail overhead are replaced by a compiled or columnar one-pass kernel.

Process-sharded vectorized proof:

```text
verdict=ACCEPT
operator_backend=process_sharded_vectorized
output_path=/opt/factorforge/data-api-datamarts/intraday_flow_distribution_moments_v1_bounded_process_sharded_vectorized_20240110_20260616T050150
rows=31482
dates=1
tickers=5247
duplicate_key_count=0
missing_dates=[]
read_seconds=1.7149
compute_seconds=44.2925
write_seconds=0.0909
warm_read_seconds=0.0325
```

Decision: combining vectorization with process sharding is contract-correct, but not materially faster on this bounded workload. Do not promote as default. The next acceleration step should be Numba/Rust kernels or a columnar one-pass plan, not additional pandas process wrappers.

Numba kernel proof:

```text
verdict=ACCEPT
operator_backend=numba
worker_python=3.12.3
temporary_venv=/tmp/ff-numba-venv
numba_version=0.65.1
output_path=/opt/factorforge/data-api-datamarts/intraday_flow_distribution_moments_v1_bounded_numba_20240110_20260616T052939
rows=31482
dates=1
tickers=5247
duplicate_key_count=0
missing_dates=[]
read_seconds=1.6894
compute_seconds=44.7291
write_seconds=0.0832
warm_read_seconds=0.0303
temporary_venv_removed=true
```

Decision: the Numba cutoff-state kernel is correct but the current single-process wrapper is not faster than exact vectorized pandas. The remaining cost is Python-side grouping/slicing and threshold preparation around the kernel. Keep `numba` experimental until it is paired with coarse process shards or rewritten around sorted contiguous arrays.

## Numba Sorted-Array Backend

Local P1.2 implementation:

```text
operator_backend=numba_sorted
local_contract_test=PASS
isolated_numba_contract_test=PASS
implementation=sorted ts_code/trade_date/hhmmss arrays with group offsets
parallelism=numba prange over stock-date groups
production_default=false
```

True-worker bounded proof:

```text
verdict=ACCEPT
parity_verdict=ACCEPT
performance_promotion_verdict=BLOCK
operator_backend=numba_sorted
instance_id=i-02cc0b6e93856fbb4
repo_path=/home/ubuntu/.openclaw/workspace/factorforge-data-api
cache_root=/home/ubuntu/factorforge_data_api_cache
minute_root=/home/ubuntu/factorforge_data_api_cache/s3_parquet/minute_bar-raw_v1-0b2b836c57d763c6
temporary_venv=/tmp/ff-numba-sorted-venv
worker_python=/tmp/ff-numba-sorted-venv/bin/python
numba_version=0.65.1
temporary_venv_removed=true
output_path=/home/ubuntu/factorforge_data_api_cache/derived_features/intraday_flow_distribution_moments_v1_bounded_numba_sorted_fixed2_20240110_20260616T000000
qa_output=/home/ubuntu/factorforge_data_api_cache/derived_features/intraday_flow_distribution_moments_v1_bounded_numba_sorted_fixed2_20240110.qa.json
catalog_output=/home/ubuntu/factorforge_data_api_cache/derived_features/intraday_flow_distribution_moments_v1_bounded_numba_sorted_fixed2_20240110.catalog.json
parity_path=/home/ubuntu/factorforge_data_api_cache/derived_features/intraday_flow_distribution_moments_v1_bounded_numba_sorted_fixed2_20240110.parity.json
rows=31482
dates=1
tickers=5247
duplicate_key_count=0
missing_dates=[]
read_seconds=4.8866
compute_seconds=95.4972
write_seconds=0.0874
warm_read_seconds=0.0475
output_file_size_bytes=7160384
vectorized_compute_seconds_for_parity=100.7728
numba_sorted_warm_compute_seconds_for_parity=95.6571
max_abs_diff_amount_sum=7.1526e-07
max_abs_diff_large_proxy_amount=4.7684e-07
max_abs_diff_signed_flow_hhi=6.5226e-16
```

This backend is intended to test the large-institution style execution plan: map by instrument/date, keep time-series operations inside a compiled kernel, and do cross-sectional work only after per-instrument state is materialized. It is contract-correct after parity proof, but not accepted as production default because same-input worker timing only improved from 100.7728s to 95.6571s. The next proof should target threshold/read preparation, exact-tail quantile cost, and DataFrame materialization rather than another wrapper-level backend.

## Prepared Minute Cache Proof

The meaningful speedup came from moving raw-minute normalization out of the research-time hot path.

```text
dataset_candidate=prepared_minute_bar_v1
source_dataset=minute_bar
prepared_columns=ts_code,trade_date,hhmmss,amount_abs,minute_ret,signed_amount,vol
proof_date=20240110
worker_instance=i-02cc0b6e93856fbb4
prepared_cache_root=/home/ubuntu/factorforge_data_api_cache/s3_parquet/minute_bar-prepared_v1-speed-p4-20240110
prepared_cache_build_seconds=78.3862
prepared_cache_size_bytes=264571199
prepared_cache_row_count=16721924
prepared_cache_date_count=31
parity_verdict=ACCEPT
row_count=31482
key_equal=true
missing_dates=[]
vectorized_compute_seconds_on_prepared_cache=27.5391
numba_sorted_warm_compute_seconds_on_prepared_cache=19.5849
numba_sorted_prepared_warm_seconds=0.8457
speedup_vs_raw_vectorized_compute=4.65x
speedup_vs_raw_numba_sorted_warm_compute=4.18x
```

Operational decision:

- Do not treat `numba_sorted` alone as the production acceleration.
- Build and validate `prepared_minute_bar_v1` as the reusable Data API datamart.
- `scripts/build_prepared_minute_bar.py` can now write parquet partitions, QA json, and standalone catalog json for this dataset.
- Minute-derived state builders may consume `prepared_minute_bar_v1` by explicit path during proof runs.
- Do not make `prepared_minute_bar_v1` the production default until full-worker backfill, worker read smoke, and research parity are accepted.
- Raw `minute_bar` should remain the source of truth, but raw normalization should run in the data update path, not inside each factor research job.

Prepared cache contract command:

```bash
python3 scripts/build_prepared_minute_bar.py \
  --minute-root /path/to/minute_bar \
  --output-root /path/to/prepared_minute_bar_v1 \
  --start 20240102 \
  --end 20240131 \
  --qa-output /path/to/prepared_minute_bar_v1.qa.json \
  --catalog-output /path/to/prepared_minute_bar_v1.catalog.json
```

Resumable full-window prepared cache command:

```bash
python3 scripts/build_prepared_minute_bar.py \
  --minute-root /path/to/minute_bar \
  --output-root /path/to/prepared_minute_bar_v1 \
  --start 20160104 \
  --end 20250711 \
  --skip-existing \
  --max-dates 20 \
  --qa-output /path/to/prepared_minute_bar_v1.batch.qa.json \
  --catalog-output /path/to/prepared_minute_bar_v1.batch.catalog.json \
  --manifest-output /path/to/prepared_minute_bar_v1.batch.manifest.json
```

Backfill safety contract:

```text
--skip-existing      skips partitions with trade_date=YYYYMMDD/part.parquet
--max-dates          limits non-skipped dates per run
manifest.processed_dates records partitions written in this batch
manifest.skipped_dates records already completed partitions
manifest.remaining_dates records dates not attempted because of max-dates
batch QA is not full-window proof until remaining_dates=[], missing_dates=[], read_errors=[]
```

Accepted true-worker resume proof:

```text
instance_id=i-02cc0b6e93856fbb4
raw_minute_root=/home/ubuntu/factorforge_data_api_cache/s3_parquet/minute_bar-raw_v1-0b2b836c57d763c6
resume_output_root=/home/ubuntu/factorforge_data_api_cache/s3_parquet/prepared_minute_bar_v1-resume-proof-20240110-20240111
proof_root=/home/ubuntu/factorforge_data_api_cache/proofs/prepared_minute_bar_v1_resume

batch1_command=max-dates=1, dates=20240110,20240111
batch1_verdict=ACCEPT
batch1_processed_dates=20240110
batch1_remaining_dates=20240111
batch1_row_count=1208860
batch1_runtime_seconds=6.3434

batch2_command=skip-existing=true, dates=20240110,20240111
batch2_verdict=ACCEPT
batch2_processed_dates=20240111
batch2_skipped_dates=20240110
batch2_remaining_dates=[]
batch2_row_count=1218760
batch2_runtime_seconds=6.2651
skip_existing_mtime_preserved=true

data_api_fetch_smoke_path=/home/ubuntu/factorforge_data_api_cache/proofs/prepared_minute_bar_v1_resume/resume.data_api_fetch_smoke.json
DataApiClient_status=ready
DataApiClient_row_count=2427620
DataApiClient_date_count=2
DataApiClient_by_date=20240110:1208860,20240111:1218760
DataApiClient_coverage_duplicate_key_count=0
DataApiClient_manual_duplicate_key_count_ts_date_hhmmss=0
DataApiClient_elapsed_seconds=1.8003
worker_stopped_after_proof=true
```

Full/backfill QA command:

```bash
python3 scripts/qa_prepared_minute_bar.py \
  --source-minute-root /path/to/minute_bar \
  --prepared-root /path/to/prepared_minute_bar_v1 \
  --start 20160104 \
  --end 20250711 \
  --source-ready-only \
  --qa-output /path/to/prepared_minute_bar_v1.full.qa.json \
  --catalog-output /path/to/prepared_minute_bar_v1.full.catalog.json \
  --read-smoke-output /path/to/prepared_minute_bar_v1.full.read_smoke.json
```

Full/backfill QA acceptance:

```text
qa.verdict=ACCEPT
expected_dates == prepared_dates
missing_dates=[]
read_errors=[]
duplicate_key_count=0
hard_checks.schema_columns_match=true
hard_checks.date_coverage_complete=true
read_smoke.verdict=ACCEPT
read_smoke.status=ready
read_smoke.coverage_duplicate_key_count=0
source_not_ready_dates reviewed and excluded from expected_dates
```

Accepted true-worker IS-candidate batch:

```text
instance_id=i-02cc0b6e93856fbb4
raw_minute_root=/home/ubuntu/factorforge_data_api_cache/s3_parquet/minute_bar-raw_v1-0b2b836c57d763c6
candidate_output_root=/home/ubuntu/factorforge_data_api_cache/s3_parquet/prepared_minute_bar_v1-is-candidate
proof_root=/home/ubuntu/factorforge_data_api_cache/proofs/prepared_minute_bar_v1_is_candidate
source_selection=explicit_source_ready_dates
dates=20160104,20160105,20160106,20160107,20160108,20160111,20160112,20160113,20160114,20160115,20160118,20160119,20160120,20160121,20160122,20160125,20240102,20240103,20240104,20240105
batch_verdict=ACCEPT
batch_row_count=13070307
batch_date_count=20
batch_duplicate_key_count=0
batch_missing_dates=[]
batch_runtime_seconds=72.1866
data_api_fetch_smoke_path=/home/ubuntu/factorforge_data_api_cache/proofs/prepared_minute_bar_v1_is_candidate/batch_ready20.data_api_fetch_smoke.json
DataApiClient_status=ready
DataApiClient_row_count=13070307
DataApiClient_date_count=20
DataApiClient_coverage_duplicate_key_count=0
DataApiClient_manual_duplicate_key_count_ts_date_hhmmss=0
DataApiClient_elapsed_seconds=10.5752
worker_stopped_after_proof=true
```

Source coverage note: the raw minute cache currently contains `.missing` marker partitions for non-trading dates such as 20160109/20160110. Full-window automation must use a source-ready trading calendar or explicit source-ready date selection; treating every `trade_date=*` directory as expected coverage will falsely block on marker partitions.

Required prepared-cache QA checks:

```text
dataset_id=prepared_minute_bar_v1
source_dataset=minute_bar
unique_key=ts_code+trade_date+hhmmss
columns=ts_code,trade_date,hhmmss,amount_abs,minute_ret,signed_amount,vol
duplicate_key_count=0
missing_dates=[]
schema_columns_match=true
catalog_load_smoke=ACCEPT
```

Accepted true-worker bounded proof:

```text
instance_id=i-02cc0b6e93856fbb4
trade_date=20240110
raw_minute_root=/home/ubuntu/factorforge_data_api_cache/s3_parquet/minute_bar-raw_v1-0b2b836c57d763c6
prepared_datamart_path=/home/ubuntu/factorforge_data_api_cache/s3_parquet/prepared_minute_bar_v1-bounded-worker-20240110
qa_path=/home/ubuntu/factorforge_data_api_cache/proofs/prepared_minute_bar_v1/prepared_minute_bar_v1_20240110.worker.qa.json
catalog_path=/home/ubuntu/factorforge_data_api_cache/proofs/prepared_minute_bar_v1/prepared_minute_bar_v1_20240110.worker.catalog.json
read_smoke_path=/home/ubuntu/factorforge_data_api_cache/proofs/prepared_minute_bar_v1/prepared_minute_bar_v1_20240110.worker.read_smoke.json
data_api_fetch_smoke_path=/home/ubuntu/factorforge_data_api_cache/proofs/prepared_minute_bar_v1/prepared_minute_bar_v1_20240110.worker.data_api_fetch_smoke.json
build_verdict=ACCEPT
build_runtime_seconds=6.2667
row_count=1208860
ticker_count=5247
duplicate_key_count=0
missing_dates=[]
direct_warm_read_seconds=0.0933
DataApiClient_status=ready
DataApiClient_elapsed_seconds=1.0381
DataApiClient_coverage_duplicate_key_count=0
```

Implementation note: DataApiClient validation must honor `catalog.datasets[dataset].metadata.unique_key`. For `prepared_minute_bar_v1`, the key is `ts_code + trade_date + hhmmss`; validating only `ts_code + trade_date` will falsely block every normal minute dataset.

## Prepared Input Opt-In

`intraday_flow_distribution_moments_v1` now has an explicit opt-in prepared-minute input path:

```bash
python3 scripts/build_intraday_flow_distribution_moments.py \
  --prepared-minute-root /path/to/prepared_minute_bar_v1 \
  --start 20240102 \
  --end 20240131 \
  --source-ready-only \
  --output-root /path/to/intraday_flow_distribution_moments_v1 \
  --qa-output /path/to/intraday_flow_distribution_moments_v1.qa.json \
  --catalog-output /path/to/intraday_flow_distribution_moments_v1.catalog.json \
  --skip-upload
```

Required QA fields for prepared-input runs:

```text
input_dataset=prepared_minute_bar_v1
input_minute_format=prepared
input_prepared_minute_columns=ts_code,trade_date,hhmmss,amount_abs,minute_ret,signed_amount,vol
performance_profile.input_dataset=prepared_minute_bar_v1
performance_profile.input_minute_format=prepared
realized_operator_backend=vectorized_prepared|polars_prepared|numba_sorted_prepared|process_sharded_vectorized_prepared
source_ready_policy.enabled=true when source root contains .missing marker partitions
source_not_ready_dates reviewed and excluded from target/lookback dates
```

Default behavior remains unchanged: existing `--minute-root` runs continue to read raw `minute_bar`-like partitions. `--prepared-minute-root` is explicit proof/runbook behavior only until full IS backfill, worker read smoke, and research parity are accepted.

## Prepared Speed Proof

Use the bounded speed proof only after source-ready filtering is explicit:

```bash
python3 scripts/run_prepared_cache_speed_proof.py \
  --raw-minute-root /path/to/minute_bar \
  --prepared-root /path/to/prepared_minute_bar_v1_speed_proof \
  --date 20240110 \
  --lookback-days 60 \
  --source-ready-only \
  --output-path /path/to/prepared_cache_speed_proof.json
```

Required proof fields:

```text
prepared_cache_source_ready_policy.enabled=true
prepared_cache_source_not_ready_dates=[] or reviewed marker partitions
prepared_dispatcher_backend=numba_sorted_prepared
prepared_dispatcher_key_equal=true
prepared_dispatcher_warm_seconds present
numba_sorted_prepared_warm_seconds present
performance_promotion_verdict=ACCEPT|BLOCK
performance_speedup_vs_vectorized present
performance_min_speedup_ratio present
```

If numba is unavailable, the parity proof must write `verdict=BLOCK` with `issues=["numba_unavailable"]` instead of crashing. That BLOCK is an environment-readiness result, not an alpha or data-contract failure.

`verdict=ACCEPT` only proves key/value parity. Operator replacement requires `performance_promotion_verdict=ACCEPT`; otherwise keep the existing production default and treat the candidate as an experimental backend.

If `--source-ready-only` is enabled and the target `--date` is not a source-ready raw minute partition, the speed proof must write `verdict=BLOCK` with `issues=["target_date_not_source_ready"]`. This is a source-coverage proof, and it must leave a JSON artifact at `--output-path` for automation/review instead of raising an unstructured exception.

For bottleneck diagnosis, use the bounded stage profiler before changing default operators:

```bash
python3 scripts/profile_flow_distribution_moments_operator.py \
  --minute-root /path/to/minute_bar \
  --date 20240110 \
  --cutoff-times 10:30:00,14:50:00 \
  --threshold-lookback-days 20,60 \
  --operator-backend vectorized \
  --source-ready-only \
  --output-path /path/to/operator_profile_20240110.json
```

Required profiler fields:

```text
stage_seconds.read_seconds
stage_seconds.prepare_seconds
stage_seconds.threshold_seconds
stage_seconds.operator_seconds
dominant_stage
input_dataset
operator_backend
realized_operator_backend
duplicate_key_count
output_key_hash
```

The profiler is proof-only. It must not trigger full-window backfill or change production backend selection by itself.

If a compiled profiler backend is unavailable, the profiler must still write a JSON proof with `verdict=BLOCK`, `issues=["operator_backend_unavailable"]`, and an `error` field. This is an environment/operator-readiness result, not source data coverage evidence.

If `--source-ready-only` filters out the requested target date, the profiler must still write a JSON proof with `verdict=BLOCK`, `issues` containing `missing_target_dates`, `missing_dates` containing the target date, and `source_not_ready_dates` listing the marker partition. This is source coverage evidence, not operator-performance evidence.

After individual profiler proofs, use the comparison wrapper to build one matrix proof:

```bash
python3 scripts/compare_flow_distribution_operator_profiles.py \
  --minute-root /path/to/minute_bar \
  --prepared-minute-root /path/to/prepared_minute_bar_v1 \
  --date 20240110 \
  --cutoff-times 10:30:00,14:50:00 \
  --threshold-lookback-days 20,60 \
  --operator-backends vectorized,numba_sorted \
  --source-ready-only \
  --output-path /path/to/operator_profile_comparison_20240110.json
```

Required comparison fields:

```text
profile_count
profiles[].profile_id
profiles[].verdict
profiles[].stage_seconds
best_profile_id
prepared_vs_raw_total_speedup
best_speedup_vs_raw_vectorized
baseline_profile_id
baseline_profile_accept
accepted_profile_row_count_equal
accepted_profile_duplicate_key_count_zero
accepted_profile_key_hash_equal
operator_replacement_verdict
operator_replacement_issues
```

The comparison wrapper must keep blocked backend profiles in `profiles[]` instead of dropping them. It is promotion evidence only; it must not change the production backend by itself.
Operator replacement must remain `BLOCK` if the `raw:vectorized` baseline is not `ACCEPT`, accepted profiles disagree on row count, disagree on `output_key_hash`, or any accepted profile has duplicate keys, even when the fastest profile is materially faster.

Before any backend replacement discussion, validate the comparison proof:

```bash
python3 scripts/validate_flow_distribution_operator_comparison.py \
  --proof-path /path/to/operator_profile_comparison_20240110.json \
  --output-path /path/to/operator_profile_comparison_20240110.validation.json
```

Validator `ACCEPT` requires:

```text
comparison verdict ACCEPT
operator_replacement_verdict ACCEPT
baseline_profile_id=raw:vectorized
baseline_profile_accept=true
accepted_profile_row_count_equal=true
accepted_profile_duplicate_key_count_zero=true
accepted_profile_key_hash_equal=true
accepted profile output_key_hash present
```

The validator is read-only. It writes a validation artifact and must not mutate backend configuration.

## Worker Bounded Proof Command

Use true factor research worker only:

```text
i-02cc0b6e93856fbb4
```

Do not use `openclaw-new` for this production proof.

Example one-month bounded proof after the worker is online and the repo is synced:

```bash
cd /home/ubuntu/projects/factor-factory-data-api

python3 scripts/build_intraday_flow_distribution_moments.py \
  --minute-root /opt/factorforge/data-api-cache/minute_bar \
  --start 20240102 \
  --end 20240131 \
  --output-root /opt/factorforge/data-api-datamarts/intraday_flow_distribution_moments_v1_is_bounded_202401 \
  --qa-output /opt/factorforge/data-api-proofs/intraday_flow_distribution_moments_v1_bounded_202401.qa.json \
  --catalog-output /opt/factorforge/data-api-catalog/intraday_flow_distribution_moments_v1_bounded_202401.catalog.json \
  --cutoff-times 10:30:00,11:30:00,14:00:00,14:30:00,14:50:00,14:55:00 \
  --threshold-lookback-days 20,60 \
  --min-minutes 20 \
  --research-window IS \
  --operator-backend vectorized \
  --skip-upload
```

To test the sorted-array kernel, change only:

```bash
  --operator-backend numba_sorted
```

Expected bounded proof artifacts:

- QA json
- standalone catalog json
- partitioned parquet datamart
- runtime profile with read/compute/write seconds

## Full IS Backfill Command

Run only after bounded proof ACCEPT and cost estimate is acceptable:

```bash
cd /home/ubuntu/projects/factor-factory-data-api

python3 scripts/build_intraday_flow_distribution_moments.py \
  --minute-root /opt/factorforge/data-api-cache/minute_bar \
  --start 20160104 \
  --end 20250711 \
  --output-root /opt/factorforge/data-api-datamarts/intraday_flow_distribution_moments_v1_is \
  --qa-output /opt/factorforge/data-api-proofs/intraday_flow_distribution_moments_v1_is.qa.json \
  --catalog-output /opt/factorforge/data-api-catalog/intraday_flow_distribution_moments_v1_is.catalog.json \
  --cutoff-times 10:30:00,11:30:00,14:00:00,14:30:00,14:50:00,14:55:00 \
  --threshold-lookback-days 20,60 \
  --min-minutes 20 \
  --research-window IS \
  --operator-backend vectorized \
  --skip-upload
```

Full production ACCEPT requires:

- `duplicate_key_count=0`
- `missing_dates=[]`
- row/date/ticker coverage summary
- worker read smoke
- performance profile
- final Data API catalog publication
- datamart closeout ACCEPT

## Current External-State Blocker

The true worker is stopped after bounded proof:

```text
instance_id=i-02cc0b6e93856fbb4
state=stopped
```

Starting the worker changes external runtime state and incurs AWS cost. It requires explicit user approval before execution.
