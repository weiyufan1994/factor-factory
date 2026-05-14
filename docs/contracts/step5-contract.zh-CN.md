> [English Version](step5-contract.md)

# Step 5 合约

## 目的
Step 5 是 Step 4 之后的第一道案例收口与证据质量关。它不得基于畸形 Step 4 输出评价因子好坏。如果 Step 4 证据缺失、内部不一致或明显有 bug，Step 5 必须把 case 标为 failed/blocked，并打回 Step 4 修复。

## 机制数学合约保存
Step5 只复制上游 `mechanism_math_contract` 到 `factor_case_master`，并在 `math_discipline_review.mechanism_math_contract_ref` 中引用核心字段。Step5 不重新做机制推理，也不允许数学解释替代 evidence identity、long-side risk-adjusted evidence、archive policy 或 prewrite gate。

## 输入
- `factor_run_master__{report_id}.json`
- `factor_spec_master__{report_id}.json`
- `data_prep_master__{report_id}.json`
- `handoff_to_step5__{report_id}.json`
- Step 4 backend 的 `evaluation_payload.json`
- 支撑归档/案例闭环所需的 Step 4 factor values 与 run metadata

## 输出
- `factor_case_master__{report_id}.json`
- `factor_evaluation__{report_id}.json`
- `archive/{report_id}/` 下的归档包
- `factor_evaluation` 与 `factor_case_master` 中都必须复制 `step4_quality_gate`

`factor_case_master` 与 `factor_evaluation` 必须保留 Step4 证据来源链：

- `artifact_identity`
- `evidence_identity`
- `implementation_mode_decision`
- `source_evidence_refs`
- `evidence_quality`

没有 provenance，不归档；没有 evidence identity，不允许 validated case close。

validated Step5 必须满足：

- 严格匹配 `factor_run_master` identity
- 至少一个 Step4 backend success/partial
- self-quant long-only 证据存在
- long-side annual return、volatility、Sharpe、max drawdown、recovery days、turnover、trading COGS、cost-adjusted Sharpe 完整
- `identity_chain_verified=true`
- `mode_decision_present=true`

相似案例只能作为类比，不能当成同一 factor 的证据，除非 artifact identity 完全匹配。

provenance gate 必须在 `archive_artifacts()` 之前执行。如果 gate 失败，Step 5 只能写 failed / not validated case 以及 `objects/validation/step5_prewrite_block__{report_id}.json`，不得归档 artifacts，也不得写出看起来可进入 Step6 的 validated handoff。

## 强制 Step4 质量关
Step 5 必须先执行 `step4_quality_gate`，再写 validated 或 partial 研究结论。这个 gate 只判断证据完整性和执行质量，不判断 alpha 好坏。

阻断条件包括：

- Step 4 有实际运行但没有 backend payload
- backend 声称 success/partial 但 payload 缺失或不可读
- `self_quant_analyzer.standard_metric_contract` 缺失或有 blocking issue
- 任一 self-quant 强制 artifact 缺失或为空
- `rank_ic_timeseries.png`、`pearson_ic_timeseries.png`、`coverage_by_day.png` 缺失
- decile return/NAV/count CSV 表畸形
- long-short return/NAV CSV 表畸形
- IC、return、count、NAV 存在 NaN/Inf
- decile NAV 或 long-short NAV 首个观测点未归一到 1.0
- NAV 非正或爆炸式异常
- decile 分组为空
- qlib backend 成功但缺少强制 qlib artifacts

## 阻断语义
如果 `step4_quality_gate.verdict == BLOCK`，Step 5 必须：

- 设置 `final_status = failed`
- 写出 `bug_hypotheses`
- 设置 `rerun_required = true`
- 写出下一步行动：修复并重跑 Step 4
- 不得把这份证据当成可供 Step 6 promotion 的 alpha 证据

## 可复现性提示
极简 fixture 仍可证明对象形态闭环，但正式研究 case 必须先通过 Step 4 证据质量检查，再进入 Step 5/6 解释。
