# Minute Factor Acceleration Roadmap

Date: 2026-06-16

Scope: Data API / data-layer acceleration for minute-derived research states. This roadmap does not authorize clean data, search_worker, official promotion, or Factor Forge production loop execution.

## Problem

Current minute data and Data API read path are usable. Warm reads of derived parquet datamarts are already sub-second in bounded proof. The bottleneck is production creation of reusable minute-state datamarts from raw `minute_bar`, especially full-market / full-window computations.

Observed bounded proof for `intraday_flow_distribution_moments_v1` on `20240110`:

```text
pandas exact vectorized: 44.49s
polars:                 43.94s
mapreduce:              46.72s
mapreduce_threaded:     54.73s
process_sharded:        41.55s
process_sharded_vec:    44.29s
numba cold:             44.73s
warm read:               0.03s
```

Conclusion: IO for consuming finished datamarts is not the blocker. Raw-minute compute operator design is the blocker.

## Acceleration Layers

### L1 IO And Layout

Goal:

- reduce raw minute read cost
- avoid repeated S3 downloads
- keep projection/predicate pushdown effective

Actions:

- keep `minute_bar` partitioned by `trade_date`
- read only required columns
- keep Mac and worker warm cache
- write derived datamarts partitioned by `trade_date`

Acceptance:

- bounded read profile reports source rows and read seconds
- warm read smoke uses projected columns
- no full-window job repeatedly downloads the same raw minute partitions

### L2 Work Decomposition

Goal:

- use the natural factor structure: per-stock or per-stock-day feature map, then cross-sectional reduce

Default decomposition:

```text
map:
  ts_code + trade_date
  or ts_code + date-window

reduce:
  trade_date-level concat
  cross-sectional rank/zscore/neutralize after state materialization
```

Acceptance:

- operator emits stable unique keys before cross-section stage
- no cross-sectional future leakage
- cutoff features use only minutes up to cutoff

### L3 Process-Level Parallelism

Goal:

- make real CPU cores work; Python ThreadPool does not solve GIL-bound kernels

Actions:

- implement `process_sharded_mapreduce`
- shard by `ts_code` hash or date
- each process receives a larger shard, not thousands of tiny group tasks
- parent process reduces shard outputs and writes parquet

Acceptance:

- bounded proof on true worker
- compute seconds materially below pandas exact vectorized baseline
- duplicate key count is zero
- output equals reference/core contract on smoke fixtures

### L4 Compiled State Kernel

Goal:

- speed up per-stock time-series math that remains slow after process sharding

Candidates:

- Numba for Python-native deployment
- Rust/C++ for stable long-term kernels

Target kernels:

- cutoff cumulative moments
- rolling corr / CPV
- EMA / slow state recurrence
- HHI / entropy
- large/small proxy
- pseudo dollar buckets

Acceptance:

- reference parity tests
- bounded worker proof
- no-future metadata
- deterministic output keys

Current local foundation:

```text
module=factor_factory/data_api/intraday_operator_kernels.py
operators=group_offsets_from_sorted_codes,group_offsets_from_sorted_frame,rolling_corr_1d,rolling_corr_grouped_arrays,terminal_corr_grouped_arrays,grouped_ema_state_arrays,terminal_ema_state_arrays,occupation_location_grouped_arrays,rolling_corr_by_group,terminal_rolling_corr_by_group,grouped_ema_state_by_group,terminal_ema_state_by_group,cpv_price_volume_corr_state,intraday_occupation_location_state
backends=numpy,numba_optional_auto,threaded_grouped,array_grouped,process_sharded_array_grouped,array_grouped_occupation,process_sharded_array_grouped_occupation,array_grouped_ema_state,process_sharded_array_grouped_ema_state,numba_grouped_ema_state,array_grouped_ema_terminal,process_sharded_array_grouped_ema_terminal,numba_grouped_ema_terminal,numba_grouped,array_grouped_terminal,process_sharded_array_grouped_terminal,numba_grouped_terminal
use_cases=CPV,Corr(price,volume),terminal_cutoff_corr_state,VWAP_minus_TWAP,occupation_location_state,rolling intraday correlation states,slow_state_recurrence,EMA_state,terminal_EMA_state
production_status=not_wired_into_datamart_or_factor_loop
parallel_grouped_backend=threaded_grouped_maps_stock_groups_then_merges_original_keys
array_grouped_backend=sorts_once_and_uses_contiguous_arrays_plus_group_offsets_and_whole_sorted_array_vectorized_cumsum_windows_for_full_rolling_corr
process_sharded_backend=uses_factorized_group_codes_to_build_coarse_shards_then_runs_array_grouped_per_shard_with_optional_ProcessPoolExecutor
compiled_grouped_backend=numba_grouped_sorts_once_and_runs_multi_group_kernel
occupation_state_backend=pandas_grouped,threaded_grouped,array_grouped_occupation,process_sharded_array_grouped_occupation,numba_grouped
terminal_state_operator=terminal_rolling_corr_by_group_returns_one_row_per_group_at_last_order
terminal_state_compute=direct_last_window_corr_without_materializing_full_rolling_vector
terminal_state_backend=array_grouped_sorts_once_and_uses_contiguous_arrays_plus_group_offsets_and_grouped_cumsum_terminal_kernel;process_sharded_array_grouped_terminal_coarse_shards_terminal_groups_then_runs_array_terminal_backend_per_shard;numba_grouped_terminal_runs_same_offsets_in_optional_compiled_parallel_kernel
ema_state_operator=grouped_ema_state_by_group_computes_state_t_equals_decay_times_state_t_minus_1_plus_one_minus_decay_times_signal_t_by_group
ema_state_backend=array_grouped_ema_state_uses_sorted_group_offsets_and_single_pass_recurrence;process_sharded_array_grouped_ema_state_coarse_shards_independent_groups_then_runs_array_backend_per_shard;numba_grouped_ema_state_uses_optional_compiled_parallel_group_kernel
terminal_ema_state_operator=terminal_ema_state_by_group_returns_one_row_per_group_at_last_order_without_materializing_full_ema_vector
terminal_ema_state_backend=array_grouped_ema_terminal_uses_sorted_group_offsets_and_single_pass_final_state;process_sharded_array_grouped_ema_terminal_coarse_shards_independent_groups_then_runs_terminal_array_backend_per_shard;numba_grouped_ema_terminal_uses_optional_compiled_parallel_group_kernel
dedicated_operator=cpv_price_volume_corr_state_wraps_price_volume_corr_contract_and_reuses_generic_backends
local_contract_tests=test_group_offsets_from_sorted_codes_handles_empty_and_contiguous_groups,test_group_offsets_from_sorted_frame_supports_multi_key_groups,test_rolling_corr_numpy_matches_pandas_rolling_corr,test_rolling_corr_grouped_arrays_matches_dataframe_wrapper,test_terminal_corr_grouped_arrays_matches_dataframe_wrapper,test_grouped_ema_state_arrays_computes_independent_group_recursion,test_terminal_ema_state_arrays_matches_last_full_group_state,test_terminal_ema_state_by_group_uses_terminal_state_not_full_vector,test_grouped_ema_state_by_group_preserves_input_order_and_group_boundaries,test_grouped_ema_state_by_group_process_sharded_matches_array_grouped,test_grouped_ema_state_by_group_process_sharded_uses_coarse_shard_builder,test_grouped_ema_state_by_group_numba_grouped_matches_array_when_available,test_occupation_location_grouped_arrays_matches_dataframe_wrapper,test_rolling_corr_by_group_preserves_rows_and_avoids_cross_stock_leakage,test_rolling_corr_auto_reports_realized_backend,test_rolling_corr_by_group_threaded_grouped_matches_numpy,test_rolling_corr_by_group_array_grouped_matches_numpy_and_preserves_input_order,test_rolling_corr_by_group_array_grouped_avoids_per_group_vector_kernel,test_rolling_corr_by_group_array_grouped_uses_whole_array_grouped_kernel,test_rolling_corr_by_group_process_sharded_array_grouped_matches_numpy,test_rolling_corr_by_group_process_sharded_array_grouped_uses_shard_helper,test_rolling_corr_by_group_process_sharded_array_grouped_uses_coarse_shard_builder,test_cpv_price_volume_corr_state_full_reuses_grouped_rolling_backend,test_cpv_price_volume_corr_state_terminal_reuses_terminal_backend,test_rolling_corr_by_group_numba_grouped_uses_grouped_kernel,test_rolling_corr_by_group_numba_grouped_matches_numpy_when_available,test_terminal_rolling_corr_by_group_matches_last_full_rolling_value,test_terminal_rolling_corr_by_group_supports_multi_key_threaded_backend,test_terminal_rolling_corr_by_group_array_grouped_matches_numpy,test_terminal_rolling_corr_by_group_array_grouped_avoids_dataframe_group_kernel,test_terminal_rolling_corr_by_group_array_grouped_uses_grouped_terminal_kernel,test_terminal_rolling_corr_by_group_process_sharded_array_grouped_matches_numpy,test_terminal_rolling_corr_by_group_process_sharded_array_grouped_uses_shard_helper,test_terminal_rolling_corr_by_group_process_sharded_array_grouped_uses_coarse_shard_builder,test_terminal_rolling_corr_by_group_numba_grouped_uses_grouped_terminal_kernel,test_terminal_rolling_corr_by_group_numba_grouped_matches_numpy_when_available,test_intraday_occupation_location_state_computes_vwap_minus_twap_by_group,test_intraday_occupation_location_state_supports_multiple_group_columns,test_intraday_occupation_location_state_threaded_grouped_matches_pandas,test_intraday_occupation_location_state_array_grouped_matches_pandas,test_intraday_occupation_location_state_process_sharded_array_grouped_matches_pandas,test_intraday_occupation_location_state_numba_grouped_uses_grouped_kernel,test_intraday_occupation_location_state_numba_grouped_matches_pandas_when_available
promotion_rule=must_run_profile_comparison_validator_and_separate_production_approval_before_replacing_existing_backend
production_default_guard=operator_implementations_must_keep_reference_or_existing_backend_as_default_until_approval_validation_accepts_evidence_scope_production_scale_or_full_is
bounded_worker_guard=real_bounded_read_only_PROMOTE_only_means_candidate_backend_is_fast_and_semantically_equivalent_enough_for_larger_validation_not_production_default_replacement
```

Terminal-state operator rationale:

Many minute factors only need the final state at a cutoff, for example the last rolling price-volume correlation for each `trade_date + ts_code`. For these cases, `terminal_rolling_corr_by_group` returns one row per group with:

```text
group keys,terminal_order,bar_count,<output_col>
```

It is designed to avoid materializing a full per-minute output column when the downstream cross-section only consumes the terminal value. `terminal_ema_state_by_group` follows the same contract for first-order state recurrences such as slow moneyflow state: it returns only the final state per group and does not call the full `grouped_ema_state_arrays` vector kernel. It is not wired into CPV or any research loop yet.

Implementation note: the full rolling `array_grouped` backend avoids per-group DataFrame/Series kernels for CPV-style rolling correlation: it sorts once, computes group offsets, builds cumulative sums on the whole sorted contiguous array, vectorizes all rolling-window differences while masking cross-group windows, and writes results back to the original input row order without crossing stock groups. The low-level `group_offsets_from_sorted_codes` and `group_offsets_from_sorted_frame` helpers define the shared group-boundary contract for both wrappers and future datamart builders; use them after sorting by `group_cols + order_col` to produce `starts/ends/sizes`. The multi-key sorted-frame helper compares adjacent key columns directly instead of constructing a `MultiIndex`; local smoke on 1,024-8,192 groups x 240 bars showed about 8.7x-10x faster offset generation than the old `MultiIndex.from_frame(...).factorize(...)` path. The low-level `rolling_corr_grouped_arrays`, `terminal_corr_grouped_arrays`, `grouped_ema_state_arrays`, `terminal_ema_state_arrays`, and `occupation_location_grouped_arrays` APIs expose the same style of kernels directly for prepared/minute datamart builders that already have sorted arrays plus `starts/ends` offsets and should not pay DataFrame grouping cost. `occupation_location_grouped_arrays` currently returns `bar_count,amount_sum,volume_sum,twap,vwap,vwap_minus_twap` and supports `array_grouped` plus optional `numba_grouped`; it is intended for VWAP/TWAP and occupation-location state builders. Its `array_grouped` backend computes all group sums with prefix arrays rather than per-group Python slices. Local direct-array smoke on 1,024-8,192 groups x 240 bars showed about 1.37x-1.53x versus the old Python loop, while DataFrame wrapper profiles may still be dominated by sorting and key assembly. Production datamart builders should therefore prefer direct sorted arrays plus offsets when possible. `process_sharded_array_grouped` assigns factorized group codes to coarse shards and runs the same array backend per shard; it no longer builds a Python list containing one DataFrame per stock before concatenating shards. The occupation state wrapper also supports `process_sharded_array_grouped`, which shards by group code and runs `array_grouped_occupation` inside each shard. The EMA state and terminal EMA wrappers support the same coarse-shard pattern because state continuity is only required within each group, not across groups. Use these for worker/EC2 real bounded benchmarks. Local macOS sandbox runs may need `--max-workers 1` because multiprocessing semaphores can be restricted; single-worker proofs should not be used to judge process-sharded speed because they include shard setup without parallel payoff. `cpv_price_volume_corr_state` is the first dedicated wrapper: it fixes the CPV field contract and metadata while delegating full/terminal math to the generic kernels. It is not wired into Factor Forge or any datamart builder yet. The terminal corr path computes the last-window correlation directly. It does not call the full `rolling_corr_1d` vector kernel internally. The terminal `array_grouped` backend additionally avoids per-group DataFrame and per-group array kernels: it sorts once, computes group offsets, builds cumulative sums over contiguous arrays, and evaluates all terminal windows in one vectorized pass over group offsets. The terminal `process_sharded_array_grouped` backend uses the same coarse shard builder for terminal groups and runs the array terminal backend per shard, producing one row per group instead of a full minute vector. The terminal EMA path computes the final recurrence state directly, and its process-sharded backend produces one row per group instead of a full minute state vector. The `numba_grouped` terminal backends use the same offsets but push the group loop into optional compiled parallel kernels. If numba is unavailable, the profiler must emit a BLOCK profile for that candidate rather than silently replacing semantics. These paths are benchmark candidates, not production defaults.

Production replacement rule:

- Operator implementations must keep the existing/reference backend as the code default until a separate production approval artifact is validated.
- Synthetic and real bounded proofs may emit `PROMOTE`, but this only authorizes larger validation. It does not authorize changing the production default.
- `scripts/validate_operator_backend_production_approval.py` requires an explicit approval artifact with `evidence_scope=production_scale` or `evidence_scope=full_is`; bounded-only evidence must remain a candidate proof.
- Data API runners may pass an optimized backend explicitly during benchmark/proof runs. Factor Forge or datamart production paths must use the registry/approval validation path before selecting a non-default backend.

Local bounded profiler:

```text
script=scripts/profile_intraday_operator_kernels.py
validator=scripts/validate_intraday_operator_kernel_profile.py
gate_runner=scripts/run_intraday_operator_kernel_benchmark_gate.py
direct_array_profiler=scripts/profile_intraday_array_kernels.py
direct_array_profile_validator=scripts/validate_intraday_array_kernel_profile.py
direct_array_gate_runner=scripts/run_intraday_array_kernel_benchmark_gate.py
worker_preflight=scripts/run_intraday_operator_worker_preflight.py
worker_runner=scripts/run_intraday_operator_worker_benchmark.py
worker_bundle_validator=scripts/validate_intraday_operator_worker_benchmark.py
safe_worker_runner=scripts/run_intraday_operator_safe_worker_benchmark.py
worker_resume_bundle=scripts/build_intraday_operator_worker_resume_bundle.py
worker_resume_bundle_validator=scripts/validate_intraday_operator_worker_resume_bundle.py
selection_policy=factor_factory/data_api/operator_backend_policy.py
runtime_backend_registry=factor_factory/data_api/operator_backend_registry.py
input=deterministic_synthetic_intraday_panel_or_explicit_bounded_parquet
baseline_profiles=rolling_corr_by_group:numpy,intraday_occupation_location_state:pandas
candidate_profiles=cpv_price_volume_corr_state:array_grouped,cpv_price_volume_corr_state:array_grouped_terminal,cpv_price_volume_corr_state:process_sharded_array_grouped_terminal,rolling_corr_by_group:array_grouped,rolling_corr_by_group:process_sharded_array_grouped,rolling_corr_by_group:threaded_grouped,intraday_occupation_location_state:array_grouped_occupation,intraday_occupation_location_state:process_sharded_array_grouped_occupation,intraday_occupation_location_state:threaded_grouped,grouped_ema_state_by_group:array_grouped_ema_state,grouped_ema_state_by_group:process_sharded_array_grouped_ema_state,grouped_ema_state_by_group:numba_grouped_ema_state,terminal_ema_state_by_group:array_grouped_ema_terminal,terminal_ema_state_by_group:process_sharded_array_grouped_ema_terminal,terminal_ema_state_by_group:numba_grouped_ema_terminal,rolling_corr_by_group:numba_grouped,intraday_occupation_location_state:numba_grouped,terminal_rolling_corr_by_group:array_grouped_terminal,terminal_rolling_corr_by_group:process_sharded_array_grouped_terminal,terminal_rolling_corr_by_group:threaded_grouped_terminal,terminal_rolling_corr_by_group:numba_grouped_terminal
performance_gate_baseline_rule=cpv_price_volume_corr_state_full_uses_array_grouped_baseline;cpv_price_volume_corr_state_terminal_uses_array_grouped_terminal_baseline
proof_fields=verdict,profile_count,input,profiles,comparison_issues,performance_gate,safety
terminal_profile_fields=terminal_rolling_corr_summary.full_row_count,terminal_rolling_corr_summary.terminal_row_count,terminal_rolling_corr_summary.row_reduction_ratio
bundle_summary_fields=profile_summary.performance_candidates,profile_summary.terminal_rolling_corr_summary,validation_summary,safety
blocked_backend_issue=operator_backend_unavailable
performance_gate_default_threshold=1.2x_speedup
performance_gate_benchmark_scope=synthetic_bounded|real_bounded_read_only
worker_evidence_scope=bounded_worker|production_scale|full_is
performance_gate_production_default_allowed=false
rolling_corr_parity_tolerance=1e-6_rtol_atol_for_grouped_cumsum_roundoff
performance_gate_default_replacement_verdict=NO_CANDIDATE|PROMOTE|HOLD|BLOCK
performance_gate_semantics=verdict_accept_means_parity_and_safety_only;synthetic_promote_only_allows_worker_real_sample_benchmark;real_bounded_promote_requires_reviewer_acceptance_before_wiring;production_default_requires_separate_approval
direct_array_profile_scope=synthetic_bounded_direct_array_or_real_bounded_direct_array_for_sorted_arrays_plus_starts_ends_offsets
safety_uses_real_market_data=false_for_synthetic_true_for_input_parquet
safety_starts_backfill=false
safety_writes_datamart=false
safety_production_loop_side_effect=false
contract_tests=test_intraday_operator_kernel_profiler_writes_baseline_proof,test_intraday_operator_kernel_profiler_accepts_array_grouped_rolling_candidate,test_intraday_operator_kernel_profiler_accepts_process_sharded_array_grouped_candidate,test_intraday_operator_kernel_profiler_profiles_cpv_operator_candidate,test_intraday_operator_kernel_profiler_profiles_terminal_cpv_operator_candidate,test_intraday_operator_kernel_profiler_profiles_terminal_cpv_process_candidate_with_terminal_baseline,test_intraday_operator_kernel_profiler_rolling_compare_allows_grouped_cumsum_roundoff,test_intraday_operator_kernel_profiler_accepts_threaded_grouped_candidate,test_intraday_operator_kernel_profiler_profiles_terminal_rolling_corr,test_intraday_operator_kernel_profiler_profiles_terminal_process_sharded_candidate,test_intraday_operator_kernel_profiler_profiles_terminal_numba_candidate_when_requested,test_intraday_operator_kernel_profiler_reads_bounded_parquet_without_production_permission,test_intraday_operator_kernel_profiler_blocks_unavailable_numba_grouped,test_intraday_operator_kernel_performance_gate_separates_parity_from_promotion,test_operator_kernel_profile_validator_accepts_safe_real_bounded_proof,test_operator_kernel_profile_validator_blocks_synthetic_when_real_bounded_required,test_operator_kernel_profile_validator_blocks_production_default_permission,test_intraday_operator_kernel_benchmark_gate_runner_accepts_real_bounded,test_intraday_operator_kernel_benchmark_gate_runner_includes_terminal_summary,test_intraday_operator_kernel_benchmark_gate_runner_summarizes_terminal_process_sharded_candidate,test_intraday_operator_kernel_benchmark_gate_runner_passes_array_grouped_candidate,test_intraday_operator_kernel_benchmark_gate_runner_passes_process_sharded_candidate,test_intraday_operator_kernel_benchmark_gate_runner_passes_cpv_operator_candidate,test_intraday_operator_kernel_benchmark_gate_runner_passes_terminal_cpv_process_candidate,test_intraday_operator_kernel_benchmark_gate_runner_blocks_synthetic_when_real_required,test_worker_preflight_blocks_busy_research_process,test_worker_preflight_accepts_idle_worker,test_worker_benchmark_runner_stops_when_preflight_blocks,test_safe_worker_benchmark_stops_before_input_read_when_preflight_blocks,test_safe_worker_benchmark_runs_preflight_benchmark_and_validation,test_intraday_operator_worker_benchmark_validator_accepts_complete_safe_bundle,test_intraday_operator_worker_benchmark_validator_blocks_unsafe_bundle,test_backend_policy_keeps_default_when_production_permission_is_false,test_backend_policy_requires_separate_production_approval_even_when_profile_gate_allows,test_backend_policy_keeps_default_when_validation_blocks,test_backend_policy_identifies_promoted_candidate_but_requires_approval_when_first_candidate_holds,test_backend_policy_keeps_default_when_no_promoted_candidate_matches_operator,test_backend_registry_keeps_default_without_approval_validation,test_backend_registry_keeps_default_when_approval_validation_blocks,test_backend_registry_keeps_default_when_operator_mismatches,test_backend_registry_allows_exact_approved_configured_backend
direct_array_contract_tests=test_intraday_array_kernel_profiler_accepts_direct_array_candidates,test_intraday_array_kernel_profiler_profiles_optional_numba_candidate,test_array_kernel_profile_validator_accepts_complete_profile,test_array_kernel_profile_validator_blocks_wrong_scope_or_safety,test_intraday_array_kernel_benchmark_gate_accepts_real_bounded,test_intraday_array_kernel_benchmark_gate_blocks_synthetic_when_real_required,test_intraday_array_kernel_benchmark_gate_blocks_real_bounded_below_min_rows
resume_bundle_contract_tests=test_intraday_operator_worker_resume_bundle_accepts_cpv_terminal_plan,test_intraday_operator_worker_resume_bundle_validator_blocks_remote_execution
```

Example bounded local proof command:

```bash
PYTHONPATH=. python3 scripts/profile_intraday_operator_kernels.py \
  --output-path /tmp/intraday_operator_kernel_profile.json \
  --groups 128 \
  --rows-per-group 240 \
  --window 20 \
  --include-cpv-operator \
  --cpv-backend array_grouped \
  --include-array-grouped \
  --include-process-sharded-array-grouped \
  --include-terminal-rolling-corr \
  --include-ema-state \
  --include-terminal-ema-state \
  --include-threaded-grouped \
  --max-workers 8 \
  --include-numba-grouped
```

This command is intentionally not a production benchmark. It is a replacement gate in two layers:

1. `verdict=ACCEPT` means candidate outputs match baseline on a bounded deterministic panel and the proof had no safety side effects.
2. `performance_gate.default_replacement_verdict=PROMOTE` on this synthetic proof only means the backend is worth taking to a real worker/data benchmark.
3. `performance_gate.production_default_allowed=false` is hard-coded for this proof type; production default replacement still requires a separate real-data bounded proof, QA, and reviewer acceptance.

`HOLD` means the candidate is contract-correct but not yet proven fast enough. `BLOCK` means the candidate profile itself is unusable, for example because `numba` is unavailable.

Example direct-array kernel proof command:

```bash
PYTHONPATH=. python3 scripts/profile_intraday_array_kernels.py \
  --output-path /tmp/intraday_array_kernel_profile_4096.json \
  --groups 4096 \
  --rows-per-group 240 \
  --window 20
```

Validate it:

```bash
PYTHONPATH=. python3 scripts/validate_intraday_array_kernel_profile.py \
  --profile-path /tmp/intraday_array_kernel_profile_4096.json \
  --output-path /tmp/intraday_array_kernel_profile_4096.validation.json \
  --min-row-count 900000
```

This proof bypasses DataFrame sorting and grouping and benchmarks the low-level kernels that production datamart builders should call when they already have sorted arrays plus `starts/ends` offsets. The validator requires `benchmark_scope=synthetic_bounded_direct_array`, `direct_array_inputs=true`, `production_default_allowed=false`, no comparison issues, and safety flags showing no backfill/datamart/production-loop side effects. A representative local synthetic proof on 4,096 groups x 240 bars returned `verdict=ACCEPT` with approximate speedups versus reference Python loops: `rolling_corr_grouped_arrays` 15.1x, `terminal_corr_grouped_arrays` 37.9x, and `occupation_location_grouped_arrays` 1.68x; validation also returned `ACCEPT` with `promotion_candidate_count=3`. This is still bounded synthetic evidence only; it proves the direct-array strategy is worth worker-scale validation, not that any production default should be replaced.

Example real bounded direct-array proof command:

```bash
PYTHONPATH=. python3 scripts/profile_intraday_array_kernels.py \
  --output-path /tmp/direct_array_real_bounded_profile.json \
  --input-parquet /tmp/direct_array_real_bounded_sample.parquet \
  --window 20

PYTHONPATH=. python3 scripts/validate_intraday_array_kernel_profile.py \
  --profile-path /tmp/direct_array_real_bounded_profile.json \
  --output-path /tmp/direct_array_real_bounded_profile.validation.json \
  --require-real-bounded \
  --min-row-count 30000
```

For real bounded direct-array profiles, the profiler sorts by `group_cols + order_col`, computes shared offsets with `group_offsets_from_sorted_frame`, then runs the low-level kernels. The validator requires `benchmark_scope=real_bounded_direct_array`, `uses_real_market_data=true`, `direct_array_inputs=true`, `production_default_allowed=false`, and no side effects. A local bounded parquet smoke with 32,768 rows and 512 groups returned `ACCEPT`; candidate speedups were about 8.1x for rolling corr, 46.2x for terminal corr, and 4.1x for occupation/VWAP. This still does not authorize production replacement; it is the right proof shape to repeat on the true worker with real minute cache and larger row/date thresholds.

Preferred direct-array gate command:

```bash
PYTHONPATH=. python3 scripts/run_intraday_array_kernel_benchmark_gate.py \
  --output-dir /tmp/intraday_array_kernel_gate \
  --label real_direct_array_worker_sample \
  --input-parquet /tmp/direct_array_real_bounded_sample.parquet \
  --window 20 \
  --require-real-bounded \
  --min-row-count 30000
```

This combined gate writes:

```text
real_direct_array_worker_sample.profile.json
real_direct_array_worker_sample.validation.json
real_direct_array_worker_sample.bundle.json
```

Use the bundle as the review handoff for low-level direct-array kernels. `bundle.verdict=ACCEPT` means the sorted-array inputs, reference parity, performance candidates, and validator safety checks passed. It still does not backfill, write a datamart, start a production loop, or authorize production default backend replacement.

Example real bounded read-only proof command:

Build the bounded profiler input first. This is a read-only sample builder; it writes only the benchmark parquet and proof, not a datamart or catalog.

Raw minute input:

```bash
PYTHONPATH=. python3 scripts/build_intraday_operator_benchmark_sample.py \
  --input-root /path/to/minute_bar \
  --input-format raw_minute_bar \
  --output-parquet /tmp/bounded_minute_sample.parquet \
  --proof-output /tmp/bounded_minute_sample.proof.json \
  --start 20240110 \
  --end 20240110 \
  --row-limit 500000
```

Prepared-minute input:

```bash
PYTHONPATH=. python3 scripts/build_intraday_operator_benchmark_sample.py \
  --input-root /path/to/prepared_minute_bar_v1 \
  --input-format prepared_minute_bar_v1 \
  --output-parquet /tmp/bounded_minute_sample.parquet \
  --proof-output /tmp/bounded_minute_sample.proof.json \
  --start 20240110 \
  --end 20240110 \
  --row-limit 500000
```

When `input-format=prepared_minute_bar_v1`, the benchmark sample maps `price=minute_ret`, `volume=vol`, and `amount=amount_abs`. This is deliberately labeled `semantic_scope=operator_speed_benchmark_not_alpha_input`; it is suitable for mechanical operator-speed benchmarking but not for alpha semantics.

```bash
PYTHONPATH=. python3 scripts/profile_intraday_operator_kernels.py \
  --output-path /tmp/intraday_operator_kernel_profile.real_bounded.json \
  --input-parquet /path/to/bounded_minute_sample.parquet \
  --row-limit 500000 \
  --window 20 \
  --include-cpv-operator \
  --cpv-backend array_grouped \
  --include-array-grouped \
  --include-process-sharded-array-grouped \
  --include-terminal-rolling-corr \
  --include-ema-state \
  --include-terminal-ema-state \
  --include-threaded-grouped \
  --max-workers 8
```

Required parquet columns:

```text
ts_code,trade_date,hhmmss,price,volume
```

`amount` is optional for this profiler; if missing, the profiler computes `amount=price*volume` for the occupation-state proof only. This is a benchmark fallback, not a production data definition.

Required validation command before any wiring discussion:

```bash
PYTHONPATH=. python3 scripts/validate_intraday_operator_kernel_profile.py \
  --profile-path /tmp/intraday_operator_kernel_profile.real_bounded.json \
  --output-path /tmp/intraday_operator_kernel_profile.real_bounded.validation.json \
  --require-real-bounded \
  --min-row-count 100000
```

Validator `ACCEPT` only means the proof is safe to review. It does not grant production default replacement. Tiny real parquet smokes are allowed only as IO-path checks; performance proof should set a minimum row threshold such as `--min-row-count 100000`. The validator blocks:

- `profile.verdict != ACCEPT`
- non-empty `comparison_issues`
- unsupported or non-real scope when `--require-real-bounded` is used
- input row count below `--min-row-count`
- `performance_gate.production_default_allowed != false`
- any proof that starts backfill, writes datamart, or touches production loops
- failed profile items or missing result hashes

Preferred combined gate command:

```bash
PYTHONPATH=. python3 scripts/run_intraday_operator_kernel_benchmark_gate.py \
  --output-dir /tmp/intraday_operator_kernel_gate \
  --label real_bounded_worker_sample \
  --input-parquet /path/to/bounded_minute_sample.parquet \
  --row-limit 500000 \
  --window 20 \
  --include-cpv-operator \
  --cpv-backend array_grouped \
  --include-array-grouped \
  --include-process-sharded-array-grouped \
  --include-terminal-rolling-corr \
  --include-ema-state \
  --include-terminal-ema-state \
  --include-threaded-grouped \
  --max-workers 8 \
  --require-real-bounded \
  --min-row-count 100000
```

This writes:

```text
real_bounded_worker_sample.profile.json
real_bounded_worker_sample.validation.json
real_bounded_worker_sample.bundle.json
```

Use the bundle as the handoff artifact. `bundle.verdict=ACCEPT` means the profile and validator both passed; it still does not wire any backend into Data API builders or Factor Forge Step4.

Preferred worker preflight:

```bash
PYTHONPATH=. python3 scripts/run_intraday_operator_worker_preflight.py \
  --output-path /tmp/intraday_operator_worker_benchmark/worker_preflight.json \
  --max-load-per-cpu 0.75 \
  --min-available-memory-gb 16 \
  --max-protected-process-cpu 25
```

The preflight must be `ACCEPT` before running the benchmark on a shared research worker. It blocks when load is high, available memory is low, or protected research processes such as Factor Forge, RD-Agent, or Qlib backtests are consuming CPU. This is a non-interference gate; it writes only the preflight JSON.

Preferred safe worker orchestration:

```bash
PYTHONPATH=. python3 scripts/run_intraday_operator_safe_worker_benchmark.py \
  --input-root /path/to/minute_bar \
  --input-format raw_minute_bar \
  --output-dir /tmp/intraday_operator_worker_benchmark \
  --label real_bounded_worker_sample \
  --evidence-scope bounded_worker \
  --start 20240110 \
  --end 20240110 \
  --row-limit 500000 \
  --window 20 \
  --include-cpv-operator \
  --cpv-backend array_grouped \
  --include-array-grouped \
  --include-process-sharded-array-grouped \
  --include-terminal-rolling-corr \
  --include-ema-state \
  --include-terminal-ema-state \
  --include-threaded-grouped \
  --max-workers 8 \
  --min-row-count 100000
```

This is the preferred true-worker command. It runs preflight first, stops before reading minute data when preflight is `BLOCK`, then runs the worker benchmark and validates the resulting worker bundle. It writes:

```text
real_bounded_worker_sample.preflight.json
real_bounded_worker_sample.worker_benchmark.bundle.json
real_bounded_worker_sample.worker_benchmark.validation.json
real_bounded_worker_sample.safe_worker_benchmark.bundle.json
```

The final safe bundle is the review entry point. It is still read-only and keeps `production_default_allowed=false`; an `ACCEPT` safe bundle only makes the candidate eligible for separate production approval.

`bounded_worker` is the default evidence scope and must not be used for production default replacement. Production approval requires rerunning this path with `--evidence-scope production_scale` or `--evidence-scope full_is` and a row/date coverage threshold appropriate to the operator.

Preferred plan-only CPV terminal proof bundle:

```bash
PYTHONPATH=. python3 scripts/build_intraday_operator_worker_resume_bundle.py \
  --instance-id i-02cc0b6e93856fbb4 \
  --repo /home/ubuntu/.openclaw/workspace/factorforge-data-api \
  --cache-root /home/ubuntu/factorforge_data_api_cache \
  --input-root /home/ubuntu/factorforge_data_api_cache/s3_parquet/minute_bar \
  --input-format raw_minute_bar \
  --output-dir /tmp/intraday_operator_worker_benchmark \
  --label real_bounded_cpv_terminal \
  --start 20240110 \
  --end 20240110 \
  --row-limit 500000 \
  --window 20 \
  --min-row-count 100000 \
  --max-workers 8 \
  --evidence-scope bounded_worker \
  --cpv-terminal-only \
  --include-terminal-rolling-corr \
  --include-process-sharded-array-grouped \
  --output-path /tmp/intraday_operator_worker_benchmark/real_bounded_cpv_terminal.resume_bundle.json
```

Validate the plan before using it:

```bash
PYTHONPATH=. python3 scripts/validate_intraday_operator_worker_resume_bundle.py \
  --bundle-path /tmp/intraday_operator_worker_benchmark/real_bounded_cpv_terminal.resume_bundle.json \
  --output-path /tmp/intraday_operator_worker_benchmark/real_bounded_cpv_terminal.resume_bundle.validation.json
```

This bundle is a command plan only. It contains EC2/SSM status checks and safe benchmark commands, but it never starts an instance, sends SSM commands, runs the benchmark, writes a datamart, or changes backend config. The default CPV terminal baseline is `array_grouped_terminal`; the candidate backend is `process_sharded_array_grouped_terminal`.

Manual worker one-command benchmark:

```bash
PYTHONPATH=. python3 scripts/run_intraday_operator_worker_benchmark.py \
  --input-root /path/to/minute_bar \
  --input-format raw_minute_bar \
  --output-dir /tmp/intraday_operator_worker_benchmark \
  --label real_bounded_worker_sample \
  --evidence-scope bounded_worker \
  --preflight-path /tmp/intraday_operator_worker_benchmark/worker_preflight.json \
  --start 20240110 \
  --end 20240110 \
  --row-limit 500000 \
  --window 20 \
  --include-cpv-operator \
  --cpv-backend array_grouped \
  --include-array-grouped \
  --include-process-sharded-array-grouped \
  --include-terminal-rolling-corr \
  --include-ema-state \
  --include-terminal-ema-state \
  --include-threaded-grouped \
  --max-workers 8 \
  --min-row-count 100000
```

This writes:

```text
real_bounded_worker_sample.sample.parquet
real_bounded_worker_sample.sample.proof.json
real_bounded_worker_sample.gate/real_bounded_worker_sample.profile.json
real_bounded_worker_sample.gate/real_bounded_worker_sample.validation.json
real_bounded_worker_sample.gate/real_bounded_worker_sample.bundle.json
real_bounded_worker_sample.worker_benchmark.bundle.json
```

The worker bundle is the review entry point. It combines sample-builder safety, gate validation, row-count threshold, performance candidates, and production isolation. `verdict=ACCEPT` still does not grant production replacement; it only makes the candidate eligible for separate review and production approval.

If `--preflight-path` points to a `BLOCK` preflight, the worker runner stops before reading minute data or running the gate and writes a `worker_benchmark.bundle.json` with `blocked_reason=worker_preflight_not_accept`.

Required worker bundle validation command:

```bash
PYTHONPATH=. python3 scripts/validate_intraday_operator_worker_benchmark.py \
  --bundle-path /tmp/intraday_operator_worker_benchmark/real_bounded_worker_sample.worker_benchmark.bundle.json \
  --output-path /tmp/intraday_operator_worker_benchmark/real_bounded_worker_sample.worker_benchmark.validation.json \
  --evidence-scope bounded_worker \
  --min-row-count 100000
```

This validator is the last read-only gate before a human production approval artifact can be written. It checks the sample proof, gate bundle, gate validation, row-count threshold, real bounded benchmark scope, explicit evidence scope, safety flags, and promotion candidates. It also requires `production_default_allowed=false`, so even an `ACCEPT` worker validation cannot directly replace any backend. Missing evidence scope is a `BLOCK`; `production_scale` and `full_is` scopes also require a production-scale row threshold, and bounded evidence remains ineligible for approval validation.

When `--include-terminal-rolling-corr` is set, the profile also includes:

```text
terminal_rolling_corr_summary.full_row_count
terminal_rolling_corr_summary.terminal_row_count
terminal_rolling_corr_summary.row_reduction_ratio
```

This quantifies how much output can be avoided when a minute factor only needs the cutoff terminal state. It is evidence for future CPV-style specialization, not a production replacement by itself.

Backend selection policy:

```python
from factor_factory.data_api.operator_backend_policy import decide_operator_backend
from factor_factory.data_api.operator_backend_registry import resolve_operator_backend
```

The policy must be used by any future Data API builder or Step4 adapter before selecting a non-default backend. Current profiler bundles intentionally set:

```text
production_default_allowed=false
```

Therefore current decisions must keep the default backend even when a candidate profile says `performance_verdict=PROMOTE`. A non-default backend can be selected only when all are true:

- profile verdict is `ACCEPT`
- validation verdict is `ACCEPT`
- the requested operator has a matching candidate with `performance_verdict=PROMOTE`
- safe worker benchmark bundle verdict is `ACCEPT`
- safe worker preflight, benchmark, and validation summaries are all `ACCEPT`
- a separate production approval artifact explicitly authorizes this exact operator/backend with `evidence_scope=production_scale|full_is`

If multiple candidates exist for the same operator, the policy chooses the first promoted candidate for that operator. If no promoted candidate exists, it reports the first matching candidate for diagnostics but keeps the default backend. `decide_operator_backend(...)` also rejects direct `production_approval` payloads with missing evidence scope or `evidence_scope=bounded_worker`; this prevents older approval artifacts from bypassing the validator chain.

Runtime builders must not select a configured non-default backend directly. They must call `resolve_operator_backend(...)` with the operator id, default backend, configured backend, and approval validation artifact. The resolver returns the default backend unless the approval validation is `ACCEPT`, the operator id matches, the configured backend matches the approved selected backend, `replacement_allowed=true`, and the approval validation carries matching `approval_evidence_scope` plus `safe_worker_validation_evidence_scope` in `production_scale|full_is`. Missing evidence scope, `bounded_worker`, or scope mismatch returns the default backend. The resolver is read-only and sets `safety.writes_backend_config=false`; it is a runtime guard, not a config writer.

Production approval artifact contract:

```text
verdict=ACCEPT
approval_scope=production_default_backend
operator_id=<requested operator id>
approved_backend=<candidate backend from promoted profile>
production_default_allowed=true
approved_by=<reviewer or owner>
approval_reason=<why this exact operator/backend is approved>
evidence_scope=production_scale|full_is
```

The approval artifact is deliberately separate from benchmark profile output. Pre-wiring profiles and read-only bounded proofs must continue to emit `performance_gate.production_default_allowed=false`; that field proves the profile did not grant production authority. Even if a profile claims `performance_gate.production_default_allowed=true`, the production selector must still keep the default backend unless a separate approval artifact matches the requested `operator_id` and the promoted candidate `candidate_backend`. A mismatched approval, missing approval, missing safe worker bundle, non-ACCEPT safe worker proof, non-ACCEPT validation, non-ACCEPT profile, non-PROMOTE candidate, bounded-only evidence scope, or input row count below the configured production threshold keeps the default backend.

Approval artifacts should be generated by the read-only builder rather than handwritten. The builder records evidence paths and SHA-256 hashes, requires `evidence_scope=production_scale` or `evidence_scope=full_is`, and blocks tiny bounded proofs by default:

```bash
PYTHONPATH=. python3 scripts/build_operator_backend_production_approval.py \
  --profile-path /path/to/production_scale.profile.json \
  --validation-path /path/to/production_scale.validation.json \
  --safe-worker-bundle-path /path/to/production_scale.safe_worker_benchmark.bundle.json \
  --safe-worker-validation-path /path/to/production_scale.safe_worker_validation.json \
  --operator-id moneyflow_slow_state_v1 \
  --approved-backend array_grouped \
  --evidence-scope production_scale \
  --approved-by <reviewer-or-owner> \
  --approval-reason "production-scale safe worker proof accepted" \
  --output-path /path/to/moneyflow_slow_state_v1.production_approval.json
```

Required approval validation command before any backend config change:

```bash
PYTHONPATH=. python3 scripts/validate_operator_backend_production_approval.py \
  --profile-path /path/to/real_bounded_worker_sample.profile.json \
  --validation-path /path/to/real_bounded_worker_sample.validation.json \
  --approval-path /path/to/operator_backend.production_approval.json \
  --safe-worker-bundle-path /path/to/real_bounded_worker_sample.safe_worker_benchmark.bundle.json \
  --operator-id cpv_price_volume_corr_state \
  --default-backend array_grouped \
  --output-path /path/to/operator_backend.production_approval.validation.json
```

For moneyflow slow-state safe proofs, also pass the safe worker validation artifact:

```bash
PYTHONPATH=. python3 scripts/validate_operator_backend_production_approval.py \
  --profile-path /tmp/moneyflow_slow_state_worker_benchmark/real_bounded_slow_state.gate/real_bounded_slow_state.profile.json \
  --validation-path /tmp/moneyflow_slow_state_worker_benchmark/real_bounded_slow_state.gate/real_bounded_slow_state.validation.json \
  --approval-path /path/to/moneyflow_slow_state_v1.production_approval.json \
  --safe-worker-bundle-path /tmp/moneyflow_slow_state_worker_benchmark/real_bounded_slow_state.safe_worker_benchmark.bundle.json \
  --safe-worker-validation-path /tmp/moneyflow_slow_state_worker_benchmark/real_bounded_slow_state.safe_worker_benchmark.validation.json \
  --operator-id moneyflow_slow_state_v1 \
  --default-backend reference \
  --output-path /path/to/moneyflow_slow_state_v1.production_approval.validation.json
```

This validator is read-only. It writes only a validation JSON and sets `safety.writes_backend_config=false`; it does not mutate Data API builders, Factor Forge Step4, or any production loop.

Required plan artifact before manual config change:

```bash
PYTHONPATH=. python3 scripts/plan_operator_backend_replacement.py \
  --approval-validation-path /path/to/operator_backend.production_approval.validation.json \
  --target-scope data_api_operator_backend_registry \
  --output-path /path/to/operator_backend.replacement.plan.json
```

The plan artifact is also read-only. `replacement_action=plan_only` and `safety.writes_backend_config=false` mean the artifact is suitable for review, not an automatic mutation. The plan must carry `proof_paths.profile_path`, `proof_paths.validation_path`, `proof_paths.safe_worker_bundle_path`, and `proof_paths.safe_worker_validation_path` when those artifacts exist, so a reviewer can trace the exact evidence before any manual config change. A `BLOCK` plan means no backend config may be changed.

This keeps current research isolated while still letting us collect acceleration evidence.

### L5 Columnar Engine Proofs

Goal:

- identify workloads better served by SQL/columnar engines

Candidates:

- Polars Lazy / streaming
- ClickHouse MergeTree or clickhouse-local
- DuckDB for local parquet joins and filters

Best-fit workloads:

- large scans
- group by aggregation
- joins with universe/tradability flags
- repeated analyst queries over finished datamarts

Non-goal:

- treating ClickHouse or Polars as a universal replacement for per-stock rolling kernels

Acceptance:

- bounded query proof versus pandas reference
- clear statement of workload class where engine wins

### L6 Reusable Datamarts

Goal:

- avoid raw-minute recomputation for every factor revision

Priority datamarts:

- `intraday_flow_distribution_moments_v1`
- `intraday_flow_state_v2`
- `intraday_pseudo_dollar_bar_v1`
- `cpv_state_v1`
- `rolling_corr_state_v1`
- `moneyflow_slow_state_v1`

Current local operator status for `moneyflow_slow_state_v1`:

```text
module=factor_factory/data_api/moneyflow_slow_state.py
profiler=scripts/profile_moneyflow_slow_state_operator.py
profile_validator=scripts/validate_moneyflow_slow_state_operator_profile.py
gate_runner=scripts/run_moneyflow_slow_state_operator_benchmark_gate.py
sample_builder=scripts/build_moneyflow_slow_state_benchmark_sample.py
worker_runner=scripts/run_moneyflow_slow_state_worker_benchmark.py
safe_worker_runner=scripts/run_moneyflow_slow_state_safe_worker_benchmark.py
safe_worker_validator=scripts/validate_moneyflow_slow_state_safe_worker_benchmark.py
worker_resume_bundle=scripts/build_moneyflow_slow_state_worker_resume_bundle.py
worker_resume_bundle_validator=scripts/validate_moneyflow_slow_state_worker_resume_bundle.py
worker_instance_readiness=scripts/validate_moneyflow_slow_state_worker_instance_readiness.py
generic_backend_readiness_validator=scripts/validate_operator_backend_readiness.py
backend_readiness_validator=scripts/validate_moneyflow_slow_state_backend_readiness.py_compat_wrapper
dataset_id=moneyflow_slow_state_v1
source_dataset=intraday_flow_distribution_moments_v1
unique_key=ts_code,trade_date,cutoff_time,lambda
function=derive_moneyflow_slow_state_v1
params=MoneyflowSlowStateParams
default_lambdas=0.70,0.85,0.93
default_cutoff_time=14:50:00
state_equation=H_t=lambda*H_t_minus_1+(1-lambda)*v19d_score_t
state_group=ts_code+cutoff_time+lambda
state_source=prior_state_continuous
state_init_policy=first_finite_signal
is_end_date=20250711
oos_rule=trade_date_after_20250711_marked_OOS_only
backend=array_grouped_ema_state_from_generic_grouped_ema_operator
candidate_backends=reference,array_grouped,process_sharded_array_grouped
profile_contract=emits_performance_gate.operator_id=moneyflow_slow_state_v1_with_candidate_backends_and_production_default_allowed=false
max_workers=passed_to_process_sharded_array_grouped_backend
qa_helper=build_moneyflow_slow_state_qa
local_contract_tests=test_moneyflow_slow_state_recurs_by_stock_cutoff_and_lambda_without_year_reset,test_moneyflow_slow_state_emits_multiple_lambda_paths_with_independent_keys,test_moneyflow_slow_state_reference_and_process_sharded_match_array_backend,test_moneyflow_slow_state_passes_max_workers_to_process_backend,test_moneyflow_slow_state_qa_blocks_duplicate_unique_keys,test_moneyflow_slow_state_profiler_compares_reference_and_optimized_backends,test_backend_policy_understands_moneyflow_slow_state_performance_gate,test_moneyflow_slow_state_safe_worker_stops_before_input_read_when_preflight_blocks,test_moneyflow_slow_state_safe_worker_runs_preflight_and_worker_gate,test_moneyflow_safe_worker_validator_accepts_complete_safe_bundle,test_moneyflow_safe_worker_validator_blocks_unsafe_or_tiny_bundle,test_production_approval_validator_accepts_moneyflow_safe_worker_validation,test_production_approval_validator_blocks_moneyflow_without_safe_validation,test_moneyflow_worker_resume_bundle_is_plan_only_and_contains_safe_commands,test_moneyflow_worker_resume_bundle_blocks_invalid_row_threshold,test_moneyflow_resume_bundle_validator_accepts_plan_only_bundle,test_moneyflow_resume_bundle_validator_blocks_remote_execution_and_safety_drift,test_worker_instance_readiness_accepts_running_and_ssm_online,test_worker_instance_readiness_blocks_stopped_or_ssm_offline,test_backend_readiness_accepts_complete_reviewed_chain,test_backend_readiness_blocks_when_true_worker_safe_validation_missing
replacement_plan_contract_test=test_backend_replacement_plan_carries_moneyflow_safe_worker_provenance
production_status=operator_only_not_datamart_not_catalog_not_factor_loop
```

Bounded local profiler command:

```bash
PYTHONPATH=. python3 scripts/profile_moneyflow_slow_state_operator.py \
  --output-path /tmp/moneyflow_slow_state_operator_profile.json \
  --tickers 512 \
  --dates 240 \
  --lambdas 0.70,0.85,0.93 \
  --operator-backends reference,array_grouped,process_sharded_array_grouped \
  --max-workers 8
```

Bounded sample builder command for partitioned upstream roots:

```bash
PYTHONPATH=. python3 scripts/build_moneyflow_slow_state_benchmark_sample.py \
  --input-root /path/to/partitioned_slow_state_input_root \
  --output-parquet /tmp/moneyflow_slow_state_input_sample.parquet \
  --proof-output /tmp/moneyflow_slow_state_input_sample.proof.json \
  --start 20240110 \
  --end 20240110 \
  --row-limit 500000
```

The sample builder is intentionally strict. It only standardizes existing columns:

```text
ts_code,trade_date,cutoff_time,v18a_z,v18b_z,v19d_score
```

It must BLOCK rather than inventing `v18a_z/v18b_z/v19d_score` from raw minute fields.

Bounded local validator command:

```bash
PYTHONPATH=. python3 scripts/validate_moneyflow_slow_state_operator_profile.py \
  --profile-path /tmp/moneyflow_slow_state_operator_profile.json \
  --output-path /tmp/moneyflow_slow_state_operator_profile.validation.json
```

True-worker validation must add:

```bash
--require-real-bounded --min-row-count <bounded_real_row_minimum>
```

One-step benchmark gate command:

```bash
PYTHONPATH=. python3 scripts/run_moneyflow_slow_state_operator_benchmark_gate.py \
  --output-dir /tmp/moneyflow_slow_state_operator_gate \
  --label real_bounded_slow_state \
  --input-parquet /path/to/bounded_intraday_flow_distribution_moments_v1.parquet \
  --lambdas 0.70,0.85,0.93 \
  --operator-backends reference,array_grouped,process_sharded_array_grouped \
  --max-workers 8 \
  --require-real-bounded \
  --min-row-count <bounded_real_row_minimum>
```

Preferred true-worker safe one-step command:

```bash
PYTHONPATH=. python3 scripts/run_moneyflow_slow_state_safe_worker_benchmark.py \
  --input-root /path/to/partitioned_slow_state_input_root \
  --output-dir /tmp/moneyflow_slow_state_worker_benchmark \
  --label real_bounded_slow_state \
  --start 20240110 \
  --end 20240110 \
  --row-limit 500000 \
  --lambdas 0.70,0.85,0.93 \
  --operator-backends reference,array_grouped,process_sharded_array_grouped \
  --max-workers 8 \
  --min-row-count <bounded_real_row_minimum>
```

This is the preferred command on a shared research worker. It runs the worker preflight first and stops before reading the upstream input root if the worker is busy, memory is low, or protected research processes are active. It writes:

```text
real_bounded_slow_state.preflight.json
real_bounded_slow_state.worker_benchmark.bundle.json
real_bounded_slow_state.safe_worker_benchmark.bundle.json
```

Required safe-bundle validation command:

```bash
PYTHONPATH=. python3 scripts/validate_moneyflow_slow_state_safe_worker_benchmark.py \
  --bundle-path /tmp/moneyflow_slow_state_worker_benchmark/real_bounded_slow_state.safe_worker_benchmark.bundle.json \
  --output-path /tmp/moneyflow_slow_state_worker_benchmark/real_bounded_slow_state.safe_worker_benchmark.validation.json \
  --min-row-count <bounded_real_row_minimum> \
  --evidence-scope bounded_worker
```

For production-scale or full-IS approval evidence, the validation command must explicitly raise the evidence scope and coverage requirements:

```bash
PYTHONPATH=. python3 scripts/validate_moneyflow_slow_state_safe_worker_benchmark.py \
  --bundle-path /tmp/moneyflow_slow_state_worker_benchmark/production_scale.safe_worker_benchmark.bundle.json \
  --output-path /tmp/moneyflow_slow_state_worker_benchmark/production_scale.safe_worker_benchmark.validation.json \
  --min-row-count <production_row_minimum> \
  --min-date-count <production_date_minimum> \
  --evidence-scope production_scale
```

For a full IS proof:

```bash
PYTHONPATH=. python3 scripts/validate_moneyflow_slow_state_safe_worker_benchmark.py \
  --bundle-path /tmp/moneyflow_slow_state_worker_benchmark/full_is.safe_worker_benchmark.bundle.json \
  --output-path /tmp/moneyflow_slow_state_worker_benchmark/full_is.safe_worker_benchmark.validation.json \
  --min-row-count <full_is_row_minimum> \
  --min-date-count <full_is_date_minimum> \
  --required-start 20160104 \
  --required-end 20250711 \
  --evidence-scope full_is
```

The validator is read-only. It checks preflight, sample proof, gate profile, gate validation, row/date threshold, requested date coverage, benchmark scope, safety flags, and `production_default_allowed=false`. `operator_replacement_verdict=HOLD` is acceptable for a safe proof; only `BLOCK` blocks the proof. A validated safe proof still does not grant production replacement; it only supplies scoped evidence to the approval builder.

Plan-only resume bundle command for when the true worker is stopped:

```bash
PYTHONPATH=. python3 scripts/build_moneyflow_slow_state_worker_resume_bundle.py \
  --instance-id i-02cc0b6e93856fbb4 \
  --repo /home/ubuntu/.openclaw/workspace/factorforge-data-api \
  --cache-root /home/ubuntu/factorforge_data_api_cache \
  --input-root /path/to/partitioned_slow_state_input_root \
  --output-dir /tmp/moneyflow_slow_state_worker_benchmark \
  --label real_bounded_slow_state \
  --start 20240110 \
  --end 20240110 \
  --row-limit 500000 \
  --min-row-count <bounded_real_row_minimum> \
  --evidence-scope bounded_worker \
  --max-workers 8 \
  --output-path /tmp/moneyflow_slow_state_worker_benchmark/real_bounded_slow_state.resume_bundle.json
```

For full-IS planning, include the production coverage contract:

```bash
PYTHONPATH=. python3 scripts/build_moneyflow_slow_state_worker_resume_bundle.py \
  --instance-id i-02cc0b6e93856fbb4 \
  --repo /home/ubuntu/.openclaw/workspace/factorforge-data-api \
  --cache-root /home/ubuntu/factorforge_data_api_cache \
  --input-root /path/to/partitioned_slow_state_input_root \
  --output-dir /tmp/moneyflow_slow_state_worker_benchmark \
  --label full_is_slow_state \
  --start 20160104 \
  --end 20250711 \
  --min-row-count <full_is_row_minimum> \
  --min-date-count <full_is_date_minimum> \
  --required-start 20160104 \
  --required-end 20250711 \
  --evidence-scope full_is \
  --approved-backend array_grouped \
  --approved-by <reviewer-or-owner> \
  --approval-reason "full IS safe worker proof accepted" \
  --max-workers 8 \
  --output-path /tmp/moneyflow_slow_state_worker_benchmark/full_is_slow_state.resume_bundle.json
```

This bundle does not start the instance, send SSM commands, run benchmarks, write backend config, or mutate datamarts. It records two command groups: local read-only readiness commands (`aws ec2 describe-instance-status`, `aws ssm describe-instance-information`, and `validate_moneyflow_slow_state_worker_instance_readiness.py`) plus the worker-side command sequence for safe benchmark, scoped safe validation, production approval builder, production approval validation, and plan-only replacement artifact generation. If reviewer fields are left as placeholders, the approval builder writes `BLOCK` rather than granting production replacement.

Validate the resume bundle before using its commands:

```bash
PYTHONPATH=. python3 scripts/validate_moneyflow_slow_state_worker_resume_bundle.py \
  --bundle-path /tmp/moneyflow_slow_state_worker_benchmark/real_bounded_slow_state.resume_bundle.json \
  --output-path /tmp/moneyflow_slow_state_worker_benchmark/real_bounded_slow_state.resume_bundle.validation.json
```

The resume-bundle validator blocks AWS start commands, SSM dispatch commands, non-plan-only execution policy, and safety drift such as `starts_instance=true`, `runs_benchmark=true`, or `writes_backend_config=true`. It also checks that local readiness commands are describe-only plus the instance-readiness validator.

Before dispatching any worker-side command, validate the instance status from read-only AWS status outputs:

```bash
PYTHONPATH=. python3 scripts/validate_moneyflow_slow_state_worker_instance_readiness.py \
  --instance-id i-02cc0b6e93856fbb4 \
  --ec2-status-path /tmp/moneyflow_worker_ec2_status.json \
  --ssm-status-path /tmp/moneyflow_worker_ssm_status.json \
  --output-path /tmp/moneyflow_slow_state_worker_benchmark/real_bounded_slow_state.worker_instance_readiness.json
```

This validator does not start the instance, send SSM commands, or run the benchmark. It returns `ACCEPT` only when the instance is `running` and SSM `PingStatus=Online`; stopped or offline workers return `BLOCK`.

Final readiness gate before any manual backend configuration change:

```bash
PYTHONPATH=. python3 scripts/validate_operator_backend_readiness.py \
  --operator-id moneyflow_slow_state_v1 \
  --safe-validation-path /tmp/moneyflow_slow_state_worker_benchmark/real_bounded_slow_state.safe_worker_benchmark.validation.json \
  --approval-validation-path /tmp/moneyflow_slow_state_worker_benchmark/real_bounded_slow_state.production_approval.validation.json \
  --replacement-plan-path /tmp/moneyflow_slow_state_worker_benchmark/real_bounded_slow_state.backend_replacement.plan.json \
  --output-path /tmp/moneyflow_slow_state_worker_benchmark/real_bounded_slow_state.backend_readiness.json
```

`scripts/validate_moneyflow_slow_state_backend_readiness.py` is a compatibility wrapper around the same generic validator. This final gate returns `ACCEPT` only after true-worker safe validation, reviewer approval validation, and plan-only replacement artifact all accept, and all three agree on `evidence_scope=production_scale` or `evidence_scope=full_is`. `bounded_worker` evidence, evidence-scope mismatch, a missing true-worker safe validation, or a non-plan-only replacement artifact returns `BLOCK`; this is the expected state until a production-scale/full-IS proof has been reviewed.

Before a manual backend config change, run the chain audit as well. It verifies the evidence chain and the runtime registry decision agree:

```bash
PYTHONPATH=. python3 scripts/audit_operator_backend_chain.py \
  --operator-id moneyflow_slow_state_v1 \
  --default-backend reference \
  --configured-backend array_grouped \
  --safe-validation-path /tmp/moneyflow_slow_state_worker_benchmark/real_bounded_slow_state.safe_worker_benchmark.validation.json \
  --approval-validation-path /tmp/moneyflow_slow_state_worker_benchmark/real_bounded_slow_state.production_approval.validation.json \
  --replacement-plan-path /tmp/moneyflow_slow_state_worker_benchmark/real_bounded_slow_state.backend_replacement.plan.json \
  --output-path /tmp/moneyflow_slow_state_worker_benchmark/real_bounded_slow_state.backend_chain.audit.json
```

The audit is also read-only. It returns `BLOCK` if readiness accepts but `resolve_operator_backend(...)` would still select the default backend, or if runtime selection does not match the planned configured backend.

Manual true-worker one-step command:

```bash
PYTHONPATH=. python3 scripts/run_moneyflow_slow_state_worker_benchmark.py \
  --input-root /path/to/partitioned_slow_state_input_root \
  --output-dir /tmp/moneyflow_slow_state_worker_benchmark \
  --label real_bounded_slow_state \
  --start 20240110 \
  --end 20240110 \
  --row-limit 500000 \
  --lambdas 0.70,0.85,0.93 \
  --operator-backends reference,array_grouped,process_sharded_array_grouped \
  --max-workers 8 \
  --min-row-count <bounded_real_row_minimum>
```

This proof only validates operator parity and bounded speed. It must not promote `moneyflow_slow_state_v1` as a production datamart without catalog, QA, coverage, and worker read smoke.

Acceptance:

- Data API catalog entry
- QA json
- worker read smoke
- coverage summary
- performance proof

### L7 Daily Incremental Update

Goal:

- full backfill once, then append daily states after raw minute update

Acceptance:

- daily update writes only new trade dates
- catalog freshness updates
- QA catches missing partitions and duplicate keys
- OOS holdout metadata is preserved

## Execution Order

P0: `process_sharded_mapreduce`

- implement for `intraday_flow_distribution_moments_v1`
- keep exact current math contract
- bounded true-worker proof on `20240110`
- promote only if materially faster than `44.49s`

Status:

```text
verdict=ACCEPT
operator_backend=process_sharded_mapreduce
rows=31482
tickers=5247
duplicate_key_count=0
missing_dates=[]
compute_seconds=41.5452
warm_read_seconds=0.0302
```

Decision: keep as experimental. It is directionally faster than exact vectorized, but the gain is not material enough to become the production default. The next P1 kernel should remove Python group-loop and exact-tail overhead rather than only adding process sharding.

Follow-up proof for combined vectorization + process sharding:

```text
verdict=ACCEPT
operator_backend=process_sharded_vectorized
rows=31482
tickers=5247
duplicate_key_count=0
missing_dates=[]
compute_seconds=44.2925
warm_read_seconds=0.0325
```

Decision: keep as experimental. Vectorization and parallelism can be combined, but with pandas DataFrame shards the process serialization, shard construction, global threshold preparation, and repeated exact-tail groupby offset the expected parallel gain. This points to P1/P2 rather than further pandas process tuning.

P1: Numba state kernel

- implement per-stock/day cutoff moments and CPV-style rolling corr kernels
- proof against reference fixtures
- bounded worker proof

Status for `intraday_flow_distribution_moments_v1` cutoff moments:

```text
verdict=ACCEPT
operator_backend=numba
worker_python=3.12.3
temporary_venv=/tmp/ff-numba-venv
numba_version=0.65.1
rows=31482
tickers=5247
duplicate_key_count=0
missing_dates=[]
compute_seconds=44.7291
warm_read_seconds=0.0303
temporary_venv_removed=true
```

Decision: Numba kernel is contract-correct but not production-fast in the current wrapper. The bottleneck moved to Python group iteration, threshold preparation, and per-group DataFrame slicing. Do not promote `operator_backend=numba` as default yet. Next iteration should combine the compiled kernel with coarse process shards or redesign the kernel to consume sorted contiguous arrays without pandas group loops.

P1.2 implementation status:

```text
operator_backend=numba_sorted
local_contract_test=PASS
isolated_numba_contract_test=PASS
design=sorted contiguous arrays + group offsets + numba parallel cutoff kernel
production_default=false
worker_bounded_proof=ACCEPT_contract_ACCEPT_parity_BLOCK_performance_promotion
worker_instance=i-02cc0b6e93856fbb4
worker_repo=/home/ubuntu/.openclaw/workspace/factorforge-data-api
worker_cache_root=/home/ubuntu/factorforge_data_api_cache
worker_python=/tmp/ff-numba-sorted-venv/bin/python
numba_version=0.65.1
temporary_venv_removed=true
rows=31482
tickers=5247
duplicate_key_count=0
missing_dates=[]
read_seconds=4.8866
compute_seconds=95.4972
write_seconds=0.0874
warm_read_seconds=0.0475
output_file_size_bytes=7160384
parity_verdict=ACCEPT
vectorized_compute_seconds_for_parity=100.7728
numba_sorted_warm_compute_seconds_for_parity=95.6571
max_abs_diff_amount_sum=7.1526e-07
max_abs_diff_large_proxy_amount=4.7684e-07
max_abs_diff_signed_flow_hhi=6.5226e-16
```

Decision: `numba_sorted` is contract-correct on the true worker after vectorized market-threshold fallback and signed-flow HHI repairs. It is not enough of a performance win to promote as default: same-input parity timing was 95.6571s warm `numba_sorted` vs 100.7728s vectorized. Do not run full-window backfill with this backend as a performance solution. The next optimization target is threshold/read preparation, exact-tail quantile calculation, and reducing DataFrame construction/serialization around the compiled kernel.

P4 prepared-minute cache proof:

```text
dataset_candidate=prepared_minute_bar_v1
proof_date=20240110
worker_instance=i-02cc0b6e93856fbb4
prepared_cache_root=/home/ubuntu/factorforge_data_api_cache/s3_parquet/minute_bar-prepared_v1-speed-p4-20240110
prepared_cache_build_seconds=78.3862
prepared_cache_size_bytes=264571199
prepared_cache_row_count=16721924
prepared_cache_date_count=31
parity_verdict=ACCEPT
row_count=31482
duplicate_key_count=0
missing_dates=[]
vectorized_compute_seconds_on_prepared_cache=27.5391
numba_sorted_warm_compute_seconds_on_prepared_cache=19.5849
numba_sorted_prepared_warm_seconds=0.8457
raw_path_prior_vectorized_compute_seconds=90.9807
raw_path_prior_numba_sorted_warm_compute_seconds=81.9453
speedup_vs_raw_vectorized_compute=4.65x
speedup_vs_raw_numba_sorted_warm_compute=4.18x
```

Decision: significant speedup requires a persistent prepared minute state, not another wrapper around raw minute parquet. `prepare_minute_frame` over the raw 31-partition input was measured at 74.4459s; once normalized columns are persisted (`hhmmss`, `amount_abs`, `minute_ret`, `signed_amount`, `vol`), the same exact state computation drops to 19.5849s end-to-end on loaded prepared parquet, and the prepared in-memory kernel is 0.8457s.

Current implementation status:

- `scripts/build_prepared_minute_bar.py` now emits partitioned parquet plus optional standalone QA and Data API catalog json.
- `prepared_minute_bar_v1` unique key is `ts_code + trade_date + hhmmss`.
- Catalog metadata marks `source_dataset=minute_bar`, `schema_version=prepared_minute_bar_v1_p0`, `no_future_intraday_minutes=true`, and `replacement_policy=opt_in_until_full_worker_qa_and_research_parity_accept`.
- Full-window and speed-proof commands must use `--source-ready-only` when the source root contains `.missing` marker partitions. QA/proof payloads now expose `source_not_ready_dates` or `prepared_cache_source_not_ready_dates`.
- This is not yet published as the production default catalog entry. It is an opt-in verified data-layer path until full IS backfill + worker read smoke + research parity are accepted.

Local contract smoke:

```text
script=python3 scripts/build_prepared_minute_bar.py
dataset_id=prepared_minute_bar_v1
dates=20240104
row_count=6
duplicate_key_count=0
missing_dates=[]
qa_verdict=ACCEPT
catalog_load_smoke=ACCEPT
```

True worker bounded proof:

```text
instance_id=i-02cc0b6e93856fbb4
worker_repo=/home/ubuntu/.openclaw/workspace/factorforge-data-api
package_path=/home/ubuntu/.openclaw/workspace/factorforge-data-api/factorforge_data_api/__init__.py
raw_minute_root=/home/ubuntu/factorforge_data_api_cache/s3_parquet/minute_bar-raw_v1-0b2b836c57d763c6
prepared_datamart_path=/home/ubuntu/factorforge_data_api_cache/s3_parquet/prepared_minute_bar_v1-bounded-worker-20240110
qa_path=/home/ubuntu/factorforge_data_api_cache/proofs/prepared_minute_bar_v1/prepared_minute_bar_v1_20240110.worker.qa.json
catalog_path=/home/ubuntu/factorforge_data_api_cache/proofs/prepared_minute_bar_v1/prepared_minute_bar_v1_20240110.worker.catalog.json
data_api_fetch_smoke_path=/home/ubuntu/factorforge_data_api_cache/proofs/prepared_minute_bar_v1/prepared_minute_bar_v1_20240110.worker.data_api_fetch_smoke.json
trade_date=20240110
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
manual_duplicate_key_count_ts_date_hhmmss=0
worker_stopped_after_proof=true
```

The DataApiClient smoke initially exposed the same duplicate-key class as prior intraday cutoff datasets: the worker validator counted duplicates by `ts_code + trade_date` instead of the catalog metadata `unique_key`. The worker package was patched to honor `metadata.unique_key`, then `prepared_minute_bar_v1` returned `status=ready` with `coverage_duplicate_key_count=0`.

`intraday_flow_distribution_moments_v1` prepared-input integration status:

```text
script=scripts/build_intraday_flow_distribution_moments.py
new_opt_in_arg=--prepared-minute-root
new_source_ready_arg=--source-ready-only
default_raw_arg=--minute-root
default_behavior_changed=false
qa_fields=input_dataset,input_minute_format,input_prepared_minute_columns,realized_operator_backend,source_ready_policy,source_not_ready_dates
prepared_dispatcher=derive_intraday_flow_distribution_moments_from_prepared
prepared_dispatcher_backends=vectorized_prepared,polars_prepared,numba_sorted_prepared,process_sharded_vectorized_prepared
local_contract_test=test_build_script_marks_explicit_prepared_minute_input
source_ready_contract_test=test_build_script_can_skip_source_not_ready_prepared_partitions
```

Prepared-minute full-window backfill safety status:

```text
script=scripts/build_prepared_minute_bar.py
new_resume_args=--skip-existing,--max-dates,--manifest-output
resume_success_marker=trade_date=YYYYMMDD/part.parquet
manifest_fields=processed_dates,skipped_dates,remaining_dates,missing_dates,read_errors
local_contract_test=test_prepared_minute_builder_supports_bounded_resume_manifest
full_IS_default_started=false
```

True-worker resume proof:

```text
instance_id=i-02cc0b6e93856fbb4
resume_output_root=/home/ubuntu/factorforge_data_api_cache/s3_parquet/prepared_minute_bar_v1-resume-proof-20240110-20240111
proof_root=/home/ubuntu/factorforge_data_api_cache/proofs/prepared_minute_bar_v1_resume
batch1=max-dates=1 -> processed 20240110, remaining 20240111, ACCEPT
batch2=skip-existing -> skipped 20240110, processed 20240111, remaining [], ACCEPT
skip_existing_mtime_preserved=true
DataApiClient_status=ready
DataApiClient_row_count=2427620
DataApiClient_date_count=2
DataApiClient_coverage_duplicate_key_count=0
DataApiClient_elapsed_seconds=1.8003
worker_stopped_after_proof=true
```

Prepared-minute full/backfill QA tooling:

```text
script=scripts/qa_prepared_minute_bar.py
inputs=source-minute-root,prepared-root,start,end
outputs=qa-output,catalog-output,read-smoke-output
checks=expected_dates_vs_prepared_dates,missing_dates,read_errors,schema,duplicate_key_count,DataApiClient_read_smoke
local_contract_test=test_prepared_minute_qa_writes_catalog_and_data_api_read_smoke
full_IS_default_started=false
```

True-worker IS-candidate batch:

```text
instance_id=i-02cc0b6e93856fbb4
candidate_output_root=/home/ubuntu/factorforge_data_api_cache/s3_parquet/prepared_minute_bar_v1-is-candidate
proof_root=/home/ubuntu/factorforge_data_api_cache/proofs/prepared_minute_bar_v1_is_candidate
source_selection=explicit_source_ready_dates
date_count=20
row_count=13070307
batch_runtime_seconds=72.1866
duplicate_key_count=0
missing_dates=[]
DataApiClient_status=ready
DataApiClient_elapsed_seconds=10.5752
DataApiClient_coverage_duplicate_key_count=0
worker_stopped_after_proof=true
```

Remaining blocker before full-window automation:

```text
raw minute cache includes .missing marker partitions for non-trading dates
full-window prepared backfill must use source-ready trading dates, not every trade_date=* directory
```

P4 speed proof wiring status:

```text
script=scripts/run_prepared_cache_speed_proof.py
new_source_ready_arg=--source-ready-only
parity_script=scripts/run_flow_distribution_moments_parity_smoke.py
proof_fields=prepared_dispatcher_backend,prepared_dispatcher_cold_seconds,prepared_dispatcher_warm_seconds,row_count_prepared_dispatcher,prepared_dispatcher_key_equal
promotion_fields=performance_promotion_verdict,performance_speedup_vs_vectorized,performance_min_speedup_ratio,performance_promotion_issues
operator_replacement_rule=correctness_verdict_ACCEPT_and_performance_promotion_verdict_ACCEPT
numba_missing_policy=write_BLOCK_proof_with_issues_numba_unavailable
source_not_ready_target_policy=write_BLOCK_proof_with_issues_target_date_not_source_ready
local_contract_tests=test_parity_smoke_is_wired_to_prepared_dispatcher,test_parity_smoke_blocks_with_proof_when_numba_backend_unavailable,test_parity_smoke_performance_promotion_blocks_correct_but_slow_backend,test_prepared_cache_speed_proof_builder_can_use_source_ready_dates_only,test_prepared_cache_speed_proof_main_writes_block_proof_for_not_source_ready_target
worker_bounded_speed_proof_status=pending_after_repo_sync
```

P4 stage profiler status:

```text
script=scripts/profile_flow_distribution_moments_operator.py
scope=bounded_local_or_worker_proof_only
supported_inputs=--minute-root,--prepared-minute-root
supported_operator_backend=vectorized,numba_sorted
proof_fields=stage_seconds,dominant_stage,input_dataset,operator_backend,realized_operator_backend,row_count,duplicate_key_count,output_key_hash
backend_unavailable_policy=write_BLOCK_proof_with_issues_operator_backend_unavailable
source_not_ready_policy=write_BLOCK_proof_with_issues_missing_target_dates
local_contract_tests=test_operator_profiler_writes_stage_timing_proof_for_raw_minute_root,test_operator_profiler_marks_prepared_minute_input_without_raw_prepare,test_operator_profiler_blocks_with_proof_when_backend_unavailable,test_operator_profiler_blocks_with_proof_when_target_date_is_not_source_ready
replacement_rule=profiler_does_not_replace_backend_it_only_identifies_bottleneck
```

P4 profile comparison status:

```text
script=scripts/compare_flow_distribution_operator_profiles.py
scope=bounded_local_or_worker_proof_only
compares=raw_vs_prepared,vectorized_vs_numba_sorted
proof_fields=profiles,best_profile_id,prepared_vs_raw_total_speedup,best_speedup_vs_raw_vectorized,baseline_profile_id,baseline_profile_accept,accepted_profile_row_count_equal,accepted_profile_duplicate_key_count_zero,accepted_profile_key_hash_equal,operator_replacement_verdict,operator_replacement_issues
blocked_backend_policy=keep_blocked_backend_proofs_inside_profiles
baseline_rule=raw_vectorized_must_be_ACCEPT
replacement_blockers=baseline_profile_not_accept,accepted_profile_row_count_mismatch,accepted_profile_duplicate_keys,accepted_profile_key_hash_mismatch
local_contract_tests=test_operator_profile_comparison_writes_raw_vs_prepared_matrix,test_operator_profile_comparison_keeps_blocked_backend_proofs,test_operator_profile_comparison_blocks_replacement_when_accepted_row_counts_differ,test_operator_profile_comparison_blocks_replacement_when_accepted_key_hashes_differ,test_operator_profile_comparison_blocks_replacement_when_baseline_profile_not_accept
replacement_rule=comparison_does_not_replace_backend_it_only_supplies_promotion_evidence
```

P4 comparison validator status:

```text
script=scripts/validate_flow_distribution_operator_comparison.py
scope=read_only_proof_validation_before_any_backend_replacement
requires=comparison_verdict_ACCEPT,operator_replacement_verdict_ACCEPT,raw_vectorized_baseline_ACCEPT,row_count_equal,duplicate_key_zero,key_hash_equal
local_contract_tests=test_operator_comparison_validator_accepts_complete_accept_proof,test_operator_comparison_validator_blocks_missing_required_field,test_operator_comparison_validator_blocks_replacement_gate_block
replacement_rule=validator_ACCEPT_is_required_but_still_does_not_mutate_backend_config
```

Example:

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

Matrix comparison example:

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

Validation example:

```bash
python3 scripts/validate_flow_distribution_operator_comparison.py \
  --proof-path /path/to/operator_profile_comparison_20240110.json \
  --output-path /path/to/operator_profile_comparison_20240110.validation.json
```

P2: Columnar engine one-pass proof

- Polars Lazy or ClickHouse SQL plan for moments/cutoff aggregation
- compare against P0/P1

P3: Datamart registry

- formalize reusable minute-state datasets
- require catalog + QA + worker read smoke before Factor Forge production loop uses them

P4: Full IS backfill orchestration

- shard manifest
- resume/retry
- cost estimate
- AWS Batch/Spot only after bounded proof shows acceptable economics

## Current Default

Until P0/P1 beats the bounded baseline, production default remains:

```text
operator_backend=vectorized
```

Experimental backends may exist in code but must not become production defaults without true-worker proof.
low_level_array_api=rolling_corr_grouped_arrays_terminal_corr_grouped_arrays_and_occupation_location_grouped_arrays_accept_starts_ends_arrays_without_DataFrame_groupby
