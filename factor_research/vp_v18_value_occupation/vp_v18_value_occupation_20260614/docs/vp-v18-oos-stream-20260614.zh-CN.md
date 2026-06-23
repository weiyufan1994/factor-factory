# VP V18 OOS Stream Evaluation Note

Date: 2026-06-15

## Scope

This note records the OOS evaluation for the value-occupation V18 repair/drift family. The evaluation uses the default Factor Forge research split: in-sample ends on 2025-07-11, and the tested OOS window is 2025-07-14 to 2026-06-12.

The goal is not to promote a standalone long-only strategy. The goal is to decide whether V18 is strong enough to enter the factor library or the alpha-composite candidate pool.

## Artifacts

- Value-occupation OOS research datamart: `s3://yufan-data-lake/factorforge/research_datamart/intraday_value_occupation_state_oos_stream/v1`
- Evaluation output: `s3://yufan-data-lake/factorforge/tmp/vp_v18_20260614_oos/stream_eval`
- Completion proof: `s3://yufan-data-lake/factorforge/tmp/vp_v18_20260614_oos/stream_completion.json`
- QA proof: `s3://yufan-data-lake/factorforge/tmp/vp_v18_20260614_oos/stream_value_occupation_state.qa.json`

Local inspected copies were under `/tmp/vp18_oos_stream_eval`.

## Data QA

The stream-by-date materialization succeeded.

- QA verdict: `ACCEPT`
- Output dates: 2025-07-14 to 2026-06-12
- Date coverage: 222 / 222, missing `[]`
- Output rows: 1,209,358
- Tickers: 5,529
- Evaluation merged rows: 1,008,139
- Evaluation merged tickers: 4,674
- Runtime: 8,370 seconds, about 2h19m

Implementation lesson: the earlier batch-style minute-state build was memory fragile. The stream-by-date design is the right research pattern for this class: it keeps the state decomposable by trade date and avoids holding the full minute history in one process.

## Main OOS Result

For the main signal `v18_repair_drift_score`, OOS Rank IC remains positive, but long-side top-decile excess is negative in almost all useful settings. That means the factor keeps some broad sorting information, but the long tail selected by the top bucket is not investable as-is.

| universe | horizon | rank_ic_mean | residual_ic_mean | top_decile_excess_mean | turnover | net_top_decile_excess_mean |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| full | 1D | 0.032915 | 0.003200 | -0.000102 | 0.400863 | -0.000904 |
| full | 3D | 0.030065 | 0.000457 | -0.000630 | 0.401445 | -0.001433 |
| full | 5D | 0.025068 | -0.003754 | -0.001600 | 0.402028 | -0.002404 |
| middle_20_90 | 1D | 0.037024 | 0.004624 | 0.000009 | 0.398062 | -0.000787 |
| middle_20_90 | 3D | 0.035606 | 0.001533 | -0.000521 | 0.398314 | -0.001318 |
| middle_20_90 | 5D | 0.030333 | -0.002821 | -0.001533 | 0.398636 | -0.002330 |
| largest_10 | 1D | 0.021543 | 0.001017 | -0.000335 | 0.388686 | -0.001112 |
| largest_10 | 3D | 0.018150 | 0.003977 | -0.001522 | 0.390147 | -0.002302 |
| largest_10 | 5D | 0.009414 | 0.002978 | -0.002848 | 0.391015 | -0.003630 |
| smallest_20 | 1D | 0.019109 | 0.000514 | -0.000174 | 0.444093 | -0.001062 |
| smallest_20 | 3D | 0.016280 | -0.003067 | -0.000488 | 0.445211 | -0.001379 |
| smallest_20 | 5D | 0.011915 | -0.007801 | -0.001339 | 0.445675 | -0.002230 |

## Interpretation

The V18 economic story was: below-cost repair plus lower support plus drift confirmation should identify a repair state where liquidation pressure has been absorbed and price can mean-revert upward.

The OOS evidence weakens the long-side version of that story. The positive Rank IC says the state variable is not noise. The negative top-decile excess says the highest-score names are not the best long basket after costs, and often not even before costs.

The likely failure mode is tail selection. The signal can order the cross-section mildly, but the extreme high-score set may contain crowded repair-looking names, regime-sensitive rebounds, or stocks whose apparent support is stale. In the full 5D OOS result, the universe return mean is positive while the top-bucket return lags it, so the factor is selecting stocks that rise less than the broad opportunity set.

The residual IC also deteriorates at 5D after controls such as size, short drift, 5D/20D momentum, turnover, and 20D volatility. This suggests part of the in-sample effect was carried by regime/risk/momentum structure rather than a robust independent long-side repair mechanism.

## Decision

Do not promote V18 as an official standalone long-only factor.

It can remain a weak feature candidate for a composite model, but only under an explicit marginal-contribution test:

- residualize against momentum, reversal, size, liquidity, volatility, and existing Barra-like exposures;
- measure incremental IC/IR and portfolio objective contribution inside the alpha stack;
- penalize turnover directly, because top-decile turnover is around 0.39 to 0.45;
- test whether lower-score exclusion or middle-bucket tilting works better than top-decile long selection.

Current conclusion: based on this OOS run, V18 is not "very helpful" by default for the optimizer. It is at most a diagnostic or low-weight candidate until a true incremental stack test proves otherwise.
