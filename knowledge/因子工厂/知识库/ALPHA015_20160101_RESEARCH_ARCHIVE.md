---
report_id: "ALPHA015_RESEARCH_ARCHIVE_20160101"
factor_id: "Alpha015"
decision: "iterate_archive_as_lesson"
tags:
  - "knowledge"
  - "iterate"
  - "alpha101"
  - "long_only"
  - "active_liquidity"
  - "turnover_penalty"
---

# Knowledge Record: Alpha015 2016+ Research Archive

- decision: `iterate_archive_as_lesson`
- research_window_default: `2016-01-01 onward`
- verified_actual_window: `2016-01-04 -> 2026-04-24`
- current_best_revision: `ALPHA015_SWEEP_TURNPEN_A040_20160101`
- formal_entry_rule: Step3-6 evidence came from `scripts/run_factorforge_ultimate.py`

## Source Formula

WorldQuant Alpha015 canonical formula:

```text
(-1 * sum(rank(correlation(rank(high), rank(volume), 3)), 3))
```

The canonical expression is a short-window price-volume structure signal. Higher values come from names where ranked high price and ranked volume do not show the crowded positive co-movement implied by the raw correlation term. In 2016+ A-share evidence, the original formula has meaningful cross-sectional ranking power but is too costly and unstable for long-only adoption.

## Final Research Judgment

Alpha015 is not a low-turnover or low-volatility risk-premium factor. The useful post-2016 branch appears only after confirming that the signal is expressed in high `amount` / high attention / active liquidity names.

Current best tested revision:

```text
(((-1 * sum(rank(correlation(rank(high), rank(volume), 7)), 7)) * rank(amount)) * (0.40 + (0.60 * (1 - rank(turnover)))))
```

This is best understood as:

```text
base_active_structure * mild_turnover_penalty
```

where:

```text
base_active_structure = ((-1 * sum(rank(correlation(rank(high), rank(volume), 7)), 7)) * rank(amount))
```

Key long-side metrics for `ALPHA015_SWEEP_TURNPEN_A040_20160101`:

| Metric | Value |
|---|---:|
| Rank IC mean | `0.05993` |
| Rank IC IR | `0.52357` |
| G10 annual return | `22.65%` |
| G10 Sharpe | `0.966` |
| G10 max drawdown | `-39.54%` |
| G10 recovery days | `704` |
| G10 daily turnover | `24.23%` |
| annual COGS proxy | `18.32%` |
| cost-adjusted annual return | `4.34%` |
| cost-adjusted Sharpe | `0.185` |
| cost-adjusted max drawdown | `-61.16%` |
| cost-adjusted recovery days | `3440` |
| G10 final NAV | `7.3480` |

This is a small improvement over the high-amount baseline, but it does not clear Factor Forge long-only admission gates. The cost-adjusted return is positive, but the cost-adjusted Sharpe is weak, drawdown is too deep, and recovery remains structurally unacceptable.

## Main Evidence Chain

### Canonical Alpha015

`ALPHA015_CANONICAL_FORMULA_20160101`:

| Metric | Value |
|---|---:|
| Rank IC mean | `0.03785` |
| Rank IC IR | `0.645` |
| G10 annual return | `9.77%` |
| G10 Sharpe | `0.440` |
| G10 max drawdown | `-39.81%` |
| G10 recovery days | `1771` |
| daily turnover | `46.75%` |
| cost-adjusted annual return | `-25.56%` |

Canonical Alpha015 has real signal shape, but turnover costs dominate the long side.

### Window And Smoothing Tests

`corr5_sum5` improved the signal body versus the raw 3-day formula but still failed cost-adjusted economics:

| Revision | G10 Ann. | Sharpe | Max DD | Recovery | Daily Turnover | Cost-Adj Ann. | Judgment |
|---|---:|---:|---:|---:|---:|---:|---|
| `outer_smooth5` | `8.00%` | `0.369` | `-41.31%` | `1790` | `25.63%` | `-11.37%` | smoothing alone insufficient |
| `corr5_sum5` | `10.48%` | `0.480` | `-40.23%` | `1708` | `27.47%` | `-10.28%` | better math window, still uneconomic |
| `corr3_mean5_rank` | `9.39%` | `0.430` | `-39.34%` | `1755` | `32.98%` | `-15.53%` | rank-after-smoothing does not solve cost |

Lesson: increasing the structural observation window from 3 to 5 or 7 days helps more than merely smoothing the final signal, but it does not solve the long-only cost and recovery problem.

### Regime Gate And High Amount Confirmation

Best mechanism discovery branch:

```text
((-1 * sum(rank(correlation(rank(high), rank(volume), 7)), 7)) * rank(amount))
```

`ALPHA015_REGIME_R03_CORR7_HIGHAMOUNT_20160101`:

| Metric | Value |
|---|---:|
| Rank IC mean | `0.07609` |
| Rank IC IR | `0.63141` |
| G10 annual return | `22.26%` |
| G10 Sharpe | `0.969` |
| G10 max drawdown | `-37.96%` |
| G10 recovery days | `498` |
| daily turnover | `25.40%` |
| annual COGS proxy | `19.20%` |
| cost-adjusted annual return | `3.06%` |
| cost-adjusted Sharpe | `0.133` |
| G10 final NAV | `7.1517` |

The 2018-2024 pre-924 slice still showed strong monotonicity and IC. Therefore the main problem is not that the cross-sectional structure disappeared before 2024-09-24; the problem is that the long-only path and transaction cost consume much of the tradable edge.

## Turnover Penalty Sweep

Turnover penalty form:

```text
base * (a + (1-a) * (1 - rank(turnover)))
```

where `base` is the high-amount `corr7_sum7` branch.

| Version | G10 Ann. | Sharpe | Max DD | Recovery | Daily Turnover | Cost-Adj Ann. | Cost-Adj Sharpe | G10 NAV | Judgment |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---|
| R03 high amount | `22.26%` | `0.969` | `-37.96%` | `498` | `25.40%` | `3.06%` | `0.133` | `7.152` | baseline |
| `a=0.25` | `22.32%` | `0.942` | `-40.18%` | `709` | `23.72%` | `4.39%` | `0.185` | `7.069` | highest net return, weaker shape |
| `a=0.40` | `22.65%` | `0.966` | `-39.54%` | `704` | `24.23%` | `4.34%` | `0.185` | `7.348` | best balanced variant |
| `a=0.50` | `22.66%` | `0.970` | `-39.23%` | `704` | `24.53%` | `4.12%` | `0.177` | `7.373` | close second |
| `a=0.60` | `22.44%` | `0.965` | `-38.92%` | `704` | `24.76%` | `3.72%` | `0.160` | `7.233` | too close to R03 |
| `a=0.75` | `22.35%` | `0.967` | `-38.51%` | `709` | `25.06%` | `3.42%` | `0.148` | `7.194` | too close to R03 |

The turnover penalty is useful only as a mild cost-aware shrinkage. It does not fix the deep drawdown or long recovery. The best version is `a=0.40`, not because it is economically strong, but because it gives a small cost-adjusted lift without damaging the signal body as much as stronger low-turnover penalties.

## Rejected Revision Families

### Low Amount / Slow Window Adaptation

Hypothesis tested:
- use fast window in high-amount names;
- use slower window in low-amount names.

Result:
- `fast7_slow14`, `fast7_halfslow14`, and `fast7_slow21` all failed to improve the long-only economics.
- Slow low-amount components either destroyed IC, weakened G10 returns, or flipped signal direction.

Lesson:
- `rank(amount)` is not a cost control variable in this factor. It is a mechanism gate.
- Low-amount names are not a slower version of the same Alpha015 mechanism; they are mostly outside the useful return source.

### Low Volatility Gate

`ALPHA015_RISK_A_HIGHAMOUNT_LOWVOL20_20160101`:

```text
base * (1 - rank(std(returns, 20)))
```

Result:
- G10 annual return fell to `3.90%`;
- Sharpe fell to `0.154`;
- max drawdown worsened to `-64.93%`;
- cost-adjusted annual return fell to `-15.21%`.

Lesson:
- Low volatility is not the right risk definition for Alpha015.
- The factor appears to require active liquidity and crowd attention. Removing volatile/high-activity names removes the revenue source, not just bad risk.

### Hard Low Turnover Gate

`ALPHA015_RISK_B_HIGHAMOUNT_LOWTURN_20160101`:

```text
base * (1 - rank(turnover))
```

Result:
- G10 annual return became `-32.66%`;
- cost-adjusted annual return became `-54.39%`;
- daily turnover did not even improve in the desired way.

Lesson:
- Hard low-turnover filtering breaks the Alpha015 mechanism.
- If turnover is used, it must be a mild penalty, not a gating variable.

### Kurtosis / Skewness

Direct `kurtosis()` and `skewness()` operators are not supported by the current formula DSL. Unsupported operators must block rather than fall back to fixture/plugin paths.

Moment-proxy low-kurtosis test:

`ALPHA015_RISK_C_HIGHAMOUNT_LOWKURT20_MOMENT_20160101`:

| Metric | Value |
|---|---:|
| G10 annual return | `14.20%` |
| G10 Sharpe | `0.643` |
| max drawdown | `-40.56%` |
| recovery days | `1199` |
| cost-adjusted annual return | `-4.69%` |

Lesson:
- Tail-stability filters preserve some monotonicity but weaken the high-amount active-liquidity return source.
- Do not add unsupported higher-moment operators until the DSL has a formal semantics and validator support.

### Amount Delta / Short-Term Amount Cooling

`base * (1 - rank(delta(amount, 5)))` was not accepted as a formal result in this round because the valid 2016-window wrapper proof did not reach `PASS`. A previous artifact used the wrong 2010-start window and must not be treated as evidence.

Lesson:
- When proof status and artifact status disagree, trust the wrapper proof and sample-window identity.
- This branch may be retried only with a clean report id and verified 2016 actual window, but it is not currently part of the evidence set.

## Return Source Classification

Primary classification: `behavioral_microstructure_active_liquidity`

Secondary classification: `market_structure_harvesting`

Rejected classifications:
- `low_liquidity_risk_premium`: high `amount` improves the factor; low-amount and low-turnover gates generally damage it.
- `stable_information_advantage`: the evidence is more consistent with active trading structure and crowding/reversal than persistent early information capture.
- `pure_quality_or_low_risk`: low volatility and low kurtosis filters weaken the factor.

Interpretation:
- The factor seems to make money by identifying active, high-attention stocks where the high-price and volume co-movement is not simply overheated crowd confirmation.
- It is closer to harvesting active market-structure behavior than earning a passive liquidity premium.
- The likely counterparty is not only retail; in 2016+ A-share regimes the other side can include public funds, theme followers, and crowded active allocators. The factor should avoid direct confrontation with the smartest high-frequency/quant flow, but current expression-level evidence cannot prove that separation cleanly.

## Mathematical Structure Review

The useful structure is:

```text
negative ranked rolling correlation between rank(high) and rank(volume)
```

plus:

```text
high amount confirmation
```

and only mild:

```text
turnover penalty
```

Mathematical implications:
- The 7-day correlation/sum window is a better estimator than the canonical 3-day window because it stabilizes the observed price-volume relation without making the signal stale.
- Multiplying by `rank(amount)` changes the state space. It is not a neutral scaling; it concentrates the signal into active liquidity names.
- Multiplying by strong `1-rank(turnover)` changes the mechanism too much and breaks the active-liquidity state.
- The best turnover penalty is a shrinkage coefficient, not a filter.
- Low-volatility and low-kurtosis penalties are orthogonal risk filters. They are mathematically plausible for generic risk control, but empirically wrong for this factor's revenue source.

## Why Marginal Research Value Is Now Low

Alpha015 has a real and economically interpretable signal body, but the remaining defect is not easily fixed by another expression-level scalar penalty.

Reasons to stop this branch:

1. The high-amount branch already discovered the main mechanism.
2. Turnover penalty sweep improved cost-adjusted annual return by only about `1.3` percentage points.
3. All risk-quality filters tested so far reduce the revenue source more than they reduce bad risk.
4. Gross max drawdown remains near `-40%`; recovery remains around `700` days even in the best variants.
5. Cost-adjusted max drawdown remains near or below `-60%` with unrecovered path behavior.
6. Further tuning of `a` would likely optimize noise unless the next revision introduces a real market-regime variable.

## Kill Criteria

Do not continue Alpha015-specific scalar-filter research unless a future branch can meet all of the following:

- formal wrapper proof `PASS`;
- actual window verified as `2016-01-04 -> 2026-04-24` or later 2016+ equivalent;
- long-side Sharpe remains near or above `0.80`;
- gross max drawdown improves materially toward `-35%`;
- recovery days compress materially toward one trading year;
- cost-adjusted annual return improves without cost-adjusted max drawdown staying near `-60%`;
- the revision changes the economic state variable, not just another scalar penalty.

Promising future direction, if Alpha015 is reopened:
- true market-regime gate using market-wide turnover/risk appetite/theme activity, if the data contract and formula language support it formally;
- clean amount-cooling test with a new report id and verified wrapper proof;
- interaction with a separately validated theme/crowding regime factor, not a direct portfolio rule.

## Transferable Patterns

Reusable pattern:
- For Alpha101 price-volume factors, first distinguish mechanism gate variables from risk-control variables. `rank(amount)` can be a mechanism gate, not a cost proxy.
- Mild shrinkage penalties can improve cost-adjusted returns, but should not be mistaken for solving drawdown.
- If low-volatility, low-kurtosis, or low-turnover filters reduce alpha more than risk, the factor likely monetizes active market structure rather than passive risk premium.
- Always split evidence into signal quality, long-side economics, and cost-adjusted path quality.

Anti-pattern:
- Do not keep adding generic risk filters to an active-liquidity factor.
- Do not interpret high IC and monotone deciles as promotion evidence when the cost-adjusted NAV remains unrecovered.
- Do not treat unsupported `skewness/kurtosis` as formal expressions through fixture or fallback mechanisms.
- Do not accept artifacts with wrong sample windows even if they contain metrics.

## Evidence References

- `objects/runtime_context/ultimate_run_report__ALPHA015_CANONICAL_FORMULA_20160101.json`
- `objects/runtime_context/ultimate_run_report__ALPHA015_REV_CORR5_SUM5_20160101.json`
- `objects/runtime_context/ultimate_run_report__ALPHA015_REGIME_R03_CORR7_HIGHAMOUNT_20160101.json`
- `objects/runtime_context/ultimate_run_report__ALPHA015_RISK_A_HIGHAMOUNT_LOWVOL20_20160101.json`
- `objects/runtime_context/ultimate_run_report__ALPHA015_RISK_B_HIGHAMOUNT_LOWTURN_20160101.json`
- `objects/runtime_context/ultimate_run_report__ALPHA015_RISK_B_HIGHAMOUNT_HALFLOWTURN_20160101.json`
- `objects/runtime_context/ultimate_run_report__ALPHA015_RISK_C_HIGHAMOUNT_LOWKURT20_20160101.json`
- `objects/runtime_context/ultimate_run_report__ALPHA015_RISK_C_HIGHAMOUNT_LOWKURT20_MOMENT_20160101.json`
- `objects/runtime_context/ultimate_run_report__ALPHA015_SWEEP_TURNPEN_A025_20160101.json`
- `objects/runtime_context/ultimate_run_report__ALPHA015_SWEEP_TURNPEN_A040_20160101.json`
- `objects/runtime_context/ultimate_run_report__ALPHA015_SWEEP_TURNPEN_A060_20160101.json`
- `objects/runtime_context/ultimate_run_report__ALPHA015_SWEEP_TURNPEN_A075_20160101.json`
- `evaluations/ALPHA015_SWEEP_TURNPEN_A040_20160101/self_quant_analyzer/evaluation_payload.json`
- `evaluations/ALPHA015_SWEEP_TURNPEN_A040_20160101/self_quant_analyzer/quantile_nav_10groups.csv`

## Links

- [[知识库/A股量价因子市场结构先验|A股量价因子市场结构先验]]
