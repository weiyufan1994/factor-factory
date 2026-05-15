---
report_id: "ALPHA015_REGIME_R01_CORR7_SUM7_20160101"
factor_id: "Alpha015"
decision: "iterate"
tags:
  - "knowledge"
  - "iterate"
---

# Knowledge Record: Alpha015 (ALPHA015_REGIME_R01_CORR7_SUM7_20160101)

- decision: `iterate`

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
- self_quant backend completed and produced interpretable IC diagnostics
- cross-sectional ranking signal is directionally positive in self_quant diagnostics
- rank_ic_mean=0.039470 is positive, so the raw cross-sectional ordering contains directional information.
- rank_ic_ir=0.454 is usable for a first-pass daily factor, but not strong enough to ignore robustness checks.
- long-side highest-score group mean return=0.100218 is positive; this is revenue evidence but no longer sufficient alone for adoption.
- volatility-drag adjusted growth proxy=0.076991 is positive under mean - 0.5*sigma^2.

## Failure Patterns
- current run is still partial rather than fully validated
- qlib backend is not yet consistently successful
- long-side Sharpe=0.465 is below candidate threshold 0.50
- long-side Sharpe=0.465 is below the candidate threshold 0.50; improve risk-adjusted performance rather than raw return only.
- max_drawdown=-0.416 breaches the soft capital-cost limit -0.35; reduce drawdown before promotion.
- recovery_days=1755 is longer than the soft payback limit; the factor may not survive its drawdown cycle.

## Expected Failure Regimes
- market-structure rule changes
- liquidity stress or execution degradation
- anomaly crowding after the pattern becomes widely known

## Modification Hypotheses
- close remaining partial coverage gap before promotion
- stabilize qlib backtest path and payload contract
- revise factor expression/code to improve long-side Sharpe by reducing volatility drag and drawdown, not by adding short exposure
- Fill missing evaluation backend outputs
- Repair archive or validation gaps and rerun Step 5

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

## Links

- [[普通因子库/ALPHA015_REGIME_R01_CORR7_SUM7_20160101|Factor Record]]

- [[研究迭代/ALPHA015_REGIME_R01_CORR7_SUM7_20160101|Research Iteration]]
