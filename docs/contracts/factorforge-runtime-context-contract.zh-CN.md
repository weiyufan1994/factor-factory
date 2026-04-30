# Factor Forge Runtime Context Contract v1

## 目标

所有 Step / Skill / Worker 都必须通过统一 runtime context 获取路径，不再在各自脚本里反复猜：

- `FACTORFORGE_ROOT`；
- EC2 legacy workspace；
- `objects/`；
- `runs/`；
- `evaluations/`；
- handoff / factor_values / branch result 的具体文件名。

这份 contract 的目的不是替换 Step1-6 的业务对象，而是提供一张统一地图。

## 标准 Python 接口

```python
from factor_factory.runtime_context import resolve_factorforge_context

ctx = resolve_factorforge_context()

ctx.factorforge_root
ctx.objects_root
ctx.runs_root
ctx.evaluations_root
ctx.archive_root
ctx.clean_data_root

ctx.object_path('handoff_to_step4', report_id)
ctx.object_path('factor_evaluation', report_id)
ctx.factor_values_path(report_id, 'parquet')
ctx.step3a_daily_input_path(report_id)
ctx.evaluation_payload_path(report_id, 'self_quant_analyzer')
ctx.search_branch_result_path(report_id, branch_id)
ctx.remap_legacy_path(raw_path)
```

## 标准 Manifest

任何 step 可以生成 manifest：

```bash
python3 scripts/build_factorforge_runtime_context.py --report-id <report_id> --write
```

输出位置：

```text
factorforge/objects/runtime_context/runtime_context__<report_id>.json
```

分支任务可以生成：

```bash
python3 scripts/build_factorforge_runtime_context.py --report-id <report_id> --branch-id <branch_id> --write
```

输出位置：

```text
factorforge/objects/runtime_context/runtime_context__<report_id>__<branch_id>.json
```

Manifest 现在包含四层：

- `objects`：canonical object artifact 路径，例如 `factor_spec_master`、`handoff_to_step4`、`factor_case_master`。
- `runs`：run-level artifact 路径，例如 `factor_values_parquet`、`step3a_daily_input_csv`、`run_metadata`。
- `evaluations`：Step4 backend payload 路径，例如 `self_quant_payload`、`qlib_backtest_payload`。
- `step_io`：按 Step3/4/5/6 展开的输入/输出清单。

## Step I/O 责任边界

从 v1.1 起，Factor Forge 的执行边界是：

- skill / agent / top-level orchestrator 负责寻找输入、确定输出、生成 manifest；
- step script 只消费 manifest 中给出的路径；
- step script 可以保留 `--report-id` 兼容旧流程，但这只是 fallback；
- 若 manifest 中已有路径，脚本不得再枚举候选目录或悄悄使用旧文件；
- backend worker 也必须继承同一个 manifest / `FACTORFORGE_ROOT`。

推荐执行方式：

```bash
python3 scripts/build_factorforge_runtime_context.py --report-id <report_id> --write
python3 skills/factor-forge-step3/scripts/run_step3.py --manifest factorforge/objects/runtime_context/runtime_context__<report_id>.json
python3 skills/factor-forge-step3/scripts/run_step3b.py --manifest factorforge/objects/runtime_context/runtime_context__<report_id>.json
python3 skills/factor-forge-step4/scripts/run_step4.py --manifest factorforge/objects/runtime_context/runtime_context__<report_id>.json
python3 skills/factor-forge-step5/scripts/run_step5.py --manifest factorforge/objects/runtime_context/runtime_context__<report_id>.json
python3 skills/factor-forge-step6/scripts/run_step6.py --manifest factorforge/objects/runtime_context/runtime_context__<report_id>.json
```

## 路径解析规则

1. 优先使用显式 `FACTORFORGE_ROOT`。
2. EC2 上若存在 `/home/ubuntu/.openclaw/workspace/factorforge`，使用该目录。
3. 否则使用当前 repo root 作为 local runtime root。
4. handoff 中可以保留相对路径，但 consumer 必须通过 `ctx.remap_legacy_path()` 解析。
5. 旧 EC2 绝对路径可以 remap 到当前 active `factorforge_root`。
6. 若 manifest 已提供路径，step worker 不应再自行枚举候选目录。

## JSON 写入规则

所有新 worker 应使用：

```python
from factor_factory.runtime_context import write_json_atomic, update_json_locked
```

要求：

- 普通对象写入用 atomic replace；
- shared ledger / task index / branch ledger 更新用 locked update；
- 不允许 `load -> modify -> write` 裸写共享 ledger。

## Step 间接口纪律

- Step1/2/3/4/5/6 的业务契约仍由各 step contract 决定；
- Runtime Context 只负责路径和 artifact locator；
- 不得在 Runtime Context 中塞业务判断；
- 不得让 worker 自己猜 data root 或 canonical artifact path；
- 若缺路径，应报明确的 missing artifact，而不是 silent fallback 到旧文件。

## 首批接入状态

已接入：

- `run_program_search_bayesian_worker.py`
- `run_step3.py`：支持 `--manifest`，Step3A 使用 manifest 指定的 root / clean data root。
- `run_step3b.py`：支持 `--manifest`，first-run 只生成 `factor_values` / `run_metadata`，不再调用 Step4。
- `validate_step3.py`：支持 `--manifest`。
- `validate_step3b.py`：支持 `--manifest`，并阻断 Step3B 越界生成 Step4-only artifacts。
- `run_step4.py`：支持 `--manifest`，并向内置/custom backend 传递同一个 manifest / `FACTORFORGE_ROOT`。
- `self_quant_adapter.py`：接受 Step4 传入的 `--manifest`。
- `qlib_backtest_adapter.py`：接受 Step4 传入的 `--manifest`。
- `run_step5.py`：支持 `--manifest`。
- `run_step6.py`：支持 `--manifest`。

待接入：

- `run_program_search_audit_worker.py`
- `record_search_branch_result.py`
- `prepare_approved_search_branch.py`
- Step1/2/3 validators

## 对 Bernard / Humphrey 的要求

以后新增 Factor Forge skill 或 worker 时：

1. 先读取 `factor_factory.runtime_context`；
2. 不要在脚本里新写一套 `LEGACY_WORKSPACE + FACTORFORGE_ROOT + candidates`；
3. 如果确实需要新 artifact 类型，先扩展 `FactorForgeContext.object_path()` 或新增专门 locator；
4. 修改 shared ledger 时必须使用 lock；
5. 自然语言回报里应说明使用了哪个 runtime root 和哪些 canonical paths。
