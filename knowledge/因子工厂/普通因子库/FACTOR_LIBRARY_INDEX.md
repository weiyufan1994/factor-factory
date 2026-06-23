# 因子库索引 — 2026-04-21 更新

> 本次更新：Alpha004 变体三波测试 → 新增 4 个独立/复合因子

---

## 新增因子

| 因子 ID | 名称 | Formula | IC | IC IR | G10 多头 | 状态 |
|--------|------|---------|-----|-------|---------|------|
| COMBO_MCAP_VOL_20160101_20250711 | combo_mcap_vol | `(-TsRank(r_mcap) + -TsRank(r_vol)) / 2` | 0.072 | 0.592 | +0.071% | ✅ validated |
| PB_VALUE_20160101_20250711 | PB | `rank(PB)` | 0.070 | 0.528 | +0.056% | ✅ validated |
| SIZE_MCAP_20160101_20250711 | SIZE | `rank(mcap)` | 0.068 | 0.520 | +0.051% | ✅ validated |
| ALPHA004_PAPER_20160101_20250711 | Alpha004(原始) | `(-1 * Ts_Rank(rank(low), 9))` | 0.036 | 0.276 | — | ✅ validated |
| ALPHA005_PAPER_20160101_20250711 | Alpha005 | `(-TsRank(rank(delta(TsArgMax(close9d,8),7)),9))` | ≈0 | ≈0 | — | ❌ reject |
| ALPHA008_PAPER_20160101_20250711 | Alpha008 | `(-1 * rank(((sum(open,5)*sum(returns,5))-delay(...))))` | 0.018 | 0.159 | — | ❌ reject |
| ALPHA009_PAPER_20160101_20250711 | Alpha009 | regime-adaptive: monotonic_up→delta, mixed→-delta | 0.020 | 0.171 | — | ❌ reject |
| ALPHA006_PAPER_20160101_20250711 | Alpha006 | `(-1 * corr(open, volume, 10))` | 0.026 | 0.309 | +0.001% | ✅ iterate |
| ALPHA007_PAPER_20160101_20250711 | Alpha007(kurt-skew) | `folded * (1 + 0.5*(kurt_zs - skew_zs))` | 0.057 | 0.678 | +0.022% | ✅ validated |
| VP_SUPPORT_OVERHANG_BELOW_COST_GUARD_202401 | VP support-overhang | `lower_support_ratio - upper_overhang_ratio` | 0.189 / 0.168 / 0.040 | 2024-01 smoke only | top10 excess +0.883% / +1.501% / +2.058% | 🔬 exploratory_smoke |
| MONEYFLOW_FEATURE_CANDIDATES_V15_V18_V19_20260617 | Moneyflow repaired absorption / first-passage features | `V18b`, `min(z18a,z18b)` | V19d raw rank IC 0.043 full / 0.060 fixed_small_20 | feature only | after-cost standalone failed | 🧩 feature_candidate |
| LCR_RETAINED_CHIP_RATIO_FEATURE_CANDIDATE_20260619 | Retained chip ratio / survival inventory state | `sum(amount*survival(turnover))/sum(amount)` | OOS raw 5D IC 0.0476 full / 0.0704 CSI2000 | residual weak | raw long-side works in CSI2000/microcap, independent alpha weak | 🧩 feature_candidate |
| VOLUME_AMOUNT_RANK_MISMATCH_FEATURE_CANDIDATE_20260622 | Volume-vs-Amount rank mismatch | `rank(sum(volume,30))/rank(sum(amount,30))` | IS RankIC5D 0.0388 / OOS 0.0065 | feature only | OOS Q10-Q1 NAV 0.872, direction unstable | 🧩 feature_candidate |

---

## 因子对比总表

| 因子 | IC | IC IR | LS Spread | G10 多头 | 主要收益 |
|------|-----|-------|---------|---------|---------|
| combo_mcap_vol | **0.072** | 0.592 | **+0.380%** | **+0.071%** | 多空双向 |
| turnover_pb_combo | 0.071 | 0.577 | +0.382% | +0.066% | 多空双向 |
| short_low_pb | 0.071 | 0.530 | +0.320% | +0.065% | 多头明确 |
| PB | 0.070 | 0.528 | +0.308% | +0.056% | 多头明确 |
| SIZE | 0.068 | 0.520 | +0.292% | +0.051% | 多头明确 |
| short_low_vol | 0.054 | **0.609** | +0.283% | +0.032% | 空头侧 |
| Alpha007(kurt-skew) | **0.057** | **0.678** | +0.298% | +0.022% | regime-adap |
| VP support-overhang | 0.189 / 0.168 / 0.040 | 2024-01 smoke only | +1.057% / +2.612% / +1.638% | top10 excess +0.883% / +1.501% / +2.058% | 研究线索，需 full-window |
| Moneyflow V18b/V19d | 0.043-0.060 raw rank IC on V19d | feature candidate | gross/residual signal exists | after-cost standalone failed | 可用于模型组合，不是正式单因子 |
| LCR retained chip ratio | OOS raw 5D IC 0.0476 full / 0.0704 CSI2000 | residual IC weak | raw top long positive in CSI2000/microcap | residualized independence insufficient | 筹码留存状态特征，不是正式独立因子 |
| Volume-vs-Amount Rank Mismatch | IS 5D RankIC 0.0388 / OOS 0.0065 | feature candidate | IS Q10-Q1 NAV positive, OOS LS negative | OOS Q10-Q1 NAV 0.872 | 低价/散户参与/交易结构状态特征，不是正式独立因子 |

---

## 关键结论

1. **combo_mcap_vol 是全场最优（纯 IC）**：IC=0.072，spread 最宽（+0.380%/天），G10=+0.071%
2. **Alpha007(kurt-skew) 是单调性最佳**：rho=0.988, p<0.0001，完美单调，G10 稳定在正值区间
3. **Regime 加权的意义**：kurtosis+skewness 组合将 crash regime 的判断内化到公式，牺牲了部分 IC（0.068→0.057）换取单调性
4. **skewness > kurtosis**：|skew| 和 kurt-skew 都能改善单调性；raw skew 和 negated skew 方向错误
5. **市值中性无效**：因子对小市值暴露本来低，mcap neutralize 几乎不影响结果

---

## 下一步建议

- combo_mcap_vol + short_low_pb 叠加测试（两因子相关性 0.84）
- 纯 vol 中性化市值后信号 vs combo
- 低市值+低成交量+低PB 三条件交集
