# Phase R Step3 数据就绪与执行闸门任务说明书

> **执行对象:** Factor Factory coder thread
> **审查对象:** reviewer thread
> **问题反馈:** `/Users/humphrey/projects/factor-factory/docs/operations/factorforge-step3-data-readiness-feedback-20260530.zh-CN.md`
> **架构依据:** `/Users/humphrey/projects/factor-factory/docs/operations/factorforge-step3-data-readiness-architecture.zh-CN.md`
> **目标:** 关闭 Step3A 数据解析、Step3 readiness gate、Step3B direct_code smoke、worker proof reporting 的控制面漏洞。

> **执行说明:** 本文件保留为 Phase R 总任务说明。实际落地拆成三份独立计划：
>
> 1. `phase-r1-step3-daily-data-api-task.zh-CN.md`：先修 daily `clean_daily_bar` Data API 和 Step3A daily path。
> 2. `phase-r2-clean-minute-bar-data-api-task.zh-CN.md`：单独建设 `clean_minute_bar` 数据产品和 Data API。
> 3. `phase-r3-step3-readiness-worker-proof-task.zh-CN.md`：修 readiness gate、Step3B direct_code smoke 和 worker proof reporting。
>
> 不要把 R1/R2/R3 合并成一个大补丁；分钟数据清洗尤其不能和当前 daily blocker 混在同一验收链里。

## 0. 当前 BLOCK 证据

当前 run：

```text
report_id = kaiyuan_20200516_amplitude_factor_hidden_structure
run_id    = 20260529T154706762813Z_kaiyuan_20200516_amplitude_factor_hidden_structure_step1_6d29236ea9d1
repo_sha  = 7909c7c0c543a6457d7eb7879025eb98e6db132d
```

已观察到：

```text
data_prep_master.feasibility = blocked
blocked_items[0].code = SHARED_CLEAN_DAILY_LAYER_MISSING
daily_filter_policy = null
handoff_to_step4.step3a_ready = false
handoff_to_step4.step3b_ready = true
ultimate_run_report.status = FAIL
failure.command = validate_step3b
```

Step3B 失败栈包含：

```text
TypeError: compute_factor() got an unexpected keyword argument 'daily_df'
polars.exceptions.ComputeError: UDF failed: sub operation not supported for dtypes `str` and `str`
```

同时 S3 canonical clean daily 和研究机 `daily_input.parquet` 实际存在，因此不能简单归因为“没有日线数据”。

## 1. 修改文件

必须修改：

```text
/Users/humphrey/projects/factor-factory/skills/factor-forge-step3/scripts/run_step3.py
/Users/humphrey/projects/factor-factory/skills/factor-forge-step3/scripts/validate_step3.py
/Users/humphrey/projects/factor-factory/skills/factor-forge-step3/scripts/run_step3b.py
/Users/humphrey/projects/factor-factory/skills/factor-forge-step3/scripts/validate_step3b.py
/Users/humphrey/projects/factor-factory/scripts/run_factorforge_ultimate.py
```

按需要修改：

```text
/Users/humphrey/projects/factor-factory/factor_factory/data_access/*
/Users/humphrey/projects/factor-factory/scripts/factorforge_data_api.py
/Users/humphrey/projects/factor-factory/tests/test_step3a_data_api_integration.py
/Users/humphrey/projects/factor-factory/tests/test_data_api_package.py
/Users/humphrey/projects/factor-factory/tests/test_data_api_catalog.py
```

不要修改：

```text
Step1 raw artifacts
Step2 raw artifacts
alpha_idea_master / factor_spec_master 手工内容
research worker production data
official library writeback
Step6 council prompt
```

## 2. Task A: Step3A 改为 Data API / catalog-first resolution

### 要求

在 `run_step3.py` 中新增或接入统一 resolution builder：

```python
def resolve_step3a_data_requirements(report_id: str, factor_spec_master: dict, sample_window: dict) -> dict:
    ...
```

必须优先通过 Data API 解析：

```text
clean_daily_bar
minute_bar, only if formula requires minute
daily_basic fields, only if formula requires valuation/basic fields
```

禁止在 formal run 中只因 `<artifact_root>/data/clean` 缺失就判定系统数据缺失。

### 输出 contract

`data_prep_master`、`qlib_adapter_config`、`handoff_to_step4` 都必须写入同一份 `data_api_resolution` 摘要。

`data_prep_master.daily_filter_policy` 必须来自 clean daily metadata 或 Data API dataset metadata。

### blocked 行为

如果 catalog missing 或 dataset missing：

```text
feasibility = blocked
data_api_resolution.status in {catalog_missing, blocked}
step3a_ready = false
step3b_ready = false
workflow_may_dispatch_worker = false
```

同时写：

```text
objects/data_requirements/factorforge_data_requirement__<report_id>.json
```

## 3. Task B: 修正 Step3 readiness gate

### 要求

`validate_step3.py` 必须拒绝：

```text
data_prep_master.feasibility=blocked
handoff.step3b_ready=true
```

并要求：

```text
handoff.step3a_ready == (feasibility in {"ready", "proxy_ready"})
handoff.step3b_ready == false before Step3B
```

如果 Step3B 已经产生 artifacts，validator 必须区分：

```text
step3a_validator
step3b_validator
```

不要让 Step3A validator 为 Step3B ready 背书。

### 验收反例

构造 artifact：

```json
{
  "data_prep_master": {"feasibility": "blocked"},
  "handoff_to_step4": {"step3a_ready": false, "step3b_ready": true}
}
```

`validate_step3.py` 必须 FAIL，错误 token 建议：

```text
BLOCK_STEP3_READY_STATE_CONTRADICTION
```

## 4. Task C: direct_code Step3B smoke 必须验证真实调用契约

### 要求

`validate_step3b.py` 不得只检查 source text 中有 `def compute_factor`。必须 import generated module 并检查：

1. `compute_factor` 存在；
2. signature 支持 declared input contract；
3. validator 只使用一种正式调用约定；
4. smoke fixture schema 覆盖 required fields；
5. 输出 schema 包含 `ts_code, trade_date, factor_value`；
6. warm-up 之后 `factor_value` 不得全 NaN；
7. key uniqueness 和 sortedness 合法。

对于 direct_code，推荐统一 entrypoint：

```python
def compute_factor(daily_df: pl.DataFrame, minute_df: pl.DataFrame | None = None) -> pl.DataFrame:
    ...
```

validator 应用 keyword 调用：

```python
compute_factor(daily_df=daily_input, minute_df=minute_input)
```

如果 Step2 code contract 不是这个签名，Step3B 必须生成 adapter wrapper 或 BLOCK，不能靠 try/except 轮流猜。

### 错误 token

建议新增：

```text
BLOCK_STEP3B_DIRECT_CODE_SIGNATURE_MISMATCH
BLOCK_STEP3B_DIRECT_CODE_REQUIRED_FIELDS_MISSING
BLOCK_STEP3B_DIRECT_CODE_SMOKE_FAILED
BLOCK_STEP3B_DIRECT_CODE_ALL_NULL_OUTPUT
BLOCK_STEP3B_DIRECT_CODE_UNCLEAN_INPUT_PROOF_MISSING
```

## 5. Task D: clean input proof gate

### 要求

如果 direct_code 包含以下模式：

```text
effective = np.ones(...)
assume all days are effective
```

或没有在代码内部执行停牌/一字涨跌停过滤，则 Step3B 必须要求 Step3A artifact 中存在：

```text
daily_filter_policy.drop_suspended = true
daily_filter_policy.drop_limit_events = true
local_input_paths.snapshot_source in {"data_api_clean_daily_bar", "shared_clean_daily_layer"}
```

缺失时 Step3B 必须 BLOCK，不得写 `step3b_ready=true`。

## 6. Task E: Ultimate wrapper 和 worker reporting 修正

### 要求

`run_factorforge_ultimate.py` 在进入 Step3B/4/5 前必须检查：

```text
step3a_ready == true
data_prep_master.feasibility in {"ready", "proxy_ready"}
workflow_may_dispatch_worker == true
```

如果 SSM command 被派发，汇报层必须读取：

```text
aws ssm get-command-invocation
ultimate_run_report__<report_id>.json
```

并将以下字段写入 final report：

```text
ssm_status
ssm_response_code
ultimate_status
failed_command
```

`send-command` 成功只能表示 dispatch accepted，不能表示 worker running 或 run success。

## 7. 测试要求

### 7.1 单元测试

新增或扩展：

```text
tests/test_step3a_data_api_integration.py
tests/test_data_api_package.py
tests/test_data_api_catalog.py
tests/test_step3_readiness_gate.py
tests/test_step3b_direct_code_contract.py
```

必须覆盖：

1. S3/catalog ready path；
2. catalog missing blocked path；
3. blocked + step3b_ready=true 反例；
4. direct_code signature mismatch；
5. direct_code all-null output；
6. direct_code clean input proof missing；
7. generated factor with warm-up NaN but后续非空的合法路径。

### 7.2 Wrapper smoke

必须跑：

```bash
python3 -m py_compile \
  skills/factor-forge-step3/scripts/run_step3.py \
  skills/factor-forge-step3/scripts/validate_step3.py \
  skills/factor-forge-step3/scripts/run_step3b.py \
  skills/factor-forge-step3/scripts/validate_step3b.py \
  scripts/run_factorforge_ultimate.py
```

必须跑 Data API 相关 pytest：

```bash
uv run --no-project --with pytest --with pandas --with pyarrow python -m pytest \
  tests/test_data_api_package.py \
  tests/test_data_api_catalog.py \
  tests/test_step3a_data_api_integration.py \
  tests/test_step3_readiness_gate.py \
  tests/test_step3b_direct_code_contract.py \
  -q
```

如本地缺 `uv` 或依赖，必须汇报未跑原因，不得声称通过。

## 8. 验收标准

### 必须 PASS

1. `data_api_resolution` 出现在 `data_prep_master`、`qlib_adapter_config`、`handoff_to_step4`。
2. `daily_filter_policy` 在 clean daily ready path 非空。
3. `feasibility=blocked` 时 `step3b_ready=false`。
4. Step3B direct_code signature mismatch 能被结构化 BLOCK。
5. direct_code 依赖 clean input 但缺 `daily_filter_policy` 时 BLOCK。
6. worker report 不再把 dispatch accepted 写成 RUNNING/SUCCESS。

### 必须不做

1. 不手工 patch 当前 run artifact。
2. 不复用旧失败 evidence 进入 Step6。
3. 不启动 worker 作为测试替代品。
4. 不修改 Step1/Step2 raw。
5. 不为了让 validator PASS 而删除 `blocked_items`。

## 9. Reviewer 检查问题

Reviewer 必须回答：

1. 是否还存在 `blocked + step3b_ready=true` 的路径？
2. 是否还存在本地 clean layer 缺失导致忽略 S3 catalog 的路径？
3. 是否所有 ready path 都有 `daily_filter_policy`？
4. 是否 direct_code smoke 只使用一个正式 entrypoint contract？
5. 是否 worker reporting 同时报告 SSM 和 ultimate report？
6. 是否当前修复不会改动 Step1/Step2 raw 或污染旧 run？

## 10. 推荐后续验证 run

修复通过后，建议不要在旧失败 artifact 上 hot patch。使用目标 HEAD 新开 formal run，至少执行：

```text
Step1 -> Step2 -> Step3A
```

只有当：

```text
Step3A feasibility ready/proxy_ready
daily_filter_policy non-null
step3a_ready true
step3b_ready false before Step3B
```

才允许启动最小 worker Step3B/Step4。Step5/Step6 仍需单独验收。
