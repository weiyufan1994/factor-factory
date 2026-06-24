# Alpha101 Operator OOS Refresh Contract

日期：2026-06-24

## 目的

为普通 Alpha101 Formula-IR / operator 因子补一个 OOS factor-value refresh
合同，用于在不重写 parent IS artifacts 的情况下生成 OOS holdout
factor values，并为后续 `factor_library_exposure_panel_v1` append/rebuild
提供可审输入。

该合同最先用于 Alpha015：

```text
ALPHA015_SWEEP_TURNPEN_A040_20160101
```

当前 Alpha015 的正式阻塞是：

```text
BLOCK_ALPHA101_GENERIC_OOS_FACTOR_VALUE_REFRESH_MISSING
```

## 合同边界

`scripts/run_alpha101_operator_oos_refresh.py` 只做一件事：

1. 读取 source report id、factor id、原始 formula、目标 OOS window；
2. 从 `clean_daily_bar_oos_slice` 读取 OOS 所需数据和足够 lookback history；
3. 用 Formula-IR evaluator 计算 factor values；
4. 只保留目标 OOS window；
5. 写入 window-scoped artifact；
6. 写 metadata 和 factor-library append compatibility proof。

输出路径形如：

```text
runs/<source_report_id>/oos_refresh/<start>_<end>/
  factor_values__<source_report_id>__oos_<start>_<end>.parquet
  run_metadata__<source_report_id>__oos_<start>_<end>.json
  factor_library_append_compatibility__<source_report_id>__oos_<start>_<end>.json
```

这避免覆盖 parent IS artifact：

```text
runs/<source_report_id>/factor_values__<source_report_id>.parquet
```

## 必须证明

metadata 必须证明：

- `source_report_id` 保持不变；
- `formula_hash` 存在且可追溯；
- `revision_fitting_allowed=false`；
- `same_report_id_parent_factor_parquet_overwrite=false`；
- 输出只覆盖 OOS target window；
- duplicate key count 为 0；
- 没有 future return label；
- append compatibility proof 为 `ACCEPT`。

## Smoke

`scripts/run_alpha101_operator_oos_refresh_smoke.py` 使用小样本：

```text
formula: rank(close)
window: 20250714-20250715
universe: 000001.SZ,000002.SZ
dataset: clean_daily_bar_oos_slice
```

验收：

```text
verdict: ACCEPT
row_count: 4
date_count: 2
ticker_count: 2
non_null_coverage: 1.0
```

## Full OOS Cold-Cache Boundary

Mac cold-cache full OOS refresh was deliberately stopped after more than five
minutes without a result. The stack trace showed the run was still inside Data
API S3 parquet partition download:

```text
factorforge_data_api/backends/s3_file.py
_download_s3_parquet_to_path(...)
aws s3 cp ...
```

This means the first bottleneck is cold S3 partition hydration, not Formula-IR
evaluation. Full OOS execution should therefore use one of:

1. true research worker with persistent warm `FACTORFORGE_DATA_CACHE`;
2. a batch/monthly refresh plan with checkpointed partition outputs;
3. a pre-hydrated local/S3-derived OOS factor refresh datamart.

The small smoke remains valid for contract behavior, but it is not a
performance proof for full OOS.

## Batch Checkpoint Contract

To avoid a single unbounded full-window run, the branch adds:

```text
scripts/run_alpha101_operator_oos_refresh_batch.py
scripts/run_alpha101_operator_oos_refresh_batch_smoke.py
```

The batch runner splits the OOS target window by calendar month, calls the
single-window refresh for each month, and writes a checkpoint manifest under:

```text
runs/<source_report_id>/oos_refresh_batch/<start>_<end>/
  batch_manifest__<source_report_id>__oos_<start>_<end>.json
```

Each month still writes its own window-scoped factor values and compatibility
proof:

```text
runs/<source_report_id>/oos_refresh/<month_start>_<month_end>/
```

The batch manifest proves:

- `batch_execution_plan.version=factorforge_batch_execution_plan_v1`;
- `checkpoint_resume_supported=true`;
- each completed batch has metadata and compatibility proof;
- failed batches are isolated and can be rerun;
- parent IS artifact is still not overwritten.

Batch smoke:

```text
verdict: ACCEPT
window: 20250714-20250801
batch_count: 2
completed_batch_count: 2
row_count: 30
date_count_sum: 15
failed_batch_count: 0
```

Cold-cache timing:

```text
20250714-20250731: 124.83s
20250801-20250801: 7.12s
total: 131.95s
```

This confirms the batch contract works, but also confirms Mac cold-cache S3
hydration remains too slow for a full OOS production run. Full Alpha015 OOS
should use this batch contract on a worker with persistent warm cache, or first
hydrate the Data API cache.

Follow-up hardening:

- the manifest now carries an explicit bounded batch execution plan;
- future smoke uses the shorter cross-month window `20250731-20250801` to keep
  contract verification cheap while still covering two monthly batches.

## 非目标

该合同不做：

- Alpha015 全 OOS 正式研究；
- factor library exposure panel append/rebuild；
- residual/style/model-combination proof；
- Step6 promotion；
- OOS formula fitting 或参数搜索；
- portfolio policy repair。

在主 wrapper 集成和 Alpha015 全 OOS factor values 产生之前，本合同只能关闭
“可实现性”风险，不能关闭 Alpha015 promotion gate。
