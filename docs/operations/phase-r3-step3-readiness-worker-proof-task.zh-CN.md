# Phase R3 Step3 Readiness Gate 与 Worker Proof 计划书

> **执行对象:** Factor Factory coder thread
> **审查对象:** reviewer thread
> **架构依据:** `/Users/humphrey/projects/factor-factory/docs/operations/factorforge-step3-data-readiness-architecture.zh-CN.md`
> **目标:** 修复 `blocked + step3b_ready=true`、Step3B direct_code smoke、ultimate/worker 汇报不可信的问题。

## 1. 背景

当前已观察到：

```text
data_prep_master.feasibility=blocked
handoff_to_step4.step3a_ready=false
handoff_to_step4.step3b_ready=true
```

并且 Humphrey 曾把 failed SSM command 汇报成 RUNNING。Step3 必须把 readiness 和 worker proof 收紧。

## 2. 修改范围

必须修改：

```text
skills/factor-forge-step3/scripts/validate_step3.py
skills/factor-forge-step3/scripts/run_step3b.py
skills/factor-forge-step3/scripts/validate_step3b.py
scripts/run_factorforge_ultimate.py
```

按需修改：

```text
skills/factor-forge-step3/scripts/run_step3.py
tests/test_step3_readiness_gate.py
tests/test_step3b_direct_code_contract.py
tests/test_factorforge_ultimate_worker_reporting.py
```

不修改：

```text
Data clean products
Step1/Step2 raw artifacts
Step6 council prompt
```

## 3. Readiness gate

`validate_step3.py` 必须强制：

```text
handoff.step3a_ready == (data_prep_master.feasibility in {"ready", "proxy_ready"})
```

Step3A validator 阶段：

```text
step3b_ready must be false
workflow_may_dispatch_worker must be false
```

Step3B validator PASS 后才允许：

```text
step3b_ready=true
workflow_may_dispatch_worker=true
```

错误 token：

```text
BLOCK_STEP3_READY_STATE_CONTRADICTION
```

## 4. Direct_code smoke

`validate_step3b.py` 必须 import generated module 并使用唯一正式调用方式：

```python
compute_factor(daily_df=daily_input, minute_df=minute_input)
```

必须检查：

1. entrypoint 存在；
2. signature 支持正式调用；
3. required fields 存在；
4. 输出 schema 合法；
5. warm-up 后 `factor_value` 非全 NaN；
6. key uniqueness 合法；
7. dtype 错误被结构化 BLOCK，不只抛 traceback。

错误 token：

```text
BLOCK_STEP3B_DIRECT_CODE_SIGNATURE_MISMATCH
BLOCK_STEP3B_DIRECT_CODE_REQUIRED_FIELDS_MISSING
BLOCK_STEP3B_DIRECT_CODE_SMOKE_FAILED
BLOCK_STEP3B_DIRECT_CODE_ALL_NULL_OUTPUT
```

## 5. Clean input proof gate

如果 generated direct_code 不在代码内部处理有效交易日，而依赖输入已经清洗，则 Step3B 必须要求：

```text
data_prep_master.daily_filter_policy.drop_suspended=true
data_prep_master.daily_filter_policy.drop_limit_events=true
local_input_paths.snapshot_source=data_api
```

缺失时 BLOCK：

```text
BLOCK_STEP3B_DIRECT_CODE_UNCLEAN_INPUT_PROOF_MISSING
```

## 6. Ultimate / worker reporting

`run_factorforge_ultimate.py` 进入 worker/Step4/5 前必须检查：

```text
step3a_ready=true
step3b_ready=true
workflow_may_dispatch_worker=true
```

worker 汇报必须记录：

```text
ssm_command_id
instance_id
SSM Status
ResponseCode
ultimate_run_report.status
failed_command
artifact_ready
```

禁止把 `send-command` accepted 写成 RUNNING/SUCCESS。

## 7. 验收

### Contradiction fixture

```text
feasibility=blocked
step3a_ready=false
step3b_ready=true
```

必须 FAIL。

### Direct_code signature fixture

`compute_factor(df)` 不支持 `daily_df=` keyword 时必须 FAIL，并给结构化 token。

### Worker reporting fixture

模拟 SSM Failed：

```text
Status=Failed
ResponseCode=1
```

汇报不得出现 RUNNING/SUCCESS。

## 8. 验证命令

```bash
python3 -m py_compile \
  skills/factor-forge-step3/scripts/validate_step3.py \
  skills/factor-forge-step3/scripts/run_step3b.py \
  skills/factor-forge-step3/scripts/validate_step3b.py \
  scripts/run_factorforge_ultimate.py
```

```bash
uv run --no-project --with pytest --with pandas --with pyarrow python -m pytest \
  tests/test_step3_readiness_gate.py \
  tests/test_step3b_direct_code_contract.py \
  tests/test_factorforge_ultimate_worker_reporting.py \
  -q
```

## 9. Reviewer 问题

1. 是否所有 `blocked + step3b_ready=true` 都会 FAIL？
2. Step3B 是否只用一个正式 direct_code 调用约定？
3. clean input proof 缺失时是否会 BLOCK？
4. SSM failed 是否仍可能被汇报成 running/success？
5. Step4/5 是否只能消费 `ultimate_run_report.status=PASS` 的 execution evidence？
