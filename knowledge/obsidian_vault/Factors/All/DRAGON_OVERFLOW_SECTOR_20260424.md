---
report_id: "DRAGON_OVERFLOW_SECTOR_20260424"
factor_id: "DragonOverflowSector"
decision: "promote_candidate"
iteration_no: 1
run_status: "success"
final_status: "validated"
tags:
  - "factor"
  - "library_all"
  - "promote_candidate"
  - "dragon-overflow"
  - "trend-consistency"
  - "sector-neutral"
---

# DragonOverflowSector (DRAGON_OVERFLOW_SECTOR_20260424)

## Source
Derived from Alpha011 (Kakushadze 101 Formulas, Formula #11) via dragon_overflow_experiment (2026-04-24)

## Formula
```
sector_neutral(rank(ts_max((high+low+close)/3 - close, 3)) + rank(ts_min((high+low+close)/3 - close, 3)))
```

## Summary
Sector-neutral trend consistency factor. Measures how consistently price holds above its VWAP (approximated as HLC/3). Q10 represents Dragon-2 overflow (institutional participation still ongoing), not exhausted Dragon-1.

## Headline Metrics
- `rank_ic_mean`: `0.0388`
- `rank_ic_ir`: `0.3256` ✅ (exceeds 0.3 threshold)
- `spread_mean`: `20.96 bps/day`
- `spread_ir`: `0.2213`
- `long_short_nav`: `113.73` (over ~9.5 years)

## Quantile Returns
| Decile | Mean Fwd Ret |
|--------|-------------|
| Q1 (lowest) | -0.130%/day |
| Q2 | +0.010%/day |
| Q3 | +0.030%/day |
| Q4 | +0.040%/day |
| Q5 | +0.040%/day |
| Q6 | +0.060%/day |
| Q7 | +0.070%/day |
| Q8 | +0.090%/day |
| Q9 | +0.090%/day |
| Q10 (highest) | **+0.080%/day** ← Dragon-2 overflow |

## Variant Comparison
| Variant | IC | IR | Q10 |
|---------|-----|-----|-----|
| I_trend_consistency_raw | 0.0382 | 0.3144 | +0.08% |
| **I_trend_consistency_sector** | **0.0388** | **0.3256** | **+0.08%** |
| I_trend_consistency_mcap | 0.0223 | 0.1826 | -0.13% |
| I_trend_consistency_both | 0.0233 | 0.1932 | -0.13% |
| D_sign_power_raw | 0.0335 | 0.3554 | ~0% |
| D_sign_power_sector | 0.0341 | 0.3682 | -0.01% |

## Key Insight
Q10 being positive (+0.08%/day) distinguishes this from all other factors studied (Alpha010, Alpha011, where Q10 was near-zero or negative). This is because the factor captures **Dragon-2 overflow** (institutions still participating consistently) rather than **exhausted Dragon-1** (trend too crowded). The additive structure (A+B) preserves Q10 positivity; the multiplicative structure (A×B) in Alpha011 suppressed Q10.

## Design Lessons
1. **Additive (A+B)** → preserves Q10; good for overflow/leader-following
2. **Multiplicative (A×B)** → suppresses Q10; good for avoiding exhausted leaders
3. **Volume acceleration is noise** in trend_consistency factors — removing delta_vol improves IR 6x
4. **Mcap neutral destroys** this signal — factor is inherently size-correlated
5. **Sector neutral helps marginally** (+0.01 IR) — always try it

## Decision: promote_candidate
Enter library_all as promote_candidate. Recommend OOS validation (200+ days held out) before promoting to official.
