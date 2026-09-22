# Step3 numerical execution, performance and batching

Read the relevant section when implementing Formula-IR engines, performance options, large inputs or batch/stateful methods. Options do not authorize a wider sample or a performance experiment.

## Sample metadata and engine options

  - `run_metadata.performance_profile` with contract version
    `factorforge_step3b_performance_profile_v1`, row count, phase timings for
    input read / factor compute / normalize-sort / parquet write / CSV write,
    compute rows/sec, and output byte sizes.
  - For Formula-IR operator implementations, `run_metadata.performance_profile`
    should include `formula_engine_profile` showing the evaluator engine,
    reference engine, memoization/cache stats, deterministic parity status,
    sample size, max absolute diff, rank correlation, and sortedness flags.
    The pandas reference evaluator remains the correctness oracle; optimized
    execution must match it or block before sample factor values are written.
    Operator-level profiling is observation-only and can be enabled with
    `FACTORFORGE_ENABLE_OPERATOR_PROFILE=1` or `--operator-profile`; it records
    `formula_engine_profile.operator_profile` and `parity_profile` without
    changing formula semantics, the default pandas path, or parity enforcement.
  - CSV audit writes are controlled by the explicit policy
    `full_csv|sample_csv|no_csv` (`FACTORFORGE_CSV_OUTPUT_POLICY` or
    `--csv-output-policy`). The default remains `full_csv`. `sample_csv` writes
    deterministic head/tail sample CSV artifacts and `no_csv` writes no CSV;
    both are opt-in performance modes while parquet remains the formal
    high-performance read path.
## Formula-IR engine selection

  - Formula-IR execution defaults to pandas optimized with pandas reference as
    the correctness oracle. A reviewed subset of default NumPy time-series
    kernels may run inside this `pandas_optimized` path for `min`, `max`,
    `delta`, `delay`, `argmin`, `argmax`, `ts_rank`, `corr`, `correlation`,
    and `covariance`; rollback must be available through
    `FACTORFORGE_DISABLE_DEFAULT_NUMPY_TS_KERNEL=1`. This default kernel subset
    is production acceleration and must be active on Mac and EC2 unless a
    rollback/debug run records the reason. `sum`, `mean`, and
    `std/stddev` remain pandas fallback in the default path because tiny
    floating-point accumulation differences can be amplified by downstream
    cross-sectional `rank`. The
    experimental Polars backend is
    opt-in only (`FACTORFORGE_ENABLE_EXPERIMENTAL_POLARS=1` or
    `--formula-engine polars_experimental`), must record parity metadata, and
    must BLOCK on missing dependency or parity failure. Unsupported Polars
    operators may fall back to pandas only when the metadata records an explicit
    `polars_fallback_reason`. The adaptive selector is also explicit opt-in
    (`--formula-engine adaptive`); it may select lazy Polars only for native
    parquet Formula-IR subsets, otherwise it must choose pandas optimized and
    record `formula_engine_profile.adaptive_selector.reason`.
  - The experimental `ts_rank` engine is opt-in only
    (`FACTORFORGE_ENABLE_EXPERIMENTAL_TS_RANK_ENGINE=1` plus
    `FACTORFORGE_TS_RANK_ENGINE=numpy_sliding_window_experimental`, or
    `--ts-rank-engine numpy_sliding_window_experimental`). This independent
    engine remains separate from the default Formula-IR NumPy kernel subset;
    experimental runs must record `formula_engine_profile.ts_rank_engine_profile`,
    pass pandas-reference sample parity, and obey the runtime guard before
    writing factor values.
    The legacy `FACTORFORGE_ENABLE_EXPERIMENTAL_TS_RANK_FAST` flag must not
    enable or select an experimental engine; if present, metadata should record
    it only as an ignored stale environment flag.
  - Formula-IR operator kernels default to `pandas_optimized` with pandas
    reference as the correctness oracle and the default NumPy time-series kernel
    subset enabled. Experimental kernels beyond that reviewed default subset are
    opt-in only (`FACTORFORGE_ENABLE_EXPERIMENTAL_FORMULA_KERNEL=1` plus
    `FACTORFORGE_FORMULA_KERNEL_ENGINE=numpy_rolling_experimental`, or
    `--formula-kernel-engine numpy_rolling_experimental`). Step3B must record
    `formula_engine_profile.kernel_profile`; experimental kernels must not be
    marked `safe_to_make_default`, and must BLOCK on invalid engine, missing
    explicit enable gate, parity failure, dependency failure, or runtime guard
    failure.
  - Production Step3B runs must not enable experimental Polars, the independent
    experimental `ts_rank` engine, or future experimental Formula-IR kernel
    engines unless the user explicitly asks for a performance experiment. The
    production path is Formula-IR `pandas_optimized` with pandas reference
    parity, default NumPy time-series kernels, Parquet IO, and optional
    `sample_csv` audit output. Step3B is an executability proof and must use
    Data API sample queries or a capped deterministic local sample; it must not
    run a full formal data window or write formal factor values.
## Direct-code and custom blocks

  - For `direct_code` or `hybrid` custom blocks that cannot be represented as
    Formula-IR, generated implementations should prefer vectorized NumPy and/or
    Polars. Pandas remains acceptable as a reference or compatibility layer, but
    Python row loops and pandas `groupby.apply` require explicit justification
    in the implementation plan and generated-code comments.
## Large data and bounded batches

  - Direct-code and hybrid implementations over minute bars, tick data, or any
    large intraday source must expose a bounded batch path. The implementation
    plan must include `batch_execution_plan.version=factorforge_batch_execution_plan_v1`
    with memory budget, estimated peak memory, partition key, selected columns,
    predicate pushdown policy, rolling/lookback overlap or carried state,
    checkpoint/resume path, and reference/parity sample. If the estimator cannot
    be batch-safe, Step3B must BLOCK with `BLOCK_MEMORY_PRESSURE_BATCH_REQUIRED`
    instead of emitting all-in-memory code.
  - Batch-safe code must stream partitions and write per-batch Parquet/cache
    outputs; it must not build an unbounded list of intermediate DataFrames for
    final concat. Time-series windows require overlap or state carry, and
    cross-sectional operators require complete per-date cross-sections or a
    two-pass plan. This applies to future model-training scaffolds as well:
    use mini-batches, dataset streaming, checkpointing, and gradient
    accumulation rather than loading full tensors into RAM.
