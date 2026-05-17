---
report_id: "ALPHA016_CANONICAL_FORMULA_20160101"
factor_id: "Alpha016"
doc_type: "mechanism_context"
decision_context: "iterate_not_promoted"
audience:
  - "Factor Forge Researcher"
  - "Step6 Revision Council"
  - "Architecture Review"
tags:
  - "alpha101"
  - "mechanism_math"
  - "price_volume_microstructure"
  - "rank_copula"
  - "transient_price_pressure"
---

# Alpha016 2016+ Mechanism Context

This note is supplemental research context for `ALPHA016_CANONICAL_FORMULA_20160101`.

It corrects and sharpens the generic Step6 mechanism summary. The wrapper proof remains the formal evidence source; this note is a human researcher mechanism note for future Step6 revision council use.

## Formal Evidence Boundary

- report_id: `ALPHA016_CANONICAL_FORMULA_20160101`
- formula: `(-1 * rank(covariance(rank(high), rank(volume), 5)))`
- formal proof: `objects/runtime_context/ultimate_run_report__ALPHA016_CANONICAL_FORMULA_20160101.json`
- proof status: `PASS`
- actual sample window: `2016-01-04 -> 2026-04-24`
- Step6 decision: `iterate`, not promoted
- long-only policy: no short selling, no direct decile trading, no promotion from long-short spread

## Why This Note Exists

The first Step6 run classified the factor too generically. It described Alpha016 as a liquidity shock / behavioral microstructure factor, which is directionally plausible, but its mechanism math summary used overly broad language and did not state the implied stochastic state or conditional distribution clearly enough.

For Alpha016, the mechanism is not well described as a generic residual projection. It is better described as a nonparametric price-volume rank-dependence state estimator.

## Mathematical Object

For stock `i` on date `t`, define:

```text
H_{i,t} = CSRank_t(high_{i,t})
V_{i,t} = CSRank_t(volume_{i,t})
C_{i,t} = Cov_5(H_{i,t}, V_{i,t})
A_{i,t} = -CSRank_t(C_{i,t})
```

where:

- `CSRank_t` is the cross-sectional rank at date `t`;
- `Cov_5` is a rolling five-trading-day covariance within each stock;
- `A_{i,t}` is the Alpha016 score.

The random object is not just the price process `P_{i,t}`. It is the joint rank process:

```text
{(H_{i,t-k}, V_{i,t-k}) : k = 0, 1, 2, 3, 4}
```

and its rolling dependence statistic `C_{i,t}`.

## Process Hypothesis

Alpha016 implicitly assumes a transient price-pressure or crowded-attention process:

```text
P_{i,t} = F_{i,t} + I_{i,t} + epsilon_{i,t}
```

where:

- `F_{i,t}` is slow-moving fundamental value or broad state;
- `I_{i,t}` is transient impact from attention, chasing, liquidity demand, or crowded flow;
- `epsilon_{i,t}` is residual noise.

The transient impact state decays:

```text
I_{i,t+1} = rho * I_{i,t} + eta_{i,t+1},  0 < rho < 1
```

`C_{i,t}` is an observable estimator of whether recent high-price states were confirmed by volume states. High `C_{i,t}` means a stock repeatedly sat high in the cross-section while also sitting high in the volume cross-section. In A-share microstructure, that can represent crowded confirmation, theme chasing, short-term price pressure, or liquidity-demand exhaustion.

## Conditional Distribution Hypothesis

The target functional is:

```text
E[r_{i,t+1} | F_t, C_{i,t}]
```

or more generally:

```text
F_{r | C}(x | C_{i,t})
```

The evidence does not support a simple linear "higher Alpha016 score is always better" story. It supports a weaker and more precise statement:

```text
E[r_{i,t+1} | high C_{i,t}] < E[r_{i,t+1} | mid/low C_{i,t}]
```

Because Alpha016 applies a negative rank to `C`, high factor scores correspond to low covariance states. The strongest observed evidence is that high covariance states are bad, not that the lowest covariance states are necessarily the best long candidates.

## Economic Mechanism

Primary mechanism classification:

```text
behavioral_microstructure / crowded_price_volume_confirmation_reversal
```

Economic interpretation:

- High `C_{i,t}` means price strength and volume strength were synchronized over the last five days.
- In an information-diffusion world, that could be bullish confirmation.
- In the observed A-share 2016+ evidence, it behaves more like crowded attention or transient price pressure.
- The low-score group collapses, so the factor is very good at identifying bad flow.
- The high-score group is only weakly positive, so the factor is not yet a strong long-only alpha.

Likely counterparty states:

- retail and theme-chasing flow buying after visible price-volume confirmation;
- constrained public funds or benchmark-sensitive allocators joining crowded themes late;
- active funds or short-horizon traders facing liquidity exhaustion after volume-confirmed highs.

This is not primarily a passive low-liquidity risk premium. It is closer to identifying the decay of a temporary price-pressure state.

## Metric Signature

Formal full-sample evidence:

| Metric | Value |
|---|---:|
| Rank IC mean | `0.0533` |
| Rank IC IR | `0.7815` |
| G10 annual return | `3.84%` |
| G10 Sharpe | `0.169` |
| G10 max drawdown | `-51.26%` |
| G10 recovery days | `3440` |
| G10 daily turnover | `48.64%` |
| cost-adjusted annual return | `-32.91%` |
| cost-adjusted Sharpe | `-1.450` |

10-group final NAV:

```text
G01 0.0004, G02 0.0839, G03 0.2638, G04 0.4675, G05 0.7653,
G06 0.9793, G07 1.2447, G08 1.5135, G09 2.0533, G10 1.1875
```

Interpretation:

- Rank IC is real and not obviously leakage-driven.
- The monotonicity is not a clean "G10 dominates" pattern.
- `G9 > G10`, and `G01` is catastrophic.
- Long-short diagnostics are dominated by short-side weakness and cannot support adoption.
- Long-only G10 economics are too weak after cost.

## Regime Evidence

| Regime | G10 annual | Rank IC mean | Interpretation |
|---|---:|---:|---|
| `2016-2019` | `1.02%` | `0.0591` | IC exists; long side weak |
| `2020-2024-09-23` | `-8.03%` | `0.0467` | sorting still exists; G10 underwater |
| `post-2024-09-24` | `36.12%` | `0.0582` | active-theme regime improves G10, sample short |

The factor's rank information persists across regimes, but the long-only monetization fails in the 2020-2024 stress period and depends heavily on post-924 active-market recovery.

## What Would Falsify This Mechanism

Future council or revision work should explicitly test:

1. Delay test:
   - If `delay(base, 1)` destroys IC and monotonicity, the factor may depend on untradeable same-close information or ultra-short microstructure noise.
2. Persistence test:
   - If `mean(base, 3/5)` or a longer covariance window lowers turnover without destroying IC, the transient state is not purely one-day noise.
3. State-shape test:
   - If G9 remains better than G10, the target relation is non-monotone and should not be treated as "lowest covariance is best."
4. Exposure test:
   - If the signal is only small-cap, high-turnover, or junk-stock avoidance, then the mechanism is closer to bad-stock filtering than tradable alpha.
5. Cost test:
   - If any revision still has cost-adjusted annual return deeply negative, stop the branch even if Rank IC remains high.

## Council Context

The next revision council should not receive only the generic Step6 summary. It should treat this mechanism note as required context.

Recommended council framing:

- Primary question:
  - Can Alpha016 be converted from a bad-flow detector into a long-only selector?
- Mechanism target:
  - latent crowded price-volume confirmation state
- Estimator:
  - rolling covariance of cross-sectional price rank and volume rank
- Target functional:
  - `E[r_{i,t+1} | F_t, C_{i,t}]`
- Main failure:
  - high turnover and short-side-dominant evidence; G10 is weak and G9 is better than G10
- Forbidden repair:
  - no long-short adoption, no shorting G01, no direct decile trading, no portfolio-expression fix

Suggested branches:

1. `delay_sanity`
   - `delay(base, 1)` or equivalent expression-level lag, to test implementability and timing robustness.
2. `persistence_smoothing`
   - `mean(base, 3)` or `mean(base, 5)`, to reduce turnover and check whether the state persists.
3. `long_side_state_gate`
   - `base * rank(amount)` or a mild turnover/amount gate, to distinguish tradable active-liquidity names from low-attention dead names.

## Research Decision

Current Alpha016 canonical should remain:

```text
iterate_not_promoted
```

Reason:

- The factor has genuine rank information.
- The economic mechanism is plausible and mathematically interpretable.
- The current expression is a bad-state detector, not a strong long-only alpha.
- Promotion is blocked by weak G10, high turnover, deep drawdown, and negative cost-adjusted economics.

## Evidence References

- `objects/runtime_context/ultimate_run_report__ALPHA016_CANONICAL_FORMULA_20160101.json`
- `objects/factor_spec_master/factor_spec_master__ALPHA016_CANONICAL_FORMULA_20160101.json`
- `objects/factor_case_master/factor_case_master__ALPHA016_CANONICAL_FORMULA_20160101.json`
- `objects/research_iteration_master/loop_research_brief__ALPHA016_CANONICAL_FORMULA_20160101__iter1.md`
- `objects/research_iteration_master/researcher_memo__ALPHA016_CANONICAL_FORMULA_20160101.json`
- `evaluations/ALPHA016_CANONICAL_FORMULA_20160101/self_quant_analyzer/evaluation_payload.json`
- `evaluations/ALPHA016_CANONICAL_FORMULA_20160101/self_quant_analyzer/quantile_nav_10groups.csv`
