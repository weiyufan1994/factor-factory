# V19 Return-Volume Full-Window Research Note

Date: 2026-06-13
Owner: Factor Forge Ultimate research
Scope: value-occupation V19 return-volume confirmation, full-window IS through 2025-07-11

## Research Question

Test whether intraday return-volume covariation adds incremental long-side information to the value-occupation repair family across broad and index universes:

- full A-share research universe
- middle_20_90, largest_10, smallest_20
- CSI800, CSI800+CSI1000, CSI2000, CSI All Share
- fixed_small_20 with the prior small-cap eligibility rule

The factor mechanism being tested is not "price-volume correlation is good" in isolation. The intended state is: below-cost/value-occupation repair plus intraday flow confirmation, where high volume is not concentrated in downside break minutes and where price response is consistent with absorption or constructive repair.

## Data Artifacts

Research-side return-volume state was materialized before evaluation:

- S3 datamart: `s3://yufan-data-lake/factorforge/research_datamart/intraday_return_volume_state_research/v1/`
- full materialization proof: `s3://yufan-data-lake/factorforge/research_datamart/intraday_return_volume_state_research/v1/_meta/full_window_proof.json`
- rows: 9,068,963 in materialization proof; evaluation loaded 9,114,038 cached rows over 2,312 VP dates because evaluation aligns to the VP/daily clean intersection

This is a research datamart, not a Data API P0 production dataset. It is reusable for research because it is a decomposable daily state: each date/instrument value can be computed from that date's minute bars up to cutoff.

## Execution Lesson

The first full-window evaluator used an all-in-memory panel:

1. load full VP state, about 9.1M rows;
2. load full return-volume state, about 9.1M rows;
3. load full daily clean and merge forward-return/control columns;
4. load index universe membership and create all universe flags;
5. residualize size against every requested universe in one process.

This failed twice on the 30GiB `factor-research-worker`:

- first failure during all-universe index membership merge: kernel OOM killed Python with about 31.7GiB anonymous RSS;
- second failure after retry with batched index universe logic, still before evaluation, because the base VP+flow+daily merge was too large.

Conclusion: for full-window minute-derived factors, preaggregating minute state is necessary but not sufficient. Step4-style evaluation must also be partitioned when the merged panel is multi-million rows and includes forward returns, universe flags, and residual controls.

## Correct Execution Pattern

V19 was downgraded to `--stream-by-date`:

- read one VP date partition;
- read one cached return-volume feature partition;
- join the matching daily clean rows for that date;
- compute cross-sectional z-scores and V19 signals for that date;
- load index universe membership only for that date;
- compute size-neutral residuals inside the current date/universe slice;
- emit daily IC/top-decile rows and release the daily frame.

The only carried state is the per-stock `no_break` history needed for V18 2-day and 3-day persistence gates. This preserves the persistence mechanism without holding the full VP panel in memory.

## Current Run

Command id:

- `1f620e0a-04cf-4883-bf93-2c778e837517`

Output prefix:

- `s3://yufan-data-lake/factorforge/tmp/vp_v19_20260613/full_window_materialized_flow_stream`

Final run status:

- SSM command id: `1f620e0a-04cf-4883-bf93-2c778e837517`
- status: `Success`
- elapsed: `PT1H51M17.357S`
- output prefix: `s3://yufan-data-lake/factorforge/tmp/vp_v19_20260613/full_window_materialized_flow_stream/`
- output files: `vp_v19_return_volume_metrics.csv`, `vp_v19_return_volume_all_period.md`, `vp_v19_return_volume_summary.json`, `vp_v19_return_volume_feature_profile.json`, `run.log`
- coverage: 2,312 VP dates, 8,033,907 daily-clean rows, 1,365 aggregated metric rows

The stream evaluator completed without OOM. Peak observed process memory was below the 30GiB worker limit, whereas the all-in-memory evaluator was killed twice.

## Full-Window Result Summary

Horizon 5 all-period comparison:

| universe | signal | dates | IC | residual IC | gross top excess | net top excess | turnover | hit |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| full | v18_repair_drift_score__sn_full | 2312 | 0.055114 | 0.006642 | 0.001163 | 0.000418 | 0.372486 | 0.578287 |
| full | v19_rv_corr_repair__sn_full | 2312 | 0.048596 | 0.006152 | 0.001005 | 0.000133 | 0.436140 | 0.569204 |
| middle_20_90 | v18_repair_drift_score__sn_middle_20_90 | 2312 | 0.057101 | 0.005733 | 0.001337 | 0.000587 | 0.374916 | 0.584343 |
| middle_20_90 | v19_rv_corr_repair__sn_middle_20_90 | 2312 | 0.049985 | 0.005079 | 0.001232 | 0.000353 | 0.439443 | 0.572664 |
| largest_10 | v18_repair_drift_score | 2311 | 0.039556 | 0.011868 | 0.001485 | 0.000708 | 0.388847 | 0.548680 |
| largest_10 | v19_rv_corr_repair | 2311 | 0.038729 | 0.013395 | 0.001547 | 0.000651 | 0.448017 | 0.556469 |
| smallest_20 | v18_repair_drift_score__sn_smallest_20 | 2312 | 0.054263 | 0.005555 | 0.001229 | 0.000427 | 0.400980 | 0.532007 |
| smallest_20 | v19_rv_corr_repair__sn_smallest_20 | 2312 | 0.045098 | 0.003051 | 0.000932 | 0.000007 | 0.462528 | 0.528547 |
| fixed_small_20 | v18_repair_drift_score | 2312 | 0.056668 | 0.004278 | 0.001098 | 0.000342 | 0.377795 | 0.532439 |
| fixed_small_20 | v19_rv_corr_repair__sn_fixed_small_20 | 2312 | 0.048541 | 0.002959 | 0.001068 | 0.000183 | 0.442145 | 0.537197 |
| csi800 | v18_repair_drift_score__sn_csi800 | 2294 | 0.037072 | 0.004866 | 0.000768 | -0.000029 | 0.398593 | 0.540541 |
| csi800 | v19_rv_corr_repair__sn_csi800 | 2294 | 0.034631 | 0.006183 | 0.000859 | -0.000067 | 0.463141 | 0.533130 |
| csi800_csi1000 | v18_repair_drift_score__sn_csi800_csi1000 | 2294 | 0.044378 | 0.004126 | 0.000941 | 0.000169 | 0.386353 | 0.555362 |
| csi800_csi1000 | v19_rv_corr_repair__sn_csi800_csi1000 | 2294 | 0.039635 | 0.004582 | 0.000912 | 0.000006 | 0.453078 | 0.557105 |
| csi2000 | v18_repair_drift_score | 449 | 0.057526 | 0.006709 | 0.002061 | 0.001326 | 0.367428 | 0.581292 |
| csi2000 | v19_rv_corr_repair | 449 | 0.049131 | 0.005811 | 0.001809 | 0.000941 | 0.433737 | 0.601336 |
| csi2000 | below_cost_depth_score_raw | 449 | 0.039670 | 0.012156 | 0.002105 | 0.001681 | 0.212300 | 0.469933 |
| csi_all_share | v18_repair_drift_score__sn_csi_all_share | 2294 | 0.054806 | 0.006079 | 0.001119 | 0.000368 | 0.375368 | 0.580209 |
| csi_all_share | v19_rv_corr_repair__sn_csi_all_share | 2294 | 0.048229 | 0.005743 | 0.000964 | 0.000085 | 0.439203 | 0.564516 |

## Interpretation

1. V19 return-volume confirmation is not a better main factor than V18 drift repair on the full window. In every broad universe, the best V19 variant has lower IC and lower net top-decile excess than the V18 drift score or its size-neutral version.

2. The best V19 family member is consistently `v19_rv_corr_repair`, especially with universe-specific size neutralization outside `largest_10`. More complex flow-confirmed, guarded, absorption, or upside-confirmed composites generally add turnover and lose net long-side quality.

3. The useful V19 clue is in large caps. In `largest_10`, V19 has slightly lower IC than V18 but higher residual IC and similar gross/net long-side quality:
   - V18 horizon 5: IC 0.039556, residual IC 0.011868, net top excess 0.000708
   - V19 RV corr horizon 5: IC 0.038729, residual IC 0.013395, net top excess 0.000651

   This supports the idea that intraday return-volume covariation is closer to an institutional absorption/participation diagnostic than a universal alpha upgrade.

4. CSI800 is not enough by itself after cost. V19 improves gross top excess and residual IC versus V18 in CSI800 horizon 5, but turnover rises from 0.398593 to 0.463141, pushing net top excess from -0.000029 to -0.000067. For a CSI800-style index enhancement, V19 must be used as a low-turnover gate or interaction, not as an additive score that reshuffles names.

5. Small-cap and fixed-small universes do not benefit from V19 as currently formulated. V19 lowers IC and increases turnover. In `smallest_20`, V19 horizon 5 net top excess is effectively zero (0.000007) versus V18 size-neutral 0.000427. In `fixed_small_20`, V19 is positive but weaker than V18.

6. CSI2000 looks strong, but coverage is only 449 dates. The best net signal there is actually raw `below_cost_depth_score_raw` because turnover is low. Treat CSI2000 as a promising but shorter-history diagnostic, not the primary proof.

## Mechanism Read

The stochastic-process intuition survived, but the formula implementation was too eager:

- RV correlation captures a semimartingale covariation term between return increments and liquidity/volume increments.
- When this covariation is positive inside a below-cost repair state, it can indicate that volume is arriving with constructive price response rather than with downside breaks.
- But at daily rebalancing, the intraday covariation component has higher state volatility than the slower value-occupation repair state.
- Additive scoring therefore raises turnover faster than it raises gross edge.

The right next direction is not "more return-volume terms". It is lower-churn use of the term:

- as a gate only when V18/top repair candidates disagree;
- as a tie-breaker inside large-cap repair candidates;
- as a persistence filter requiring 2-3 days of constructive RV state;
- or as a turnover-aware interaction that cannot overturn the V18 state ranking by itself.

## Lessons For Future Factor Forge Research

- If the state variable is decomposable by `trade_date, ts_code`, materialize it once as daily state before factor iteration.
- Do not assume a daily-state datamart makes the evaluator safe. The dangerous object may be the merged research panel.
- Treat full-universe, multi-universe, size-neutral, multi-horizon evaluation as a batch problem by default.
- For persistence gates, carry minimal ticker-level state instead of loading the full history.
- The research boundary remains: datamart stores state variables; alpha formulas and composite scores stay in research code until promoted.

## Decision

Do not promote V19 as a standalone replacement for V18 drift repair.

Keep the return-volume state datamart and `v19_rv_corr_repair` as a research component. The next branch should test a low-turnover large-cap gate:

`V18_repair_drift_score + gated_small_weight(RV_corr_z)` only inside stable V18 candidates, with a hard constraint that turnover cannot exceed the V18 baseline by more than a small tolerance.
