# Factor Forge Ultimate 反馈：Alpha036 生产验收暴露的问题

Date: 2026-06-02

Audience: Factor Forge Architect / Reviewer

Report id:

```text
ALPHA036_CANONICAL_FORMULA_20160101_PROD_ACCEPTANCE
```

## 1. 总结

Alpha036 最终完成了生产验收 run：

```text
wrapper status=PASS
Step3/3B/4/5/6 validators=PASS
Step6 decision=iterate
Council status=awaiting_agent_results
```

但这次不是“一条命令无摩擦通过”。真实生产路径暴露了几个合同缺口，主要集中在：

1. Alpha101 canonical formula 的标准字段派生不完整；
2. Step3A report-local snapshot 没有稳定承诺 formula-required standard fields；
3. Step3B sample output 和 Step4 formal factor values 的 ownership 容易混淆；
4. performance profile 对 Step3B/Step4 metadata 的读取路径需要区分；
5. Qlib native provider 已可 report-local 构建，但 Step4 仍是 `partial`，不能被误读为完整 qlib backtest 成功；
6. 部分 artifact 顶层字段不一致，例如 `run_id` 在 `artifact_identity.run_id`，不是顶层字段。

这些问题已经在本轮为 Alpha036 做了窄修或绕开，但建议架构师继续硬化成正式合同。

## 2. 生产验收过程中的实际问题

### 2.1 `adv20` / `vwap` 字段合同缺口

Alpha036 公式需要：

```text
volume
returns
vwap
adv20
```

但基础 clean daily layer 主要提供：

```text
vol
amount
pct_chg
```

因此生产路径一开始会遇到标准字段无法稳定解析的问题。

本轮做的窄修：

- `factor_factory/formula/field_aliases.py` 支持 `advN` 和 `vwap` alias；
- `factor_factory/formula/evaluator.py` 在公式执行前从 `vol/amount/pct_chg` 派生 `volume/returns/vwap/advN`；
- `factor_factory/formula/parity.py` 让 parity fixture 使用同一套标准字段派生逻辑；
- `skills/factor-forge-step3/scripts/run_step3.py` 在 Step3A report-local snapshot 中 materialize formula-required standard fields。

建议合同化：

```text
Step2/Step3A 应显式声明 required_standard_formula_fields。
Step3A 必须在 report-local snapshot 中写出这些字段，或者 BLOCK。
Step3B/Step4 不应各自猜 alias。
```

### 2.2 Step3A snapshot schema 应成为正式执行合同

这次 Step3A 最终写出了：

```text
volume
returns
vwap
adv20
```

并且 sort contract schema 中可见这些字段。但这更像本轮修复后的结果，不应依赖研究员临场判断。

建议：

1. `data_prep_master.local_input_paths.derived_field_contract` 必须列出：
   - source fields；
   - derived fields；
   - formula-required fields；
   - derivation rules；
   - lookback / leakage policy。
2. `validate_step3.py` 应校验所有 formula-required fields 在 report-local parquet/csv 中存在。
3. 如果 formula 需要 `adv20`，Step3A 应确认 20 日 rolling window 的信息集合法，不能由 Step3B 静默补。

### 2.3 Step3B sample output 与 Step4 formal output 容易混淆

生产边界要求：

```text
Step3B = executability proof / sample output
Step4 = formal factor values owner
```

但旧路径容易让 Step3B 写出 formal-looking 文件名，导致后续 profile 或 validator 把 Step3B sample 与 Step4 formal output 混读。

本轮做的窄修：

- Step3B first-run 改成写：

```text
step3b_sample_factor_values__<report_id>.parquet
step3b_sample_factor_values__<report_id>.csv
step3b_sample_run_metadata__<report_id>.json
```

- Step3B metadata 声明：

```text
is_formal_factor_values=false
formal_factor_values_owner=Step4
```

- Step3B 会清理 stale formal-named sample outputs，避免污染 Step4。

建议：

```text
Step3B validator 应 BLOCK 任何 Step3B 写出的 formal factor_values__*.parquet/csv。
Performance profile 应明确分开 Step3B sample metadata 和 Step4 formal run_metadata。
```

### 2.4 Performance profile 需要更清晰的嵌套结构

当前 profile 是扁平结构：

```text
step3b_performance_profile
self_quant_performance_profile
formula_engine_profile
kernel_profile
wrapper_command_timing
```

但用户验收通常问：

```text
Step3B total / phase breakdown
Step4 total / phase breakdown
backend
reuse hits
metric parity
```

本轮我需要手动读多个字段并重新整理。建议 profile 写一个面向验收的 summary block：

```json
{
  "acceptance_summary": {
    "step3b": {
      "backend": "...",
      "input_format": "parquet",
      "phase_seconds": {},
      "formula_engine_profile": {}
    },
    "step4": {
      "self_quant": {},
      "qlib_native": {},
      "input_format": "parquet"
    },
    "reuse": {},
    "side_effects": {},
    "metrics": {}
  }
}
```

这样研究员不需要从五六个 artifact 中人工拼验收口径。

### 2.5 Qlib native provider 仍应明确区分 `attempted / partial / success`

本轮已构建 report-local qlib provider：

```text
/Users/humphrey/projects/factorforge/runs/ALPHA036_CANONICAL_FORMULA_20160101_PROD_ACCEPTANCE/qlib_provider
```

Provider raw smoke 通过后，Step4 确实进入 qlib native path：

```text
qlib_native.attempted=true
qlib_native.status=partial
```

但这不等于 qlib backtest 完整成功。当前验收必须说：

```text
self_quant_analyzer=success
qlib_native=partial
```

建议：

1. `validate_step4.py` 对 qlib native 输出分层：
   - `not_attempted`
   - `preflight_ready`
   - `partial_payload`
   - `native_backtest_success`
2. `factor_evaluation.backend_summary` 不要让 `qlib_backtest=partial` 看起来像与 self-quant 对等的成功 backend。
3. 如果生产验收要求 qlib native success，应允许 wrapper 以明确 blocker 停下，而不是 PASS + partial。

### 2.6 Artifact 顶层字段一致性仍需强化

本轮最终确认：

```text
run_id = artifact_identity.run_id = run_001
```

但 `factor_run_master` 顶层没有 `run_id`，`ultimate_run_report` 顶层也没有 `artifact_root`。这使得验收时容易误判为缺字段。

建议：

```text
所有 formal master artifact 顶层保留 report_id、run_id、artifact_root、producer、status/verdict。
artifact_identity 可以继续保留完整版本，但验收字段不应只藏在 artifact_identity 里。
```

### 2.7 Step6 研究文本中出现“current run is partial”的歧义

Step6 research judgment 中写了：

```text
current run is still partial rather than fully validated
qlib backend is not yet consistently successful
```

这从 qlib backend 角度是对的，但 wrapper 和 validators 已经 PASS。容易让读者混淆：

- wrapper validation 是否 PASS？
- self-quant 是否成功？
- qlib 是否 partial？
- 因子研究结论是否完整？

建议 Step6 区分：

```text
wrapper_validation_status=PASS
self_quant_evidence_status=complete
qlib_native_status=partial
research_decision=iterate
```

不要用一个笼统的 `partial` 描述整个 run。

## 3. 这次研究遇到的困难

### 3.1 研究难点

Alpha036 本身不是一个简单单机制因子。它把五个不同状态直接加权：

- lagged volume/body dependence；
- weak close；
- delayed negative return memory；
- unsigned vwap-adv dependence；
- long-term mean displacement/body interaction。

这导致 economic hypothesis 很容易变得泛化。为了避免模板化，我必须把它解释成一个 composite transient-pressure state，而不是简单说“price-volume microstructure”。

最大的研究困难是：

```text
公式有弱正 IC，但 high-score long side 亏钱。
```

这说明它可能确实捕捉到某种排序信息，但方向、分量组合、成本或组合可交易性不支持直接做多。此类因子不能简单 reject，也不能 promote，最合理是让 Council 做分量级 revision。

### 3.2 工程难点

本轮生产验收要同时满足：

- Mac/EC2 高性能默认路径；
- Data API 边界；
- Qlib native provider；
- Step3B/Step4 ownership；
- performance profile；
- side-effect proof；
- Council agentic dispatch。

任何一个合同不清楚都会让验收报告变得不可信。实际最耗时的不是 compute，而是把每个 artifact 的权责边界校准清楚。

## 4. 建议的后续改造

优先级 P0:

1. 标准字段派生合同化：`volume/returns/vwap/advN` 这类字段必须由 Step2/Step3A 明确声明和校验。
2. Step3B sample 与 Step4 formal artifact ownership 固化，避免同名污染。
3. Step4 backend status 明确区分 qlib partial 和 qlib full success。

优先级 P1:

1. Performance profile 增加 `acceptance_summary`。
2. Formal artifact 顶层统一 `run_id/artifact_root/status`。
3. Step6 research judgment 拆分 wrapper/self-quant/qlib 三种状态。

优先级 P2:

1. Council taskbook 对 composite formula 自动要求 component ablation proposal。
2. 对 `abs(corr(...))` 这类 direction-losing transform 增加 math critic 必答项。
3. 对加权和公式增加 “component sign consistency / dimensional consistency / latent-state independence” 检查。

## 5. 研究员给架构师的明确请求

请把本轮 Alpha036 暴露的问题收敛为以下合同：

```text
1. Step2/3A standard_formula_fields_contract
2. Step3B sample-only output contract
3. Step4 qlib_native_status taxonomy
4. Performance profile acceptance_summary
5. Formal artifact top-level run_id/artifact_root/verdict fields
6. Step6 backend evidence status split
```

这些不是美化项，而是生产验收的可审计性要求。否则后续每个 Alpha101 公式都会在 alias、sample/formal ownership、profile 汇报和 qlib partial 状态上重复消耗研究员时间。
