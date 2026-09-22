# Phase R2 Clean Minute Bar + Data API 计划书

> **执行对象:** Factor Factory data/coder thread
> **审查对象:** reviewer thread
> **架构依据:** `/Users/humphrey/projects/factor-factory/docs/operations/factorforge-step3-data-readiness-architecture.zh-CN.md`
> **目标:** 建设 `clean_minute_bar` 数据产品和 Data API catalog entry，让分钟因子不再直接消费 raw minute path。

## 1. 背景

当前分钟数据还没有处理干净。Step3A 不应临时扫描：

```text
s3://yufan-data-lake/tushares/分钟数据/raw/stk_mins_1min/
```

或本地 raw minute cache 后直接给 worker 使用。分钟数据必须先形成 clean data product，再由 Data API 暴露。

## 2. 修改范围

新增或修改：

```text
scripts/build_clean_minute_layer.py
factor_factory/data_access/minute_policy.py
factor_factory/data_access/minute_layer.py
factor_factory/data_access/*
scripts/factorforge_data_api.py
tests/test_clean_minute_layer.py
tests/test_data_api_minute_catalog.py
```

按需修改：

```text
skills/factor-forge-step3/scripts/run_step3.py
skills/factor-forge-step3/scripts/validate_step3.py
```

不修改：

```text
Step1/Step2 raw artifacts
daily clean logic except shared helper reuse
Step4/5 backtest metrics
```

## 3. `clean_minute_bar` schema

最低字段：

```text
ts_code
trade_date
trade_time
bar_time
minute_index
open
high
low
close
vol
amount
```

推荐 metadata：

```text
rows
tickers
trade_dates
start
end
source_uri
source_hash
policy_hash
calendar_version
daily_alignment_dataset
```

## 4. minute clean policy

必须定义：

```json
{
  "session_filter": "cn_a_share_regular_session",
  "keep_sessions": ["09:30-11:30", "13:00-15:00"],
  "drop_zero_volume_bars": true,
  "drop_null_price_bars": true,
  "deduplicate_key": ["ts_code", "trade_date", "trade_time"],
  "trade_calendar_aligned": true,
  "daily_clean_universe_aligned": true,
  "limit_event_handling": "inherit_daily_clean_bar_flag_or_drop_day",
  "missing_minute_policy": "mark_and_report_no_forward_fill"
}
```

禁止默认 forward-fill 缺失分钟。

## 5. Data API behavior

`clean_minute_bar` ready 时返回：

```json
{
  "status": "ready",
  "dataset_id": "clean_minute_bar",
  "source_uri": "s3://...",
  "schema": ["ts_code", "trade_date", "trade_time", "..."],
  "coverage": {},
  "policy": {}
}
```

未 ready 时返回：

```json
{
  "status": "blocked",
  "dataset_id": "clean_minute_bar",
  "blocked_reason": "CLEAN_MINUTE_BAR_MISSING"
}
```

Step3A 必须在分钟因子遇到 `CLEAN_MINUTE_BAR_MISSING` 时 BLOCK，不得 raw fallback。

## 6. 验收

### Clean job

```text
build_clean_minute_layer.py writes parquet + meta
meta contains policy
duplicate key count = 0
regular session filter applied
missing minute report emitted
```

### Data API

```text
factorforge_data_api.py describe clean_minute_bar
factorforge_data_api.py sample clean_minute_bar --start ... --end ...
```

### Step3A blocked-before-ready

如果 catalog 没有 `clean_minute_bar`：

```text
minute factor feasibility=blocked
blocked_items includes CLEAN_MINUTE_BAR_MISSING
step3a_ready=false
step3b_ready=false
```

## 7. 验证命令

```bash
python3 -m py_compile \
  scripts/build_clean_minute_layer.py \
  factor_factory/data_access/minute_policy.py \
  factor_factory/data_access/minute_layer.py
```

```bash
uv run --no-project --with pytest --with pandas --with pyarrow python -m pytest \
  tests/test_clean_minute_layer.py \
  tests/test_data_api_minute_catalog.py \
  -q
```

## 8. Reviewer 问题

1. 是否还有 Step3A 直接消费 raw minute 的 formal path？
2. 缺失分钟是否被报告而不是 forward-fill？
3. minute clean 是否与 daily clean universe/calendar 对齐？
4. `clean_minute_bar` 未 ready 时，worker 是否绝不会启动？
