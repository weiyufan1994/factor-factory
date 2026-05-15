---
report_id: "ALPHA015_REGIME_R01_CORR7_SUM7_20160101"
factor_id: "Alpha015"
decision: "iterate"
iteration_no: 1
tags:
  - "iteration"
  - "iterate"
---

# Research Iteration: Alpha015 (ALPHA015_REGIME_R01_CORR7_SUM7_20160101)

## Evidence Summary

- source_case_status: `partial`

- run_status: `success`

- backend_statuses: `{'self_quant_analyzer': 'success', 'qlib_backtest': 'partial'}`

## Evidence Metrics

- `rank_ic_mean`: `0.03947001742746446`

- `rank_ic_ir`: `0.45438329481693107`

- `pearson_ic_mean`: `0.027509476758708178`

- `pearson_ic_ir`: `0.3575257716948933`

- `group_long_short_spread_mean`: `0.0019794756967261035`

- `group_long_short_spread_ir`: `0.333588346498872`

- `group_top_decile_mean_return`: `0.00039800148868511076`

- `group_bottom_decile_mean_return`: `-0.0015814742080409925`

- `metric_period`: `daily`

- `annualization_factor`: `252`

- `long_side_mean_return_daily`: `0.00039768874235594114`

- `long_side_annual_return`: `0.10021756307369717`

- `long_side_return_std_daily`: `0.013577185214193179`

- `long_side_annual_volatility`: `0.21553113348611028`

- `long_side_sharpe`: `0.4649795203724274`

- `long_side_max_drawdown`: `-0.4161507654793969`

- `long_side_recovery_days`: `1755`

- `long_side_turnover_mean_daily`: `0.1927281762684937`

- `turnover_mean`: `0.1927281762684937`

- `trading_cogs_daily`: `0.0005781845288054811`

- `trading_cogs_annual`: `0.14570250125898124`

- `cost_adjusted_return_daily`: `-0.00018026358382752978`

- `cost_adjusted_annual_return`: `-0.045426423124537506`

- `cost_adjusted_long_side_sharpe`: `-0.21076040339671112`

- `cost_adjusted_long_side_max_drawdown`: `-0.7391859600724915`

- `cost_adjusted_long_side_recovery_days`: `3440`

## Step5 Lessons
- Step 5 closed the case using only verified upstream artifacts.

## Step5 Next Actions
- Fill missing evaluation backend outputs
- Repair archive or validation gaps and rerun Step 5

## Research Judgment

- decision: `iterate`

- thesis: Factor has usable evidence but still needs another implementation/evaluation round.

## Strengths
- self_quant backend completed and produced interpretable IC diagnostics
- cross-sectional ranking signal is directionally positive in self_quant diagnostics
- rank_ic_mean=0.039470 is positive, so the raw cross-sectional ordering contains directional information.
- rank_ic_ir=0.454 is usable for a first-pass daily factor, but not strong enough to ignore robustness checks.
- long-side highest-score group mean return=0.100218 is positive; this is revenue evidence but no longer sufficient alone for adoption.
- volatility-drag adjusted growth proxy=0.076991 is positive under mean - 0.5*sigma^2.

## Weaknesses
- current run is still partial rather than fully validated
- qlib backend is not yet consistently successful
- long-side Sharpe=0.465 is below candidate threshold 0.50
- long-side Sharpe=0.465 is below the candidate threshold 0.50; improve risk-adjusted performance rather than raw return only.
- max_drawdown=-0.416 breaches the soft capital-cost limit -0.35; reduce drawdown before promotion.
- recovery_days=1755 is longer than the soft payback limit; the factor may not survive its drawdown cycle.

## Risks
- Pearson IC is weaker than Rank IC; the expression may be ordinal rather than linearly monotonic, so revision should improve the factor expression itself rather than switch to rank/decile trading.
- group long-short spread mean=0.001979 is positive, but this is diagnostic only because short selling and direct decile trading are not allowed.
- group long-short spread IR=0.334 is positive, but cannot justify adoption without long-side evidence.
- Benchmark is an empty Series, so native qlib output is absolute-strategy evidence rather than benchmark-relative alpha evidence.
- long-short NAV is extremely high; Step6 must inspect short-leg dominance, costs, and compounding assumptions.

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

## DD · View · Edge · Trade
- (none)

## Research Commentary
- The signal is usable, but the current evidence still leaves room to sharpen either the economic story or the implementation path.

## Loop Action

- should_modify_step3b: `False`

- next_runner: `stop`

- stop_reason: `advisory_only`

## Modification Targets
- close remaining partial coverage gap before promotion
- stabilize qlib backtest path and payload contract
- revise factor expression/code to improve long-side Sharpe by reducing volatility drag and drawdown, not by adding short exposure
- Fill missing evaluation backend outputs
- Repair archive or validation gaps and rerun Step 5

## Links

- [[普通因子库/ALPHA015_REGIME_R01_CORR7_SUM7_20160101|Factor Record]]

- [[知识库/ALPHA015_REGIME_R01_CORR7_SUM7_20160101|Knowledge Record]]
