# VP Cached-IS Toy Diagnostic

日期：2026-06-10

状态：

```text
research_status = toy_diagnostic_only
production_status = not_validated
factor_status = do_not_promote
```

## 目标

在 Data 组处理 `intraday_value_occupation_state_v1` production datamart 前，先用 worker 上已有的 cached minute partitions 做一个 toy diagnostic。目的不是替代 full-window validation，而是检查 2024-01 smoke 里的 support-overhang long-side 是否能在 cached sample 中继续站住。

## 执行记录

第一次尝试：

```text
scope = all cached IS dates
eligible cached IS dates = 384
status = stopped manually after about 2 hours
reason = no checkpoint / no progress artifact before final concat; CPU and IO were still progressing but runtime was not suitable for interactive toy diagnostic
```

第二次尝试改为均匀抽样：

```text
test_name = VP cached-IS diagnostic toy
sample_policy = evenly_spaced
eligible cached IS dates = 384
selected dates = 96
ready source dates = 96
lookback_days = 1
cutoff_time = 14:50:00
state_rows = 498,213
merged_rows = 420,405
merged_date_count = 96
merged_ticker_count = 4,947
cost_bps = 20
```

Artifacts：

```text
worker_output_dir = /tmp/factorforge_vp_cached_is_toy_even96_20260610
s3_summary = s3://yufan-data-lake/factorforge/tmp/vp_cached_is_toy_even96_20260610/vp_cached_is_toy_summary.json
s3_run_log = s3://yufan-data-lake/factorforge/tmp/vp_cached_is_toy_even96_20260610/run.log
s3_state = s3://yufan-data-lake/factorforge/tmp/vp_cached_is_toy_even96_20260610/intraday_value_occupation_state_v1.cached_is_toy.parquet
s3_merged = s3://yufan-data-lake/factorforge/tmp/vp_cached_is_toy_even96_20260610/vp_cached_is_toy_merged.parquet
local_summary = /tmp/vp_cached_is_toy_summary.json
```

## 关键结果

### Middle universe: 20% < total_mv rank pct < 90%

这是用户指定的剔除最大 10% 和最小 20% 后的主诊断 universe。

| signal | horizon | rank IC mean | IC positive rate | top10 excess | net top10 excess |
| --- | ---: | ---: | ---: | ---: | ---: |
| `support_minus_overhang` | 1D | -0.0038 | 41.7% | -0.060% | -0.238% |
| `support_minus_overhang` | 3D | -0.0037 | 49.0% | -0.235% | -0.413% |
| `support_minus_overhang` | 5D | -0.0078 | 49.0% | -0.386% | -0.565% |
| `support_absorption_minus_overhang` | 1D | -0.0030 | 42.7% | -0.041% | -0.219% |
| `support_absorption_minus_overhang` | 3D | -0.0037 | 49.0% | -0.232% | -0.410% |
| `support_absorption_minus_overhang` | 5D | -0.0076 | 50.0% | -0.369% | -0.547% |
| `below_cost_depth` | 1D | -0.0177 | 46.9% | -0.145% | -0.314% |
| `below_cost_depth` | 3D | -0.0078 | 39.6% | -0.226% | -0.395% |
| `below_cost_depth` | 5D | -0.0162 | 34.4% | -0.315% | -0.484% |
| `below_cost_guarded_support` | 1D | -0.0155 | 38.5% | -0.217% | -0.393% |
| `below_cost_guarded_support` | 3D | -0.0143 | 39.6% | -0.326% | -0.502% |
| `below_cost_guarded_support` | 5D | -0.0128 | 47.9% | -0.438% | -0.614% |

解释：

```text
middle universe 中，support-overhang 没有延续 2024-01 smoke 的正向表现。
below_cost_depth 继续是负向或 value-trap 方向。
把 below-cost 加 gate 也没有修复 long side。
```

### Full universe

| signal | horizon | rank IC mean | top10 excess | net top10 excess |
| --- | ---: | ---: | ---: | ---: |
| `support_minus_overhang` | 1D | -0.0015 | -0.035% | -0.212% |
| `support_minus_overhang` | 3D | 0.0024 | -0.180% | -0.357% |
| `support_minus_overhang` | 5D | -0.0003 | -0.281% | -0.457% |
| `below_cost_depth` | 1D | -0.0176 | -0.163% | -0.332% |
| `below_cost_depth` | 3D | -0.0116 | -0.298% | -0.467% |
| `below_cost_depth` | 5D | -0.0211 | -0.385% | -0.554% |

解释：

```text
full universe 中 support-overhang 近似无效，top10 excess 仍为负。
below-cost 单体仍显著偏负。
```

### Size diagnostics

Largest 10%：

```text
support_minus_overhang:
  1D rank_ic_mean = -0.0305, top10_excess = -0.091%
  3D rank_ic_mean = -0.0176, top10_excess = -0.201%
  5D rank_ic_mean = -0.0089, top10_excess = -0.216%
```

Smallest 20%：

```text
support_minus_overhang:
  1D rank_ic_mean = 0.0005, top10_excess = -0.004%
  3D rank_ic_mean = 0.0011, top10_excess = -0.111%
  5D rank_ic_mean = -0.0077, top10_excess = -0.172%
```

解释：

```text
小市值里 support-overhang 比大市值更接近 neutral，但扣简单 turnover cost 后仍为负。
大市值里 support-overhang 明显不支持 long side。
```

## 结论

这个 toy diagnostic 对当前叙事是负面结果：

```text
1. 2024-01 smoke 的 support-overhang 正向，很可能包含强 regime/sample 成分。
2. cached evenly-spaced toy sample 中，support_minus_overhang 在 middle universe 的 1D/3D/5D 都为负。
3. below_cost_depth 单独继续表现为 value-trap / reverse signal。
4. below_cost_guarded_support 没有把 long side 修复出来。
5. turnover 很高，20bps 简单成本扣减后 top10 excess 全部更差。
```

但这还不是正式否决：

```text
1. sample 不是随机样本，是现有 cached partitions 的均匀抽样；
2. 口径是 lookback_days=1，不是 production 目标的 lookback_days=20；
3. cost adjustment 是 turnover proxy，不是正式执行模拟；
4. 缺少完整 2016-2025 full-window datamart 和 Step4 组合层 proof。
```

## 后续研究建议

不要把 `support_minus_overhang` 直接推进 candidate factor。后续应等 Data 组 production datamart 后做正式 L20 检验，并优先测试：

```text
1. persistence confirmation:
   support_minus_overhang 需要 2-3 天持续，而不是单日价格轴快照。

2. regime gate:
   2024-01 下跌环境中它像相对抗跌信号；普通 cached sample 中不稳定。

3. absorption / no-break as hard gate:
   当前 absorption multiplier 不够，应改为 regime/gate，不是线性加成。

4. below_cost as penalty/control:
   below_cost_depth 不应作为 positive long 主体。

5. lower turnover construction:
   当前 top set turnover 约 0.88-0.89，任何日频 long-only 都会被成本吃掉。
```

当前库状态应保持：

```text
library_status = exploratory_smoke
promotion = no
candidate_factor = no
next_gate = production L20 datamart full-window test
```
