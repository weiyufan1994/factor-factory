---
report_id: "ALPHA015_RISK_C_HIGHAMOUNT_LOWKURT20_MOMENT_20160101"
factor_id: "Alpha015"
decision: "iterate"
iteration_no: 1
run_status: "success"
final_status: "validated"
tags:
  - "factor"
  - "library_all"
  - "iterate"
---

# Alpha015 (ALPHA015_RISK_C_HIGHAMOUNT_LOWKURT20_MOMENT_20160101)

## Summary

- decision: `iterate`

- iteration_no: `1`

- run_status: `success`

- final_status: `validated`

## Headline Metrics

- `rank_ic_mean`: `0.057408685929270335`

- `rank_ic_ir`: `0.5215084758520968`

- `pearson_ic_mean`: `0.04281487514794629`

- `pearson_ic_ir`: `0.42621254115016094`

- `group_long_short_spread_mean`: `0.0030299753660747715`

- `group_long_short_spread_ir`: `0.3651535951181231`

- `group_top_decile_mean_return`: `0.0005619584620404806`

- `group_bottom_decile_mean_return`: `-0.00246801690403429`

- `metric_period`: `daily`

- `annualization_factor`: `252`

- `long_side_mean_return_daily`: `0.0005634916244950443`

- `long_side_annual_return`: `0.14199988937275115`

- `long_side_return_std_daily`: `0.013908205456433762`

- `long_side_annual_volatility`: `0.22078591692549193`

- `long_side_sharpe`: `0.6431564628312391`

- `long_side_max_drawdown`: `-0.4056419125626116`

- `long_side_recovery_days`: `1199`

- `long_side_turnover_mean_daily`: `0.2499746065136578`

- `turnover_mean`: `0.2499746065136578`

- `trading_cogs_daily`: `0.0007499238195409734`

- `trading_cogs_annual`: `0.18898080252432528`

- `cost_adjusted_return_daily`: `-0.000186130171759767`

- `cost_adjusted_annual_return`: `-0.046904803283461284`

- `cost_adjusted_long_side_sharpe`: `-0.21251019007586608`

- `cost_adjusted_long_side_max_drawdown`: `-0.7726305385326033`

- `cost_adjusted_long_side_recovery_days`: `3440`

## Strengths
- self_quant backend completed and produced interpretable IC diagnostics
- cross-sectional ranking signal is directionally positive in self_quant diagnostics
- long-side Sharpe clears the candidate threshold; this is adoption-relevant but still below official certainty
- rank_ic_mean=0.057409 is positive, so the raw cross-sectional ordering contains directional information.
- rank_ic_ir=0.522 is usable for a first-pass daily factor, but not strong enough to ignore robustness checks.
- long-side highest-score group mean return=0.142000 is positive; this is revenue evidence but no longer sufficient alone for adoption.
- long-side Sharpe=0.643 clears the candidate threshold 0.50, but still needs more evidence for official admission.
- volatility-drag adjusted growth proxy=0.117627 is positive under mean - 0.5*sigma^2.

## Weaknesses
- qlib backend is not yet consistently successful
- max_drawdown=-0.406 breaches the soft capital-cost limit -0.35; reduce drawdown before promotion.
- recovery_days=1199 is longer than the soft payback limit; the factor may not survive its drawdown cycle.

## Risks
- Pearson IC is weaker than Rank IC; the expression may be ordinal rather than linearly monotonic, so revision should improve the factor expression itself rather than switch to rank/decile trading.
- group long-short spread mean=0.003030 is positive, but this is diagnostic only because short selling and direct decile trading are not allowed.
- group long-short spread IR=0.365 is positive, but cannot justify adoption without long-side evidence.
- Benchmark is an empty Series, so native qlib output is absolute-strategy evidence rather than benchmark-relative alpha evidence.
- long-short NAV is extremely high; Step6 must inspect short-leg dominance, costs, and compounding assumptions.

## Framework
- `factor_family`: `market_structure_microstructure_factor`
- `monetization_model`: `constraint_driven_arbitrage`
- `bias_type`: `constraint_plus_behavior`
- `objective_constraint_dependency`: `high`
- `crowding_risk`: `medium_to_high`

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
- 把每次失败当作搜索轨迹的一部分写回知识库；不要只保存胜出的公式。

## Revision Principles
- revision 先服务于收益来源假说，而不是先服务于指标美化。
- 若是风险补偿型，优先提升可交易性、稳健性和暴露控制，而不是过度压平风险特征。
- 若是信息优势型，优先强化识别条件、样本边界和解释链条，而不是盲目扩大适用范围。
- 若是约束驱动套利型，优先验证客观约束是否真实、是否持续、是否仍可被结构化利用。
- 宏观修订改收益来源假说或因子家族；微观修订只改因子表达式、窗口、阈值、符号、输入变换或标准化，两者必须分开记录。
- 不得通过卖空、long-short、直接分位数组交易或 portfolio expression 修复来让一个 long-side 不赚钱的因子通过。
- 入库目标从 raw long-side return 升级为 long-side Sharpe / volatility drag / drawdown / recovery 的综合资本效率。
- 迭代时至少保留一个 exploit 分支和一个 explore 分支，避免只在上一轮噪声附近局部爬山。
- 每次修改都必须回答：它在强化哪一种收益来源，以及为什么比上一版更合理。

## Links

- [[知识库/ALPHA015_RISK_C_HIGHAMOUNT_LOWKURT20_MOMENT_20160101|Knowledge Record]]

- [[研究迭代/ALPHA015_RISK_C_HIGHAMOUNT_LOWKURT20_MOMENT_20160101|Research Iteration]]
