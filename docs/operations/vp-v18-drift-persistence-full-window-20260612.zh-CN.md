# VP V18 Drift Persistence Full Window Research - 2026-06-12

## Scope

本次只做研究侧组合因子验证，不修改 Data 组交付的
`intraday_value_occupation_state_v1` P0 datamart。P0 仍只包含 state variables；
`v18_repair_*` 均在研究脚本中下游生成。

输入：

- VP P0 datamart: `s3://yufan-data-lake/factorforge/datamart/intraday_value_occupation_state/v1/`
- Daily clean: `/home/ubuntu/.openclaw/workspace/factorforge/data/clean/daily_clean.parquet`
- Window: `20160104-20250711`
- VP rows: `9,105,107`
- Merged rows: `8,026,806`
- Dates: `2,312`
- Tickers: `5,004`
- Horizons: `1D, 3D, 5D`
- Long-side cost model: top-decile one-way turnover * `20bps`

Worker proof:

- Instance: `i-02cc0b6e93856fbb4`
- SSM command: `a0ee539a-e514-48ce-8147-519bcd63404b`
- Status: `Success`
- Runtime: `PT31M37.9S`
- Output S3: `s3://yufan-data-lake/factorforge/tmp/vp_v18_20260612/full/`

Artifacts:

- `vp_v18_drift_persistence_metrics.csv`
- `vp_v18_drift_persistence_summary.json`
- `vp_v18_drift_persistence_all_period.md`
- `run.log`

Local copies:

- `/tmp/factorforge_vp_v18_full_local_20260612/vp_v18_drift_persistence_metrics.csv`
- `/tmp/factorforge_vp_v18_full_local_20260612/vp_v18_drift_persistence_summary.json`
- `/tmp/factorforge_vp_v18_full_local_20260612/vp_v18_drift_persistence_all_period.md`
- `/tmp/factorforge_vp_v18_full_local_20260612/run.log`

## Signal Definitions

V18 的主体是 value-occupation repair 加一个软漂移项：

```text
base = z(below_cost_depth_score_raw) + z(lower_support_mass)
mom_3d_to_cutoff = reference_price / close_lag3 - 1
v18_repair_drift_score = base + 0.35 * z(mom_3d_to_cutoff) - 0.25 * z(vol_20d)
```

其中 `reference_price` 是 cutoff 前最后一分钟 close，避免使用当日收盘之后的信息。

测试的门控版本：

- `v18_repair_no_break_2d`: base 需要连续 2 天 no-break，否则打到低分。
- `v18_repair_no_break_3d`: base 需要连续 3 天 no-break。
- `v18_repair_mild_drift`: base 需要 3D cutoff 动量为正、1D cutoff drift 不太差、20D 不过热。
- `v18_repair_persist_mild_drift`: 同时要求 2D no-break 和 mild drift。
- `v18_repair_downside_guard`: 放松版 downside guard。

Residual IC 控制项：

```text
ln_total_mv, drift_1d_to_cutoff, mom_5d_to_cutoff, mom_20d_to_cutoff, turnover_rate, vol_20d
```

这不是完整 Barra/行业中性检验，但能初步判断是否只是 size、短中期动量、换手和波动的换皮。

## Main Result

`middle_20_90` universe 是当前最重要的排除极端大小盘后的指增候选池。

| signal | horizon | Rank IC | Residual IC | top decile excess | top turnover | net top excess |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| `v18_repair_drift_score` | 1D | 0.040031 | 0.006158 | 0.000537 | 0.373099 | -0.000209 |
| `v18_repair_drift_score` | 3D | 0.051340 | 0.006121 | 0.000975 | 0.373105 | 0.000229 |
| `v18_repair_drift_score` | 5D | 0.055573 | 0.005748 | 0.001232 | 0.373086 | 0.000486 |
| `v18_repair_base_z` | 1D | 0.032765 | 0.006219 | 0.000452 | 0.393823 | -0.000335 |
| `v18_repair_base_z` | 3D | 0.039010 | 0.006225 | 0.000701 | 0.393819 | -0.000087 |
| `v18_repair_base_z` | 5D | 0.040486 | 0.005883 | 0.000737 | 0.393809 | -0.000051 |
| `below_cost_depth_score_raw` | 5D | 0.020716 | 0.003863 | 0.000356 | 0.219404 | -0.000082 |
| `lower_support_mass` | 5D | 0.026485 | 0.003483 | 0.000504 | 0.448528 | -0.000393 |
| `support_minus_overhang` | 5D | -0.005686 | 0.002759 | -0.000048 | 0.542981 | -0.001134 |

解释：

- `v18_repair_drift_score` 是本轮最强版本。相比 `base`，Rank IC 从 5D `0.040486`
  提升到 `0.055573`，扣费后 top-decile excess 从 `-0.000051` 转为 `0.000486`。
- 1D 仍然扣费后为负，说明这个方向不是日内或隔日极速换手因子，更像 3-5 天修复/续航因子。
- Residual IC 保持正值，说明信号中确有 occupation-measure 相关增量；但 residual IC 没随 drift_score 同步提高，
  也说明 rank IC 的提升有一部分来自短期漂移项。
- `support_minus_overhang` 继续失败，线性扣 upper overhang 会带来高 turnover 和负 long-side。

## Period Stability

`middle_20_90 / v18_repair_drift_score`：

| horizon | period | dates | Rank IC | Residual IC | top excess | turnover | net top excess |
| ---: | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 1D | 2016_2020 | 1217 | 0.043598 | 0.007794 | 0.000694 | 0.386112 | -0.000078 |
| 1D | 2021_2024_0923 | 903 | 0.032875 | 0.004502 | 0.000362 | 0.352109 | -0.000343 |
| 1D | post_20240924 | 192 | 0.051080 | 0.003567 | 0.000364 | 0.387559 | -0.000411 |
| 3D | 2016_2020 | 1217 | 0.056153 | 0.007236 | 0.001071 | 0.386111 | 0.000299 |
| 3D | 2021_2024_0923 | 903 | 0.041446 | 0.004674 | 0.000809 | 0.352125 | 0.000105 |
| 3D | post_20240924 | 192 | 0.067356 | 0.005856 | 0.001147 | 0.387552 | 0.000372 |
| 5D | 2016_2020 | 1217 | 0.060876 | 0.006417 | 0.001295 | 0.386080 | 0.000523 |
| 5D | 2021_2024_0923 | 903 | 0.044705 | 0.004844 | 0.001101 | 0.352113 | 0.000397 |
| 5D | post_20240924 | 192 | 0.073068 | 0.005753 | 0.001445 | 0.387585 | 0.000669 |

解释：

- 3D/5D 在三个 regime 都是扣费后正值。
- 2021-2024_0923 较弱，但没有断裂。
- post_20240924 很强，但不是唯一来源；full-window 不是只靠最近行情撑起来。

## Universe Comparison

All-period `v18_repair_drift_score`：

| universe | horizon | Rank IC | Residual IC | net top excess |
| --- | ---: | ---: | ---: | ---: |
| full | 1D | 0.039100 | 0.006689 | -0.000263 |
| full | 3D | 0.049551 | 0.006872 | 0.000092 |
| full | 5D | 0.053069 | 0.006544 | 0.000281 |
| middle_20_90 | 1D | 0.040031 | 0.006158 | -0.000209 |
| middle_20_90 | 3D | 0.051340 | 0.006121 | 0.000229 |
| middle_20_90 | 5D | 0.055573 | 0.005748 | 0.000486 |
| largest_10 | 1D | 0.026195 | 0.010216 | -0.000243 |
| largest_10 | 3D | 0.037870 | 0.011907 | 0.000256 |
| largest_10 | 5D | 0.039556 | 0.011868 | 0.000708 |
| smallest_20 | 1D | 0.046100 | 0.009975 | -0.000271 |
| smallest_20 | 3D | 0.052869 | 0.008461 | 0.000113 |
| smallest_20 | 5D | 0.055130 | 0.007193 | 0.000291 |

解释：

- `largest_10` 的 Rank IC 不最高，但 residual IC 和 5D net top excess 都很好，值得做大盘/中证800近似池的专门复核。
- `smallest_20` IC 高，但扣费后不如 `middle_20_90` 和 `largest_10` 稳；这和前面“小市值更容易被交易成本吃掉”的结论一致。
- `middle_20_90` 是当前最均衡的候选 universe。

## Mechanism Read

这次结果支持的数学机制不是“低于成本后必然反转”，而是：

```text
occupation support mass gives a candidate repair region
+ positive finite-variation drift confirms repair is already being priced
- realized volatility penalizes martingale noise and false starts
```

用 semimartingale 语言说，`below_cost_depth_score_raw + lower_support_mass`
更像定义了一个靠近下方 occupation support 的状态空间；`mom_3d_to_cutoff`
不是 alpha 的全部，而是对 drift 项 `A_t` 已经从负转平或转正的弱确认；`vol_20d`
是对局部 martingale variance 的惩罚。这样比 hard barrier confirmation 更贴近 first-passage 机制：
价格不是必须连续 2-3 天不破位才有优势，而是只要修复区存在，且短期漂移已经不反向，触及上方目标的概率就改善。

## What Failed

- `v18_repair_persist_mild_drift` 失败：`middle_20_90 / 5D` Rank IC 只有 `0.013197`，
  net top excess `-0.000311`。硬门控把有效横截面排序压扁，且没有显著降低 turnover。
- `no_break_2d/no_break_3d` 没有提供足够增量：IC 低于 base 和 drift_score。
- `support_minus_overhang` 不应作为线性主体，overhang 更适合作为非线性风险/拥挤惩罚或目标距离变量。

## Current Verdict

V18 应作为一个候选指增因子继续推进，但主体应采用软漂移版本：

```text
v18_repair_drift_score
= z(below_cost_depth_score_raw)
+ z(lower_support_mass)
+ 0.35 * z(reference_price / close_lag3 - 1)
- 0.25 * z(vol_20d)
```

推荐使用：

- horizon: `3D-5D`
- universe: 先做 `middle_20_90`，同时追加 `largest_10` / 中证800近似池复核
- portfolio usage: 指增打分组件，不适合作为纯 1D 高频换手 long-only 主体

还不能做的结论：

- 不能说已经通过完整 Barra/行业中性增量检验。
- 不能说 long-short 实盘可行；目前 long-side 3D/5D 好于 1D，但 turnover 仍高。
- 不能把 V18 composite 写回 Data 组 datamart；Data 组应继续只交 state variables。

## Next Step

下一步建议做 V19 量价关系融合，而不是继续加硬确认门：

```text
v19 = v18_repair_drift_score
    + f(corr(price, volume), signed_amount_pressure, absorption)
```

研究问题：

- 在 repair zone 内，价格上涨是否伴随成交额扩张，还是缩量漂移？
- 下跌分钟的 amount 是否被吸收，形成 high-volume-no-break？
- `corr(price, volume)` 是否能降低 turnover 或改善 long-side hit rate，而不是只提高 Rank IC？

