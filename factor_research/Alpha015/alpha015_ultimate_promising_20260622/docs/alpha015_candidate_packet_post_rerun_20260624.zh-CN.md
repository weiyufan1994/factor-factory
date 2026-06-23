# Alpha015 Post-Rerun Candidate Packet

日期：2026-06-24

工作区：

`factor_research/Alpha015/alpha015_ultimate_promising_20260622`

本文件是 Alpha015 在 signal coverage 修复并完成 Step3B-Step6 rerun 后的候选包。它用于沉淀候选因子和可复用研究经验，不是 official promotion 证明。

## 当前结论

```text
candidate_library: yes
feature_candidate: yes
official_factor_library: no
best_branch: ALPHA015_SWEEP_TURNPEN_A040_20160101
mechanism_claim_level: component_validated
stochastic_process_status: framing_only
payer_validation: not_validated
```

Alpha015 是当前 Alpha101 批次里最强的候选之一。parent 分支的覆盖问题已经修复，high-score long side 有真实 gross edge；但回撤、恢复时间、成本后 Sharpe、payer validation、stochastic validation 和组合边际贡献仍不足以支持 official promotion。

## 证据分层

`promotion_gate_evidence`：

- 官方 wrapper rerun 的 parent Step3B-Step6 指标。
- 覆盖率、RankIC、long-side return、turnover、cost-adjusted return、drawdown/recovery。

`robustness_evidence`：

- full IS / OOS window evidence。
- component ablation。
- size/liquidity neutralization。
- size bucket diagnostic。

`diagnostic_evidence`：

- LOOP01 和 LOOP02 rerun 后没有改善经济目标。
- 更强 turnover gate 被证伪，不应继续机械加强。

`exploratory_evidence`：

- OOS 和分层证据可以解释稳定性，但在当前状态下不能替代正式 promotion gate。

## 因子表达式

当前最佳分支：

`ALPHA015_SWEEP_TURNPEN_A040_20160101`

定义短窗价格-成交量压力：

$$
C_{i,t}
=
\operatorname{corr}_{7}
\left(
\operatorname{rank}(H_{i,\cdot}),
\operatorname{rank}(V_{i,\cdot})
\right)_t
$$

定义压力状态、参与确认和 turnover 状态：

$$
X_{i,t}
=
-\sum_{k=1}^{7}\operatorname{rank}(C_{i,t-k+1})
$$

$$
L_{i,t}=\operatorname{rank}(A_{i,t})
$$

$$
G_{i,t}=0.40+0.60\left(1-\operatorname{rank}(T_{i,t})\right)
$$

最终因子：

$$
F^{015}_{i,t}=X_{i,t}L_{i,t}G_{i,t}
$$

其中：

- $H_{i,t}$：股票 $i$ 在 $t$ 日的最高价。
- $V_{i,t}$：股票 $i$ 在 $t$ 日的成交量。
- $A_{i,t}$：股票 $i$ 在 $t$ 日的成交额或参与度代理。
- $T_{i,t}$：股票 $i$ 在 $t$ 日的换手率。
- $X_{i,t}$：价格-成交量耦合后的压力状态。
- $L_{i,t}$：市场参与确认，不是单独买高成交额股票。
- $G_{i,t}$：turnover friction / 拥挤 / 活跃参与状态的温和调制。

## 经济假设

Alpha015 的更准确描述是：

> liquidity-participation conditioned price-volume pressure feature。

它不是简单的高成交额因子，也不是单纯小市值或流动性因子。它尝试捕捉的是：

1. 价格和成交量在短窗内形成异常耦合；
2. 这个压力状态有足够成交参与确认；
3. 但不能完全落在高换手拥挤交易里；
4. 未来收益来自边际参与者在压力状态形成后继续支付流动性、注意力或委托执行成本。

可能的 profit payer：

- late attention buyers；
- 被流动性/委托压力推着追随的资金；
- 在压力状态已经显性化之后才进入的边际参与者。

这些 payer 目前只是可检验假设，还没有直接 proxy 证据，所以 `payer_validation=not_validated`。

## 数学机制

最保守的条件收益投影是：

$$
\mathbb{E}[r_{i,t+1}\mid\mathcal{F}_t]
=
\mu_0
+\beta_X X_{i,t}
+\beta_{XL}X_{i,t}L_{i,t}
+\beta_{XLG}X_{i,t}L_{i,t}G_{i,t}
+\varepsilon_{i,t+1}
$$

当前证据最支持的是：

$$
\beta_{XL}>0
$$

也就是：价格-成交量压力状态与成交参与确认的乘积有真实排序信息。

但目前不能声称：

$$
\beta_{XLG}
$$

已经被验证为完全独立于流动性状态的 residual alpha。原因是 liquidity residualization 后 full IS long-side 明显减弱。

因此当前机制等级是：

```text
math_framed: yes
metric_consistent: yes
component_validated: yes
stochastic_validated: no
payer_validated: no
```

## 正式 Rerun 指标

Parent 分支：

```text
report_id: ALPHA015_SWEEP_TURNPEN_A040_20160101
validator: PASS
formal_signal_coverage: 99.2156%
nonnull_date_count: 2301
nonnull_start: 20160120
nonnull_end: 20250711
RankIC mean: 0.060225
RankIC IR: 0.541872
long annual return: 22.2511%
long Sharpe: 0.9382
max drawdown: -39.54%
recovery days: 704
daily turnover: 24.49%
cost-adjusted annual return: 3.7472%
cost-adjusted Sharpe: 0.1579
cost-adjusted max drawdown: -61.16%
```

LOOP01：

```text
RankIC mean: 0.064207
RankIC IR: 0.600301
long annual return: 20.0961%
long Sharpe: 0.8557
max drawdown: -39.44%
recovery days: 714
daily turnover: 24.47%
cost-adjusted annual return: 1.6077%
cost-adjusted Sharpe: 0.0684
```

LOOP01 提高 RankIC，但降低 long-side return、Sharpe、成本后 Sharpe 和恢复质量，因此不是改进。

LOOP02：

```text
RankIC mean: 0.056898
RankIC IR: 0.541325
long annual return: 19.9593%
long Sharpe: 0.8440
max drawdown: -40.03%
recovery days: 714
daily turnover: 24.13%
cost-adjusted annual return: 1.7282%
cost-adjusted Sharpe: 0.0731
```

LOOP02 略降 turnover，但牺牲 RankIC、long-side return、Sharpe、drawdown/recovery 和成本后质量，也不是改进。

## Robustness 摘要

Full IS / OOS 诊断显示 parent 的 long-side 没有坍塌：

| Split | RankIC 1D | RankIC 5D | Top Ann. | Top Sharpe | Top Max DD | Top Turnover |
|---|---:|---:|---:|---:|---:|---:|
| Full IS | 0.0571 | 0.0787 | 0.3398 | 1.3145 | -0.4073 | 0.2449 |
| OOS | 0.0496 | 0.0611 | 0.4244 | 2.0981 | -0.1362 | 0.2132 |

Component ablation 的关键结论：

- `pressure only` 有信息；
- `pressure × amount` 是最强 raw information component；
- `amount only` 不是正确方向，说明不是单纯买高成交额；
- `turnover gate only` 有信息但不是完整 alpha。

Neutralization 的关键结论：

- size residualization 后 RankIC 大部分保留；
- liquidity residualization 后 full IS long-side 明显减弱；
- 所以 Alpha015 不能宣传为纯流动性残差 alpha。

Size bucket 的关键结论：

- 信号主要集中在 low / mid-low size；
- high size 仍有信息但明显更弱；
- 下一步如果做 promotion，需要更严格的 investability universe 和 capacity 检查。

## 为什么不能 official promotion

当前 blocker：

1. 最大回撤约 `-39.54%`，超过当前 soft limit。
2. recovery days `704`，远高于一年。
3. cost-adjusted Sharpe 只有 `0.1579`。
4. liquidity residualization 后 full IS long-side 变弱。
5. profit payer 还只是经济假设，没有直接验证。
6. stochastic-process claim 仍是 framing only，没有状态转移、半衰期、尾部/跳跃风险验证。
7. 还没有证明在模型组合中的边际贡献。

## 不要重复

- 不要继续简单加强 turnover gate。
- 不要因为 LOOP01 RankIC 更高就说它更好。
- 不要因为 LOOP02 turnover 稍低就说它更好。
- 不要把 Alpha015 说成纯 size-neutral 或 liquidity-neutral alpha。
- 不要用组合方式、换仓频率、decile long-short 来替代表达式研究。

## 下一步

建议后续只在有明确机制时继续 Alpha015：

1. Regime stability guard：必须对应可解释的 liquidity/volatility state，不能只是拟合 gate。
2. Horizon repair：降低 churn，但不能破坏 pressure-state 信息。
3. Payer proxy：验证 late attention / liquidity demander 是否真的支付收益。
4. Model combination：验证 Alpha015 作为 feature 是否给现有因子池带来边际贡献。
5. Investability：排除不可交易微盘后，测试 low / mid-low size 是否仍然成立。

在这些证据出现前，Alpha015 的状态应保持为：

```text
candidate_factor
feature_candidate
not_official_promoted
```
