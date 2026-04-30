---
report_id: "AUTO_HANDOFF_001"
factor_id: "AUTO_FACTOR"
decision: "reject"
tags:
  - "knowledge"
  - "reject"
---

# Knowledge Record: AUTO_FACTOR (AUTO_HANDOFF_001)

- decision: `reject`

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

## Success Patterns
- cross-sectional ranking signal is directionally positive in self_quant diagnostics

## Failure Patterns
- qlib backend is not yet consistently successful
- group spread IR is not yet persuasive

## Expected Failure Regimes
- market-structure rule changes
- liquidity stress or execution degradation
- anomaly crowding after the pattern becomes widely known

## Modification Hypotheses
- stabilize qlib backtest path and payload contract
- improve grouped spread monotonicity and robustness
- Repair Step 4 or upstream handoff before rerunning Step 5
- Restore missing run artifacts or evaluation payloads

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

## Links

- [[普通因子库/AUTO_HANDOFF_001|Factor Record]]

- [[研究迭代/AUTO_HANDOFF_001|Research Iteration]]
