# Factor Forge Step3 Law 隔离 / Qlib Adapter / 知识沉淀反馈

日期：2026-06-11

反馈对象：Factor Forge 架构师 / coder

范围：框架问题反馈，不评价 V17 因子有效性；不涉及 clean data、search_worker、official promotion。

## 结论

本轮 V17 研究暴露出三个长期框架问题：

1. Step3B direct-code law 版本都堆在中央 runner，导致研究迭代污染 `run_step3b.py`，版本控制和 code review 成本过高。
2. Qlib provider/Data API 已 ready，但 direct-code child 没有生成 `qlib_adapter_config__<report_id>.json`，导致 qlib backend 仍失败。
3. run 停在 `awaiting_main_agent_mechanism_memo` 时，没有写 durable research note / knowledge record，不能保证“每轮研究都沉淀”。

这三个问题都属于 Factor Forge 框架/合同问题，不是单个 V17 因子公式问题。

## P1. Step3B law 实现需要从 runner 中隔离

### 现象

当前本地 dirty tree 中，`skills/factor-forge-step3/scripts/run_step3b.py` 的 diff 非常大。原因不是每次运行 Step3 自动污染，而是 V9-V17 等 moneyflow direct-code law 都直接写进中央 runner。

观察到的状态：

```text
skills/factor-forge-step3/scripts/run_step3b.py    2108+ lines diff
```

同时 dirty tree 横跨 Step3/4/5/6、Ultimate、Data API adapter、docs、knowledge、research scripts，说明当前工作树混有框架改动、研究 law 改动和文档沉淀。

### 判断

不建议把整个 `run_step3.py` 复制成多个版本。这样会复制 pipeline 语义，反而让 Step3A/Step3B contract 分叉。

更合理的边界是：

- `run_step3.py` / `run_step3b.py` 作为稳定 engine / template；
- factor-specific direct-code law 拆到独立版本化模块；
- runner 只负责读取 executable spec、定位 law、调用 adapter；
- 每个 law 由 `law_id + code_law_hash` 唯一标识；
- 旧 law append-only，不允许为了新实验直接修改旧 law。

### 建议设计

建议新增类似结构：

```text
factor_factory/factor_laws/
  moneyflow/
    __init__.py
    miller_v09.py
    miller_v11.py
    miller_v15.py
    miller_v17.py
    registry.py
```

或放在 skill 内：

```text
skills/factor-forge-step3/laws/
  moneyflow/
    miller_v15.py
    miller_v17.py
    registry.py
```

`run_step3b.py` 只保留：

```text
law_id -> import law module -> get adapter/source/contract -> execute
```

### 验收条件

- 新增 V18/V19 law 时，不需要修改 `run_step3.py`。
- 新增 V18/V19 law 时，`run_step3b.py` diff 应很小，最好只改 registry 或无需改 runner。
- executable spec 中写入：
  - `law_id`
  - `law_module`
  - `code_law_hash`
  - `source_orchestrator_synthesis_path/hash`
- child materialization 后，old law hash 和 new law hash 可追溯。
- smoke 覆盖：
  - direct-code child law import
  - missing law id BLOCK
  - law hash mismatch BLOCK
  - old law append-only regression

## P1. direct-code child qlib adapter config 缺失

### 现象

V17 的 qlib backend 失败，但失败不是 Data API / qlib provider readiness。

真实 worker 上的 V17 qlib payload：

```json
{
  "backend": "qlib_backtest",
  "status": "failed",
  "failure_reason": "missing required qlib inputs",
  "missing_paths": [
    "/home/ubuntu/.openclaw/workspace/factorforge/objects/data_prep_master/qlib_adapter_config__ORIG_INTRADAY_FLOW_SP3_DRIFT_MINUS_NOISE_20__a__a__16115b__28__V17_BENCH_REL_REPAIR_20260610.json"
  ],
  "qlib_preflight": {
    "provider_present": true,
    "qlib_import_ok": true,
    "native_attempted": true,
    "status": "ready"
  }
}
```

同时 ultimate run report 显示：

```text
expected_artifacts_after.objects.qlib_adapter_config.exists=false
expected_artifacts_after.step_io.step3.outputs.qlib_adapter_config.exists=false
```

handoff 中却引用了：

```text
qlib_adapter_config_ref =
qlib_adapter_config__ORIG_INTRADAY_FLOW_SP3_DRIFT_MINUS_NOISE_20__a__a__16115b__28__V17_BENCH_REL_REPAIR_20260610.json
```

### 判断

Data API / qlib provider 已经 ready；这次 qlib failed 是 Factor Forge child artifact 产物合同缺口。

direct-code / minute-derived child 如果声明 qlib backend 可运行，就必须生成或继承 child-local qlib adapter config。否则应该明确标记为 `not_applicable`，不能让 qlib backend 以 `failed` 形式污染研究结论。

### 建议改法

在 Step3A / Step3B / child materialization 之间补一个硬合同：

1. 如果 `handoff_to_step4.qlib_adapter_config_ref` 存在，则对应文件必须存在。
2. direct-code child materialization 必须：
   - 从 parent 复制 qlib adapter config 并替换 report_id / paths；或
   - 基于 child `data_prep_master` 重新生成 qlib adapter config；或
   - 明确写 `qlib_native_status=not_applicable` 和原因。
3. Step4 qlib backend 对缺 config 的处理应区分：
   - provider not ready
   - qlib import failed
   - adapter config missing
   - direct-code law unsupported by qlib

### 验收条件

- direct-code child run 后，以下文件存在：

```text
objects/data_prep_master/qlib_adapter_config__<child_report_id>.json
```

- 该文件内部 `report_id == <child_report_id>`。
- handoff 引用的 `qlib_adapter_config_ref` 与实际文件一致。
- 如果 direct-code law 不能转成 qlib expression，backend status 应为：

```text
qlib_native_status=not_applicable
reason=direct_code_derived_state_not_supported_by_qlib
```

而不是：

```text
qlib_native_status=failed
failure_reason=missing required qlib inputs
```

- smoke 覆盖：
  - direct-code child qlib config generated/copied
  - handoff ref resolves
  - qlib provider ready + missing config must BLOCK before Step4 backend attempt
  - unsupported direct-code law produces `not_applicable`

## P2. paused run 没有 durable knowledge writeback

### 现象

V17 最终停在：

```text
final_outcome=awaiting_main_agent_mechanism_memo
status=PAUSED
```

worker 上没有生成：

```text
objects/research_iteration_master/loop_research_brief__<V17>__iter1.json
objects/research_knowledge_base/knowledge_record__<V17>.json
```

这意味着当前不能说“每轮研究都已经沉淀到知识库”。只有正式 Step6 闭环后，才会写完整 `loop_research_brief` / `knowledge_record`。

### 判断

`awaiting_main_agent_mechanism_memo` 是正常暂停点，但它仍然包含有价值的研究证据：

- current law id
- parent law id
- Step4/5 metrics
- qlib failure reason
- long-side / IC / cost / drawdown evidence
- next mechanism memo questions

这些信息不应只停留在 runtime artifacts 中，否则下一轮 agent 可能重复走旧路。

### 建议改法

新增 paused-run 轻量沉淀合同：

```text
objects/research_iteration_master/paused_research_note__<report_id>.json
objects/research_iteration_master/paused_research_note__<report_id>.md
```

当 loop 停在以下状态时也要写：

```text
awaiting_main_agent_mechanism_memo
awaiting_agent_results
awaiting_main_agent_council_synthesis
awaiting_next_derivation
```

paused note 不等同于正式 factor library entry，但必须被下一轮 `prior_revision_memory` / retrieval index 读取。

### paused note 最小字段

```json
{
  "report_id": "...",
  "parent_report_id": "...",
  "status": "awaiting_main_agent_mechanism_memo",
  "law_id": "...",
  "parent_law_id": "...",
  "formula_or_code_law_hash": "...",
  "core_metrics": {
    "rank_ic_mean": 0.0,
    "rank_ic_ir": 0.0,
    "long_side_annual_return": 0.0,
    "max_drawdown": 0.0,
    "recovery_days": 0,
    "cost_adjusted_annual_return": 0.0
  },
  "backend_status": {
    "self_quant": "pass",
    "qlib_native": "failed/not_applicable/pass"
  },
  "failure_or_pause_reason": "...",
  "research_lessons": [],
  "next_questions": []
}
```

### 验收条件

- V17 类 paused run 结束时，生成 paused note。
- paused note 被 retrieval index 或 next Council packet 引用。
- 正式 Step6 完成后，paused note 可升级/合并到：

```text
loop_research_brief
research_knowledge_base/knowledge_record
knowledge/因子工厂/研究迭代/
```

- smoke 覆盖：
  - paused run writes note
  - note contains core metrics and backend status
  - next run prior memory can read paused note

## 附：本轮确认过的边界

- 没有启动 clean data。
- 没有启动 search_worker。
- 没有 official promotion。
- 没有清理或回滚 dirty tree。
- 没有把 V17 因子结论写入正式因子库。
- 本反馈只针对框架合同与版本治理。

## 建议优先级

1. 先修 P1 qlib adapter config 缺口，避免 qlib failed 继续误导研究判断。
2. 再修 P1 Step3B law isolation，避免后续 V18/V19 继续污染中央 runner。
3. 最后补 P2 paused-run research note，保证每轮都有最低限度知识沉淀。

