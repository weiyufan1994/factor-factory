# Factor Forge Step3 数据产品、Data API 与执行闸门架构书

> **状态:** 待实现
> **版本:** v2 / 2026-05-31
> **范围:** daily/minute clean data product、Data API/catalog、Step3A data resolution、Step3B direct_code smoke、worker proof reporting、Mac/Humphrey/research-worker 同步边界。
> **非范围:** Step1 raw 生成、Step2 LLM 原始输出修补、Step4/5 指标体系重写、Step6 council prompt 改造、official library promotion。

## 1. 背景

当前 Step3 的实现和目标架构不一致：

1. Skill 文档写着 `Data/API preparation`，但实际 `run_step3.py` 仍主要通过 `factor_factory.data_access.clean_layer` 查本地 shared clean layer。
2. Mac 本地因为 `/Users/humphrey/projects/factor-factory/data/clean/daily_clean.parquet` 存在，所以 Step3A 容易“看起来正常”。
3. Formal run / Humphrey / research worker 下，runtime manifest 会把 clean root 指向 `<artifact_root>/data/clean`，如果该目录没有 materialized clean layer，就误报 `SHARED_CLEAN_DAILY_LAYER_MISSING`。
4. S3 上 canonical daily clean 数据存在，但 Step3A 没有通过 Data API/catalog-first resolution 去证明它存在、可用、可 materialize。
5. 分钟数据还没有独立 clean product，Step3A 不应扫描 raw minute 路径后直接给 worker 使用。

因此，本架构要把问题拆成四层：

```text
raw data
-> clean data products
-> Data API / catalog resolution
-> Step3A report-scoped materialization
-> Step3B/Step4 worker execution
```

Step3A 是 clean data product 的消费者，不是全量数据清洗器。

## 2. 设计目标

Factor Forge 的数据入口必须满足：

1. Mac、本地 Humphrey、research worker 使用同一套 repo 代码和同一套 Data API contract。
2. 日线数据走 `clean_daily_bar`，不再由 Step3A 直接猜本地路径。
3. 分钟数据先形成 `clean_minute_bar` 数据产品，再暴露给 Data API；未完成前，分钟因子必须 BLOCK，而不是 raw fallback。
4. Step3A artifact 必须证明：
   - 用了哪个 dataset；
   - 数据从哪里来；
   - schema 是什么；
   - coverage 是什么；
   - clean/filter policy 是什么；
   - materialized snapshot 在哪里。
5. Step3B/worker 只能在 Step3A readiness proof 完整时启动。

## 3. 总体架构

```text
Tushare / raw S3
  |
  |-- scripts/build_clean_daily_layer.py
  |       -> clean_daily_bar
  |       -> daily_filter_policy
  |       -> catalog entry
  |
  |-- scripts/build_clean_minute_layer.py
          -> clean_minute_bar
          -> minute_filter_policy
          -> catalog entry

catalog / Data API
  |
  |-- DataApiClient.resolve(clean_daily_bar)
  |-- DataApiClient.resolve(clean_minute_bar)
  |-- DataApiClient.materialize(report_id, window, fields)

Step3A
  |
  |-- writes data_prep_master
  |-- writes qlib_adapter_config
  |-- writes data_requirement when blocked
  |-- writes handoff_to_step4 with readiness flags

Step3B
  |
  |-- requires step3a_ready=true
  |-- imports/smokes generated code
  |-- writes implementation artifacts and first factor values only after smoke PASS

Step4/5/6
  |
  |-- consume only successful proof chain
```

## 4. 数据产品边界

### 4.1 `clean_daily_bar`

`clean_daily_bar` 是正式日线数据产品。它不是每个 run 临时生成的文件，而是共享、可 catalog 化的数据层。

最低 schema：

```text
ts_code
trade_date
open
high
low
close
pre_close
change
pct_chg
vol
amount
```

可扩展字段：

```text
turnover_rate
turnover_rate_f
volume_ratio
pe
pe_ttm
pb
ps
total_mv
circ_mv
free_float_mcap
industry_code
```

必须记录 `daily_filter_policy`：

```json
{
  "adjust_mode": "forward",
  "drop_bj": true,
  "drop_st": true,
  "min_listing_days": 60,
  "drop_suspended": true,
  "drop_limit_events": true,
  "drop_abnormal_pct_move": true,
  "limit_tolerance_ratio": 0.003
}
```

如果 direct_code 依赖“输入侧已剔除停牌/一字涨跌停”，这个 policy 是必要证明，不是可选说明。

### 4.2 `clean_minute_bar`

`clean_minute_bar` 是独立二期数据产品。它不能由 Step3A 临时扫描 raw minute path 代替。

最低 schema：

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

必须定义 `minute_filter_policy`：

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

关键原则：

- 缺失分钟不得默认 forward-fill。
- raw minute 只能作为 clean job 输入，不能作为 Step3A formal execution snapshot。
- 如果 `clean_minute_bar` 未 catalog ready，分钟因子应写 data requirement 并 BLOCK。

## 5. Data API contract

### 5.1 Dataset ids

标准 dataset id：

```text
clean_daily_bar
clean_minute_bar
daily_basic_bar
trade_calendar
industry_classification
```

Step3A 不应再写死：

```text
s3://yufan-data-lake/tushares/行情数据/daily.csv
s3://yufan-data-lake/tushares/分钟数据/raw/stk_mins_1min/
```

这些可以作为 raw source metadata，但不能作为 Step3A executable source。

### 5.2 Resolution object

Data API 返回结构：

```json
{
  "status": "ready | proxy_ready | blocked | catalog_missing",
  "dataset_id": "clean_daily_bar",
  "source_uri": "s3://...",
  "local_materialized_path": "...",
  "schema": ["ts_code", "trade_date", "open", "high", "low", "close"],
  "coverage": {
    "start": "YYYYMMDD",
    "end": "YYYYMMDD",
    "row_count": 0,
    "ticker_count": 0,
    "trade_date_count": 0
  },
  "policy": {},
  "identity": {
    "dataset_version": "v1",
    "content_hash": "...",
    "catalog_hash": "..."
  },
  "blocked_reason": null
}
```

### 5.3 Resolution order

```text
FACTORFORGE_DATA_CATALOG
-> $FACTORFORGE_ROOT/data/catalog/data_catalog.json
-> blocked + data requirement artifact
```

如果 catalog 缺失，不允许 Step3A 搜索本地 raw path 并伪装 ready。

### 5.4 Package boundary

Data API 是独立数据产品边界。Factor Forge 只能作为 consumer：

```text
from factor_factory.data_api import DataApiClient, resolve_data_api_dataset
```

允许：

```text
Step3A -> resolve clean_daily_bar / clean_minute_bar
Step3A -> read Data API 返回的 published parquet path
Step3A -> materialize report-scoped input slice
```

禁止：

```text
Step3A -> resolve_clean_daily_layer_paths()
Step3A -> clean_daily_layer_ready() 后自行 fallback
Step3A -> build_clean_daily_layer.py
Step3A -> raw daily/minute path guessing and cleaning
```

`factor_factory.data_access` 仍可保留 Step4/qlib/legacy local reader helper，但不得承载 Data API catalog resolver。

## 6. Step3A contract

Step3A 的职责是把 `factor_spec_master` 的数据需求转成 Data API query，然后 materialize report-scoped snapshot。

### 6.1 Daily-only factor

```text
factor_spec_master.required_inputs includes high/low/close/vol...
-> resolve clean_daily_bar
-> materialize runs/<report_id>/step3a_local_inputs/daily_input__<report_id>.parquet
-> write daily_filter_policy
-> step3a_ready=true
```

### 6.2 Minute factor

```text
factor_spec_master requires minute/trade_time/bar_time/minute_index
-> resolve clean_minute_bar
-> resolve clean_daily_bar if daily alignment is required
-> materialize minute_input + daily_input
-> write minute_filter_policy + daily_filter_policy
-> step3a_ready=true
```

如果 `clean_minute_bar` 不存在：

```text
feasibility=blocked
data_api_resolution.status=blocked
blocked_items includes CLEAN_MINUTE_BAR_MISSING
step3a_ready=false
step3b_ready=false
workflow_may_dispatch_worker=false
```

## 7. Artifact contract

### 7.1 `data_prep_master`

```json
{
  "report_id": "...",
  "feasibility": "ready | proxy_ready | blocked",
  "data_api_resolution": {
    "daily": {},
    "minute": null
  },
  "daily_filter_policy": {},
  "minute_filter_policy": null,
  "local_input_paths": {
    "input_mode": "daily_only | minute_plus_daily",
    "daily_df_parquet": "...",
    "minute_df_parquet": null,
    "snapshot_source": "data_api"
  },
  "blocked_items": []
}
```

### 7.2 `qlib_adapter_config`

```json
{
  "normalized_datasets": ["clean_daily_bar"],
  "instrument_field": "ts_code",
  "date_field": "trade_date",
  "qlib_field_map": {
    "$open": "open",
    "$high": "high",
    "$low": "low",
    "$close": "close",
    "$volume": "vol",
    "$amount": "amount"
  },
  "data_api_resolution": {}
}
```

### 7.3 `handoff_to_step4`

Before Step3B:

```json
{
  "step3a_ready": true,
  "step3b_ready": false,
  "workflow_may_dispatch_worker": false
}
```

After Step3B smoke PASS:

```json
{
  "step3a_ready": true,
  "step3b_ready": true,
  "workflow_may_dispatch_worker": true,
  "factor_impl_stub_ref": "...",
  "first_run_factor_values_ref": "..."
}
```

Blocked:

```json
{
  "step3a_ready": false,
  "step3b_ready": false,
  "workflow_may_dispatch_worker": false,
  "blocked_items": [...]
}
```

`blocked + step3b_ready=true` 是 hard fail。

## 8. Step3B contract

Step3B 只能在 Step3A ready 后运行。

必须验证：

1. `data_prep_master.feasibility in {"ready", "proxy_ready"}`；
2. `handoff.step3a_ready=true`；
3. executable snapshot path exists；
4. direct_code entrypoint signature 与 contract 一致；
5. fixture smoke 使用同一正式调用约定；
6. rolling-window 因子允许 warm-up NaN，但 warm-up 后不能全 NaN；
7. 输出 key 合法。

推荐 direct_code entrypoint：

```python
def compute_factor(daily_df: pl.DataFrame, minute_df: pl.DataFrame | None = None) -> pl.DataFrame:
    ...
```

validator 不应靠多轮 try/except 猜调用方式。

## 9. Worker proof reporting

任何 worker command 汇报必须同时包含：

```text
ssm_command_id
instance_id
SSM Status
ResponseCode
started_at / finished_at
ultimate_run_report.status
failed_command
artifact_ready
next_allowed_step
```

`send-command` 成功只能说明 AWS 接受了命令，不能说明 worker 正在运行，更不能说明研究完成。

## 10. Mac / Humphrey / research worker 同步边界

修改必须先进入 repo，再同步到远端：

```text
Mac local repo
-> GitHub main
-> Humphrey EC2 production checkout
-> research worker production checkout
```

不允许：

- 只在 Humphrey hot patch；
- 只在 Mac 本地修 skill；
- worker 上临时改 generated artifact；
- 修改 Step1/Step2 raw JSON。

允许保留 Humphrey-specific ops config，但 production repo code 必须对齐目标 SHA。

## 11. 实施计划拆分

本架构拆成三份独立计划书：

1. `phase-r1-step3-daily-data-api-task.zh-CN.md`
   先解决日线 `clean_daily_bar` 进入 Data API 和 Step3A，关闭当前 `SHARED_CLEAN_DAILY_LAYER_MISSING` 误判。

2. `phase-r2-clean-minute-bar-data-api-task.zh-CN.md`
   单独建设 `clean_minute_bar` 数据产品和 catalog，不与 Step3A readiness gate 混在一个补丁。

3. `phase-r3-step3-readiness-worker-proof-task.zh-CN.md`
   修 Step3 readiness gate、Step3B direct_code smoke、ultimate/worker proof reporting。

## 12. 验收顺序

推荐顺序：

```text
R1 daily Data API
-> R3 readiness / worker proof
-> fresh daily-only formal Step3A smoke
-> R2 clean minute bar
-> minute-factor formal smoke
```

原因：

- 当前 blocker 是 daily path，不需要等分钟数据清洗完成。
- readiness gate 必须尽早修，避免任何 blocked artifact 继续进入 worker。
- 分钟数据清洗 blast radius 大，应单独验收。

## 13. 成功标准

### Daily ready path

```text
data_api_resolution.daily.status=ready
data_prep_master.daily_filter_policy non-null
local_input_paths.snapshot_source=data_api
handoff.step3a_ready=true
handoff.step3b_ready=false before Step3B
validate_step3.py PASS
```

### Minute blocked path before R2

```text
clean_minute_bar not ready
minute factor Step3A writes CLEAN_MINUTE_BAR_MISSING
step3a_ready=false
step3b_ready=false
worker not dispatched
```

### Worker proof path

```text
SSM Status=Success
ResponseCode=0
ultimate_run_report.status=PASS
Step3B validator PASS
Step4/5 artifacts ready only after successful execution
```

### Failure path

任何以下情况必须 BLOCK：

```text
blocked + step3b_ready=true
daily_filter_policy=null for clean-input-dependent direct_code
direct_code signature mismatch
factor_value all null after warm-up
SSM Failed but reported RUNNING/SUCCESS
```
