---
report_id: "ALPHA014_RESEARCH_ARCHIVE_20160101"
factor_id: "Alpha014"
decision: "reject_archive_as_lesson"
tags:
  - "knowledge"
  - "reject"
  - "alpha101"
  - "long_only"
  - "liquidity_risk_premium"
---

# Knowledge Record: Alpha014 2016+ Research Archive

- decision: `reject_archive_as_lesson`
- research_window_default: `2016-01-01 onward`
- verified_actual_window: `2016-01-04 -> 2026-04-24`
- current_best_revision: `ALPHA014_REV_SMOOTH5_LOWTURN_20160101`
- formal_entry_rule: Step3-6 evidence came from `scripts/run_factorforge_ultimate.py`

## Source Formula

WorldQuant Alpha014 canonical formula:

```text
((-1 * rank(delta(returns, 3))) * correlation(open, volume, 10))
```

The formula mixes short-horizon return acceleration reversal with the relation between open price and volume. In A-share 2016+ evidence, the raw formula is too noisy and costly for long-only adoption.

## Final Research Judgment

Alpha014 has a weak but real high-score long-side tail. The useful part appears only after smoothing and low-turnover filtering, but the edge does not clear Factor Forge long-only admission gates.

Best tested version:

```text
(mean(((-1 * rank(delta(returns, 3))) * correlation(open, volume, 10)), 5) * (1 - rank(turnover)))
```

Key long-side metrics for `ALPHA014_REV_SMOOTH5_LOWTURN_20160101`:

| Metric | Value |
|---|---:|
| G10 annual return | `9.54%` |
| G10 Sharpe | `0.475` |
| G10 max drawdown | `-34.94%` |
| G10 recovery days | `1823` |
| G10 daily turnover | `22.14%` |
| annual COGS proxy | `16.74%` |
| cost-adjusted annual return | `-7.19%` |
| cost-adjusted Sharpe | `-0.358` |
| G10 final NAV | `2.0838` |

This is close to the candidate Sharpe threshold but fails on cost-adjusted return and recovery time. The factor should not be promoted.

## Tested Revisions

| Revision | G10 Ann. | Sharpe | Max DD | Recovery | Daily Turnover | Cost-Adj Ann. | Judgment |
|---|---:|---:|---:|---:|---:|---:|---|
| `smooth5_lowturn` | `9.54%` | `0.475` | `-34.94%` | `1823` | `22.14%` | `-7.19%` | best tested version, still reject |
| `smooth10_lowturn` | `8.19%` | `0.406` | `-37.08%` | `2007` | `16.68%` | `-4.42%` | lower cost but signal too stale |
| `smooth5_lowamount` | `9.81%` | `0.445` | `-43.59%` | `1792` | `21.65%` | `-6.56%` | adds crude liquidity risk, worsens drawdown |
| `smooth5_lowvol20` | `7.73%` | `0.388` | `-38.10%` | `1781` | `20.27%` | `-7.59%` | risk filter helps but weakens alpha body |

10-group evidence is not cleanly monotonic. Low-turnover variants create a U-shaped or tail-selector profile: G10 is useful, middle buckets are weak, and the full cross-sectional rank IC can be negative. Treat deciles as diagnostics only, not a trading expression.

## Return Source Classification

Primary classification: `weak_liquidity_or_neglect_risk_premium`

Secondary classification: `market_structure_avoidance`

Rejected classifications:
- `information_advantage`: not supported strongly enough after 2016. There is no evidence that the signal reliably identifies smart money with a persistent information lead.
- `pure_bosha`: not a clean retail-harvesting factor. High heat, high turnover, and high amount are not where the useful long-side edge sits.

Interpretation:
- The factor seems to earn money only when Alpha014-like price-volume structure occurs in low-turnover, lower-attention names.
- This looks more like being paid for holding neglected or liquidity-discounted names than harvesting theme-chasing behavior.
- The risk premium is not strong enough to cover turnover cost and long recovery.

## Mathematical Structure Review

The original formula is a signed product:

```text
short_return_change_component * open_volume_correlation_component
```

Smoothing helps because the raw interaction is too noisy and has high turnover. Low-turnover weighting helps because it removes the most crowded or high-heat battlefield. But each useful modification is a penalty or persistence filter, not a new alpha source.

Important lessons:
- `mean(base, 5)` is useful; `mean(base, 10)` becomes too stale.
- `1 - rank(turnover)` is the strongest tested risk selector.
- `1 - rank(amount)` is too crude; it increases low-liquidity exposure and worsens drawdown.
- `1 - rank(stddev(returns,20))` lowers risk somewhat but does not produce enough revenue.
- `skewness` and `kurtosis` are theoretically relevant but were not formally tested because the current formula DSL does not support them. Unsupported operators must block, not fallback.

## Why Marginal Research Value Is Low

Further Alpha014-specific research is unlikely to produce a robust official factor without overfitting:

1. The best version is already near the obvious expression-level improvement frontier: smoothing plus low-turnover filtering.
2. Additional filters mostly trade one failure for another: lower turnover, lower volatility, or lower amount exposure do not solve cost-adjusted losses and multi-year recovery.
3. The factor is a tail selector, not a clean monotonic cross-sectional factor. That makes expression-level improvements fragile.
4. The expected next improvements, such as low kurtosis, are risk filters rather than alpha-body repairs.
5. The 2020-2024 drawdown/recovery problem is structural, not just a parameter issue.

## Kill Criteria

Stop Alpha014 as a standalone research line unless a future system-wide enhancement changes the setup.

Do not continue Alpha014-specific iterations unless all of these are true:
- the revision changes the factor expression itself, not portfolio mechanics;
- actual 2016+ evidence uses wrapper proof with `status: PASS`;
- G10 Sharpe clears `0.50`;
- max drawdown is no worse than `-35%`;
- recovery days materially compress toward one trading year;
- cost-adjusted annual return is not negative under the default COGS proxy.

## Transferable Patterns

Reusable pattern:
- For Alpha101-style price-volume factors, test persistence smoothing before complex nonlinear filters.
- If a factor revives only after `lowturn`, interpret it as a liquidity or neglect premium candidate, not as automatic evidence of information advantage.
- If the shape becomes U-shaped, treat the factor as a tail selector and increase overfit skepticism.

Anti-pattern:
- Do not keep multiplying penalties onto a weak alpha body until G10 improves. This can create a narrow low-liquidity tail exposure with poor recovery and capacity.
- Do not use long-short spread or short-leg weakness to rescue a long-only factor.
- Do not treat unsupported `skewness/kurtosis` formulas as runnable through fixture or fallback paths.

## Future Idea Seeds

These are not Alpha014 continuation tasks; they are reusable ideas for other factors:

1. `lowturn + lowkurtosis` may be a useful risk filter for price-volume factors where the alpha body is already strong.
2. `smooth5` appears to be a reasonable first persistence test for noisy Alpha101 formulas.
3. Regime analysis should separate 2016-2019, 2020-2024-09-23, and post-2024-09-24 before accepting any post-2016 price-volume alpha.
4. For factors that only work in neglected names, capacity and recovery should be treated as first-class acceptance gates, not afterthoughts.

## Evidence References

- `objects/runtime_context/ultimate_run_report__ALPHA014_REV_SMOOTH5_LOWTURN_20160101.json`
- `objects/runtime_context/ultimate_run_report__ALPHA014_REV_SMOOTH10_LOWTURN_20160101.json`
- `objects/runtime_context/ultimate_run_report__ALPHA014_REV_SMOOTH5_LOWAMOUNT_20160101.json`
- `objects/runtime_context/ultimate_run_report__ALPHA014_REV_SMOOTH5_LOWVOL20_20160101.json`
- `objects/validation/factor_evaluation__ALPHA014_REV_SMOOTH5_LOWTURN_20160101.json`
- `objects/validation/factor_evaluation__ALPHA014_REV_SMOOTH10_LOWTURN_20160101.json`
- `objects/validation/factor_evaluation__ALPHA014_REV_SMOOTH5_LOWAMOUNT_20160101.json`
- `objects/validation/factor_evaluation__ALPHA014_REV_SMOOTH5_LOWVOL20_20160101.json`

## Links

- [[知识库/A股量价因子市场结构先验|A股量价因子市场结构先验]]
