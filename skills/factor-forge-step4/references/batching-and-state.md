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

Full-window minute execution must use a declared, bounded input route. A
published derived dataset is suitable only if its fields preserve the reviewed
estimator's observations; `minute_derived_flow_state_v1` is one flow-state
implementation, not a universal minute-factor schema. Its cutoff is not a
universal signal cutoff either.

When standard Data API minute fields suffice, research may explicitly build
and reuse its own reviewed state before Step4. Follow
[research-derived inputs](research-derived-inputs.md): this is a formal local-IS
adapter route, not a fallback around a missing datamart. Both routes bind source
and catalog identity, schema, producer code, information cutoff, coverage and
artifact hashes. Step4 consumes the prepared state and executes the factor and
evaluation; it does not secretly fetch or rebuild raw minute history.

Keep the existing block on undeclared generic raw-minute full-window streaming
and on incomplete or mismatched declared inputs. A failed published-state
request does not automatically select research-side preparation. Preparation
is an explicit bounded task with replay evidence; subsequent revisions reuse
matching partitions rather than repeating the minute read. Do not turn off
these checks to make an incompatible table run.

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
