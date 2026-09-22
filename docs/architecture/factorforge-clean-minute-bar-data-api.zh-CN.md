# Factor Forge `clean_minute_bar` 数据产品与 Data API 架构书

日期：2026-05-31

## 1. 背景

当前 Step3 已经把日线侧收敛到 `clean_daily_bar` + Data API resolution：Step3A 只消费已清洗、可审计、带 policy/coverage/schema 的数据产品。

分钟数据目前还没有达到同一标准。S3 或 EC2 上可能存在 raw minute partitions，但 raw 数据不能直接等同于 Factor Forge 的可执行数据产品。分钟因子必须等 `clean_minute_bar` 就绪后才能进入 Step3B/Step4；未就绪时应明确 `BLOCK`，不能静默扫描 raw path 或 synthetic fallback。

## 2. 设计目标

`clean_minute_bar` 的目标是成为分钟级因子的唯一标准输入层：

1. 数据本身干净：去重、排序、字段规范、异常 bar 标记或剔除。
2. 交易日语义一致：停牌、一字涨跌停、无效日的处理与 `clean_daily_bar` 对齐。
3. 可审计：每次构建写 metadata、coverage、source、policy、build sha。
4. 可发现：通过 Data API/catalog resolution 暴露，不由 Step3A 猜路径。
5. 可切片：Step3A 只 materialize report-scoped snapshot，不负责清洗分钟数据。
6. 可阻断：缺失或 coverage 不足时返回结构化 blocker。

## 3. 分层架构

```text
raw S3 minute partitions
  -> sync_tushare_raw_from_s3.py sync-minute-range
  -> local raw minute cache
  -> build_clean_minute_layer.py
  -> clean_minute_bar parquet partitions + meta
  -> data_catalog.json
  -> resolve_data_api_dataset("clean_minute_bar")
  -> Step3A data_prep_master.data_api_resolution
  -> Step3A report-scoped minute snapshot
  -> Step3B/Step4 factor execution
```

Step3A 之后的所有执行路径只认 Data API resolution，不认 raw S3 path。

## 4. 存储布局

推荐生产布局：

```text
$FACTORFORGE_ROOT/data/clean/minute_bar/
  minute_clean.meta.json
  trade_date=20160104/part-*.parquet
  trade_date=20160105/part-*.parquet
  ...
```

小样本/测试布局可支持单文件：

```text
$FACTORFORGE_ROOT/data/clean/minute_bar/
  minute_clean.parquet
  minute_clean.meta.json
```

生产优先按 `trade_date` 分区，原因是 Step3/Step4 常按日期窗口切片，按日分区可以避免读取全量分钟数据。

## 5. Schema

最小必需字段：

```text
ts_code         string
trade_date      string YYYYMMDD
trade_time      timestamp/string, full datetime
bar_time        string HH:MM:SS
minute_index    int, per stock/trade_date increasing from market open
open            float
high            float
low             float
close           float
vol             float
amount          float
```

建议审计字段：

```text
is_valid_bar
is_suspended_day
is_limit_event_day
source_partition
source_row_hash
adjust_mode
calendar
```

字段别名策略：

- `volume` 可在 Data API adapter 层映射到 `vol`，但标准物理字段保持 `vol`。
- `datetime` 可在 consumer adapter 层从 `trade_time` 派生，物理标准字段保持 `trade_time`。

## 6. 清洗规则

`clean_minute_bar` builder 必须实现并记录：

1. 规范日期和时间：
   - `trade_date` 统一为 `YYYYMMDD`。
   - `trade_time` 必须能唯一定位分钟 bar。
   - `bar_time` 从 `trade_time` 派生或校验。

2. 主键去重：
   - 主键：`["ts_code", "trade_time"]`。
   - 重复记录必须 deterministic 处理，并写入 drop count。

3. 排序契约：
   - 输出按 `["ts_code", "trade_time"]` 或分区内按该键排序。
   - metadata 写 `sort_key` 和 `sample_sortedness_check`。

4. OHLC 合法性：
   - `open/high/low/close` 必须为正数。
   - `high >= max(open, close, low)`。
   - `low <= min(open, close, high)`。

5. 量价合法性：
   - `vol >= 0`。
   - `amount >= 0`。
   - `drop_zero_volume_bars` 由 policy 控制；默认建议标记后剔除。

6. 无效交易日：
   - 停牌日和一字涨跌停日必须可识别。
   - 默认 policy：无效日不进入分钟聚合，也不进入日级 rolling window。
   - 如果保留无效日作审计，也必须 `is_valid_bar=false`，Step3 consumer 不得把它当有效样本。

7. 与日线层对齐：
   - 分钟数据的有效交易日集合必须能与 `clean_daily_bar` 对齐。
   - 对同一 `ts_code/trade_date`，分钟聚合出的 open/high/low/close 应可与日线 close/high/low 做容差校验。

## 7. Metadata Contract

`minute_clean.meta.json` 必须至少包含：

```json
{
  "dataset_id": "clean_minute_bar",
  "contract_version": "factorforge_clean_minute_bar_v1",
  "schema": {
    "columns": ["ts_code", "trade_date", "trade_time", "bar_time", "minute_index", "open", "high", "low", "close", "vol", "amount"],
    "primary_key": ["ts_code", "trade_time"],
    "partition_key": ["trade_date"],
    "sort_key": ["ts_code", "trade_time"]
  },
  "coverage": {
    "start": "20160104",
    "end": "20260531",
    "trade_dates": 0,
    "tickers": 0,
    "rows": 0
  },
  "policy": {
    "drop_suspended_days": true,
    "drop_limit_event_days": true,
    "drop_zero_volume_bars": true,
    "invalid_days_do_not_enter_window": true,
    "minimum_effective_days_policy": "factor_specific"
  },
  "quality": {
    "duplicate_key_count": 0,
    "invalid_ohlc_count": 0,
    "zero_volume_count": 0,
    "dropped_rows": 0,
    "sample_sortedness_check": true
  },
  "source": {
    "raw_s3_uri": "s3://yufan-data-lake/tushares/分钟数据/raw/stk_mins_1min/",
    "raw_sync_command": "scripts/sync_tushare_raw_from_s3.py sync-minute-range",
    "build_script": "scripts/build_clean_minute_layer.py",
    "build_repo_sha": "<git-sha>",
    "build_time_utc": "<timestamp>"
  },
  "artifacts": {
    "root": "$FACTORFORGE_ROOT/data/clean/minute_bar",
    "partition_pattern": "trade_date=*/part-*.parquet",
    "metadata_json": "$FACTORFORGE_ROOT/data/clean/minute_bar/minute_clean.meta.json"
  }
}
```

## 8. Data API Contract

`resolve_data_api_dataset("clean_minute_bar")` ready 返回：

```json
{
  "dataset_id": "clean_minute_bar",
  "status": "ready",
  "access_mode": "catalog",
  "artifacts": {
    "root": ".../data/clean/minute_bar",
    "partition_pattern": "trade_date=*/part-*.parquet",
    "metadata_json": ".../minute_clean.meta.json"
  },
  "schema": {
    "columns": ["ts_code", "trade_date", "trade_time", "close", "vol", "amount"]
  },
  "coverage": {
    "start": "20160104",
    "end": "20260531",
    "trade_dates": 0,
    "tickers": 0,
    "rows": 0
  },
  "policy": {
    "invalid_days_do_not_enter_window": true
  }
}
```

未 ready 返回：

```json
{
  "dataset_id": "clean_minute_bar",
  "status": "blocked",
  "block_code": "CLEAN_MINUTE_BAR_MISSING",
  "message": "No clean minute-bar catalog entry or local clean minute dataset is available."
}
```

coverage 不足返回：

```json
{
  "dataset_id": "clean_minute_bar",
  "status": "blocked",
  "block_code": "CLEAN_MINUTE_BAR_COVERAGE_INSUFFICIENT",
  "coverage": {"start": "20250101", "end": "20250912"},
  "required": {"start": "20160104", "end": "20260531"}
}
```

## 9. Step3A 消费规则

Step3A 对分钟因子的流程：

1. 从 `factor_spec_master` 识别 `minute/high-frequency/price-volume` 需求。
2. 调用 Data API resolution：
   - `clean_daily_bar` 必须 ready。
   - `clean_minute_bar` 必须 ready。
   - 如需 `daily_basic`，也必须通过 Data API/catalog 证明。
3. 写入：
   - `data_prep_master.data_api_resolution`
   - `data_prep_master.local_input_paths`
   - `handoff_to_step4.local_input_paths`
4. 如果任何必需数据 blocked：
   - `data_prep_master.feasibility = "blocked"`
   - `handoff_to_step4.step3a_ready = false`
   - `handoff_to_step4.step3b_ready` 不得为 true
   - 不写可执行 snapshot

## 10. Step3B / Step4 执行规则

Step3B/Step4 不直接扫描 raw minute path。

它们只消费 Step3A 产物：

```text
objects/data_prep_master/data_prep_master__<report_id>.json
objects/data_prep_master/qlib_adapter_config__<report_id>.json
objects/handoff/handoff_to_step4__<report_id>.json
runs/<report_id>/step3a_local_inputs/minute_input__<report_id>.parquet
```

direct_code 必须接受 keyword interface：

```python
compute_factor(*, daily_df, minute_df=None)
```

不接受 `compute_factor(df)` 这种 positional-only 形式，因为它会掩盖 daily/minute 输入语义。

## 11. Builder 任务拆分

### P1. Raw Minute Sync

目标：把 S3 raw minute partitions 同步到本地/EC2 raw cache。

边界：不清洗，只同步和记录 source manifest。

验收：

- 指定日期范围内 raw partitions 存在。
- latest completed meta 可定位。

### P2. Clean Minute Layer Builder

目标：实现 `scripts/build_clean_minute_layer.py`。

边界：只生成 `clean_minute_bar` 数据产品和 metadata，不触发 factor run。

验收：

- schema/coverage/policy/quality/source/artifacts 完整。
- 主键去重、OHLC、排序、无效日策略可审计。

### P3. Catalog Registration

目标：把 `clean_minute_bar` 注册进 `$FACTORFORGE_ROOT/data/catalog/data_catalog.json`。

边界：catalog 只声明可用数据产品，不负责清洗。

验收：

- Data API describe/resolve 返回 ready。
- 缺失或 coverage 不足返回 structured blocker。

### P4. Step3A Integration

目标：分钟因子通过 Data API materialize report-scoped minute snapshot。

边界：Step3A 不扫描 raw path。

验收：

- ready path 写 snapshot。
- missing path BLOCK。
- validator 禁止 blocked + `step3b_ready=true`。

## 12. 当前状态

截至 2026-05-31：

- `clean_daily_bar` 已有当前后端和 Data API resolution。
- `clean_minute_bar` 架构已定义，但生产 builder/catalog 尚未完成。
- 当前代码对 `clean_minute_bar` 缺失返回 `CLEAN_MINUTE_BAR_MISSING`，不会静默假装可用。

因此：分钟数据不是“没有 raw”，而是尚未完成 clean data product 化。
