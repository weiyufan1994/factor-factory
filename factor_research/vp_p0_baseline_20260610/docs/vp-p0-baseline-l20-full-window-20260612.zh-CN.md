# VP P0 L20 Baseline Full-Window Test

日期：2026-06-12

## 状态

```text
research_status = baseline_completed
dataset = intraday_value_occupation_state_v1
datamart_status = accepted_p0_state_only
factor_status = exploratory_baseline_only
promotion = no
```

本轮只做 B0 baseline，不加入 momentum、price-volume corr、persistence、Barra neutralization。

## 输入和执行

```text
vp_datamart = s3://yufan-data-lake/factorforge/datamart/intraday_value_occupation_state/v1
daily_clean = s3://yufan-data-lake/factorforge/datamart/clean_daily_bar/v1/daily_clean.parquet
window = 20160104-20250711
vp_rows = 9,105,107
vp_dates = 2,312
merged_rows = 8,026,806
merged_dates = 2,312
merged_tickers = 5,004
horizons = 1D, 3D, 5D
cost_bps = 20
```

Worker run:

```text
instance = i-02cc0b6e93856fbb4
ssm_command_id = 431629bc-f231-4a4f-b626-fbe6123510bb
runtime = 14m28s
```

Artifacts:

```text
s3_metrics = s3://yufan-data-lake/factorforge/tmp/vp_p0_baseline_20260612/fast_full/vp_p0_baseline_metrics.csv
s3_summary = s3://yufan-data-lake/factorforge/tmp/vp_p0_baseline_20260612/fast_full/vp_p0_baseline_summary.json
s3_run_log = s3://yufan-data-lake/factorforge/tmp/vp_p0_baseline_20260612/fast_full/run.log
local_metrics = /tmp/factorforge_vp_p0_baseline_fast_full_20260612_local/vp_p0_baseline_metrics.csv
local_summary = /tmp/factorforge_vp_p0_baseline_fast_full_20260612_local/vp_p0_baseline_summary.json
```

Note: worker 缺 `tabulate`，所以 markdown compact table 没生成；CSV/JSON 已成功写出和上传。

## Signals

P0 datamart 保持 state-only。以下组合都在研究侧临时构造：

```text
support_minus_overhang = lower_support_ratio - upper_overhang_ratio
lower_support_mass = lower_support_ratio
upper_overhang_mass_neg = -upper_overhang_ratio
below_cost_depth_score_raw = below_cost_depth_score
below_cost_guarded_support_p0 = below_cost_depth_score * lower_support_ratio * no_break_gate - upper_overhang_ratio
support_with_below_cost_cap_p0 = lower_support_ratio * (1 + clip(below_cost_depth_score, 0, 2)) * no_break_gate - upper_overhang_ratio
```

Universe:

```text
full
middle_20_90 = 20% < total_mv rank pct < 90%
largest_10 = top 10% by total_mv
smallest_20 = bottom 20% by total_mv
```

## 关键结果

### Middle universe

用户指定的主诊断 universe 是剔除最大 10% 和最小 20% 后的 `middle_20_90`。

| signal | horizon | rank IC | top decile excess | net top decile excess |
| --- | ---: | ---: | ---: | ---: |
| `below_cost_depth_score_raw` | 1D | 0.0265 | 0.015% | -0.029% |
| `below_cost_depth_score_raw` | 3D | 0.0214 | 0.029% | -0.015% |
| `below_cost_depth_score_raw` | 5D | 0.0207 | 0.036% | -0.008% |
| `lower_support_mass` | 1D | 0.0140 | 0.047% | -0.043% |
| `lower_support_mass` | 3D | 0.0243 | 0.053% | -0.037% |
| `lower_support_mass` | 5D | 0.0265 | 0.050% | -0.039% |
| `support_minus_overhang` | 1D | -0.0143 | 0.009% | -0.100% |
| `support_minus_overhang` | 3D | -0.0070 | 0.005% | -0.104% |
| `support_minus_overhang` | 5D | -0.0057 | -0.005% | -0.113% |
| `below_cost_guarded_support_p0` | 1D | -0.0144 | -0.001% | -0.098% |
| `below_cost_guarded_support_p0` | 3D | -0.0159 | -0.027% | -0.124% |
| `below_cost_guarded_support_p0` | 5D | -0.0162 | -0.049% | -0.146% |

Interpretation:

```text
1. support_minus_overhang 不是好的 B0 主体；IC 为负，扣 turnover cost 后更弱。
2. below_cost_depth_score_raw 有稳定正 IC，但 top-decile excess 很薄，全窗口扣简单换手成本后仍为负。
3. lower_support_mass 的 3D/5D IC 比 1D 更强，符合 support barrier / first-passage 方向，但换手太高。
4. below_cost_guarded_support_p0 把 below-cost、support、no-break、overhang 线性相乘/相减后反而变差。
```

### Full universe

Full universe 与 middle universe 结论一致：

| signal | horizon | rank IC | top decile excess | net top decile excess |
| --- | ---: | ---: | ---: | ---: |
| `below_cost_depth_score_raw` | 1D | 0.0250 | 0.010% | -0.033% |
| `below_cost_depth_score_raw` | 3D | 0.0194 | 0.019% | -0.024% |
| `below_cost_depth_score_raw` | 5D | 0.0189 | 0.027% | -0.016% |
| `lower_support_mass` | 1D | 0.0149 | 0.042% | -0.046% |
| `lower_support_mass` | 3D | 0.0251 | 0.043% | -0.046% |
| `lower_support_mass` | 5D | 0.0270 | 0.032% | -0.056% |
| `support_minus_overhang` | 1D | -0.0110 | 0.009% | -0.097% |
| `support_minus_overhang` | 3D | -0.0030 | 0.001% | -0.105% |
| `support_minus_overhang` | 5D | -0.0013 | -0.008% | -0.114% |

### Size diagnostics

Largest 10%:

```text
lower_support_mass:
  3D rank_ic = 0.0233, net_top_decile_excess = 0.006%
  5D rank_ic = 0.0254, net_top_decile_excess = 0.047%

support_minus_overhang:
  5D rank_ic = 0.0056, net_top_decile_excess = -0.008%
```

Smallest 20%:

```text
below_cost_depth_score_raw:
  3D rank_ic = 0.0267, net_top_decile_excess = 0.003%
  5D rank_ic = 0.0275, net_top_decile_excess = 0.034%

lower_support_mass:
  IC positive, but net top-decile excess negative.
```

Size conclusion:

```text
1. 大市值里 lower_support_mass 的 3D/5D long side 稍微能过简单成本，但幅度很小。
2. 小市值里 below_cost_depth_score_raw 的 3D/5D 有轻微正 net，但这是 bottom 20% 诊断，不等于可直接推进小微盘组合。
3. middle universe 中没有可直接交易的 B0 pure-long。
```

## Regime

Middle universe selected regimes:

```text
below_cost_depth_score_raw:
  all 1D/3D/5D IC = 0.0265 / 0.0214 / 0.0207
  post_20240924 1D/3D/5D IC = 0.0435 / 0.0450 / 0.0479
  post_20240924 net 3D/5D = 0.120% / 0.221%

lower_support_mass:
  all 1D/3D/5D IC = 0.0140 / 0.0243 / 0.0265
  post_20240924 1D/3D/5D IC = 0.0213 / 0.0352 / 0.0390
  post_20240924 net remains negative because turnover cost is high.

support_minus_overhang:
  all horizons IC negative.
  post_20240924 also negative.
```

Regime conclusion:

```text
1. below-cost depth 在 2024-09-24 之后明显增强，可能混有强反转/政策 beta/低位修复 regime。
2. lower support 的 IC 也在 post_20240924 增强，但 long-only net 被高换手吃掉。
3. support-overhang imbalance 叙事没有被 full-window production L20 数据支持。
```

## 数学和经济解释

### 被支持的部分

`lower_support_mass` 更像 occupation-measure / first-passage 变量：

```text
价格下方近邻区间的成交金额占比高
=> 当前价格附近有较厚的历史换手支撑
=> 下穿局部 barrier 的 first-passage intensity 较低
=> 3D/5D IC 比 1D 更强
```

这不是强多头收益定理，而是一个弱的下行风险缓冲 / 相对抗跌 state。

`below_cost_depth_score_raw` 更像 repair option：

```text
价格低于近期成交成本越深
=> 若没有继续破位，均值回复/修复空间越大
=> 但如果缺少 drift、persistence、volume absorption，就容易混入 falling knife
```

本轮 B0 没有加入“不再破位”和“吸收确认”，所以只能说明原子 state 有 IC，不说明纯多头已经可交易。

### 被否定的部分

`support_minus_overhang = lower_support - upper_overhang` 的线性叙事不成立。

数学原因：

```text
lower support mass 和 upper overhang mass 不是同一符号的可线性相减势能。
上方成交密度不一定是卖压，也可能是价格修复的目标区、流动性吸引区或趋势确认后的成交接力区。
```

因此把 `upper_overhang_ratio` 直接作为线性惩罚，会把有用的 lower support / below-cost repair 信息一起抵消。

## 结论

```text
B0 conclusion:
  usable_state = below_cost_depth_score_raw + lower_support_mass
  failed_story = support_minus_overhang as primary long factor
  pure_long_status = not_ready
  next_research = V18/V19 should add drift/persistence/price-volume confirmation
```

下一步不要把 `support_minus_overhang` 当主因子。更合理的 V18 方向：

```text
repair_base =
  z(below_cost_depth_score)
  + z(lower_support_mass)

gates:
  + 2-3d no-new-low / no-break persistence
  + mild positive residual momentum as semimartingale drift proxy
  + price-volume absorption / corr confirmation
  - downside tail / illiquidity trap guard

upper_overhang:
  do not use as linear penalty by default
  test only as nonlinear extreme guard or target-distance state
```

研究判断：

```text
1. 这个 datamart 值得复用。
2. B0 静态 state 有 IC，但不是直接正收益因子。
3. 增量测试必须对 momentum/reversal/Barra 做 residual IC，否则 below-cost 可能只是短反或 regime beta。
```
