---
report_id: "ALPHA001_PAPER_20100104_CURRENT"
factor_id: "Alpha001"
decision: "promote_official"
iteration_no: 4
run_status: "success"
final_status: "validated"
tags:
  - "factor"
  - "library_all"
  - "promote_official"
---

# Alpha001 (ALPHA001_PAPER_20100104_CURRENT)

## Summary

- decision: `promote_official`

- iteration_no: `4`

- run_status: `success`

- final_status: `validated`

## Headline Metrics

- `rank_ic_mean`: `0.0438539693550682`

- `rank_ic_ir`: `0.3806632056735633`

- `pearson_ic_mean`: `0.03360757043387547`

- `pearson_ic_ir`: `0.30303486488584364`

- `group_long_short_spread_mean`: `0.0024723225346664343`

- `group_long_short_spread_ir`: `0.27026113675883257`

- `group_top_decile_mean_return`: `0.00042619759655208693`

- `group_bottom_decile_mean_return`: `-0.0020461249381143473`

## Strengths
- self_quant backend completed and produced interpretable IC diagnostics
- qlib backend completed and produced grouped diagnostics plus native minimal backtest outputs
- cross-sectional ranking signal is directionally positive in self_quant diagnostics
- grouped long-short spread is positive in qlib grouped diagnostics

## Weaknesses
- (none)

## Risks
- (none)

## Framework
- `factor_family`: `style_risk_factor`
- `monetization_model`: `risk_premium`
- `bias_type`: `risk_compensation`
- `objective_constraint_dependency`: `low_to_medium`
- `crowding_risk`: `medium_to_high`

## Constraint Sources
- benchmarking and mandate-driven allocation can amplify style premia

## Expected Failure Regimes
- factor winter or long valuation compression against the style sleeve
- macro regime shifts that reverse the rewarded risk

## Improvement Frontier
- separate rewarded exposure from overlapping style bets
- improve risk budgeting and cross-factor neutralization

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

## Links

- [[知识库/ALPHA001_PAPER_20100104_CURRENT|Knowledge Record]]

- [[研究迭代/ALPHA001_PAPER_20100104_CURRENT|Research Iteration]]
