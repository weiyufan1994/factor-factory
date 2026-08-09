# Moneyflow / Miller 分钟因子当前研究状态

日期：2026-06-07

对象：Factor Forge researcher / 架构师 / coder / reviewer

Root report id：

```text
ORIG_INTRADAY_FLOW_SP3_DRIFT_MINUS_NOISE_20240102_20260525_FULL_LOOP_20260606172221
```

Child report id：

```text
ORIG_INTRADAY_FLOW_SP3_DRIFT_MINUS_NOISE_20240102_2026__aec8b09a34__LOOP01__MILLER_TAIL_PRICING_PERSISTENT_FLOW_STATE_V1
```

## 当前结论

moneyflow / Miller 分钟因子还不能给出 promote / reject 的最终研究结论。

当前应判定为：

```text
research_state = paused_by_step4_performance_block
mechanism_quality = sufficient_for_next_proof
child_revision_bridge = pass
Step3B_sample_proof = pass
full_Step4 = blocked_before_metrics
```

这不是因子机制被证伪，也不是 Council/Step6 失败；当前 blocker 是 full-window minute Step4 走 generic streaming 太慢，无法在生产时间内产出完整 evaluation。

## 经济机制

用户原始思路：

1. 资金流，尤其是净买入、大单净买入、主买主卖，可能携带聪明钱信息，也可能反映公募等机构的受迫性市场结构。
2. 小单可能更接近噪声追随或博傻。
3. 付钱方主要是没有信息优势、等待信息发酵才进场的人，或存在仓位/考核/赎回/风控压力的机构。
4. 资金流的集中度可用 HHI / monopoly of participation 近似，类比“龙头战法”中的资金垄断程度。

当前研究员解释：

```text
moneyflow is not uncertainty itself;
moneyflow is an observation channel for latent disagreement, signal precision, constrained demand, and crowding.
```

即：

```text
ObservedFlow = f(informed_pressure, opinion_dispersion, tail_optimism, forced_demand, liquidity_noise) + observation_noise
```

所以 raw positive flow 不能直接解释为 bullish。它可能是：

1. informed accumulation；
2. forced institutional demand；
3. attention-driven chasing；
4. optimistic-holder overpricing；
5. illiquidity / small-size noise。

## Miller 建模启发

Miller divergence-of-opinion / limited-short model 的核心是：

```text
P = mu + sigma_opinion * Phi^{-1}(1 - S/N)
```

其中：

```text
mu              = 平均估值
sigma_opinion   = 投资者分歧 / uncertainty / opinion dispersion
S/N             = 股票供给相对于潜在投资者数量
Phi^{-1}        = 正态分布右尾分位
```

当做空受限、只有乐观者持有股票时，价格由右尾投资者设定。此时更大的 uncertainty / disagreement 可能推高当前价格，并降低未来收益。

映射到 moneyflow：

```text
positive flow in quiet concentrated state
  -> more likely informed high-precision flow

positive flow after high turnover / high volume_ratio / prior price rise
  -> more likely Miller-style optimistic-holder overpricing
```

因此本轮 child revision 的核心不是“加强 positive flow”，而是拆分：

```text
tail pressure = informed pressure - crowded optimistic pressure - liquidity noise
```

## 当前 parent evidence

Parent metrics：

```text
rank_ic_mean                = 0.0089229067
rank_ic_ir                  = 0.0812455354
pearson_ic_mean             = 0.0120536907
pearson_ic_ir               = 0.1679377066
long_side_annual_return     = 0.0073743037
long_side_sharpe            = 0.0284604293
long_side_max_drawdown      = -0.2768799458
long_side_recovery_days     = 588
long_side_turnover_mean     = 0.8826173655
trading_cogs_annual         = 0.6672587283
cost_adjusted_annual_return = -0.6587239747
```

解释：

1. IC 为正，说明不是纯噪声。
2. long-side 年化几乎没有交易价值。
3. daily turnover 约 88%，成本完全吞噬收益。
4. parent 更像 raw detector，不是可交易 alpha。

## 已写正式研究记录

Research journal：

```text
/home/ubuntu/.openclaw/workspace/factorforge/objects/research_journal/research_journal__ORIG_INTRADAY_FLOW_SP3_DRIFT_MINUS_NOISE_20240102_20260525_FULL_LOOP_20260606172221.json
```

Miller note：

```text
/home/ubuntu/.openclaw/workspace/factorforge/objects/research_journal/miller_uncertainty_moneyflow_note__ORIG_INTRADAY_FLOW_SP3_DRIFT_MINUS_NOISE_20240102_20260525_FULL_LOOP_20260606172221.md
```

Main-agent Council synthesis：

```text
/home/ubuntu/.openclaw/workspace/factorforge/objects/research_iteration_master/revision_council/ORIG_INTRADAY_FLOW_SP3_DRIFT_MINUS_NOISE_20240102_20260525_FULL_LOOP_20260606172221/main_agent_council_synthesis__ORIG_INTRADAY_FLOW_SP3_DRIFT_MINUS_NOISE_20240102_20260525_FULL_LOOP_20260606172221.json
```

## Selected child revision

Selected law：

```text
miller_tail_pricing_persistent_flow_state_v1
```

Implementation mode：

```text
direct_code
```

核心表达式逻辑：

```text
pre_1450_signed_pressure
participation_concentration
intraday_noise
persistent_tail_pressure
lagged_overheat_penalty
liquidity_noise_penalty
size_residual_penalty
```

其中：

```text
tail_precision_state = concentration_confidence - intraday_noise
miller_tail_pressure = signed_pressure * (1 + tail_precision_state)
persistent_tail_pressure = 0.70 * current + 0.30 * lag1
prior_overheat = lagged volume_ratio + lagged turnover + lagged pct_chg
factor = persistent_tail_pressure - overpricing_penalty - liquidity_noise_penalty - size_residual_penalty
```

信息集约束：

```text
minute bars <= 14:50
daily_basic controls lagged by one security observation
same-day return is not used as label
```

## Bridge / validator 状态

Approval bridge 通过：

```text
selected_law_id       = miller_tail_pricing_persistent_flow_state_v1
implementation_mode   = direct_code
parent_formula_hash   = 55e13114cd75c723f93210d6faf1a617acd4528eec7c8dfa48a6f98fead73f75
child_formula_hash    = 71c776c8f646987664105516d89e7380fa5dac6ccbd18ce7a01264dcd2f90ab1
validate_step6.rc     = 0
```

Child materialization 通过：

```text
executable_revision_spec exists
child factor_spec_master exists
child data_prep_master exists
child handoff_to_step3 exists
child handoff_to_step4 exists
generated_code_written = false
clean_data_touched = false
official_promotion_written = false
```

Step3B sample proof 通过：

```text
row_count    = 32
date_count   = 16
ticker_count = 2
```

## 当前 BLOCK

full Step4 对 child revision 运行约 30 分钟仍未产出：

```text
factor_evaluation__<child>.json
run_metadata__<child>.json
formal factor_values parquet
```

进程状态：

```text
CPU roughly 70%
RSS roughly 8-12GB
not OOM
not system-killed
researcher cancelled intentionally
```

因此当前研究不应继续硬跑 generic minute streaming。应等待 `minute_derived_flow_state_v1` / Step4 guard / backfill runner 修复后再继续。

## 下一次恢复时应做什么

架构师/coder 修完后，研究员应：

1. 确认 repo / Mac installed skills / research worker 都同步到包含 derived datamart 的 commit。
2. 确认 `minute_derived_flow_state_v1` 覆盖研究窗口。
3. 使用同一个 child report id 或新的 child rerun id 继续 production proof。
4. 验证 Step4 不再走 generic minute streaming。
5. 产出 full Step4 metrics、NAV、IC、OOS test。
6. 让 Council 基于 full metrics 决定下一轮 revision 或 reject。

## 新研究窗口规则

默认研究切分：

```text
in_sample_end = 2025-07-11
2025-07 through latest = out-of-sample test set
```

Step6 / Council 只能用 in-sample 做主要 revision。OOS 用于最终验证，不应用于反复调参。
