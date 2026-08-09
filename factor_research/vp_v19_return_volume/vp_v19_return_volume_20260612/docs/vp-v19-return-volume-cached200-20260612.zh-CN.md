# VP V19 Return-Volume Cached200 Research - 2026-06-12

## Scope

本轮是 V19 研究侧样本测试，不是 full-window 结论。目标是验证：

```text
在 value-occupation repair state 内，minute return 与成交强度的协变结构
是否能给 V18 带来 long-side 增量。
```

本轮没有修改 Data 组 P0 datamart，也没有把 V19 composite 写入 production dataset。

## Math Object

V19 的数学对象不是 `corr(price, volume)`，而是 cutoff 前分钟收益和成交强度的局部协变：

```text
dX_t = minute log return
lambda_t = log(1 + abs(amount_t))
rv_corr = Corr(dX_t, lambda_t | t <= cutoff)
```

配套 state：

```text
up_down_amount_share_diff
  = amount_share(ret > 0) - amount_share(ret < 0)

downside_absorption
  = downside_amount_share * max(cutoff_return - intraday_drawdown, 0)

high_volume_downside_break
  = downside_amount_share * max(-cutoff_return, 0)
```

组合分数仍然以 V18 为主体：

```text
v18_repair_drift_score
= z(below_cost_depth_score_raw)
+ z(lower_support_mass)
+ 0.35 * z(reference_price / close_lag3 - 1)
- 0.25 * z(vol_20d)
```

V19 测试分支：

```text
v19_rv_corr_repair
= v18_repair_drift_score + 0.30 * z(rv_corr)

v19_upside_confirmed_repair
= v18_repair_drift_score
+ 0.35 * z(up_down_amount_share_diff)
+ 0.15 * z(amount_weighted_return)

v19_absorption_repair
= v18_repair_drift_score
+ 0.40 * z(downside_absorption) * support_state
- 0.25 * z(high_volume_downside_break)

v19_flow_confirmed_repair
= v18_repair_drift_score
+ 0.25 * z(rv_corr)
+ 0.30 * z(up_down_amount_share_diff)
+ 0.20 * z(downside_absorption) * support_state
- 0.25 * z(high_volume_downside_break)
```

## Data And Proof

Worker:

- instance: `i-02cc0b6e93856fbb4`
- corrected SSM command: `cd7402a4-9448-4984-b9d6-8a6db320203b`
- status: `Success`

Input availability:

- VP P0: `2,312` partitions available on worker after sync
- minute cache: `897` partitions under `/home/ubuntu/factorforge_data_api_cache/s3_parquet/minute_bar-raw_v1-0b2b836c57d763c6`
- VP-window minute overlap: `383 / 2,312` dates
- sampled dates: `200 / 383`

Output coverage:

- VP rows after available-date sampling: `1,037,840`
- return-volume feature rows: `1,037,900`
- merged rows: `880,086`
- merged dates: `200`
- merged tickers: `4,953`

Artifacts:

- S3: `s3://yufan-data-lake/factorforge/tmp/vp_v19_20260612/corrected_cached200/`
- local: `/tmp/factorforge_vp_v19_corrected_cached200_local_20260612/`

Important caveat:

This is `cached200`, not full-window. The 200 dates are sampled from currently cached minute partitions, not the full official calendar.

## Main Result

### Middle 20-90

`middle_20_90` 是排除极端大小盘后的主要指增候选池。这里 V19 没有改善 V18。

| signal | horizon | Rank IC | Residual IC | top excess | turnover | net top excess |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| `v18_repair_drift_score` | 1D | 0.039891 | 0.009389 | 0.000562 | 0.478685 | -0.000395 |
| `v19_rv_corr_repair` | 1D | 0.034080 | 0.009097 | 0.000599 | 0.528987 | -0.000459 |
| `v19_flow_guarded_repair` | 1D | 0.021870 | 0.004426 | 0.000768 | 0.640419 | -0.000512 |
| `v18_repair_drift_score` | 3D | 0.045991 | 0.008857 | 0.000634 | 0.478746 | -0.000324 |
| `v19_rv_corr_repair` | 3D | 0.037969 | 0.007410 | 0.000362 | 0.528957 | -0.000696 |
| `v18_repair_drift_score` | 5D | 0.049476 | 0.007948 | 0.000572 | 0.478744 | -0.000386 |
| `v19_rv_corr_repair` | 5D | 0.040999 | 0.006184 | 0.000242 | 0.528926 | -0.000816 |
| `below_cost_depth_score_raw` | 5D | 0.034064 | 0.009471 | 0.002060 | 0.328200 | 0.001404 |

Interpretation:

- V19 的 return-volume terms 在 `middle_20_90` 中提高了 turnover，削弱了 IC。
- 最复杂的 `flow_confirmed/guarded` 组合最差，说明多项 flow confirmation 线性叠加会引入噪声。
- 这个 cached sample 里 `below_cost_depth_score_raw` 的 5D long-side 很强，但这与 full-window V18 结果不一致，必须视为 sample/regime artifact，不能替代 full-window。

### Largest 10

大市值池里，V19 的简单 `rv_corr` 和 upside confirmation 有一定增量。

| signal | horizon | Rank IC | Residual IC | top excess | turnover | net top excess |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| `v18_repair_drift_score` | 1D | 0.045832 | 0.017238 | 0.001316 | 0.519919 | 0.000276 |
| `v19_upside_confirmed_repair` | 1D | 0.043826 | 0.020691 | 0.001464 | 0.573280 | 0.000317 |
| `v19_rv_corr_repair` | 1D | 0.044360 | 0.020571 | 0.001269 | 0.559593 | 0.000149 |
| `v18_repair_drift_score` | 3D | 0.049094 | 0.015060 | 0.001875 | 0.519919 | 0.000835 |
| `v19_upside_confirmed_repair` | 3D | 0.047279 | 0.015541 | 0.002033 | 0.573280 | 0.000886 |
| `v19_rv_corr_repair` | 3D | 0.046709 | 0.016134 | 0.001956 | 0.559593 | 0.000836 |
| `v18_repair_drift_score` | 5D | 0.048458 | 0.015078 | 0.002316 | 0.519919 | 0.001276 |
| `v19_rv_corr_repair` | 5D | 0.047132 | 0.016492 | 0.002827 | 0.559593 | 0.001708 |
| `v19_upside_confirmed_repair` | 5D | 0.047071 | 0.015540 | 0.002715 | 0.573280 | 0.001568 |

Interpretation:

- 大市值里，`rv_corr` 的 residual IC 和 5D long-side net 都高于 V18。
- 这符合经济机制：大盘股中成交额更可能代表真实资金确认，minute return-volume covariation 噪声低于中小盘。
- 但 turnover 仍更高，组合方式应更保守。

## Verdict

V19 的数学方向是 solid，但当前组合不是全市场增强：

```text
middle_20_90: V19 rejected as broad repair enhancement
largest_10: V19 rv_corr/upside confirmation remains worth testing
complex absorption/flow_guarded combo: rejected for now
```

更具体地说：

- `corr(return, amount)` 比 `corr(price, amount)` 更正确，这是数学对象层面的改进。
- 但“return-volume + absorption + downside guard”线性混合不是 Dirac style 的好落点；它把多个局部现象混成高 turnover score。
- 真正保留下来的候选是简单项：`v19_rv_corr_repair` 和 `v19_upside_confirmed_repair`，尤其在 `largest_10 / 5D`。

## Next Step

不建议直接把当前 V19 作为 full-universe V18 替代版。

推荐下一步：

1. 对 `largest_10` / 中证800近似池做 full-window return-volume datamart。
2. 只测试简单组合：

```text
v19_large_rv_corr_repair
= v18_repair_drift_score + a * z(rv_corr)

v19_large_upside_confirmed_repair
= v18_repair_drift_score
+ b * z(up_down_amount_share_diff)
+ c * z(amount_weighted_return)
```

3. 不继续推进 `v19_flow_confirmed_repair` / `v19_flow_guarded_repair`，除非先做非线性门控或降 turnover 设计。
4. 如果要 full-window，应该让 Data 组预聚合 `intraday_return_volume_state_v1`，不要每次研究侧冷扫 minute partitions。

