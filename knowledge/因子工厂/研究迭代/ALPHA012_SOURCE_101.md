---
report_id: "ALPHA012_SOURCE_101"
factor_id: "Alpha012"
decision: "reject"
iteration_no: 2
tags:
  - "iteration"
  - "reject"
---

# Research Iteration: Alpha012 (ALPHA012_SOURCE_101)

## Evidence Summary

- source_case_status: `failed`

- run_status: `success`

- backend_statuses: `{'self_quant_analyzer': 'success'}`

## Evidence Metrics

- (none)

## Step5 Lessons
- Step4 evidence rejected by Step5 quality gate: SELF_QUANT_STANDARD_CONTRACT_MISSING - self_quant_analyzer must emit standard_metric_contract.
- Step4 evidence rejected by Step5 quality gate: SELF_QUANT_REQUIRED_ARTIFACT_MISSING - self_quant_analyzer missing required artifact rank_ic_timeseries_png.
- Step4 evidence rejected by Step5 quality gate: SELF_QUANT_REQUIRED_ARTIFACT_MISSING - self_quant_analyzer missing required artifact pearson_ic_timeseries_png.
- Step4 evidence rejected by Step5 quality gate: SELF_QUANT_REQUIRED_ARTIFACT_MISSING - self_quant_analyzer missing required artifact coverage_by_day_png.
- Step4 evidence rejected by Step5 quality gate: SELF_QUANT_REQUIRED_ARTIFACT_MISSING - self_quant_analyzer missing required artifact quantile_returns_10groups_csv.
- Step4 evidence rejected by Step5 quality gate: SELF_QUANT_REQUIRED_ARTIFACT_MISSING - self_quant_analyzer missing required artifact quantile_nav_10groups_csv.
- Step4 evidence rejected by Step5 quality gate: SELF_QUANT_REQUIRED_ARTIFACT_MISSING - self_quant_analyzer missing required artifact quantile_counts_10groups_csv.
- Step4 evidence rejected by Step5 quality gate: SELF_QUANT_REQUIRED_ARTIFACT_MISSING - self_quant_analyzer missing required artifact quantile_summary_table_csv.
- Step4 evidence rejected by Step5 quality gate: SELF_QUANT_REQUIRED_ARTIFACT_MISSING - self_quant_analyzer missing required artifact long_short_returns_10groups_csv.
- Step4 evidence rejected by Step5 quality gate: SELF_QUANT_REQUIRED_ARTIFACT_MISSING - self_quant_analyzer missing required artifact long_short_nav_10groups_csv.
- Step4 evidence rejected by Step5 quality gate: SELF_QUANT_REQUIRED_ARTIFACT_MISSING - self_quant_analyzer missing required artifact quantile_nav_10groups_png.
- Step4 evidence rejected by Step5 quality gate: SELF_QUANT_REQUIRED_ARTIFACT_MISSING - self_quant_analyzer missing required artifact quantile_counts_10groups_png.
- Step4 evidence rejected by Step5 quality gate: SELF_QUANT_REQUIRED_ARTIFACT_MISSING - self_quant_analyzer missing required artifact long_short_nav_10groups_png.
- Step4 evidence rejected by Step5 quality gate: RETURN_TABLE_UNREADABLE - quantile_returns_10groups_csv is missing, empty, or unreadable.
- Step4 evidence rejected by Step5 quality gate: NAV_TABLE_UNREADABLE - quantile_nav_10groups_csv is missing, empty, or unreadable.
- Step4 evidence rejected by Step5 quality gate: RETURN_TABLE_UNREADABLE - long_short_returns_10groups_csv is missing, empty, or unreadable.
- Step4 evidence rejected by Step5 quality gate: NAV_TABLE_UNREADABLE - long_short_nav_10groups_csv is missing, empty, or unreadable.
- Step4 evidence rejected by Step5 quality gate: DECILE_COUNTS_TABLE_UNREADABLE - quantile_counts_10groups_csv is missing, empty, or unreadable.
- Step4 evidence rejected by Step5 quality gate: RANK_IC_IMPLAUSIBLE - rank_ic_mean is missing or implausibly large; suspect leakage, parsing, or synthetic data.
- Step4 evidence rejected by Step5 quality gate: PEARSON_IC_IMPLAUSIBLE - pearson_ic_mean is missing or implausibly large; suspect leakage, parsing, or synthetic data.

## Step5 Next Actions
- Fix the Step4 implementation/evaluator bug and rerun Step4 before Step5/6.
- Repair Step 4 or upstream handoff before rerunning Step 5
- Restore missing run artifacts or evaluation payloads
- Investigate suspected Step4 bug: self_quant_analyzer must emit standard_metric_contract.
- Investigate suspected Step4 bug: self_quant_analyzer missing required artifact rank_ic_timeseries_png.
- Investigate suspected Step4 bug: self_quant_analyzer missing required artifact pearson_ic_timeseries_png.
- Investigate suspected Step4 bug: self_quant_analyzer missing required artifact coverage_by_day_png.
- Investigate suspected Step4 bug: self_quant_analyzer missing required artifact quantile_returns_10groups_csv.
- Investigate suspected Step4 bug: self_quant_analyzer missing required artifact quantile_nav_10groups_csv.
- Investigate suspected Step4 bug: self_quant_analyzer missing required artifact quantile_counts_10groups_csv.
- Investigate suspected Step4 bug: self_quant_analyzer missing required artifact quantile_summary_table_csv.
- Investigate suspected Step4 bug: self_quant_analyzer missing required artifact long_short_returns_10groups_csv.
- Investigate suspected Step4 bug: self_quant_analyzer missing required artifact long_short_nav_10groups_csv.
- Investigate suspected Step4 bug: self_quant_analyzer missing required artifact quantile_nav_10groups_png.
- Investigate suspected Step4 bug: self_quant_analyzer missing required artifact quantile_counts_10groups_png.
- Investigate suspected Step4 bug: self_quant_analyzer missing required artifact long_short_nav_10groups_png.
- Investigate suspected Step4 bug: quantile_returns_10groups_csv is missing, empty, or unreadable.
- Investigate suspected Step4 bug: quantile_nav_10groups_csv is missing, empty, or unreadable.
- Investigate suspected Step4 bug: long_short_returns_10groups_csv is missing, empty, or unreadable.
- Investigate suspected Step4 bug: long_short_nav_10groups_csv is missing, empty, or unreadable.
- Investigate suspected Step4 bug: quantile_counts_10groups_csv is missing, empty, or unreadable.
- Investigate suspected Step4 bug: rank_ic_mean is missing or implausibly large; suspect leakage, parsing, or synthetic data.
- Investigate suspected Step4 bug: pearson_ic_mean is missing or implausibly large; suspect leakage, parsing, or synthetic data.

## Research Judgment

- decision: `reject`

- thesis: Current evidence suggests the factor should be stopped rather than iterated further.

## Strengths
- self_quant backend completed and produced interpretable IC diagnostics

## Weaknesses
- qlib backend is not yet consistently successful
- rank IC is not positive enough to support promotion
- long-side highest-score group evidence is missing

## Risks
- No Step4 backend headline metrics were available; Step6 can enforce research policy but cannot promote or finish evidence interpretation.
- handoff_to_step5.factor_run_master_path differs from expected path: objects/factor_run_master/factor_run_master__ALPHA012_SOURCE_101.json != /Users/humphrey/projects/factor-factory/objects/factor_run_master/factor_run_master__ALPHA012_SOURCE_101.json
- Step4 evidence is blocked by Step5 quality gate and must not be interpreted as alpha evidence.

## Framework
- `factor_family`: `mixed_or_unclear`
- `monetization_model`: `mixed`
- `bias_type`: `mixed_or_unclear`
- `objective_constraint_dependency`: `high`
- `crowding_risk`: `medium_to_high`
- `capacity_constraints`: `can be fragile if the alpha depends on small names, short holding periods, or thin liquidity`
- `implementation_risk`: `realized alpha may be far more sensitive to execution, slippage, and data-contract choices than headline IC suggests`

## Return Source Hypothesis
- Current evidence suggests a usable signal, but the return source is still mixed or not yet crisply separated into risk premium vs information advantage.

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
- 迭代时至少保留一个 exploit 分支和一个 explore 分支，避免只在上一轮噪声附近局部爬山。
- 每次修改都必须回答：它在强化哪一种收益来源，以及为什么比上一版更合理。

## DD · View · Edge · Trade
- (none)

## Research Commentary
- The current result does not justify more risk budget unless a materially different hypothesis emerges.

## Loop Action

- should_modify_step3b: `False`

- next_runner: `stop`

- stop_reason: `reject`

## Modification Targets
- stabilize qlib backtest path and payload contract
- revisit signal construction and cross-sectional ranking behavior
- add long-side return diagnostics and rerun Step4/5 before any promotion
- Fix the Step4 implementation/evaluator bug and rerun Step4 before Step5/6.
- Repair Step 4 or upstream handoff before rerunning Step 5
- Restore missing run artifacts or evaluation payloads
- Investigate suspected Step4 bug: self_quant_analyzer must emit standard_metric_contract.
- Investigate suspected Step4 bug: self_quant_analyzer missing required artifact rank_ic_timeseries_png.
- Investigate suspected Step4 bug: self_quant_analyzer missing required artifact pearson_ic_timeseries_png.
- Investigate suspected Step4 bug: self_quant_analyzer missing required artifact coverage_by_day_png.
- Investigate suspected Step4 bug: self_quant_analyzer missing required artifact quantile_returns_10groups_csv.
- Investigate suspected Step4 bug: self_quant_analyzer missing required artifact quantile_nav_10groups_csv.
- Investigate suspected Step4 bug: self_quant_analyzer missing required artifact quantile_counts_10groups_csv.
- Investigate suspected Step4 bug: self_quant_analyzer missing required artifact quantile_summary_table_csv.
- Investigate suspected Step4 bug: self_quant_analyzer missing required artifact long_short_returns_10groups_csv.
- Investigate suspected Step4 bug: self_quant_analyzer missing required artifact long_short_nav_10groups_csv.
- Investigate suspected Step4 bug: self_quant_analyzer missing required artifact quantile_nav_10groups_png.
- Investigate suspected Step4 bug: self_quant_analyzer missing required artifact quantile_counts_10groups_png.
- Investigate suspected Step4 bug: self_quant_analyzer missing required artifact long_short_nav_10groups_png.
- Investigate suspected Step4 bug: quantile_returns_10groups_csv is missing, empty, or unreadable.
- Investigate suspected Step4 bug: quantile_nav_10groups_csv is missing, empty, or unreadable.
- Investigate suspected Step4 bug: long_short_returns_10groups_csv is missing, empty, or unreadable.
- Investigate suspected Step4 bug: long_short_nav_10groups_csv is missing, empty, or unreadable.
- Investigate suspected Step4 bug: quantile_counts_10groups_csv is missing, empty, or unreadable.
- Investigate suspected Step4 bug: rank_ic_mean is missing or implausibly large; suspect leakage, parsing, or synthetic data.
- Investigate suspected Step4 bug: pearson_ic_mean is missing or implausibly large; suspect leakage, parsing, or synthetic data.

## Links

- [[普通因子库/ALPHA012_SOURCE_101|Factor Record]]

- [[知识库/ALPHA012_SOURCE_101|Knowledge Record]]
