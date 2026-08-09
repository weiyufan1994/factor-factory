# Moneyflow V11/V15 Portfolio Policy 研究沉淀

日期：2026-06-13

性质：研究侧沉淀，不是 official promotion；没有启动 clean data、search_worker 或官方因子入库。

## 1. 本轮研究对象

本轮使用已有 `intraday_flow_distribution_moments_v1` / `intraday_flow_state_v2` / `daily_basic_backtest_base_is` datamart，对 Miller moneyflow V11/V15 的可交易组合策略做研究侧评估。

主要结果路径：

- 本地结果：`/tmp/moneyflow_v11_portfolio_policies_20260612_exec/`
- S3 结果：`s3://yufan-data-lake/factorforge/tmp/moneyflow_v11_20260612/portfolio_policies/`
- 研究脚本：`scripts/research_moneyflow_v11_datamart_eval.py`
- worker wrapper：`scripts/run_moneyflow_portfolio_policy_worker.sh`

注意：在本文件写入前，上述结果主要存在于 `/tmp`、临时 S3 和未跟踪脚本中，不能算完整知识沉淀。

## 2. 重要纠偏

早期 portfolio proxy 曾错误使用 `fwd_5d` 作为逐日组合收益，导致组合收益被放大。该结果已废弃。

当前可采信的组合评估使用：

$$
r_{i,t+1}=\frac{P_{i,t+1}}{P_{i,t}}-1
$$

即 next-day close-to-close executable return。持仓策略只改变调仓和留存，不改变因子值本身。

## 3. 经济假设

V11/V15 的核心假设不是“资金流越正越好”，而是：

> 当卖方压力已经出现，但价格没有继续恶化，且盘中资金流/尾部结构显示吸收和修复时，股票可能处于 profit payer 卖出后的待涨状态。

换成市场参与者语言：

- profit payer：无信息优势、流动性约束、赎回/风控压力、或被动跟随信息发酵后交易的人；
- potential informed buyer：在拥挤前吸收供给、但尚未把价格推成过热状态的资金；
- 错误场景：追涨拥挤、坏的下跌惯性、纯噪声高波动、微盘流动性幻觉。

## 4. Dirac-style 数学机制

V15 当前对应的随机过程框架可以写成：

$$
dP_t = \mu_t dt + \sigma_t dW_t
$$

其中价格漂移 $\mu_t$ 不直接由净买入决定，而由一个 latent absorption/repair state 决定：

$$
\mu_t = g(H_t, C_t, B_t)
$$

其中：

- $H_t$：confirmed absorption / repair state；
- $C_t$：crowding or chasing state；
- $B_t$：bad selling / breakdown state。

V15 主要在估计：

$$
\Delta H_t > 0
$$

也就是“吸收/修复状态是否正在改善”。这解释了为什么 V15 有排序信息，但不一定足够直接识别上涨。

更强的 long-side 目标应当是 first-passage payoff：

$$
\text{long\_edge}
=
\mathbb{P}(\tau_{\text{up}}<\tau_{\text{down}}\mid \mathcal{F}_t)D_{\text{up}}
-
\mathbb{P}(\tau_{\text{down}}<\tau_{\text{up}}\mid \mathcal{F}_t)D_{\text{down}}
-
\text{cost}
$$

其中：

- $\tau_{\text{up}}$：先触及上方目标/修复目标的时间；
- $\tau_{\text{down}}$：先跌破下方防守区的时间；
- $D_{\text{up}}$：上行空间；
- $D_{\text{down}}$：下行止损距离。

因此后续表达式应该从“状态变化检测器”进化成“上涨 first-passage detector”。

## 5. 已知结果

组合策略中，`top10_dropout30_rebalance5_equal` 最有价值。它相当于：

- 买入 top 10%；
- 只要持仓没有跌出 top 30%，就继续持有；
- 每 5 日做一次 rebalance；
- 等权持仓。

它把日度 top10 策略的 turnover 从约 `0.83-0.85` 降到约 `0.14-0.15`。

代表性结果：

| law | universe | policy | net_return_mean | turnover | net_sharpe_proxy | max_drawdown_proxy | nav_final_proxy | date_count |
| --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| V15 | csi2000 | top10_dropout30_rebalance5_equal | 0.001152 | 0.139730 | 0.974126 | -0.367158 | 1.508094 | 446 |
| V15 | smallest_20 | top10_dropout30_rebalance5_equal | 0.000846 | 0.148486 | 0.817220 | -0.462782 | 4.648145 | 2302 |
| V15 | fixed_small_20 | top10_dropout30_rebalance5_equal | 0.000606 | 0.149859 | 0.577612 | -0.412417 | 2.722338 | 2302 |
| V15 | csi_all_share | top10_dropout30_rebalance5_equal | 0.000314 | 0.137956 | 0.320585 | -0.432844 | 1.557226 | 2284 |
| V15 | middle_10_80 | top10_dropout30_rebalance5_equal | 0.000291 | 0.139874 | 0.282245 | -0.426234 | 1.418961 | 2303 |

解释：

- `csi2000` 表现最好，但覆盖只有 446 天，不能作为长期结论；
- `smallest_20` 长历史表现强，但包含更多微盘/极小盘暴露；
- `fixed_small_20` 更适合作为长期小市值研究口径；
- `full`、`middle_10_80`、`csi_all_share` 有正收益但强度较弱；
- `csi800` / `csi800+csi1000` 弱，说明该机制更偏中小市值/交易结构，而不是大中盘基本面资金。

## 6. 不能重复的反模式

1. 不能再用 `fwd_5d` 直接当逐日 portfolio return。
2. 不能只看 top decile spread，因为高 turnover 会把超额全部吃掉。
3. 不能把 `rank_ic_mean` 当成可交易收益，V11/V15 更像排序型状态信号。
4. 不应继续只做 portfolio repair；表达式本身还要增强上涨方向识别。
5. `CSI2000` 可作为参考，但覆盖不足时不能替代长期 fixed small universe。

## 7. 下一步

下一步沿 V18 first-passage 方向测试：

- 加入已有 registry 中的 `miller_flow_v18a_absolute_long_edge_gate_v1`；
- 加入 `miller_flow_v18b_first_passage_repair_edge_v1`；
- 加入 `miller_flow_v18c_crowding_filtered_repair_v1`；
- universe 固定新增：
  - `fixed_small_10`：市值 >= 5 亿、剔除每日最小 10% 后，取最小 10%；
  - `fixed_small_20`：市值 >= 5 亿、剔除每日最小 10% 后，取最小 20%。

评估重点：

- long-side net return 是否强于 V15；
- rank IC 是否保留；
- Pearson IC 是否与 rank IC 分化；
- turnover 是否仍依赖 `top10_dropout30_rebalance5_equal`；
- fixed-small 结果是否比 CSI2000 更适合作为长期结论。
