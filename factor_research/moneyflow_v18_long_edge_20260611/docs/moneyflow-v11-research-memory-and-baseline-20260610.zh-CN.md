# Moneyflow V11 研究记忆与基线确认

日期：2026-06-10

对象：Factor Forge researcher / Council / 架构师 / 后续 reviewer

## 结论先行

V11 目前不是已经证明的最佳结果；它是下一轮最值得验证的 challenger。

已证明的 incumbent 需要分两层看：

| 口径 | 当前最好版本 | 主要证据 | 解释 |
|---|---|---:|---|
| 最高 rank IC | V6 Fisher innovation ratio | rank IC 约 0.0452 | 排序信息最强，但 turnover 约 0.752，交易成本和回撤压力太大。 |
| 更均衡 exploit baseline | V9A hot-money preposition / profit-payer filter | rank IC 约 0.0405，long annual 约 14.8%，turnover 约 0.29 | 比 V6 更接近可交易状态，是 V11 必须击败的主基线。 |
| 稳健对照基线 | V3 / V5 posterior state | rank IC 约 0.0404 / 0.0407 | 证明 moneyflow latent state 有稳定信息，不应被 V8 式 stale penalty 过度杀掉。 |
| 已证伪分支 | V8 net-edge state decay | rank IC 约 0.0122 | 理论上更干净，但把 informed accumulation 的持久状态误杀了。 |

因此：

```text
V11_status = promising_challenger
V11_not_yet = proven_incumbent
must_compare_against = V6, V9A, V3, V5
primary_objective = improve rank IC and long-side economics
secondary_objective = turnover / cost control
```

## 已有研究经验

### 1. Moneyflow 不是 uncertainty 本身

Moneyflow 更准确地说是一个 observation channel：

$$
\mathrm{Flow}_{i,t}
=
f(
  \mathrm{informed\ pressure}_{i,t},
  \mathrm{opinion\ dispersion}_{i,t},
  \mathrm{forced\ demand}_{i,t},
  \mathrm{crowding}_{i,t},
  \mathrm{liquidity\ noise}_{i,t}
)
\;+\;
\varepsilon_{i,t}
$$

所以正资金流不能直接解释为 bullish。它可能是聪明钱吸筹，也可能是追高资金、公募受迫买入、乐观者定价、或小市值流动性噪声。

### 2. Miller 框架提供的是“分歧 + 做空受限 + 乐观者定价”

Miller-style intuition 可以压成：

$$
P_{i,t}
=
\mu_{i,t}
+
\sigma^{opinion}_{i,t}
\Phi^{-1}
\left(
1-\frac{S_{i,t}}{N_{i,t}}
\right)
$$

其中：

- $\mu_{i,t}$：平均估值。
- $\sigma^{opinion}_{i,t}$：意见分歧或不确定性。
- $S_{i,t}/N_{i,t}$：可卖出供给相对潜在买方的比例。
- $\Phi^{-1}(\cdot)$：右尾乐观者定价分位。

这给 moneyflow 的关键映射是：

$$
\mathrm{positive\ flow}
\neq
\mathrm{informed\ buying}
$$

更合理的拆分是：

$$
\mathrm{tail\ pressure}_{i,t}
=
\mathrm{informed\ pressure}_{i,t}
-
\mathrm{crowded\ optimistic\ pressure}_{i,t}
-
\mathrm{liquidity\ noise}_{i,t}
$$

### 3. V3/V5 的经验：latent state 有用，别每天重新下注

V3 的核心是把当天冲击变成状态：

$$
m_{i,t}
=
\rho m_{i,t-1}
+
(1-\rho)z_{i,t}
$$

再用 posterior quality 做 hold gate：

$$
\kappa_{i,t}
=
\frac{|m_{i,t}|}{\sigma_{\eta,i,t}+C_{i,t}+\epsilon}
$$

$$
\Phi_{i,t}
=
m_{i,t}\mathbf{1}\{\kappa_{i,t}>B\}
$$

经验结论：

- latent moneyflow state 确实有横截面排序信息；
- 交易频率过高会吞掉收益；
- 但过度追求低 turnover 会把真实状态也杀掉。

### 4. V8 的教训：不要把持久 informed accumulation 当成 stale

V8 试图惩罚陈旧状态：

$$
\Phi^{V8}_{i,t}
=
\mathrm{net\ edge}_{i,t}
\cdot
\mathrm{quality}_{i,t}
-
\mathrm{stale\ penalty}_{i,t}
$$

实证结果变差。核心教训：

如果资金是分批吸筹，真实信号本来就可能表现为：

$$
\text{persistent}
\quad
\text{low-noise}
\quad
\text{slow-moving}
$$

不能机械地把“持续”解释成“陈旧”。

### 5. 研究员2的 value-domain 样本给出的通用教训

VP / occupation-measure 的具体公式不是 V11 必须照抄的模板，但它给了一个更重要的研究纪律：

> 先选对随机对象，再压缩成因子表达式。

如果真实对象是价格轴上的占据测度：

$$
\mu_t(dp)
=
\sum_{s=t-L}^{t}
\mathrm{amount}_s
\delta(P_s-p)
$$

那把它过早压成均值、方差、$z$-score，会丢掉形状、空洞、边界、目标位和止损位。

V11 也必须遵守这个原则：distribution moments 可以用，但不能把“高阶矩”当成自动正确的数学对象。必须说明这些 moments 到底在代理什么市场行为。

## 2026-06-10 机制更新：repair-drift absorption，而不是 profit-payer gate

用户进一步澄清：long side 的目标不是机械筛“小市值 profit payer”，而是买入“profit payers 卖出的、但不是拥挤下跌/坏消息下跌”的股票。smart money 不一定主要存在于小微盘，后续应先测试 full universe 和剔除微盘/大市值后的 mid-core universe。

因此 V11 从 `distribution_shape_fixed_small` 更新为：

```text
repair-drift absorption model
```

它的合理问题不是“skewness / kurtosis 有没有统计显著”，而是：

当资金流状态 $m_{i,t}$ 存在时，日内 flow / return / volume 分布形状是否能区分：

1. informed accumulation；
2. crowded optimistic chasing；
3. liquidity noise；
4. forced demand；
5. small-size illiquidity effect。

### Stochastic calculus object

$$
dX_{i,t}
=
\left(
\mu_0
+\eta D_{i,t}
+\beta A_{i,t}
-\gamma C_{i,t}
-\nu N_{i,t}
\right)dt
+\sigma_{i,t}dW_{i,t}
$$

其中：

- $X_{i,t}=\log P_{i,t}$：可交易价格。
- $D_{i,t}=F_{i,t}-X_{i,t}$：相对潜在 fair value 的 repair space。
- $A_{i,t}$：卖压被吸收后的 absorption state。
- $C_{i,t}$：crowded chasing / optimistic-holder overpricing state。
- $N_{i,t}$：bad-selling / liquidity-noise state。

这里的目标是让 $\eta D_{i,t}+\beta A_{i,t}$ 大于 $\gamma C_{i,t}+\nu N_{i,t}$。也就是：

```text
被迫卖压造成折价
+ 有吸收
- 拥挤追涨
- 坏消息卖出 / 噪声下跌
```

### Expected return approximation

若 $D,A,C,N$ 在持有期 $h$ 内近似均值回复，则：

$$
\mathbb E_t[X_{i,t+h}-X_{i,t}]
\approx
w_DD_{i,t}
+w_AA_{i,t}
-w_CC_{i,t}
-w_NN_{i,t}
-\mathrm{cost}_{i,t}
$$

其中：

$$
w_D
=
\eta\frac{1-e^{-\kappa_D h}}{\kappa_D},
\qquad
w_A
=
\beta\frac{1-e^{-\kappa_A h}}{\kappa_A}
$$

因此 V11 的因子表达不应是 moments 加法器，而应是：

$$
\Phi^{V11}_{i,t}
=
w_D\widehat D_{i,t}
+w_A\widehat A_{i,t}
-w_C\widehat C_{i,t}
-w_N\widehat N_{i,t}
$$

其中：

- $\widehat D_{i,t}$：由前一日下跌、折价/修复空间、非上冲尾部构造。
- $\widehat A_{i,t}$：由负向 flow pressure、成交集中度、价格不继续崩溃构造。
- $\widehat C_{i,t}$：由正向 flow、正收益尾部、prior overheat 构造。
- $\widehat N_{i,t}$：由高 kurtosis、高 vol-of-vol、下行尾部、过度离散构造。

### 新增测试分支

```text
V11A = miller_flow_v11_repair_absorption_full_v1
V11B = miller_flow_v11_repair_absorption_mid_core_v1
V11C = miller_flow_v11_first_passage_lite_v1
```

V11A 在 full universe 上测试机制本身。V11B 剔除微盘和超大市值：

$$
\Omega^{mid}_{t}
=
\left\{
i:
M_{i,t}\ge 50{,}000,\
0.10 < \operatorname{rankpct}_t(M_{i,t}) \le 0.80
\right\}
$$

V11C 用 first-passage-lite 近似：

$$
\mathrm{Edge}_{i,t}
=
\mathbb P_t(\tau_{up}<\tau_{dn})U_{i,t}
-
\mathbb P_t(\tau_{dn}<\tau_{up})L_{i,t}
-
\mathrm{cost}_{i,t}
$$

当前实现用 `upside_hitting_proxy` 和 `downside_hitting_proxy` 近似这两个 hitting probability。

### 本地 adapter sample proof

```text
V11_ADAPTER_SAMPLE_ACCEPT
miller_flow_v11_repair_absorption_full_v1: non-null factor values
miller_flow_v11_repair_absorption_mid_core_v1: mid-core gate active
miller_flow_v11_first_passage_lite_v1: non-null factor values
```

## V11 需要打赢的基线

V11 不能只证明“比 parent 好”。它至少要和以下基线同表比较：

| baseline | 角色 | V11 需要证明什么 |
---|---|---|
| V6 Fisher innovation | 最高 IC 基线 | IC 接近或超过 V6，且 turnover/回撤显著更好。 |
| V9A hot-money preposition | 最重要 exploit baseline | long annual / long Sharpe / drawdown / turnover 至少不输，最好 IC 更高。 |
| V5 residualized posterior | 剥离 size/liquidity 对照 | V11 的 edge 不是纯 size/liquidity。 |
| V3 posterior hold gate | 状态模型底座 | V11 的 shape condition 是增量信息，不是破坏 latent state。 |

## 后续执行约束

1. full-window proof 只能在 true factor-research-worker / warm datamart 上跑，不在 Mac 冷扫 S3。
2. research split 固定：

```text
in_sample <= 2025-07-11
OOS holdout > 2025-07-11
```

3. 小市值空间固定：

$$
\Omega^{small}_t
=
\left\{
i:
M_{i,t}\ge 50{,}000,
\operatorname{rankpct}_t(M_{i,t})>0.10,
\operatorname{rankpct}_t(M_{i,t})\le 0.30
\right\}
$$

其中 $M_{i,t}$ 优先用 `circ_mv`，缺失时用 `total_mv`，单位为 Tushare `daily_basic` 的万元。

4. 不启动：

```text
clean data processing
search_worker
official promotion
```

5. 每轮 revision 必须沉淀：

```text
economic hypothesis
math mechanism
formula / direct-code mapping
baseline comparison
what was falsified
what remains promising
```

## 下一步建议

下一轮以 V11 作为 challenger branch，而不是 incumbent branch：

```text
parent_for_comparison = V9A / V6 / V5 / V3 evidence set
branch_to_test = V11 distribution-shape fixed-small informed-flow gate
success_condition = better long-side economics without losing rank IC
```

如果 V11 不能提升 long side 或 IC，应回到 V9A，继续做 profit-payer ecology / 龙头战法资金垄断方向，而不是继续堆 moments。
