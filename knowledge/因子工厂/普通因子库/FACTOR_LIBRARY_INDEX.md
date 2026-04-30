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
