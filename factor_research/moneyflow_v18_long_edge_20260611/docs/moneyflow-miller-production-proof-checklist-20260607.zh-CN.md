# Moneyflow / Miller Production Proof Checklist

日期：2026-06-07

对象：Factor Forge researcher / 架构师 / coder / reviewer

用途：架构师/coder 完成 minute derived datamart 与 Step4 guard 后，研究员按此清单恢复 moneyflow / Miller 因子的生产验证。本文不是新的研究结论；它是下一次 proof run 的验收合同。

## 目标

验证 `miller_tail_pricing_persistent_flow_state_v1` 这条 child revision 是否能在生产路径中完成 full Step4/5/6，并判断其是否有进一步研究价值。

Root report id：

```text
ORIG_INTRADAY_FLOW_SP3_DRIFT_MINUS_NOISE_20240102_20260525_FULL_LOOP_20260606172221
```

当前 child report id：

```text
ORIG_INTRADAY_FLOW_SP3_DRIFT_MINUS_NOISE_20240102_2026__aec8b09a34__LOOP01__MILLER_TAIL_PRICING_PERSISTENT_FLOW_STATE_V1
```

如果因 artifact isolation 或 rerun policy 需要新 child id，必须保留 parent lineage、Council synthesis、executable revision spec 和 selected law id，不得静默回退 parent 公式。

## 前置条件

开始 production proof 前必须确认：

```text
repo_sha = latest reviewed commit after 8fd0ddf
Mac installed skills = synced
research worker = synced
direct_code_revision_bridge_smoke = ACCEPT
performance_smoke = ACCEPT, if touched Step4 runtime
```

数据条件：

```text
minute_derived_flow_state_v1 registered in Data API catalog
coverage_start <= 2016-01-01, if running full historical window
coverage_end >= 2025-07-11 for in-sample proof
coverage includes 2025-07 through latest for OOS proof, if final validation is requested
FACTORFORGE_DATA_CACHE points to persistent cache
FACTORFORGE_S3_REGION is set correctly
```

Step4 运行条件：

```text
full-window generic minute streaming is forbidden
full factor CSV is forbidden unless explicitly sample-only
daily/parquet or derived-state artifacts are preferred
same-day future labels must not leak into factor values
```

## 正式入口

所有正式恢复必须走 wrapper/loop，不得手工改 generated code 或绕过 validator。

建议恢复命令由当时最新 artifact 状态决定：

```bash
python3 scripts/run_factorforge_ultimate_loop.py \
  --report-id ORIG_INTRADAY_FLOW_SP3_DRIFT_MINUS_NOISE_20240102_20260525_FULL_LOOP_20260606172221 \
  --start-step 6 \
  --max-loops 5 \
  --council-mode auto
```

如果 wrapper 判断 child materialization 已存在，应复用或显式生成新的 child rerun id。不能因为 child 已存在而重复 materialize 失败，也不能继续未选中的 sibling branch。

## 必查 artifacts

Root / parent：

```text
objects/runtime_context/ultimate_loop_report__<root_report_id>.json
objects/runtime_context/ultimate_run_report__<root_report_id>.json
objects/research_iteration_master/revision_council/<root_report_id>/main_agent_council_synthesis__<root_report_id>.json
objects/research_iteration_master/revision_council/<root_report_id>/approval_bridge__<root_report_id>.json
```

Child：

```text
objects/factor_spec_master/factor_spec_master__<child_report_id>.json
objects/research_iteration_master/executable_revision_spec__<child_report_id>.json
objects/factor_evaluation/factor_evaluation__<child_report_id>.json
objects/runtime_context/run_metadata__<child_report_id>.json
objects/validation/performance_profile__<child_report_id>.json
objects/research_iteration_master/revision_council/<child_report_id>/revision_council_packet__<child_report_id>.json
```

Charts / NAV：

```text
objects/factor_evaluation/charts/<child_report_id>/
objects/factor_evaluation/*nav*<child_report_id>*
objects/factor_evaluation/*quantile*<child_report_id>*
```

## Step4 性能验收

必须证明 Step4 使用 derived state / daily preaggregation，而不是 full-window generic minute streaming。

需要在 `run_metadata` 或 `performance_profile` 中看到类似字段：

```text
minute_derived_state_selected = true
minute_derived_state_id = minute_derived_flow_state_v1
derived_state_reuse_hit = true or first_build_then_reuse
input_io_profile.daily_selected_format = parquet
full_factor_csv_written = false
```

需要回报：

```text
Step4 total
load_factor_or_derived_state
load_daily_snapshot_or_backtest_base
ic_calculation
quantile_assignment
quantile_nav
long_side_evidence
write_tables
write_plots
rows_per_second_total
cache_hit / cache_miss
```

如果 Step4 仍然从全量分钟 parquet 逐因子扫描并在 20-30 分钟内没有产出 formal evaluation，应 BLOCK：

```text
BLOCK_STEP4_MINUTE_GENERIC_STREAMING_FULL_WINDOW_FORBIDDEN
```

## Metrics 验收

必须同时给出 in-sample 与 OOS 的核心指标。

研究窗口：

```text
in_sample_start = 2016-01-01, if full history is available
in_sample_end   = 2025-07-11
oos_start       = 2025-07-12 or next trading day
oos_end         = latest available date
```

如果当前数据只支持 2024+，必须明确降级为 short-window proof，不得宣称 2016+ 正式结论。

必报指标：

```text
rank_ic_mean
rank_ic_ir
pearson_ic_mean
pearson_ic_ir
long_side_annual_return
long_side_sharpe
long_side_max_drawdown
long_side_recovery_days
long_side_turnover_mean
trading_cogs_annual
cost_adjusted_annual_return
10-quantile NAV / monotonicity
long-side NAV chart
```

如果存在 U 型 NAV 或单调性降低，Council 必须解释：

```text
small-size contamination
crowded optimistic-holder overpricing
liquidity regime split
flow sign / horizon mismatch
Miller tail-pricing state mis-specified
```

## Step6 / Council 验收

Council 不应只给 verdict。必须基于 Step1/2 的 economic hypothesis、math/physics mechanism、Step4/5 metrics 和 preliminary analysis 做推导。

每个 real-agent result 必须包含：

```text
research_question
limiting_cases
economic_hypothesis_review
math_mechanism_derivation
model_to_formula_translation
expected_metric_signature
falsification_tests
```

本轮特别要求 Council 检查：

```text
Miller limited-short / divergence-of-opinion mapping
moneyflow as latent uncertainty / precision observation channel
smart-money accumulation vs crowded optimistic flow
dollar-bar / event-time proxy feasibility
absolute order-size vs relative order-size normalization
Ledoit-Wolf / shrinkage / filtering for player classification
HHI participation concentration and supply-demand accounting
```

如果 child revision 被证伪，未到 max loops 时不得直接 terminal reject 整个因子；应生成下一轮 derivation 或 multibranch exploration，除非 terminal authority 合同明确满足。

## BLOCK 条件

以下任一命中必须 BLOCK，不得硬跑或伪造结论：

```text
BLOCK_MINUTE_DERIVED_STATE_COVERAGE_INCOMPLETE
BLOCK_MINUTE_DERIVED_STATE_IDENTITY_MISMATCH
BLOCK_STEP4_MINUTE_DERIVED_STATE_REQUIRED
BLOCK_STEP4_MINUTE_GENERIC_STREAMING_FULL_WINDOW_FORBIDDEN
BLOCK_RESEARCH_WINDOW_SPLIT_MISSING
BLOCK_REVISION_USES_OOS_FOR_FITTING
BLOCK_FORMAL_ARTIFACT_SCHEMA_INVALID
BLOCK_DIRECT_CODE_REVISION_CONTRACT_MISSING
BLOCK_CHILD_FORMULA_HASH_NO_EFFECT
BLOCK_PROMOTION_WITHOUT_OOS_EVIDENCE
```

## Side-effect 边界

本 proof 不允许：

```text
clean data processing
clean data mutation
real search_worker, unless explicitly requested
official promotion, unless promotion gate truly passed
manual generated_code edits
manual Step3B handoff edits
UBL / CPV fixture fallback
```

需要回报：

```text
clean_data_digest_before / after
generated_code_digest_before / after
official_promotion_absent
search_worker_started = false
worker identity / instance id
repo_sha / run_id / artifact_root
```

## 预期判定

可能结论：

```text
promoted
rejected
exhausted
awaiting_next_derivation
max_loops_reached
blocked_by_performance_contract
blocked_by_data_coverage
```

当前更合理的预期不是直接 promote，而是：

1. 先证明 derived-state production path 能跑完。
2. 再判断 Miller revision 是否改善 raw moneyflow parent 的高 turnover / 高成本 / 低 long-side return 问题。
3. 若 IC 仍有但交易价值弱，Council 应优先研究降 turnover、事件时间、玩家分类、small-size neutralization 和 OOS 稳健性，而不是提前 reject。
