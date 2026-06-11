---
report_id: "VP_SUPPORT_OVERHANG_BELOW_COST_GUARD_202401"
factor_id: "vp_support_overhang_below_cost_guard"
decision: "iterate"
iteration_no: 1
run_status: "limited_research_smoke_success"
final_status: "exploratory_smoke"
tags:
  - "research_iteration"
  - "index_enhancement_hypothesis"
  - "intraday"
  - "support_overhang"
---

# VP Support-Overhang Below-Cost Guard Research Iteration

## Research Verdict

沉淀为指增研究线索，但不写成正式 validated 因子，也不写成已成立的指增候选。

当前最重要的经验是：

- `below_cost_depth` 裸信号是反向的；
- `support_minus_overhang = lower_support_ratio - upper_overhang_ratio` 是更可靠主体；
- below-cost 应降级为 guard / value-trap control；
- 该因子更像相对抗跌和短期修复排序，适合指增 stock selection。

## Evidence Surface

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

主信号 `support_minus_overhang`:

| horizon | rank IC | top10 excess | top-bottom |
| --- | ---: | ---: | ---: |
| 1D | 0.189 | 0.883% | 1.057% |
| 3D | 0.168 | 1.501% | 2.612% |
| 5D | 0.040 | 2.058% | 1.638% |

裸 `below_cost_depth`:

| horizon | rank IC | top10 excess | top-bottom |
| --- | ---: | ---: | ---: |
| 1D | -0.229 | -0.813% | -1.229% |
| 3D | -0.188 | -1.627% | -6.267% |
| 5D | -0.059 | -2.441% | -6.295% |

## Research Lesson

不要把“低于成本”理解成均值回归买点。低于成本如果没有价格轴下方支撑和上方套牢释放，经常是继续下跌的状态。真正可交易的对象是价格轴 occupation measure 的支撑/阻力不对称：

```text
lower_support_ratio - upper_overhang_ratio
```

当前证据窗口只有 2024-01 的 22 个交易日，因此所有指标只能作为 full-window 研究优先级排序，不作为生产或指增结论。

## Required Next Action

进入 production 研究前必须先有 Data API 预处理：

```text
dataset_id = intraday_value_occupation_state_v1
unique_key = ts_code + trade_date + cutoff_time + lookback_days
```

正式评估要求：

- full-window IS through 2025-07-11;
- 1D / 3D / 5D horizon;
- top bucket excess and long-side cost-adjusted return;
- large-cap and CSI-style universe diagnostics;
- size/industry residual IC;
- turnover and capacity diagnostics.

## Full-Window Blocker

2026-06-10 worker cache probe:

```text
ssm_command_id = 1cdd1b13-e752-4fc4-974b-8937af378294
IS daily dates = 2,313
cached minute IS partitions = 384
missing minute IS partitions = 1,929
coverage_ratio = 16.6%
```

This is not enough for full-window validation. The next production step is a Data API/datamart backfill for `intraday_value_occupation_state_v1`, after which Step4 can evaluate the filtered index-enhancement universe.

## Links

- [[普通因子库/VP_SUPPORT_OVERHANG_BELOW_COST_GUARD_202401|Library Record]]
- Research note: `docs/operations/value-occupation-long-side-research-20260610.zh-CN.md`
- Full-window test plan: `docs/operations/vp-support-overhang-full-window-test-plan-20260610.zh-CN.md`
