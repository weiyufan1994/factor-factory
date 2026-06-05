# Factor Forge 长期合同缺口反馈：部分解决与未解决事项

Date: 2026-06-03

Audience: Factor Forge Architect / Reviewer

## 1. 结论

最新改动已经解决了一部分长期问题，尤其是：

1. Step1/2 对 canonical formula 的 formula-specific economic hypothesis / math hypothesis 更强；
2. Step3A 如果不可执行，Step3B 不再能继续假装 ready；
3. Step3B sample output 与 Step4 formal factor values 的 ownership 开始被区分。

但长期来看，Factor Forge 仍有几个关键合同没有完全闭合。它们不是 Alpha036 个案问题，而是以后每个 Alpha101-like 或新研报因子都会反复遇到的生产验收问题：

```text
1. standard formula fields contract 仍未成为 Step2 -> Step3A -> Step4 的硬合同；
2. Step3A derived fields 的信息集、量纲、单位、lookback policy 仍不够显式；
3. performance profile 缺少统一的 production acceptance summary；
4. qlib native status 仍可能被 partial/success 语义误读；
5. formal artifacts 顶层验收字段不统一；
6. Step6 evidence status 仍把 wrapper / self-quant / qlib / research decision 混在一起；
7. Dirac-style research report 仍没有被 validator 强制成 production research standard。
```

这些缺口如果不收口，研究员每次都需要人工从多个 artifact 中拼 evidence，并且很容易把 “wrapper PASS”、“self-quant 成功”、“qlib partial”、“研究结论 iterate/reject/promote” 混成一个模糊状态。

## 2. 已经解决的长期问题

### 2.1 Step1/2 formula-specific mechanism modelling 有改善

最新 smoke 显示，无 volume 的 Alpha019-like 公式不会再被归成 generic price-volume / liquidity mechanism。Step1/2 能根据公式字段和算子形成更贴近公式的：

- economic hypothesis；
- math hypothesis；
- formula understanding；
- mechanism math contract。

这是长期正确方向。主 agent 和后续 Council 才能围绕具体公式做推导，而不是围绕模板词做 revision。

仍需注意：

```text
这解决的是 mechanism specificity，不等于已经解决 execution contract 和 production acceptance contract。
```

### 2.2 Step3A blocked gate 已经明显改善

现在 Step3A 若不可执行，Step3B 会 BLOCK，而不是继续写 stale implementation / stale first_run_outputs。

这解决了一个重要长期风险：

```text
坏的 Step3A artifact 不会被 worker 或 Step3B 当作可执行输入消费。
```

这是 production workflow 的基础防线，应保留。

### 2.3 Step3B sample 与 Step4 formal ownership 已初步硬化

Step3B 现在会使用 sample-named outputs：

```text
step3b_sample_factor_values__<report_id>.parquet
step3b_sample_factor_values__<report_id>.csv
step3b_sample_run_metadata__<report_id>.json
```

并声明：

```text
is_formal_factor_values=false
formal_factor_values_owner=Step4
```

Step3B validator 也会阻止 Step3B 写 formal `factor_values__*.parquet` / `run_metadata__*.json`。

这基本解决了 sample/formal 文件名污染问题。

## 3. 部分解决但仍需合同化的问题

### 3.1 Standard formula fields contract 仍不完整

当前已有局部派生能力，例如：

```text
volume  <- vol
returns <- pct_chg / return
vwap    <- amount / volume
advN    <- rolling_mean(volume, N)
```

但这还不是完整的 Step2 -> Step3A -> Step4 合同。

当前缺口：

1. Step2 没有稳定输出 `standard_formula_fields_contract`；
2. Step3A 虽能 materialize derived fields，但合同字段过于简略；
3. `validate_step3.py` 没有强制校验 report-local snapshot 包含所有 formula-required standard fields；
4. Step4 仍可能依赖输入中已有字段，而不是校验字段来源和 derivation policy；
5. `returns` 的单位仍需明确：`pct_chg` 是百分比还是小数收益，不能只靠代码习惯；
6. `vwap=amount/vol` 的单位需要明确：A 股 `amount` 和 `vol` 的单位在不同数据源中可能不一致；
7. `advN` 的 rolling policy 需要明确是否包含 t 日，是否只使用 factor timestamp 可见数据。

长期建议：

```json
{
  "standard_formula_fields_contract": {
    "required_standard_formula_fields": ["volume", "returns", "vwap", "adv20"],
    "source_field_candidates": {
      "volume": ["vol"],
      "returns": ["pct_chg", "return", "close", "pre_close"],
      "vwap": ["amount", "vol"],
      "adv20": ["volume"]
    },
    "derivation_rules": {
      "volume": "vol",
      "returns": "pct_chg / 100 if pct_chg is percent; otherwise explicit unit contract required",
      "vwap": "amount / volume with amount/volume unit policy",
      "advN": "rolling_mean(volume, N) using no future data"
    },
    "lookback_policy": "uses data available at factor timestamp only",
    "block_if_unavailable": true
  }
}
```

应由 Step2 生成，Step3A 执行，Step3 validator 和 Step4 validator 共同检查。

### 3.2 Derived field contract 的审计信息不够强

当前 Step3A 能写 `derived_field_contract`，但它更像“派生了什么字段”的记录，而不是完整审计合同。

长期应该包含：

- required fields；
- source fields；
- formula-specific derivation rules；
- source unit；
- output unit；
- lookback window；
- whether current day is included；
- missing source blocker；
- clean data mutation = false；
- report-local only = true；
- validation result；
- sample schema parity；
- leakage policy。

建议 blocker：

```text
BLOCK_STANDARD_FORMULA_FIELDS_MISSING
BLOCK_STANDARD_FORMULA_FIELD_SOURCE_MISSING
BLOCK_STANDARD_FORMULA_DERIVATION_POLICY_MISSING
BLOCK_STANDARD_FORMULA_DERIVED_FIELD_NOT_IN_SNAPSHOT
BLOCK_STANDARD_FORMULA_FIELD_UNIT_AMBIGUOUS
```

## 4. 尚未解决的长期问题

### 4.1 Performance profile 缺少 production acceptance summary

现在 performance profile 已经能区分 Step3B sample metadata 和 Step4 formal metadata，这是进步。但研究员仍要人工拼：

- Step3B phase breakdown；
- Step3B backend / kernel / parity；
- Step4 self-quant phase breakdown；
- qlib status；
- reuse hit / miss；
- wrapper validator verdict；
- side effects；
- key metrics。

长期应增加一个顶层：

```json
{
  "acceptance_summary": {
    "report_id": "...",
    "repo_sha": "...",
    "run_id": "...",
    "artifact_root": "...",
    "wrapper_status": "PASS",
    "validator_verdicts": {},
    "step3b": {
      "backend": "pandas_formula_ir_optimized",
      "input_format": "parquet",
      "phase_seconds": {},
      "formula_engine_profile": {},
      "is_formal_factor_values": false
    },
    "step4": {
      "formal_factor_values_owner": "Step4",
      "self_quant_status": "success",
      "qlib_native_status": "partial_payload",
      "phase_seconds": {}
    },
    "reuse": {
      "data_api_snapshot_reused": true,
      "step4_factor_values_reuse_gate": "...",
      "qlib_provider_reused": true
    },
    "side_effects": {
      "clean_data_mutated": false,
      "search_worker_used": false,
      "official_promotion_written": false,
      "generated_code_digest_changed": false
    },
    "metrics": {}
  }
}
```

这不是展示层优化，而是生产验收的可审计入口。用户要求“汇报 repo_sha、run_id、artifact_root、backend、reuse、profile、validator verdict”时，应能从一个 summary block 直接读取。

### 4.2 Qlib native status taxonomy 仍不够清楚

当前仍容易出现：

```text
qlib_backtest status=partial
mode=sample_stub
```

这对内部代码可用，但对研究验收容易误读。

长期建议把 qlib native status 拆为：

```text
not_attempted
preflight_blocked
preflight_ready
partial_payload
native_minimal_success
native_backtest_success
```

并明确：

- `partial_payload` 不能被当作 qlib native success；
- `sample_stub` 只能作为 signal diagnostics；
- `native_minimal_success` 必须有 portfolio / benchmark / turnover artifacts；
- `native_backtest_success` 才能被写入生产级 qlib evidence；
- wrapper 是否允许 qlib partial 下 PASS，需要由 run mode 明确决定。

### 4.3 Formal artifacts 顶层验收字段仍不统一

当前很多字段藏在 `artifact_identity` 中，例如：

```text
artifact_identity.run_id
artifact_identity.producer
artifact_identity.branch_id
```

但 formal acceptance 需要顶层字段，避免每次人工追结构：

```json
{
  "report_id": "...",
  "run_id": "...",
  "artifact_root": "...",
  "producer": "...",
  "status": "...",
  "verdict": "..."
}
```

建议所有 formal master artifact 顶层保留：

- `report_id`
- `factor_id`
- `run_id`
- `artifact_root`
- `producer`
- `status` 或 `verdict`
- `artifact_identity`

涉及对象：

- `alpha_idea_master`
- `factor_spec_master`
- `data_prep_master`
- `implementation_plan_master`
- `factor_run_master`
- `factor_case_master`
- `research_iteration_master`
- `ultimate_run_report`
- `ultimate_loop_report`
- `performance_profile`

### 4.4 Step6 evidence status 仍混在一起

Step6 目前仍可能写：

```text
current run is still partial rather than fully validated
qlib backend is not yet consistently successful
```

这会造成长期误解。应该拆成四层：

```json
{
  "evidence_status": {
    "wrapper_validation_status": "PASS",
    "self_quant_evidence_status": "complete",
    "qlib_native_status": "partial_payload",
    "research_decision": "iterate",
    "promotion_gate_status": "blocked_by_long_side"
  }
}
```

这样读者能清楚区分：

- wrapper 是否通过；
- self-quant 是否完整；
- qlib 是否只是 partial；
- 因子研究是否可 promote；
- Step6 说 partial 到底指哪一层。

### 4.5 Dirac-style research report 尚未变成硬 production standard

目前 Step1/2/6 已经比以前更接近“先经济假设，再数学模型，再公式映射，再 metrics falsification”。但长期标准还没完全硬化。

正式研究报告应强制包含：

1. formula-implied information：公式结构被迫告诉我们什么；
2. anomaly review：哪些 metric 与原假设矛盾；
3. model-linked metrics：每个关键 metric 对应验证数学模型中的哪一项；
4. volatility drag：收益是否被波动率拖累；
5. drawdown recovery days / recovery area；
6. component-level interpretation：每个分量估计哪个 latent state；
7. component ablation proposal；
8. direction-losing transforms review，例如 `abs(corr(...))`；
9. dimensional / unit consistency；
10. stochastic projection check：即便主模型不是 stochastic process，也要用 stochastic projection 做一次辅助验证。

建议 Step6 validator 或 researcher packet validator 增加必填项：

```text
formula_implied_information
model_linked_metric_signature
metric_anomaly_review
volatility_drag_review
drawdown_recovery_area
component_level_revision_axes
stochastic_projection_consistency_check
```

否则 LLM 容易写出“看起来合理”的机制解释，但没有把公式、模型和指标真正闭环。

## 5. 建议优先级

### P0

1. `standard_formula_fields_contract`：Step2 生成，Step3A 执行，Step3/Step4 validators 检查。
2. `acceptance_summary`：performance profile 顶层生产验收 summary。
3. `qlib_native_status` taxonomy：禁止把 partial qlib payload 误读为 qlib success。

### P1

1. formal artifacts 顶层统一 `run_id / artifact_root / producer / status / verdict`。
2. Step6 `evidence_status` 拆分 wrapper / self-quant / qlib / research decision。
3. derived field unit/lookback/leakage policy 写入硬合同。

### P2

1. Dirac-style research report validator。
2. component-level Council packet requirements。
3. direction-losing transform review。
4. stochastic projection as auxiliary validation for non-stochastic primary models。

## 6. 建议验收 smoke

新增或扩展以下 smoke：

```text
run_factorforge_alpha101_standard_field_contract_smoke.py
run_factorforge_production_acceptance_contract_smoke.py
run_factorforge_qlib_status_taxonomy_smoke.py
run_factorforge_step6_evidence_status_smoke.py
run_factorforge_dirac_research_report_contract_smoke.py
```

Negative cases 必须覆盖：

- formula 需要 `adv20` 但没有 volume source；
- formula 需要 `vwap` 但没有 amount 或 volume source；
- Step3A snapshot 缺 required derived field；
- Step3B 写 formal factor values；
- performance profile 缺 acceptance summary；
- qlib partial 被标为 success；
- Step6 只有笼统 partial 文本，没有 evidence status split；
- research report 缺 formula-implied information / model-linked metrics。

## 7. 给架构师的简短请求

请不要把这次修复只理解为 Alpha036 个案收尾。真正需要收口的是长期生产合同：

```text
Step2 declares formula-required standard fields.
Step3A materializes and validates those fields in report-local snapshots.
Step3B only proves executability with sample artifacts.
Step4 owns formal factor values and backend evidence status.
Performance profile exposes one production acceptance summary.
Step6 separates wrapper/self-quant/qlib/research statuses.
Research reports must close formula -> model -> metric -> falsification.
```

这些合同闭合后，后续 Alpha101 和新研报研究才不会靠研究员临场补洞。
