# VP Support-Overhang Full-Window Test Plan

更新日期：2026-06-10

## 目标

把 2024-01 smoke 中发现的 value-domain / volume-profile 研究线索升级为正式 full-window 检验。

当前状态：

```text
library_status = exploratory_smoke
full_window_status = BLOCKED_DATASET_INCOMPLETE
```

阻塞原因：

```text
ssm_command_id = 1cdd1b13-e752-4fc4-974b-8937af378294
IS daily dates = 2,313
cached minute IS partitions = 384
missing minute IS partitions = 1,929
coverage_ratio = 16.6%
```

因此不能把当前 worker cache 直接当成 full-window。

## Universe

用户指定：剔除大市值和小微盘后的 universe。

默认测试口径：

```text
per trade_date:
  mcap_pct = rank(total_mv)
  keep 20% < mcap_pct < 90%
```

解释：

- 剔除最大 10% 大市值；
- 剔除最小 20% 小微盘；
- 保留中间 70% 股票；
- `total_mv` 缺失的股票不进入该 universe。

后续可增加敏感性：

```text
middle_80 = 10% < mcap_pct < 90%
middle_60 = 20% < mcap_pct < 80%
```

## Narrative / Hypothesis Branches

support-overhang imbalance 现在就一起测试，不等后面。

原因：

- 2024-01 smoke 已显示裸 `below_cost_depth` 是反向；
- 如果 full-window 只测 below-cost reversal，会把错误叙事继续放大；
- 正式检验应该把叙事作为可证伪分支，而不是事后解释。

并行测试三组：

### A. Naked below-cost

```text
below_cost_depth
```

预期：可能为负或 value-trap control。

### B. Below-cost guarded support

```text
below_cost_guarded_support =
  below_cost_depth_score
  * lower_support_ratio
  * (1 + absorption_confirmation)
  * no_break_gate
  - upper_overhang_ratio
```

预期：如果 below-cost 有用，必须在 lower support 和 no-break 条件下才有效。

### C. Support-overhang imbalance

```text
support_minus_overhang = lower_support_ratio - upper_overhang_ratio
```

可选：

```text
support_absorption_minus_overhang =
  lower_support_ratio * (1 + absorption_confirmation) - upper_overhang_ratio
```

预期：这是当前主叙事，解释为价格轴下方支撑和上方套牢的不对称。

## Required Data Product

需要 Data API/datamart 预处理：

```text
dataset_id = intraday_value_occupation_state_v1
unique_key = ts_code + trade_date + cutoff_time + lookback_days
source = minute_bar
coverage = 2016-01-04 to 2025-07-11
```

必要字段：

- `lower_support_ratio`
- `upper_overhang_ratio`
- `below_cost_depth`
- `below_cost_depth_score`
- `absorption_confirmation`
- `no_break_gate`
- `support_minus_overhang`
- `support_absorption_minus_overhang`
- `below_cost_guarded_support`
- `minute_count`
- `amount_total`
- `cutoff_time`
- `lookback_days`

## Evaluation

Horizon:

```text
1D, 3D, 5D
```

Portfolio diagnostics:

- rank IC mean / IR;
- top decile excess vs filtered universe;
- top-bottom spread as diagnostic only;
- long-side cost-adjusted return;
- turnover under 3D/5D rebalance;
- drawdown and recovery;
- size and industry residual IC if metadata is available.

Universe diagnostics:

- filtered middle universe: primary;
- full universe: reference;
- largest 10%: negative/control check;
- smallest 20%: excluded universe diagnostic.

## Decision Rule

Promote from `exploratory_smoke` to `candidate_factor` only if:

- support-overhang branch remains positive in full-window filtered universe;
- naked below-cost does not dominate the explanation;
- top decile excess survives costs or turnover-aware rebalance;
- results are not driven only by 2024-01 down-market regime.
