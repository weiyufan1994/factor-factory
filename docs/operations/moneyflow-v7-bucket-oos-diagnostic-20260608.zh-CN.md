# Moneyflow V7 分桶与 OOS 诊断

日期：2026-06-08

Report id：

```text
ORIG_INTRADAY_FLOW_SP3_DRIFT_MINUS_NOISE_20__a47321ba09__LOOP01__MILLER_FLOW_FISHER_HYSTERETIC_EXPECTED_COST_BOUNDARY_V1
```

研究机：

```text
i-02cc0b6e93856fbb4
repo_head = ee40fd7b8d25f66ce3193fbe82a4125543976d43
artifact_root = /home/ubuntu/.openclaw/workspace/factorforge
```

诊断方式：

```text
read-only diagnostic
no new production loop
no clean data processing
no search_worker
no official promotion
```

使用现有 artifact：

```text
runs/<V7>/merged_signal_return__<V7>.parquet
/home/ubuntu/factorforge_data_api_cache/backtest_base_daily_controls_v1/identity=aceb074e071b646e/backtest_base_daily_controls_v1__aceb074e071b646e.parquet
```

输出位置：

```text
/home/ubuntu/.openclaw/workspace/factorforge/objects/research_diagnostics/<V7>/v7_bucket_oos_diagnostic__<V7>.json
/home/ubuntu/.openclaw/workspace/factorforge/objects/research_diagnostics/<V7>/v7_bucket_oos_diagnostic__<V7>.md
```

SSM command：

```text
f7724b1c-6804-4d31-ac86-9167cd14b8ef
```

## 一句话结论

V7 在全市场仍未达到 promotion 标准，但“小市值 20%”里信号明显更强，而且 2025-07-11 之后 OOS 仍然站住。

因此现在不应继续泛化地改 V7，而应把下一轮研究聚焦到：

```text
small-size bucket + moneyflow hysteresis + bucket-specific cost boundary
```

## 指标总览

| subset | rows | dates | rank IC | IC IR | turnover | long annual | Sharpe | max DD | recovery | cost adj annual |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| all IS | 1,660,019 | 368 | 0.0323 | 0.3152 | 0.2575 | 0.1142 | 0.4563 | -0.2329 | 179 | -0.0805 |
| all OOS | 940,609 | 207 | 0.0272 | 0.3376 | 0.2536 | 0.1241 | 0.7058 | -0.1272 | 57 | -0.0677 |
| small20 IS | 331,856 | 368 | 0.0394 | 0.4267 | 0.2835 | 0.2761 | 0.7624 | -0.4061 | 178 | 0.0617 |
| small20 OOS | 188,043 | 207 | 0.0356 | 0.4660 | 0.2736 | 0.2290 | 1.0517 | -0.1425 | 45 | 0.0222 |

成本假设：

```text
cost_adjusted_annual_return = long_side_annual_return - turnover_mean * 0.003 * 252
```

## 经济解释

V7 的经济假设是：

> 有信息含量的资金流状态会持续一段时间，但只有当它强到足以覆盖交易成本时，才值得进入；进入后也不要因为轻微信号回落就立刻退出。

小市值桶表现更好，说明 moneyflow edge 很可能不是纯粹“全市场聪明钱”效应，而是更接近：

```text
information advantage + liquidity/attention constraint + small-size market structure
```

也就是说：

1. 小市值股票更容易被局部资金流改变边际定价。
2. 资金流集中度和方向在小市值里更可能代表真实边际买盘，而不是全市场噪声。
3. 慢资金或没有信息优势的资金在小市值里反应更慢，给了 V7 state 一个可观测窗口。

这可以写成：

$$
\Delta P_{i,t+1}
=
\lambda(size_i, liquidity_i)
\cdot
H_{i,t}
+
\varepsilon_{i,t+1}
$$

其中：

- $H_{i,t}$：V7 的 hysteretic Fisher moneyflow state。
- $\lambda(size_i, liquidity_i)$：资金流状态转化为未来收益的价格弹性。
- 小市值 / 较低流动性股票中，$\lambda$ 可能更高。

## 数学机制解释

V7 的核心状态：

$$
H_{i,t}
=
\lambda_H H_{i,t-1}
+
(1-\lambda_H)\Delta m_{i,t}\sqrt{\mathcal I_{i,t}}
$$

其中：

- $m_{i,t}$：latent moneyflow state。
- $\Delta m_{i,t}$：资金流状态创新。
- $\mathcal I_{i,t}$：Fisher-style 信息精度。
- $H_{i,t}$：带记忆的可交易资金流状态。

分桶结果说明，下一步不应把 $H_{i,t}$ 一刀切用于全市场，而应允许成本边界和信号弹性依赖 size/liquidity bucket：

$$
B^{enter}_{i,t}
=
B^{base}_{bucket,t}
+
\eta_C C_{i,t}
$$

$$
\Phi_{i,t}
=
H_{i,t}
\cdot
\mathbf 1
\left\{
|H_{i,t}| > B^{enter}_{bucket,t}
\ \text{or}\
\left(
position_{i,t-1}\neq 0
\land
|H_{i,t}| > B^{exit}_{bucket,t}
\right)
\right\}
$$

其中：

- $B^{enter}_{bucket,t}$：按 size/liquidity bucket 调整后的进入阈值。
- $B^{exit}_{bucket,t}$：退出阈值。
- $B^{enter}>B^{exit}$：保留 hysteresis，避免反复换手。

## Decile 观察

全市场 OOS：

```text
D1 annualized_return = -21.35%
D6-D10 mostly positive
D10 annualized_return = 12.42%
```

小市值 OOS：

```text
D1 annualized_return = -10.52%
D5-D10 all positive
D10 annualized_return = 22.83%
```

小市值 OOS 的高分组收益明显更强，但不是严格 D1 到 D10 单调递增。更像是：

```text
low-score names are bad
middle-high score names are broadly good
top-score is good but not uniquely dominant
```

这意味着下一版不一定要继续追求 top decile 更尖锐，而应考虑：

1. 排除低分组 / 负状态；
2. 在 D5-D10 中降低换手；
3. 用流动性和成本边界决定是否进入；
4. 不要过度惩罚持久 state。

## 当前判断

V7 现在应升级为：

```text
incumbent = true
promotion = false
next_research_focus = small20 / bucket-aware V7
```

它不是全市场可直接推广的 alpha，但已经具备继续研究价值。

## 下一步建议

优先顺序：

1. 用正式 wrapper 生成一个 V7 small-size bucket diagnostic branch，而不是直接改公式。
2. 验证小市值 OOS 的 NAV、turnover、capacity、回撤恢复是否稳定。
3. 如果稳定，再做 V9：

```text
V9 = V7 hysteretic Fisher state
     + size/liquidity bucket-specific cost boundary
     + mild quality weight
     - no strong stale decay
```

不建议：

```text
continue V8 stale decay
promote V7 full universe
add more hard filters before confirming edge source
```
