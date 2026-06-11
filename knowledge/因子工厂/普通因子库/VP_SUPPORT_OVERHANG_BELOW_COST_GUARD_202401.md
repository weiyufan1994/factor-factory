---
report_id: "VP_SUPPORT_OVERHANG_BELOW_COST_GUARD_202401"
factor_id: "vp_support_overhang_below_cost_guard"
decision: "iterate"
iteration_no: 1
run_status: "limited_research_smoke_success"
final_status: "exploratory_smoke"
tags:
  - "factor"
  - "library_all"
  - "index_enhancement_hypothesis"
  - "intraday"
  - "volume_profile"
  - "support_overhang"
---

# VP Support-Overhang Below-Cost Guard

## Summary

- intended role: 指增选股增强研究线索，尚不是候选因子结论
- status: `exploratory_smoke`, not full-window validated
- primary horizon: `3D-5D`
- required data product: `intraday_value_occupation_state_v1`

## Factor Definition

主表达式：

```text
support_minus_overhang = lower_support_ratio - upper_overhang_ratio
```

可选确认表达式：

```text
support_absorption_minus_overhang =
  lower_support_ratio * (1 + absorption_confirmation) - upper_overhang_ratio
```

谨慎使用的 below-cost guard：

```text
below_cost_guarded_support =
  below_cost_depth_score
  * lower_support_ratio
  * (1 + absorption_confirmation)
  * no_break_gate
  - upper_overhang_ratio
```

不要把裸 `below_cost_depth` 当成正向主体。当前证据里，裸 below-cost 是反向信号。

## Economic Hypothesis

这不是“跌破成交成本就反转”的因子。核心机制是：

- 当前价下方近邻价格带有较厚成交额支撑；
- 当前价上方近邻价格带成交额较少，短期套牢/阻力较轻；
- 高分股票更像相对抗跌和修复排序，而不是立即绝对上涨；
- below-cost 只能作为 repair 条件或 value-trap 风险提示。

## Mathematical Object

价格轴成交额占用测度：

```text
mu_t(dp) = sum amount_s * delta(P_s - p), s <= t and trade_time_s <= cutoff_time
```

`lower_support_ratio`、`upper_overhang_ratio`、`below_cost_depth`、`absorption_confirmation` 都是该测度或其路径确认项的函数。

## Evidence

Limited worker 2024-01 smoke:

```text
worker_instance_id = i-02cc0b6e93856fbb4
ssm_command_id = bf631f78-7a83-4a24-82db-86f2a5e1b057
worker_output_path = /tmp/factorforge_vp_worker_202401_support_smoke.json
state_rows = 115,521
merged_rows = 99,714
date_count = 22
ticker_count = 4,590
elapsed_seconds = 147.413
```

| signal | horizon | rank IC | top10 excess | top-bottom |
| --- | ---: | ---: | ---: | ---: |
| `support_minus_overhang` | 1D | 0.189 | 0.883% | 1.057% |
| `support_minus_overhang` | 3D | 0.168 | 1.501% | 2.612% |
| `support_minus_overhang` | 5D | 0.040 | 2.058% | 1.638% |
| `support_absorption_minus_overhang` | 1D | 0.185 | 0.812% | 0.983% |
| `support_absorption_minus_overhang` | 3D | 0.163 | 1.205% | 2.317% |
| `support_absorption_minus_overhang` | 5D | 0.040 | 1.987% | 1.571% |
| `below_cost_depth` | 1D | -0.229 | -0.813% | -1.229% |
| `below_cost_depth` | 3D | -0.188 | -1.627% | -6.267% |
| `below_cost_depth` | 5D | -0.059 | -2.441% | -6.295% |

按日稳定性，`support_minus_overhang`：

| horizon | IC positive rate | top10 excess positive rate | top-bottom positive rate |
| --- | ---: | ---: | ---: |
| 1D | 59.1% | 68.2% | 54.5% |
| 3D | 63.6% | 72.7% | 72.7% |
| 5D | 68.2% | 77.3% | 72.7% |

## Interpretation

IC 高的不是裸 below-cost，而是价格轴支撑/套牢结构。`below_cost_depth` 的反向表现说明：

- 深度跌破成本经常意味着趋势破坏或流动性陷阱；
- 如果没有下方支撑和不破位确认，below-cost 更像 value trap；
- 指增使用时应优先使用 `support_minus_overhang`，并把 below-cost 作为辅助 guard。

当前样本窗口只有 2024-01 的 22 个交易日，且处于下跌/修复环境。该记录只能证明研究线索值得 full-window 验证，不能证明因子已适合生产指增。

## Suggested Index-Enhancement Usage

候选用法：

```text
score =
  rank(support_minus_overhang)
  + optional_small_weight * rank(no_break_gate * below_cost_guarded_support)
```

组合层面优先看：

- top bucket excess vs universe / benchmark;
- cost-adjusted long-side return;
- drawdown and recovery;
- turnover under 3D/5D rebalance;
- industry and size residual IC.

## Next Tests

1. 把 `intraday_value_occupation_state_v1` 交给 Data API/datamart 预处理。
2. 跑 full-window 2016-01-04 到 2025-07-11 Step4/Step5。
3. 单独测试 3D/5D 持有期、换手成本和大市值 universe。
4. 做 residualization：size、industry、turnover、volatility。

## Full-Window Readiness Check

2026-06-10 worker cache probe:

```text
ssm_command_id = 1cdd1b13-e752-4fc4-974b-8937af378294
IS daily dates = 2,313
cached minute IS partitions = 384
missing minute IS partitions = 1,929
coverage_ratio = 16.6%
```

因此当前记录仍必须停留在 `exploratory_smoke`。任何使用现有 worker cache 的扩展测试都只能标记为 `cached-IS diagnostic`，不能写作 full-window result。

## Links

- [[研究迭代/VP_SUPPORT_OVERHANG_BELOW_COST_GUARD_202401|Research Iteration]]
- Research note: `docs/operations/value-occupation-long-side-research-20260610.zh-CN.md`
- Full-window test plan: `docs/operations/vp-support-overhang-full-window-test-plan-20260610.zh-CN.md`
