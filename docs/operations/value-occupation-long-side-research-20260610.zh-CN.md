# Value Occupation Long-Side Research Note

更新日期：2026-06-10

## 研究目标

本研究把用户提出的“从值域而不是时间域看价格和成交量分布”落到 Factor Forge 可执行形态。目标不是直接预测下一分钟，而是把 1 分钟 bar 预聚合成日频的价格轴 occupation state，再由日频因子做 3-5 天持有期选股。

## 数学对象

核心对象是价格轴上的成交额占用测度：

```text
mu_t(dp) = sum amount_s * delta(P_s - p), s <= t and trade_time_s <= cutoff_time
```

其中 `P_s` 先用 1 分钟 close 近似，`amount_s` 是分钟成交额。POC、VAH、VAL、HVN、LVN、下方支撑和上方套牢都应看作 `mu_t` 的函数，而不是滚动均值和标准差的替代名。

## 经济假设

Long side 的主体不是“便宜会涨”，而是：

1. 当前价低于窗口成交成本，存在 repair 空间；
2. 当前价下方有已成交密集区，形成防守/止损附近支撑；
3. 同一时间窗口内出现成交吸收或卖压衰竭；
4. 上方到目标区之间没有过重套牢盘，或者有 LVN vacuum；
5. 下方没有一侧尾部风险和流动性陷阱。

对应 payer 是被迫止损、追涨回补、或短期流动性提供不足下的反向修复资金；若没有吸收和不破位确认，低于成本只可能是继续下跌的 value trap。

## 原型字段

脚本：

```text
scripts/research_vp_occupation_state.py
```

研究 dataset 名称：

```text
intraday_value_occupation_state_v1
```

唯一键建议：

```text
ts_code + trade_date + cutoff_time + lookback_days
```

核心字段：

- `reference_price`
- `vwap_cost`
- `poc_price`
- `value_area_low`
- `value_area_high`
- `below_cost_depth`
- `below_cost_depth_score`
- `lower_support_mass`
- `upper_overhang_mass`
- `lower_support_ratio`
- `upper_overhang_ratio`
- `downside_lvn_gap`
- `upside_lvn_vacuum`
- `absorption_confirmation`
- `one_sided_downside_tail_risk`
- `illiquidity_trap_penalty`
- `reward_risk_proxy`
- `reward_risk_score`
- `no_break_gate`
- `defended_support_gate`
- `vp_below_cost_repair_v1`
- `support_minus_overhang`
- `support_absorption_minus_overhang`
- `vp_support_defense_repair_v1`
- `below_cost_guarded_support`
- `support_with_below_cost_cap`

## 当前组合律

`vp_below_cost_repair_v1` 是 gate-style repair score：

```text
below_cost_depth_score
* (1 + lower_support_ratio)
* (1 + absorption_confirmation)
* no_break_gate
* defended_support_gate
* log(1 + reward_risk_score)
* (1 + upside_lvn_vacuum)
- upper_overhang_ratio
- one_sided_downside_tail_risk
- illiquidity_trap_penalty
```

其中 `below_cost_depth_score = below_cost_depth * 100`。保留原始 `below_cost_depth` 用于解释，组合律使用 bps 化后的主体，避免 bps 级 repair 空间被 ratio 级惩罚项机械压扁。

`reward_risk_score = min(reward_risk_proxy, 5.0)`。保留原始 `reward_risk_proxy` 用于诊断，但组合律必须使用 capped 版本，避免 downside distance 接近 0 时出现几何奇点并支配排序。

这不是最终公式，只是为了验证“低于成本 + 成交吸收 + 不再破位”的 long-side 方向是否有可执行测度。

2024-01-02 单日 forward smoke 后，新增 support-first 变体：

```text
support_minus_overhang = lower_support_ratio - upper_overhang_ratio
support_absorption_minus_overhang =
  lower_support_ratio * (1 + absorption_confirmation) - upper_overhang_ratio
vp_support_defense_repair_v1 =
  support_absorption_minus_overhang * no_break_gate
  - one_sided_downside_tail_risk
  - 0.1 * illiquidity_trap_penalty
```

初步结论是：`below_cost_depth` 单独在 2024-01-02 截面为反向信号，深度 below-cost 更容易选到继续下跌；`lower_support_ratio - upper_overhang_ratio` 才是更稳定的价格域主体。后续应把 below-cost 降级为 repair 条件、风险提示或轻量 gating，而不是主 alpha。

## 本地 smoke

命令：

```text
python3 scripts/research_vp_occupation_state.py --fixture --output-dir /tmp/factorforge_vp_occupation_research_smoke
```

输出：

```text
/tmp/factorforge_vp_occupation_research_smoke/intraday_value_occupation_state_v1.parquet
/tmp/factorforge_vp_occupation_research_smoke/intraday_value_occupation_state_v1.summary.json
```

结果摘要：

- `row_count=12`
- `date_count=4`
- `ticker_count=3`
- 合成的“低于成本 + 尾盘吸收 + 未破位”样本排第一；
- 合成的“深度 below-cost 但已破位”样本因 `no_break_gate=0` 被压制。

真实 2024-01-02 单日 minute cache smoke：

```text
python3 scripts/research_vp_occupation_state.py \
  --minute-path /Users/humphrey/projects/factorforge-data-api-cache/s3_parquet/minute_bar-raw_v1-0b2b836c57d763c6/trade_date=20240102/part-000.parquet \
  --output-dir /tmp/factorforge_vp_occupation_research_20240102 \
  --lookback-days 1 \
  --cutoff-time 14:50:00
```

输出：

```text
/tmp/factorforge_vp_occupation_research_20240102/intraday_value_occupation_state_v1.parquet
/tmp/factorforge_vp_occupation_research_20240102/intraday_value_occupation_state_v1.summary.json
```

结果摘要：

- `row_count=5242`
- `date_count=1`
- `ticker_count=5242`
- 真实单日全市场读取和 VP occupation 聚合约 11 秒完成。

Forward return smoke：

```text
python3 scripts/research_vp_forward_eval.py \
  --vp-state /tmp/factorforge_vp_occupation_research_20240102/intraday_value_occupation_state_v1.parquet \
  --daily-clean /Users/humphrey/projects/factor-factory/data/clean/daily_clean.parquet \
  --output-dir /tmp/factorforge_vp_forward_eval_20240102 \
  --horizons 1,3,5 \
  --signals vp_below_cost_repair_v1,support_minus_overhang,support_absorption_minus_overhang,vp_support_defense_repair_v1,below_cost_guarded_support,support_with_below_cost_cap
```

输出：

```text
/tmp/factorforge_vp_forward_eval_20240102/vp_forward_eval_summary.json
/tmp/factorforge_vp_forward_eval_20240102/vp_forward_eval_merged.parquet
```

单日诊断摘要：

| signal | horizon | rank IC | top10 excess vs universe | top-bottom |
| --- | ---: | ---: | ---: | ---: |
| `vp_below_cost_repair_v1` | 1D | 0.193 | 0.132% | 0.671% |
| `vp_below_cost_repair_v1` | 3D | 0.273 | 0.606% | 1.530% |
| `vp_below_cost_repair_v1` | 5D | 0.312 | 1.248% | 2.740% |
| `support_minus_overhang` | 1D | 0.190 | 0.294% | 0.795% |
| `support_minus_overhang` | 3D | 0.289 | 1.019% | 1.977% |
| `support_minus_overhang` | 5D | 0.326 | 1.697% | 3.182% |
| `support_absorption_minus_overhang` | 1D | 0.188 | 0.278% | 0.779% |
| `support_absorption_minus_overhang` | 3D | 0.288 | 1.020% | 1.978% |
| `support_absorption_minus_overhang` | 5D | 0.326 | 1.718% | 3.203% |

市值分层单日诊断：

- 最大市值 10% 和 20% 中，support-overhang 的 3D/5D top10 excess 仍为正，且不弱于全市场；
- 最小市值 20% 中，support-overhang 的 1D/3D top10 excess 较弱，`vp_below_cost_repair_v1` 反而略好；
- 初步看这不是纯小票效应，更像大中市值里“下方成交支撑、上方套牢较轻”的相对防守/修复信号。

## Worker 2024-01 多日 smoke

本机 raw S3 下载 2024-01 缺失分区时，单个 `aws s3 cp` 在 60 秒以上无输出，确认 Mac 冷补 cache 不适合多日研究。随后改用 true factor-research-worker 的 warm minute cache。

worker：

```text
i-02cc0b6e93856fbb4
factor-research-worker
```

cache probe：

```text
ssm_command_id = a0883139-42f6-4402-aaef-1b717471b9fb
2024-01 cached minute partitions = 22 trading days
```

多日 smoke：

```text
ssm_command_id = bf631f78-7a83-4a24-82db-86f2a5e1b057
worker_output_path = /tmp/factorforge_vp_worker_202401_support_smoke.json
state_rows = 115,521
merged_rows = 99,714
date_count = 22
ticker_count = 4,590
seconds = 147.413
```

该 worker 临时脚本只验证 support-overhang 主体，没有写 catalog，没有写 production datamart，也没有启动正式 Factor Forge loop。

结果摘要：

| signal | horizon | rank IC | universe mean | top10 mean | top10 excess | top-bottom |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| `support_minus_overhang` | 1D | 0.189 | -1.017% | -0.134% | 0.883% | 1.057% |
| `support_minus_overhang` | 3D | 0.168 | -3.692% | -2.192% | 1.501% | 2.612% |
| `support_minus_overhang` | 5D | 0.040 | -6.066% | -4.008% | 2.058% | 1.638% |
| `support_absorption_minus_overhang` | 1D | 0.185 | -1.017% | -0.206% | 0.812% | 0.983% |
| `support_absorption_minus_overhang` | 3D | 0.163 | -3.692% | -2.488% | 1.205% | 2.317% |
| `support_absorption_minus_overhang` | 5D | 0.040 | -6.066% | -4.079% | 1.987% | 1.571% |
| `below_cost_depth` | 1D | -0.229 | -1.017% | -1.831% | -0.813% | -1.229% |
| `below_cost_depth` | 3D | -0.188 | -3.692% | -5.320% | -1.627% | -6.267% |
| `below_cost_depth` | 5D | -0.059 | -6.066% | -8.507% | -2.441% | -6.295% |

按日稳定性，`support_minus_overhang`：

| horizon | IC positive rate | top10 excess positive rate | top-bottom positive rate |
| --- | ---: | ---: | ---: |
| 1D | 59.1% | 68.2% | 54.5% |
| 3D | 63.6% | 72.7% | 72.7% |
| 5D | 68.2% | 77.3% | 72.7% |

研究结论更新：

- `support_minus_overhang` 是当前更好的主因子主体；
- `support_absorption_minus_overhang` 没有明显优于纯 support-overhang，absorption 应先作为辅助确认或 regime gate，而不是强乘数；
- `below_cost_depth` 单独是明确反向信号，应避免作为正向主体；
- 这个因子在 2024-01 的下跌环境中更像“相对抗跌/修复排序”，top10 绝对收益仍可能为负，必须在正式 Step4 中看 benchmark-relative、long-only cost-adjusted 和 drawdown。

## 信息集边界

- 当前原型只使用 `trade_time <= cutoff_time` 的分钟 bar。
- 正式 production dataset 必须记录 `cutoff_time`。
- 正式 join、dedupe、QA 必须包含 `ts_code + trade_date + cutoff_time + lookback_days`。
- full-window 研究不得每轮直接扫 raw `minute_bar`；应先 worker backfill 成 partitioned parquet datamart。

## 下一步

1. 用 deterministic fixture 验证公式和字段方向。
2. 在 worker 上用代表日期读取 `minute_bar`，生成小样本 `intraday_value_occupation_state_v1` proof。
3. 加 Data API catalog entry、QA json、worker read smoke。
4. Factor Forge Step3/Step4 消费该日频 datamart，测试 1D、3D、5D forward return，重点看 long-side cost-adjusted return、Sharpe、drawdown、turnover，而不是只看 long-short。
