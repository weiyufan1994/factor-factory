# Phase R1 Step3 Daily Data API 计划书

> **执行对象:** Factor Factory coder thread
> **审查对象:** reviewer thread
> **架构依据:** `/Users/humphrey/projects/factor-factory/docs/operations/factorforge-step3-data-readiness-architecture.zh-CN.md`
> **目标:** 让 Step3A daily-only path 通过 Data API/catalog 解析 `clean_daily_bar`，不再依赖 `<artifact_root>/data/clean`。

## 1. 背景

当前 Mac 本地 Step3 能读到：

```text
/Users/humphrey/projects/factor-factory/data/clean/daily_clean.parquet
/Users/humphrey/projects/factor-factory/data/clean/daily_clean.meta.json
```

但 formal run 中 Step3A 会把 clean root 指向：

```text
<artifact_root>/data/clean
```

从而误报 `SHARED_CLEAN_DAILY_LAYER_MISSING`。S3 上已有 canonical clean daily，因此应改为 Data API/catalog-first resolution。

## 2. 修改范围

必须修改：

```text
factor_factory/data_api/*
skills/factor-forge-step3/scripts/run_step3.py
skills/factor-forge-step3/scripts/validate_step3.py
tests/test_step3a_data_api_integration.py
tests/test_data_api_catalog.py
```

按需修改：

```text
scripts/factorforge_data_api.py
scripts/update_clean_daily_bar_after_daily_update.py
docs/operations/factorforge-entrypoints.md
```

不修改：

```text
Step1/Step2 raw artifacts
Step3B direct_code generation
worker dispatch
minute data cleaning
```

## 3. 任务

### Task A: 定义 `clean_daily_bar` Data API resolution

Data API 必须能返回：

```json
{
  "status": "ready",
  "dataset_id": "clean_daily_bar",
  "source_uri": "s3://...",
  "schema": ["ts_code", "trade_date", "open", "high", "low", "close", "vol", "amount"],
  "coverage": {},
  "policy": {}
}
```

如果 catalog 缺失，返回 `catalog_missing`，不得 fallback 到 raw local path。

Data API resolver 必须位于 `factor_factory.data_api`，不得位于
`factor_factory.data_access.data_api`。`data_access` 可以继续服务 Step4
本地读写、date normalization 和 qlib adapter helper，但不能作为 Step3A
catalog resolver。

### Task B: Step3A daily-only path 使用 Data API

`run_step3.py` 的 daily-only path 应改为：

```text
derive required daily fields
resolve clean_daily_bar via Data API
materialize report-scoped daily_input parquet
write daily_filter_policy
write data_api_resolution
```

`data_sources` 可以继续记录 raw provenance，但 executable source 必须是 `clean_daily_bar`。

### Task C: artifact 写入

`data_prep_master` 必须包含：

```text
data_api_resolution.daily
daily_filter_policy
local_input_paths.snapshot_source=data_api
```

`qlib_adapter_config` 和 `handoff_to_step4` 必须写同一份 resolution 摘要或 ref。

## 4. 验收

### Ready path

```text
clean_daily_bar catalog present
validate_step3.py PASS
data_prep_master.feasibility=ready/proxy_ready
daily_filter_policy non-null
step3a_ready=true
step3b_ready=false before Step3B
```

### Blocked path

```text
catalog missing
feasibility=blocked
data_api_resolution.status=catalog_missing
objects/data_requirements/factorforge_data_requirement__<report_id>.json exists
step3a_ready=false
step3b_ready=false
```

## 5. 验证命令

```bash
python3 -m py_compile \
factor_factory/data_api/*.py \
  skills/factor-forge-step3/scripts/run_step3.py \
  skills/factor-forge-step3/scripts/validate_step3.py
```

```bash
uv run --no-project --with pytest --with pandas --with pyarrow python -m pytest \
  tests/test_data_api_catalog.py \
  tests/test_step3a_data_api_integration.py \
  -q
```

## 6. Reviewer 问题

1. 是否还存在 `<artifact_root>/data/clean` 缺失就直接 BLOCK daily-only factor 的 formal path？
2. 是否所有 daily ready artifact 都有 `daily_filter_policy`？
3. 是否 catalog missing 时没有 raw fallback？
4. 是否 Step3A ready 后仍保持 `step3b_ready=false`，等待 Step3B 自己证明？
