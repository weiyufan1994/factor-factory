# Bounded execution and reusable inputs

Read for minute/state-dependent factors, large panels or a declared reuse policy.

Formal factor compute and evaluation must be memory-bounded. For minute bars,
tick data, large daily universes, or future model-training/evaluator paths,
Step4 must estimate peak memory before execution. If the estimate exceeds about
50-60% available RAM, or if a run shows `Killed`, exit 137, OOM-kill logs,
allocator failure, or swap exhaustion, Step4 must not retry the same
all-in-memory path. It must switch to
`batch_execution_plan.version=factorforge_batch_execution_plan_v1` or BLOCK
with `BLOCK_MEMORY_PRESSURE_BATCH_REQUIRED`.

The batch plan must state memory budget, estimated peak memory, partition key,
selected columns, predicate pushdown, rolling/lookback overlap or carried state,
checkpoint/resume paths, output cache identity, and a bounded parity sample.
Step4 writes per-batch Parquet/cache outputs and releases intermediates between
batches. It must not accumulate all partitions in a Python list for final concat
unless the resulting materialization is proven within budget. Cross-sectional
rank/quantile evaluation must preserve complete per-date cross-sections or use
a documented two-pass plan. Backtest labels, masks, calendars, cost tables, and
static joins should come from reusable `backtest_base_dataset` artifacts instead
of being rebuilt for every factor, child, or sibling branch when identity and
data-window lineage match.

Full-window minute production must not fall back to generic raw-minute
streaming. For formal 2016-2026-style windows, Step4 must first consume a
declared `minute_derived_state_requirements[]` contract, currently including
`minute_derived_flow_state_v1` for signed-flow / pressure / concentration /
intraday-noise factors. The derived datamart is partitioned by `trade_date` and
must carry source data version, cutoff time, schema version, producer version,
and artifact hash. Step4 may load the derived parquet and then run only the
factor expression and evaluation. If the required derived state is absent,
incomplete, or identity-mismatched, Step4 must BLOCK with one of:
`BLOCK_STEP4_MINUTE_DERIVED_STATE_REQUIRED`,
`BLOCK_STEP4_MINUTE_GENERIC_STREAMING_FULL_WINDOW_FORBIDDEN`,
`BLOCK_MINUTE_DERIVED_STATE_COVERAGE_INCOMPLETE`, or
`BLOCK_MINUTE_DERIVED_STATE_IDENTITY_MISMATCH`. Building or refreshing the
derived state is an explicit backfill task
(`scripts/build_minute_derived_datamart.py`), not an implicit side effect of
Step4.

Daily controls are also reusable infrastructure, not per-run cold IO. Step4
must prefer the `daily_basic` parquet datamart / persistent warm cache over S3
CSV or per-day CSV reads for market-cap, turnover, volume-ratio, valuation,
liquidity, size-neutralization, Bayesian-condition, and subgroup-control
features. The current cache contract is
`daily_basic_parquet_v1`, partitioned by `trade_date`, with metadata carrying
source data version, schema version, producer version, and artifact hash. Step4
must expose proof fields in run metadata / diagnostics:
`daily_basic_selected_format`, `daily_basic_cache_hit`,
`daily_basic_cache_path`, `daily_basic_rows`, `daily_basic_dates`,
`daily_basic_tickers`, and `daily_basic_load_seconds`.

Step4 must also reuse a prepared `backtest_base_daily_controls_v1` artifact
when the Step4 data contract identity matches. This base contains the merged
clean daily bars plus daily controls used by evaluators. Rebuilding labels,
masks, calendars, cost proxies, daily_basic controls, and static joins for
every child/sibling revision is a performance defect unless the identity or
data window changed. If a run declares parquet / reuse as required but falls
back to CSV or rebuilds a matching base, it should BLOCK with
`BLOCK_FACTORFORGE_DAILY_BASIC_PARQUET_REQUIRED` or
`BLOCK_FACTORFORGE_BACKTEST_BASE_REUSE_REQUIRED`.

Default research-window policy for current minute-factor research is
in-sample through `2025-07-11`; later data is OOS holdout. Step4 should preserve
`research_window_contract` in run metadata, and Step5/Step6 must not repeatedly
fit revisions on OOS evidence.
