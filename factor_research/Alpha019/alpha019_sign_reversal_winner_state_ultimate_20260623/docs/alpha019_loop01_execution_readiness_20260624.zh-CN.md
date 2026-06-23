# Alpha019 LOOP01 Execution Readiness

日期：2026-06-24

工作区：

`factor_research/Alpha019/alpha019_sign_reversal_winner_state_ultimate_20260623`

本文是 Alpha019 LOOP01 的执行就绪沉淀。它不是 Step3B/Step4 结果，也不是授权执行记录。它只说明：如果用户明确批准 LOOP01，下一步应如何通过正式 Factor Forge revision path 执行，以及如何判断这次 child 是否有研究价值。

## 当前状态

```text
parent_report_id: ALPHA019_SIGN_REVERSAL_WINNER_STATE_20160101
proposed_child_report_id: ALPHA019_SIGN_REVERSAL_WINNER_STATE_20160101__LOOP01__ALPHA019_SMOOTHED_PULLBACK_PERSISTENCE_V1
execution_status: pending_human_approval
execution_allowed_by_default: false
active_handoff_to_step3b: absent
revision_loop_budget_cost: 1
user_loop_cap: <=5
```

Alpha019 parent 的 Step6 状态是 `iterate`，但需要人工批准后才能进入 child Step3B。当前不能直接运行 child。

## Parent 问题

Parent 公式可以理解为：

$$
S_{i,t}=B_{i,t}(1+M_{i,t})
$$

其中：

$$
B_{i,t}=-\operatorname{sign}(C_{i,t}-C_{i,t-7})
$$

$$
M_{i,t}
=
\operatorname{rank}_{t}
\left(
1+\sum_{k=0}^{249}r_{i,t-k}
\right)
$$

Parent 的弱点不是完全没有信息，而是硬 sign 状态 $B_{i,t}$ 在零附近容易翻转：

$$
\operatorname{NetEdge}
=
\operatorname{GrossEdge}
-
\operatorname{Turnover}\times\operatorname{Cost}
<0
$$

已知 parent 指标：

| Metric | Value |
|---|---:|
| Rank IC mean | 0.0285904 |
| Rank IC IR | 0.280932 |
| Gross long annual return | 7.06% |
| Gross long Sharpe | 0.310 |
| Max drawdown | -48.83% |
| Daily turnover | 30.69% |
| Cost-adjusted annual return | -16.13% |
| Cost-adjusted Sharpe | -0.709 |

## 拟议 Child

用连续 pullback intensity 替代硬 sign：

$$
P_{i,t}
=
\operatorname{rank}_{t}
\left(
\frac{C_{i,t-7}-C_{i,t}}{C_{i,t-7}}
\right)
$$

再做短窗持久化：

$$
\bar{P}_{i,t}
=
\operatorname{mean}_{5}(P_{i,t})
$$

Child 因子：

$$
F^{019,\mathrm{child}}_{i,t}
=
\bar{P}_{i,t}
\left(1+M_{i,t}\right)
$$

Formula-IR 草案：

```text
mean(rank(((delay(close, 7) - close) / delay(close, 7))), 5)
*
(1 + rank((1 + sum(returns, 250))))
```

## Preflight 证据

`alpha019_loop01_formula_preflight_20260624` 已完成只读可行性检查：

```text
parse_status: success
formula_hash: 8cb8e209277990fb9bb5af3df4c240ade2e010144e16144943bd32d3a017a3e8
required_fields: close, returns
operator_set: delay, divide, mean, minus, multiply, plus, rank, sum
max_formula_ir_lookback: 250
synthetic_rows: 3840
synthetic_non_null_factor_rows: 852
synthetic_nonnull_dates: 71
```

这只证明表达式可执行且在有足够 lookback 的样本上不是全空，不证明 alpha 质量。

## 批准后执行路径

如果用户明确批准：

```text
approve Alpha019 LOOP01
```

下一步应通过正式 Factor Forge revision path：

1. materialize child revision package；
2. 生成 child `alpha_idea_master`、`factor_spec_master`、`data_prep_master` 和 executable revision spec；
3. 使用 single wrapper 从 Step3B 跑到 Step6；
4. 写入 child 的 Step4 evidence、Step5 closeout、Step6 loop_research_brief；
5. 把成功或失败经验写回 `knowledge/canonical` 和 human-readable notes。

不得：

- 手工改 baseline Step3；
- 用 portfolio policy、rebalance frequency、decile trading、short leg 来救因子；
- 直接运行未 materialize 的 provisional formula；
- 跳过 Step6 知识沉淀。

## 成功签名

LOOP01 成功需要满足：

1. turnover 明显低于 parent 的 `0.3069`；
2. gross long annual return 不明显低于 parent 的 `7.06%`；
3. cost-adjusted annual return 明显改善，最好转正；
4. RankIC 不能坍塌到接近零；
5. max drawdown 和 recovery days 改善；
6. high-score long side 改善，而不是靠 long-short 或 short side 诊断。

## Kill Criteria

应停止该 child，如果：

1. cost-adjusted annual return 仍明显为负；
2. turnover 没有显著下降；
3. gross long annual return 被平滑项删除；
4. long-side Sharpe 低于 parent；
5. 改善来自 portfolio mechanics 而非表达式本身。

## 复杂度判断

本次复杂度变化：

```text
removed: hard sign boundary
added: continuous pullback ratio
added: mean_5 persistence smoothing
net_complexity_delta: small_positive_or_neutral
```

这次 child 的合理性不在于增加复杂度，而在于删除硬边界带来的状态翻转噪声。若 turnover 不降或 long-side 被削弱，则说明连续化和平滑删除了有效信息，应该 kill。

## 当前需要用户决策

当前唯一缺口是人工批准：

```text
是否批准 Alpha019 LOOP01 正式执行？
```

若批准，本分支消耗 1 个 revision loop，仍满足用户设定的 `<=5` loop 上限。
