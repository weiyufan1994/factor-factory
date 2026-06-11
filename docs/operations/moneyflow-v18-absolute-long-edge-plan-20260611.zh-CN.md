# Moneyflow V18 多分支研究计划

日期：2026-06-11

范围：研究侧机制记录，不是 alpha 结论；不启动 clean data、search_worker 或 official promotion。

## 1. 上一轮证据

V15 当前是最近一组 moneyflow 分支里最好的 baseline。它有稳定排序信息，但 long side 仍弱：

- `rank_ic_mean`: `0.045943724604180905`
- `rank_ic_ir`: `0.5912055170098856`
- `long_side_annual_return`: `-0.0022432925846382983`
- `long_side_sharpe`: `-0.00959288578845138`
- `max_drawdown`: `-0.6355132721147592`

这说明 V15 更像是相对排序状态，而不是可直接买入的正收益状态：

$$
\mathbb{E}[r_{i,t+1}\mid S^{V15}_{i,t}\text{ high}]
>
\mathbb{E}[r_{i,t+1}\mid S^{V15}_{i,t}\text{ low}]
$$

但它没有证明：

$$
\mathbb{E}[r_{i,t+1}\mid S^{V15}_{i,t}\text{ high}] > 0
$$

因此 V18 不再把 V15 当最终买入分数，而是把它当作 latent repair state，再追加 long-side gate。

## 2. 经济假设

我们要买入的不是“资金流异常”本身，而是：

> profit payers 正在卖出或被动提供供给，但该供给被更有信息或更有耐心的资金吸收；同时该股票还没有进入拥挤追涨状态，所以下一段上涨通道仍然打开。

对应三个必要条件：

1. `repair`: 资金流修复确认，卖压衰减，买方吸收有效。
2. `tradable`: 不是极端微盘，也不是大市值钝化资产；流动性足够承接但没有过热。
3. `long edge`: 上行 first-passage payoff 大于下行 breakdown payoff 和交易成本。

## 3. 随机过程

设 $X_{i,t}$ 是股票 $i$ 在 $t$ 后的短期可交易收益状态，$H_{i,t}$ 是 V15 推出的 latent repair / absorption state，$C_{i,t}$ 是 crowding / overheat state，$L_{i,t}$ 是 liquidity / tradability state。

工作模型：

$$
dX_{i,t}
=
\left(
\mu_0
+ aH_{i,t}
+ bL_{i,t}
- cC_{i,t}
- k\mathrm{Cost}_{i,t}
\right)dt
+ \sigma_{i,t}dW_{i,t}
$$

V15 的问题是只强化了 $H_{i,t}$ 的横截面排序，没有要求 drift 进入正区间。V18 的硬约束是：

$$
\mu^{\mathrm{long}}_{i,t}
=
\mu_0+aH_{i,t}+bL_{i,t}-cC_{i,t}-k\mathrm{Cost}_{i,t}
>0
$$

只有满足这个正 drift 条件的 repair state 才能成为 long-side signal。

## 4. First-Passage 形式

V18B 进一步把买入问题写成 hitting payoff：

$$
\tau_{\mathrm{up}}
=
\inf\{s>t:P_{i,s}\ge U_{i,t}\}
$$

$$
\tau_{\mathrm{down}}
=
\inf\{s>t:P_{i,s}\le D_{i,t}\}
$$

$$
\mathrm{Edge}_{i,t}
=
\mathbb{P}(\tau_{\mathrm{up}}<\tau_{\mathrm{down}}\mid\mathcal{F}_t)(U_{i,t}-P_{i,t})
-
\mathbb{P}(\tau_{\mathrm{down}}<\tau_{\mathrm{up}}\mid\mathcal{F}_t)(P_{i,t}-D_{i,t})
-
\mathrm{Cost}_{i,t}
$$

这里 $U_{i,t}$ 不是价格轴 VP target 的正式版本，因为当前 V18 还没有切到 `intraday_value_occupation_state_v1`；本轮先用 V15 repair/absorption、tail asymmetry、overheat 和 volatility shape 构造 proxy。若 V18B 有改善，再迁移到 occupation-measure / VP first-passage。

## 5. 三个分支

### V18A: absolute long edge gate

Law:

```text
miller_flow_v18a_absolute_long_edge_gate_v1
```

目的：在 V15 sorting state 上增加正 drift / 可买门槛。

形式：

$$
S^{18A}_{i,t}
=
\mathrm{Margin}^{+}_{i,t}
\cdot
G^{\mathrm{long}}_{i,t}
\cdot
G^{\mathrm{tradable}}_{i,t}
-
\mathrm{Crowding}_{i,t}
$$

预期：long side annual return 和 Sharpe 应优先改善，即使 IC 小幅下降也可接受。

### V18B: first-passage repair edge

Law:

```text
miller_flow_v18b_first_passage_repair_edge_v1
```

目的：把 buy/sell 决策变成上行 hitting probability 乘上行距离，减去下行 hitting probability 乘下行距离。

形式：

$$
S^{18B}_{i,t}
=
p^{\mathrm{up}}_{i,t}d^{\mathrm{up}}_{i,t}
-
p^{\mathrm{down}}_{i,t}d^{\mathrm{down}}_{i,t}
-
\mathrm{Cost}_{i,t}
$$

预期：减少“方向变化 detector”误买，提高 top decile 的绝对收益。

### V18C: crowding-filtered smart repair

Law:

```text
miller_flow_v18c_crowding_filtered_repair_v1
```

目的：区分“聪明钱早期吸收”和“拥挤追涨”。V15 的 confirmed absorption 如果同时伴随高 overheat / 高 crowding，则更可能是拥挤而不是待涨。

形式：

$$
S^{18C}_{i,t}
=
H^{+}_{i,t}
\cdot
G^{\mathrm{smart}}_{i,t}
\cdot
G^{\mathrm{tradable}}_{i,t}
-
\mathrm{Crowding}_{i,t}
$$

预期：long side drawdown 和 cost-adjusted return 应改善；如果 IC 下降但 long-side payoff 改善，也保留继续研究价值。

## 6. 本地 registry proof

`scripts/run_factorforge_step3_law_qlib_knowledge_smoke.py` 已验证新增 laws 可以 resolve、hash、执行小样本：

- V18A `code_law_hash`: `249ada613bdc32d1512381b12aa861a71212bfcb73e624b245ab5f9bc2519905`
- V18B `code_law_hash`: `6d157309cf4fea5014bfd87eaafefe98cead2c496bb8caba0440da634bd25d2b`
- V18C `code_law_hash`: `42a39843f62c351282ce7e5d99471d188318a2229d491d53058efb4caaf22f23`

## 7. Kill Criteria

任一分支若出现以下情况，应停止该分支：

1. `rank_ic_mean <= V15 - 0.01` 且 long-side annual return 未改善。
2. top decile 仍不能战胜 market / benchmark proxy。
3. max drawdown 没有改善或继续深于 `-35%`，且没有显著 IC 提升。
4. cost-adjusted annual return 仍显著为负。
5. 分支只是复制 size / liquidity / momentum 暴露，不能证明增量。

