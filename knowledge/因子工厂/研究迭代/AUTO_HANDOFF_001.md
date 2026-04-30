---
report_id: "AUTO_HANDOFF_001"
factor_id: "AUTO_FACTOR"
decision: "reject"
iteration_no: 4
tags:
  - "iteration"
  - "reject"
---

# Research Iteration: AUTO_FACTOR (AUTO_HANDOFF_001)

## Evidence Summary

- source_case_status: `failed`

- run_status: `failed`

- backend_statuses: `{'self_quant_analyzer': 'skipped'}`

## Evidence Metrics

- `rank_ic_mean`: `0.9344262295081968`

- `rank_ic_ir`: `2.6020435681899228`

- `pearson_ic_mean`: `0.8291975930875846`

- `pearson_ic_ir`: `2.602890546692364`

## Step5 Lessons
- Evaluation used a synthetic fallback snapshot; IC is diagnostic only and must not be treated as production evidence.
- Cross-sectional breadth is only 3.0 names per day; IC is statistically fragile.
- Absolute rank_ic_mean=0.934 under a tiny universe is suspiciously high; check for synthetic structure or leakage before trusting the signal.

## Step5 Next Actions
- Repair Step 4 or upstream handoff before rerunning Step 5
- Restore missing run artifacts or evaluation payloads

## Research Judgment

- decision: `reject`

- thesis: Current evidence suggests the factor should be stopped rather than iterated further.

## Strengths
- cross-sectional ranking signal is directionally positive in self_quant diagnostics

## Weaknesses
- qlib backend is not yet consistently successful
- group spread IR is not yet persuasive

## Risks
- Evaluation used a synthetic fallback snapshot; IC is diagnostic only and must not be treated as production evidence.
- Cross-sectional breadth is only 3.0 names per day; IC is statistically fragile.
- Absolute rank_ic_mean=0.934 under a tiny universe is suspiciously high; check for synthetic structure or leakage before trusting the signal.

## Framework
- `factor_family`: `market_structure_microstructure_factor`
- `monetization_model`: `constraint_driven_arbitrage`
- `bias_type`: `constraint_plus_behavior`
- `objective_constraint_dependency`: `high`
- `crowding_risk`: `medium_to_high`
- `capacity_constraints`: `can be fragile if the alpha depends on small names, short holding periods, or thin liquidity`
- `implementation_risk`: `realized alpha may be far more sensitive to execution, slippage, and data-contract choices than headline IC suggests`

## Return Source Hypothesis
- Returns likely come from recurring objective constraints or frictions, where other market participants are pushed into predictable behavior and the strategy acts as a structured, not strictly risk-free, arbitrageur.

## Constraint Sources
- exchange rules or transfer mechanisms
- fund mandate or benchmark constraints
- insurance / public-fund style behavior patterns
- execution and liquidity frictions that force predictable action

## Expected Failure Regimes
- market-structure rule changes
- liquidity stress or execution degradation
- anomaly crowding after the pattern becomes widely known

## Improvement Frontier
- separate objective-constraint edge from pure noise
- stabilize the signal with robust transforms before increasing complexity
- verify monotonicity across wider windows and different liquidity buckets

## Review Checklist
- 先判断这条收益更像风险补偿、信息优势，还是约束驱动套利；不要直接从 metric 下结论。
- 明确对手盘为什么会在客观约束下做出可预测行为，例如制度规则、考核约束、资金属性、流动性约束。
- 检查当前证据是在支持收益来源本身，还是只是在支持某个脆弱实现。
- 区分 factor 与 feature：这是一条可重复交易的系统化暴露，还是局部有效但尚未稳定抽象的特征组合。
- 在决定 promote / iterate / reject 前，先写清失效条件、容量约束、拥挤风险与实现风险。

## Revision Principles
- revision 先服务于收益来源假说，而不是先服务于指标美化。
- 若是风险补偿型，优先提升可交易性、稳健性和暴露控制，而不是过度压平风险特征。
- 若是信息优势型，优先强化识别条件、样本边界和解释链条，而不是盲目扩大适用范围。
- 若是约束驱动套利型，优先验证客观约束是否真实、是否持续、是否仍可被结构化利用。
- 每次修改都必须回答：它在强化哪一种收益来源，以及为什么比上一版更合理。

## DD · View · Edge · Trade
- `risk_view`: `This factor does not look like a pure compensated-risk sleeve; most of the edge likely comes from interpretation or structure rather than passive risk bearing.`
- `information_view`: `Information edge is probably secondary here; the main question is whether the rewarded exposure is real and persistent.`
- `edge_view`: `The edge likely mixes some risk-bearing with better interpretation of short-horizon structure.`
- `trade_view`: `Do not treat a good IC as sufficient; the trade expression must still survive turnover, liquidity, and crowding checks.`

## Research Commentary
- The current result does not justify more risk budget unless a materially different hypothesis emerges.

## Loop Action

- should_modify_step3b: `False`

- next_runner: `stop`

- stop_reason: `reject`

## Modification Targets
- stabilize qlib backtest path and payload contract
- improve grouped spread monotonicity and robustness
- Repair Step 4 or upstream handoff before rerunning Step 5
- Restore missing run artifacts or evaluation payloads

## Links

- [[普通因子库/AUTO_HANDOFF_001|Factor Record]]

- [[知识库/AUTO_HANDOFF_001|Knowledge Record]]
