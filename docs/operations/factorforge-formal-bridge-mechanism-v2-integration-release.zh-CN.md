# Factor Forge Formal Bridge 与 Mechanism Math v2 集成发布架构

日期：2026-05-25

## 目标

本文档定义 RTA-16/RTA-17 repo-side formal LLM bridge 与 RTA-18
`mechanism_math_contract_v2` 的集成、发布和任务分工边界。

核心目标是让新研报正式入口从 PDF / manifest 出发，先在主机侧生成并验证
Step1、Step2、Step3A formal artifacts，再允许上层 workflow 启动研究机执行
Step3B/Step4。任何 Step1/2/3A formal artifact 不完整、schema 不合格、或
mechanism math v2 合同不合格时，都必须 BLOCK，不能生成 runtime context，
不能同步坏 artifact 到 worker，也不能声称 worker 已经开始运行。

## 当前状态

### RTA-16/RTA-17：formal LLM bridge repo-side contract

程序员2号已完成 scoped commit：

```text
e475e41 Add formal LLM bridge contracts
```

该 commit 范围限定为 bridge / report / docs / smoke，不包含
`mechanism_math_v2` dirty worktree 改动。它覆盖：

- Step1 bridge provider missing -> `BLOCK_STEP1_LLM_PROVIDER_UNAVAILABLE`
- Step1 fixture raw outputs，只用于 smoke，必须标记 `fixture_only=true`
  和 `formal_llm_extraction=false`
- Step1 command provider 接口：stdin 接收 prompt/context/provenance JSON，
  stdout 返回 raw JSON
- Step2 bridge provider missing -> `BLOCK_STEP2_LLM_PROVIDER_UNAVAILABLE`
- Step2 必须依赖 Step1 raw LLM 三件套，不能只依赖 `alpha_idea_master`
- Step2 fixture raw outputs，只用于 smoke
- prepare report dispatch 字段语义：
  - `formal_artifacts_valid`
  - `workflow_may_dispatch_worker`
  - `worker_started=false`
  - `worker_dispatch_status=not_dispatched_by_prepare`
- formal LLM bridge smoke PASS，且不生成 runtime context，不启动 worker

Scoped 验证门禁：

```bash
git diff --check
python3 -m py_compile \
  scripts/run_factorforge_step1_llm_bridge.py \
  scripts/run_factorforge_step2_llm_bridge.py \
  scripts/prepare_factorforge_formal_artifacts.py \
  scripts/run_factorforge_formal_llm_bridge_smoke.py

python3 scripts/run_factorforge_formal_llm_bridge_smoke.py \
  --fresh \
  --root /tmp/factorforge_formal_llm_bridge_post_commit
```

期望：

```text
verdict=ACCEPT
runtime_context_written=false
worker_started=false
```

### RTA-18：primary mechanism model 与 stochastic price-process projection

程序员1号已完成 `mechanism_math_contract_v2` 主体工作，并通过 reviewer closure。
当前本地 broader formal artifact smoke 仍可能被一个 unrelated dirty blocker 阻断：

```text
BLOCK_MECHANISM_MATH_V2_FORMULA_MAPPING_SELF_REFERENTIAL
```

这个 blocker 属于 RTA-18 机制数学合同，不属于 RTA-16/RTA-17 bridge commit。
它必须由 RTA-18 owner 单独修复，不能混入 bridge release。

RTA-18 已确认的目标边界：

- Step1 增加：
  - `market_process_thesis`
  - `primary_mechanism_model_candidates`
  - `stochastic_price_process_projection`
- Step2 写入 `mechanism_math_contract_v2`，并同步到：
  - `factor_spec_master`
  - `canonical_spec`
  - `handoff_to_step3`
- Step6 增加：
  - `mechanism_projection_diagnosis`
  - `metric_signature_match`
  - `model_layer_failure_attribution`
  - `revision_model_target`
- Council revision proposal 增加：
  - `revision_model_layer`
  - model-layer attribution
- validator 必须 BLOCK：
  - placeholder v2 fields
  - decorative generic SDE
  - formula explains formula
  - Step6 metric/model linkage 未覆盖 implementation contract 层

## 架构边界

### Bridge 与 mechanism v2 的分层

RTA-16/RTA-17 只解决 raw LLM provenance 与 formal artifact 编译入口：

```text
PDF / manifest
  -> Step1 LLM bridge raw outputs
  -> Step2 LLM bridge raw outputs
  -> prepare_factorforge_formal_artifacts.py
  -> validate_step1.py / validate_step2.py / validate_step3.py
```

RTA-18 解决 formal artifact 内部的研究模型质量与机制数学合同：

```text
Step1 thesis fields
  -> Step2 mechanism_math_contract_v2
  -> Step5/Step6 evidence attribution
  -> Council revision model-layer attribution
```

两者交叉点只有 Step1/Step2 formal artifact schema 和 validator。交叉点不代表
两个 release 可以混在同一个 commit 中。bridge release 可以先 scoped 发布；
mechanism v2 blocker 必须单独修复后再跑 broader integration gate。

### prepare 脚本职责

`scripts/prepare_factorforge_formal_artifacts.py` 是 formal artifact compiler
和 validator，不是 PDF/LLM 理解器，也不是 worker dispatcher。

它可以：

- 消费 Step1/Step2 raw LLM outputs
- 编译 Step1/Step2/Step3A formal artifacts
- 运行 validators
- 写 prepare report
- 给上层 workflow 返回是否可以继续

它不可以：

- 伪造正式 LLM extraction
- 在正式模式下用 deterministic fallback 冒充正式结果
- 写 runtime context
- 启动研究机 worker
- 同步 artifact 到 worker

`worker_dispatch_allowed` 如果继续保留，只能作为 legacy alias，语义等同于
`workflow_may_dispatch_worker`：validator 全 PASS 后，上层 workflow 可以继续。
它不能表示 prepare 脚本已经实际 dispatch worker。

### formal LLM bridge 职责

Step1 bridge 是唯一 repo-side Step1 raw LLM 入口：

```bash
python3 scripts/run_factorforge_step1_llm_bridge.py \
  --report-id <report_id> \
  --report-pdf <local_pdf_or_local_manifest_json> \
  --out-dir objects/raw_llm/<report_id>/step1 \
  --provider command \
  --write-report
```

必须输出：

```text
objects/raw_llm/<report_id>/step1/step1_primary_raw.json
objects/raw_llm/<report_id>/step1/step1_challenger_raw.json
objects/raw_llm/<report_id>/step1/step1_chief_raw.json
```

Step2 bridge 是唯一 repo-side Step2 raw LLM 入口：

```bash
python3 scripts/run_factorforge_step2_llm_bridge.py \
  --report-id <report_id> \
  --factorforge-root <factorforge_root> \
  --out-dir objects/raw_llm/<report_id>/step2 \
  --provider command \
  --write-report
```

必须输出：

```text
objects/raw_llm/<report_id>/step2/step2_primary_raw.json
objects/raw_llm/<report_id>/step2/step2_challenger_raw.json
objects/raw_llm/<report_id>/step2/step2_auditor_raw.json
```

Step2 bridge 必须读取 Step1 raw LLM 三件套作为 provenance context。
`alpha_idea_master` 只能作为附加上下文，不能替代 Step1 raw provenance。

### worker dispatch gate

上层 Humphrey/OpenClaw workflow 的 dispatch gate 必须使用以下顺序：

1. Step1 bridge 生成 raw LLM 三件套。
2. Step2 bridge 生成 raw LLM 三件套。
3. `prepare_factorforge_formal_artifacts.py --end-step 3a --write-report`。
4. `validate_step1.py` PASS。
5. `validate_step2.py` PASS。
6. `validate_step3.py` PASS。
7. mechanism v2 validator PASS。
8. prepare report:
   - `formal_artifacts_valid=true`
   - `workflow_may_dispatch_worker=true`
   - `worker_started=false`
   - `worker_dispatch_status=not_dispatched_by_prepare`
9. workflow 层才允许创建 runtime context、同步 artifacts、启动研究机。

任一环节失败时必须返回 BLOCK，不得启动研究机。

## 发布策略

### Bridge scoped release

RTA-16/RTA-17 可以按 `e475e41` scoped release 进入发布准备，前提是：

- release 只包含该 commit 的 6 个 scoped files
- 不夹带 RTA-18 dirty files
- formal LLM bridge smoke PASS
- prepare report 明确不 dispatch worker

目标是先把“正式 raw LLM bridge 合同”和“缺 raw 就 BLOCK”的门禁发布出去。

### Mechanism v2 blocker release

RTA-18 必须单独修复：

```text
BLOCK_MECHANISM_MATH_V2_FORMULA_MAPPING_SELF_REFERENTIAL
```

修复后再单独 commit，并通过 mechanism v2 与 broader formal smoke。

### Integration release gate

两个 scoped release 都完成后，才跑完整 integration gate：

```bash
python3 scripts/run_factorforge_formal_llm_bridge_smoke.py \
  --fresh \
  --root /tmp/factorforge_formal_llm_bridge_integration

python3 scripts/run_factorforge_formal_artifact_smoke.py \
  --fresh \
  --root /tmp/factorforge_formal_artifact_integration

python3 scripts/run_factorforge_mechanism_math_v2_smoke.py \
  --fresh \
  --root /tmp/factorforge_mechanism_math_v2_integration

python3 scripts/run_factorforge_performance_smoke.py \
  --fresh \
  --root /tmp/factorforge_performance_integration
```

期望：

```text
verdict=ACCEPT
canonical_pollution=false
runtime_context_written=false
worker_started=false
```

## EC2 同步边界

GitHub main、Mac 本地、research worker 生产计算代码应尽量保持共享 source 对齐。

Humphrey EC2 可能包含 OpenClaw / 研究机 dispatch 所需的运维差异。发布同步时必须区分：

- 共享 Factor Forge source：可按 release commit 同步
- touched installed skills：按 touched step 同步
- Humphrey-specific orchestration / ops changes：必须保留
- research-worker runtime code：应保持生产计算路径对齐

不得为了追求 byte-for-byte equality 覆盖 Humphrey EC2 的运维改动。

## Reviewer 分配

### Reviewer A：RTA-16/RTA-17 bridge scoped review

只审 `e475e41` 范围：

- bridge provider missing BLOCK 是否明确
- fixture provider 是否标记 fixture-only
- command provider stdin/stdout contract 是否可复现
- Step2 是否强制 Step1 raw provenance
- alpha-only bypass 是否关闭
- prepare report 是否不写 runtime context、不启动 worker
- scoped smoke 是否 ACCEPT
- diff 是否没有 mechanism v2 混入

### Reviewer B：RTA-18 mechanism v2 blocker review

只审 RTA-18 blocker fix：

- `formula_component_mapping` 是否禁止自引用
- 合法的 formula-to-mechanism 映射是否不会被误杀
- placeholder / generic SDE / formula-explains-formula BLOCK 是否仍有效
- Step6 metric/model linkage 是否仍覆盖 implementation contract 层
- mechanism v2 smoke 是否 ACCEPT
- broader formal artifact smoke 是否 ACCEPT

### Integration reviewer

在两个 release 都完成后审集成：

- Step1/Step2 raw bridge outputs 能进入 prepare
- prepare 生成的 artifacts 能通过 Step1/2/3 validators
- mechanism v2 validator 与 formal bridge raw schema 不冲突
- bad artifacts 不会进入 Step3B/Step4
- workflow 层只有在 formal artifacts 全 PASS 后才允许启动 worker

## 最终验收

完整验收必须证明：

- 无 raw LLM artifacts：BLOCK，不启动 worker
- provider missing：BLOCK，不启动 worker
- Step2 alpha-only：BLOCK，不启动 worker
- fixture raw 仅用于 smoke，不能被标为 formal extraction
- command provider raw outputs 可进入 prepare
- `validate_step1.py` PASS
- `validate_step2.py` PASS
- `validate_step3.py` PASS
- mechanism v2 validator PASS
- broader formal artifact smoke ACCEPT
- performance smoke ACCEPT
- `canonical_pollution=false`
- GitHub/Mac/research worker 同步共享 source
- Humphrey EC2 运维差异被保留
