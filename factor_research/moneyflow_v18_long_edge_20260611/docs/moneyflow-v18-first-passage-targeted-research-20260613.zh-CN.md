# Moneyflow V18 first-passage targeted research note

Date: 2026-06-13

Author: Codex / Factor Forge researcher

This note deposits the V18 targeted research round before any next moneyflow
branch is started. It is a research-side targeted proof, not an official
Factor Forge promotion or full `run_factorforge_ultimate_loop.py` closure.

## Run Identity

- Research family: Miller moneyflow / intraday flow distribution moments
- Parent reference: V15 repair-confirmed absorption first-passage law
- Tested laws:
  - `miller_flow_v15_repair_confirmed_absorption_fp_v1`
  - `miller_flow_v18a_absolute_long_edge_gate_v1`
  - `miller_flow_v18b_first_passage_repair_edge_v1`
  - `miller_flow_v18c_crowding_filtered_repair_v1`
- Worker instance: `i-02cc0b6e93856fbb4`
- SSM command: `ba3bb930-5dd3-4a65-932b-14879ac87f1c`
- S3 result root:
  `s3://yufan-data-lake/factorforge/tmp/moneyflow_v18_20260613/targeted_results/`
- Local result copy:
  `/tmp/moneyflow_v18_targeted_20260613_results/`
- Evaluation window: `20160104` to `20250711`
- OOS rule: data after `2025-07-11` remains holdout and was not used here.
- Cutoff time: `14:50`
- Cost assumption: `20 bps * turnover`
- Portfolio policy emphasized:
  `top10_dropout30_rebalance5_equal`

Side effects:

- `clean_data_started=false`
- `search_worker_started=false`
- `official_promotion_started=false`
- `factor_forge_artifacts_written=false`

## Dirac-Style Research Equation

The working economic hypothesis is not simply that moneyflow predicts return.
The target state is:

> buy stocks currently receiving sell pressure from profit payers or forced
> sellers, but only when the flow/return shape implies absorption and repair,
> not crowded chasing or unresolved distress.

The stochastic benchmark is:

$$
dP_{i,t}
=
\mu(H_{i,t}, C_{i,t}, B_{i,t})\,dt
+ \sigma_{i,t}\,dW_{i,t}
$$

where:

- $H_{i,t}$ is hidden repair / absorption state.
- $C_{i,t}$ is crowding and prior overheat state.
- $B_{i,t}$ is breakdown or bad-selling-noise state.
- $\mu(\cdot)$ is the conditional drift that should be positive only when
  absorption has been confirmed and downside barrier risk is lower than upside
  repair potential.

The first-passage form is:

$$
\tau_{\mathrm{up}}
=
\inf\{s>t:P_{i,s}\ \text{hits repair target}\}
$$

$$
\tau_{\mathrm{down}}
=
\inf\{s>t:P_{i,s}\ \text{breaks downside barrier}\}
$$

The tradable long edge should satisfy:

$$
\mathrm{LongEdge}_{i,t}
=
\Pr(\tau_{\mathrm{up}} < \tau_{\mathrm{down}}\mid \mathcal F_t)
\,D_{\mathrm{up},i,t}
-
\Pr(\tau_{\mathrm{down}} < \tau_{\mathrm{up}}\mid \mathcal F_t)
\,D_{\mathrm{down},i,t}
-
\mathrm{Cost}_{i,t}
$$

The useful expression is therefore not just a rank score. It must increase with
confirmed absorption and upside repair distance, and decrease with crowding,
bad-selling-noise, unresolved distress, and expected turnover cost.

## Tested Mechanisms

### V15 Baseline

V15 already contains the strongest prior result:

- identify sell pressure,
- require repair confirmation between earlier and later cutoff states,
- reward absorption momentum,
- penalize bad-selling-noise and crowding,
- map the result into a first-passage-like absorption-minus-breakdown score.

### V18a

V18a adds an absolute long-edge gate:

$$
\mathrm{Signal}_{18a}
=
M_{18}\,G_{\mathrm{long}}\,
(0.70 + 0.36G_{\mathrm{tradable}})
-
0.18(0.50-G_{\mathrm{long}})^+
-
0.08C_{18}
$$

where $M_{18}$ is absolute long margin, $G_{\mathrm{long}}$ is the probability
gate for absolute long edge, $G_{\mathrm{tradable}}$ is a tradability/mid-cap
gate, and $C_{18}$ is crowding overheat.

Interpretation: V18a asks whether the signal is not only cross-sectionally
ranked well, but also absolutely buyable on the long side.

### V18b

V18b makes the first-passage structure explicit:

$$
\mathrm{Signal}_{18b}
=
G_{\mathrm{tradable}}
\left[
p_{\mathrm{up}}(0.54+0.30D_{\mathrm{up}})
-
p_{\mathrm{down}}(0.56+0.26D_{\mathrm{down}})
-
0.10U
-
0.08O
\right]
$$

where:

- $p_{\mathrm{up}}$ estimates repair-hit probability,
- $p_{\mathrm{down}}$ estimates downside-break probability,
- $D_{\mathrm{up}}$ and $D_{\mathrm{down}}$ are upside/downside distance proxies,
- $U$ is unconfirmed distress penalty,
- $O$ is prior overheat.

Interpretation: V18b is closest to the Dirac-style stopped-process equation.

### V18c

V18c adds a stricter smart-repair gate:

$$
\mathrm{Signal}_{18c}
=
Q_{\mathrm{repair}}G_{\mathrm{smart}}
(0.68+0.24G_{\mathrm{tradable}})
-
0.22C_{18}
-
0.14U
$$

Interpretation: this tries to separate smart repair from crowding more
aggressively. Evidence below shows this filter is too harsh or mis-specified.

## Main Portfolio Evidence

Policy: `top10_dropout30_rebalance5_equal`.

| law | universe | date_count | net_return_mean | turnover | net_sharpe_proxy | max_drawdown_proxy | nav_final_proxy |
| --- | --- | --- | --- | --- | --- | --- | --- |
| V15 | csi2000 | 446 | 0.001152 | 0.139730 | 0.974126 | -0.367158 | 1.508094 |
| V18a | csi2000 | 446 | 0.001157 | 0.140022 | 0.985487 | -0.349720 | 1.516246 |
| V18b | csi2000 | 446 | 0.001217 | 0.142389 | 0.990782 | -0.346160 | 1.548443 |
| V18c | csi2000 | 446 | 0.000406 | 0.146167 | 0.302726 | -0.327841 | 1.067130 |
| V15 | fixed_small_10 | 2302 | 0.000632 | 0.156679 | 0.557505 | -0.421773 | 2.776920 |
| V18a | fixed_small_10 | 2302 | 0.000746 | 0.153959 | 0.679276 | -0.411044 | 3.673678 |
| V18b | fixed_small_10 | 2302 | 0.000727 | 0.157157 | 0.624552 | -0.417707 | 3.437384 |
| V18c | fixed_small_10 | 2302 | 0.000238 | 0.165310 | 0.145434 | -0.525282 | 1.097970 |
| V15 | fixed_small_20 | 2302 | 0.000606 | 0.149859 | 0.577612 | -0.412417 | 2.722338 |
| V18a | fixed_small_20 | 2302 | 0.000761 | 0.148492 | 0.729367 | -0.393847 | 3.930542 |
| V18b | fixed_small_20 | 2302 | 0.000648 | 0.151404 | 0.606235 | -0.403276 | 2.966116 |
| V18c | fixed_small_20 | 2302 | 0.000358 | 0.157067 | 0.260164 | -0.418859 | 1.509526 |
| V15 | smallest_20 | 2302 | 0.000846 | 0.148486 | 0.817220 | -0.462782 | 4.648145 |
| V18a | smallest_20 | 2302 | 0.001101 | 0.147955 | 1.041066 | -0.442239 | 8.423317 |
| V18b | smallest_20 | 2302 | 0.001054 | 0.148694 | 0.969172 | -0.441669 | 7.438977 |
| V18c | smallest_20 | 2302 | 0.000869 | 0.153495 | 0.765886 | -0.420178 | 4.807781 |
| V15 | middle_10_80 | 2303 | 0.000291 | 0.139874 | 0.282245 | -0.426234 | 1.418961 |
| V18a | middle_10_80 | 2303 | 0.000344 | 0.140248 | 0.350934 | -0.398592 | 1.621108 |
| V18b | middle_10_80 | 2303 | 0.000338 | 0.143334 | 0.305777 | -0.394077 | 1.572287 |
| V18c | middle_10_80 | 2303 | -0.000132 | 0.148997 | -0.219813 | -0.409871 | 0.524260 |
| V15 | full | 2303 | 0.000215 | 0.138112 | 0.218360 | -0.424914 | 1.222486 |
| V18a | full | 2303 | 0.000240 | 0.136152 | 0.249072 | -0.398888 | 1.316937 |
| V18b | full | 2303 | 0.000275 | 0.140137 | 0.236399 | -0.393681 | 1.408425 |
| V18c | full | 2303 | -0.000077 | 0.142211 | -0.184212 | -0.403886 | 0.620242 |

## IC Evidence

Horizon 1 selected rows:

| law | universe | rank_ic_mean | pearson_ic_mean | top_decile_return | universe_mean_return | top_decile_excess |
| --- | --- | --- | --- | --- | --- | --- |
| V15 | csi2000 | 0.065000 | 0.046994 | 0.001360 | 0.001079 | 0.000281 |
| V18a | csi2000 | 0.054905 | 0.036397 | 0.001359 | 0.001079 | 0.000279 |
| V18b | csi2000 | 0.056824 | 0.044925 | 0.001370 | 0.001079 | 0.000290 |
| V18c | csi2000 | 0.005748 | -0.010845 | 0.000015 | 0.001079 | -0.001064 |
| V15 | fixed_small_10 | 0.064037 | 0.052165 | 0.001006 | 0.000597 | 0.000409 |
| V18a | fixed_small_10 | 0.059332 | 0.045647 | 0.001170 | 0.000597 | 0.000573 |
| V18b | fixed_small_10 | 0.059456 | 0.057294 | 0.001061 | 0.000597 | 0.000465 |
| V18c | fixed_small_10 | 0.016156 | 0.006299 | 0.000222 | 0.000597 | -0.000375 |
| V15 | fixed_small_20 | 0.062609 | 0.046074 | 0.001000 | 0.000638 | 0.000363 |
| V18a | fixed_small_20 | 0.057372 | 0.040472 | 0.001139 | 0.000638 | 0.000501 |
| V18b | fixed_small_20 | 0.057539 | 0.051205 | 0.001092 | 0.000638 | 0.000455 |
| V18c | fixed_small_20 | 0.014073 | 0.004941 | 0.000254 | 0.000638 | -0.000384 |
| V15 | smallest_20 | 0.057790 | 0.042251 | 0.001271 | 0.001119 | 0.000152 |
| V18a | smallest_20 | 0.052884 | 0.036196 | 0.001309 | 0.001119 | 0.000190 |
| V18b | smallest_20 | 0.051931 | 0.048160 | 0.001370 | 0.001119 | 0.000251 |
| V18c | smallest_20 | 0.015517 | 0.006933 | 0.000870 | 0.001119 | -0.000249 |

Rank IC is usually higher than Pearson IC for V15/V18a, which means the signal
contains broad ordinal information. V18b often improves Pearson IC while rank
IC falls modestly, which is consistent with a more continuous first-passage
edge score rather than a pure rank separator.

## Conclusion

1. V18a is the best current all-window small-universe long-side expression.
   It improves net return, Sharpe proxy, NAV, and drawdown versus V15 in
   `fixed_small_10`, `fixed_small_20`, `smallest_20`, `middle_10_80`, `full`,
   and `csi_all_share`.
2. V18b is the cleanest Dirac-style mathematical branch and is strongest in
   `csi2000`, but the CSI2000 evidence only has 446 dates because the current
   index-universe history is short. Treat it as promising but not full-window
   proof.
3. V18c is falsified for now. The stronger crowding filter destroys rank IC,
   top-decile excess, and net return in most universes. Do not repeat this
   exact crowding penalty without a better observable for "retail crowding"
   versus "smart absorption".
4. The expression itself still needs evolution, but the direction should be
   V18a/V18b style:
   - preserve repair confirmation,
   - preserve first-passage reward/risk,
   - keep absolute long-edge gating,
   - avoid over-filtering concentration/crowding,
   - focus first on `fixed_small_20`, `fixed_small_10`, and a longer-history
     index-like small/mid universe when available.

## Feature-Candidate Validation: Residual IC

This follow-up reframes V15/V18 as candidate model features, not standalone
single-factor strategies. The validation question is:

> Does the signal still contain useful cross-sectional information after
> simple size, liquidity, and one-day-return controls, so it is worth feeding
> into later ML or Ledoit-Wolf-style portfolio construction?

Run evidence:

- Worker: `i-02cc0b6e93856fbb4`
- SSM command: `6c5acb34-a4b6-4a05-9a0e-de56d1ae56e6`
- S3 result root:
  `s3://yufan-data-lake/factorforge/tmp/moneyflow_v18_20260613/feature_validation_chunked_results/`
- Local result cache:
  `/tmp/moneyflow_feature_validation_core_20260613_results/`
- Window: `20160104-20250711`
- Horizon: `1`
- Cutoff: `14:50`
- Universes:
  - `full`
  - `middle_10_80`
  - `fixed_small_20`
- Controls residualized cross-sectionally by trade date:
  - `log_circ_mv`
  - `turnover_rate_f`
  - `volume_ratio`
  - `pct_chg`
- Side effects: `clean_data_started=false`, `search_worker_started=false`,
  `official_promotion_started=false`, `factor_forge_artifacts_written=false`

The run was chunked by year. A prior full-window residual-validation attempt
was killed by the worker, so this class of validation should remain chunked or
streamed by date. The worker also lacks optional `tabulate`, so the final
runner writes CSV summaries instead of relying on `DataFrame.to_markdown`.

Aggregated feature evidence:

| universe | feature | raw rank IC | Pearson IC | signal-resid rank IC | both-resid rank IC | raw top-decile excess | resid top-decile excess |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| full | V18b | 0.039787 | 0.036309 | 0.012279 | 0.014648 | 0.000200 | 0.000442 |
| full | V18a | 0.039814 | 0.025947 | 0.014624 | 0.012609 | 0.000110 | 0.000018 |
| full | V15 | 0.049061 | 0.033683 | 0.009791 | 0.009795 | 0.000120 | -0.000109 |
| middle_10_80 | V18b | 0.050134 | 0.042346 | 0.012635 | 0.017249 | 0.000351 | 0.000498 |
| middle_10_80 | V18a | 0.050477 | 0.032955 | 0.015750 | 0.015405 | 0.000284 | -0.000007 |
| middle_10_80 | V15 | 0.058464 | 0.039389 | 0.012206 | 0.013325 | 0.000235 | -0.000110 |
| fixed_small_20 | V18b | 0.057539 | 0.051206 | 0.012163 | 0.020410 | 0.000455 | 0.000583 |
| fixed_small_20 | V18a | 0.057372 | 0.040473 | 0.016741 | 0.018014 | 0.000501 | 0.000144 |
| fixed_small_20 | V15 | 0.062609 | 0.046076 | 0.012106 | 0.015450 | 0.000363 | 0.000006 |

Interpretation:

1. V15 remains the strongest raw ordinal sorter. It should stay in the feature
   library as the baseline moneyflow absorption signal.
2. V18b is the best current residual-information feature. It has the strongest
   `both_resid_rank_ic_mean` in all three tested universes and keeps positive
   residual top-decile excess.
3. V18a remains useful as a long-side portfolio expression, but it is less
   dominant than V18b after residualizing the signal and return on simple
   controls.
4. The two simple hand-combos did not beat V18b on residual IC. Later blending
   should let ML or shrinkage-weighted optimization learn weights, instead of
   hard-coding a small number of fixed coefficients.
5. The residual edge weakens in 2022-2024 but remains positive. Treat this as
   regime sensitivity, not full falsification.

Feature-library decision:

- Keep V15 as raw sorting / baseline absorption feature.
- Keep V18a as portfolio-policy long-side expression.
- Promote V18b within the research feature library as the preferred
  first-passage / residual-information feature.
- Keep V18c rejected.

OOS caveat:

This validation used the IS datamarts through `2025-07-11`. OOS validation
after `2025-07-11` was not run because aligned OOS moneyflow moments,
daily_basic, and clean-data datamarts were not part of this result set.

## Transferable Lessons

- Portfolio policy alone is not enough; expression-level V18a/V18b changed
  long-side economics versus V15.
- High rank IC is not sufficient. V18a's value is that top-decile realized
  return and cost-adjusted portfolio evidence improved.
- The smallest universe is powerful but can embed small-size premium. Use
  `fixed_small_10/20` as the more reusable research universe: remove market cap
  below 500 million CNY and the smallest 10%, then take the smallest 10%/20% of
  the remaining names.
- `csi2000` results are strong but currently short-coverage and must not be
  treated as 2016-2025 full-window evidence.
- Strong crowding penalties are dangerous when the observable cannot separate
  profit-payer crowding from informed absorption.
- For later model combination, residual IC matters more than standalone NAV.
  Under this lens, V18b is stronger than V15 even though V15 has higher raw
  rank IC.

## Next Research Questions

1. Promote V18a as the next exploit parent for small-universe research, not as
   official factor.
2. Keep V18b as the mathematically cleaner exploration branch. It should be
   retested when CSI2000 or a CSI2000-like reusable universe has longer
   coverage.
3. Replace V18c with a better crowding observable before testing again. A useful
   next proxy should separate:
   - early concentrated absorption after low turnover,
   - late broad chasing after price appreciation,
   - one-sided bad selling pressure without repair.
4. If pseudo dollar bar is used later, mark it explicitly as pseudo-from-1m-bar,
   not true tick dollar bar.

## Follow-Up Before Next Run

Before starting another branch, record the next check explicitly:

- The first V18 targeted run omitted `csi800` and `csi800_csi1000`, although the
  evaluator supports them.
- A narrow follow-up should run V18a only on:
  - `csi800`
  - `csi800_csi1000`
  - optionally `largest_10` as a large-cap falsification control
- Keep the same IS window, cutoff, cost policy, and portfolio policy so the
  result is comparable to the first V18 note.
- Do not rerun all V18 branches unless this narrow check reveals a stronger
  universe-specific pattern.

## Follow-Up Result: V18a On CSI800 / CSI800+CSI1000 / Largest 10%

Run evidence:

- Worker: `i-02cc0b6e93856fbb4`
- SSM command: `eb906029-31a3-4f21-9e08-27a709e51ede`
- S3 result root:
  `s3://yufan-data-lake/factorforge/tmp/moneyflow_v18_20260613/v18a_other_universes_results/`
- Local result cache:
  `/tmp/moneyflow_v18a_other_universes_20260613_results2/`
- Window: `20160104-20250711`
- Law: `miller_flow_v18a_absolute_long_edge_gate_v1`
- Policy focus: `top10_dropout30_rebalance5_equal`
- Side effects: `clean_data_started=false`, `search_worker_started=false`,
  `official_promotion_started=false`, `factor_forge_artifacts_written=false`

Narrow follow-up result:

| universe | dates | gross return | net return | turnover | cost | net hit rate | Sharpe proxy | max DD | NAV |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| csi800_csi1000 | 2284 | 0.000325 | 0.000055 | 0.135014 | 0.000270 | 0.513135 | 0.010095 | -0.427384 | 0.893864 |
| csi800 | 2284 | 0.000291 | 0.000032 | 0.129668 | 0.000259 | 0.499124 | -0.019008 | -0.398612 | 0.866277 |
| largest_10 | 2303 | 0.000173 | -0.000073 | 0.122960 | 0.000246 | 0.495875 | -0.110732 | -0.444589 | 0.662672 |

Horizon-1 IC evidence:

| universe | rank IC | Pearson IC | top decile return | universe mean return | top decile excess |
| --- | ---: | ---: | ---: | ---: | ---: |
| csi800_csi1000 | 0.025069 | 0.014766 | 0.000271 | 0.000320 | -0.000049 |
| csi800 | 0.011791 | 0.004997 | 0.000133 | 0.000322 | -0.000189 |
| largest_10 | 0.003599 | 0.002069 | 0.000048 | 0.000150 | -0.000102 |

Interpretation:

1. V18a is not a large-cap factor. `largest_10` is a clean falsification
   control: weak IC, negative net portfolio return, and NAV below 1.
2. `csi800_csi1000` is directionally better than `csi800`, which is consistent
   with the profit-payer / absorption hypothesis needing enough retail or
   constrained-flow participation. However, the top-decile excess remains
   negative and the portfolio NAV remains below 1 after cost, so it is not the
   exploit universe.
3. The current strongest evidence is still in small / smaller-mid universes,
   especially `fixed_small_20`, `fixed_small_10`, and `smallest_20`. The
   follow-up narrows the next search: avoid core large caps, and prefer a
   reusable small-to-mid universe that excludes microcaps but still contains
   enough non-institutional profit payers.
4. V18a has ordinal information in broader index universes, but the long-side
   payoff is not strong enough there. This means the next expression-level
   change should not simply broaden the universe; it should improve target /
   repair quality or add a better profit-payer-vs-absorption separator.

Runner lessons:

- The first follow-up attempt failed because the worker script did not set
  `PYTHONPATH`, causing `ModuleNotFoundError: No module named 'factor_factory'`.
- The second attempt only produced `largest_10` because index universe state was
  missing on the worker. `csi800` and `csi800_csi1000` were skipped with
  `index_universe_profile.status=missing_root`.
- The fixed runner now syncs `index_weight_universe/v1` before evaluation and
  verifies partition count. Future index-universe research runners should carry
  the same guard.

## OOS Pilot: V15 / V18a / V18b Feature Validation

Run evidence:

- Worker: `i-02cc0b6e93856fbb4`
- SSM build command: `2ed60302-d11a-4291-ad45-6357735ab76e`
- SSM validation-only rerun: `4da63403-1c11-4cf4-a60d-351b81a5ab33`
- S3 result root:
  `s3://yufan-data-lake/factorforge/tmp/moneyflow_v18_20260613/oos_feature_validation_pilot_results/`
- Local result cache:
  `/tmp/moneyflow_oos_feature_validation_pilot_20260614_results/`
- Window: `20250714-20250829`
- Cutoff: `14:50`
- Horizon: `1d`
- Laws:
  - `miller_flow_v15_repair_confirmed_absorption_fp_v1`
  - `miller_flow_v18a_absolute_long_edge_gate_v1`
  - `miller_flow_v18b_first_passage_repair_edge_v1`
- Rows:
  - daily rows: `158,962`
  - moment rows after cutoff filter: `189,261`
  - OOS moment datamart rows: `1,135,566`
- Universes: `full`, `middle_10_80`, `fixed_small_20`
- Side effects:
  - `clean_data_started=false`
  - `search_worker_started=false`
  - `official_promotion_started=false`
  - `factor_forge_artifacts_written=false`
  - `formal_catalog_modified=false`

Best OOS pilot feature evidence:

| universe | feature | raw rank IC | raw t | both-resid rank IC | both-resid t | raw top-decile excess | resid top-decile excess |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| fixed_small_20 | V18a | 0.070204 | 6.606276 | 0.024747 | 2.732682 | 0.000367 | 0.000794 |
| full | V18a | 0.055302 | 5.805865 | 0.021706 | 3.174341 | -0.000052 | 0.000204 |
| middle_10_80 | V18a | 0.063952 | 6.052610 | 0.021441 | 2.945137 | -0.000001 | 0.000085 |

Baseline comparison:

| universe | feature | raw rank IC | both-resid rank IC | resid top-decile excess | interpretation |
| --- | --- | ---: | ---: | ---: | --- |
| full | V15 | 0.059040 | 0.010326 | -0.000636 | raw ordinal signal survives, but residual long-side payoff is poor |
| full | V18b | 0.045013 | 0.011270 | 0.000124 | residual payoff positive but weaker than V18a |
| middle_10_80 | V15 | 0.068062 | 0.013711 | -0.000655 | strong raw sorting, weak long-side residual payoff |
| middle_10_80 | V18b | 0.054836 | 0.010665 | 0.000293 | better long-side excess than V15, but weaker residual IC than V18a |
| fixed_small_20 | V15 | 0.069166 | 0.013018 | 0.000169 | raw sorting survives and long side is mildly positive |
| fixed_small_20 | V18b | 0.059868 | 0.013883 | -0.000031 | not the OOS pilot winner |

Interpretation:

1. V18a is the OOS pilot winner. It is the only branch that is consistently
   positive after residualizing both signal and return on `log_circ_mv`,
   `turnover_rate_f`, `volume_ratio`, and `pct_chg`, with economically positive
   residual top-decile excess in all three universes.
2. V15 still contains strong ordinal information, especially raw rank IC, but
   its top-decile payoff becomes negative after residualization in `full` and
   `middle_10_80`. Treat V15 as a ranking/diagnostic feature, not the current
   best long-side expression.
3. V18b did not beat V18a OOS. The first-passage repair edge idea remains
   useful conceptually, but this implementation is weaker than the simpler
   absolute long-edge gate in the pilot.
4. The strongest OOS pilot result is `fixed_small_20 + V18a`: raw rank IC
   `0.070204`, both-resid rank IC `0.024747`, and residual top-decile excess
   `0.000794`. This supports continuing V18a before expanding new formula
   complexity.

OOS runner lessons:

- The first OOS attempt failed after downloading clean daily because the runner
  treated a missing index-universe directory as a hard `find` failure under
  `set -euo pipefail`.
- The second attempt built OOS moments successfully but validation failed because
  temporary daily-basic parquet files contained physical `trade_date` as string
  while hive partition inference produced integer `trade_date`; validation then
  hit `ArrowTypeError: string vs int32`.
- The final runner writes temporary daily-basic parquet without physical
  `trade_date`, uses hive partition date, and skips recomputing moments when the
  expected OOS partitions already exist.
- OOS moments emitted repeated `divide by zero encountered in log` warnings.
  They did not block QA or validation, but the moments builder should eventually
  make zero-amount / zero-ratio log transforms explicit and counted.

Next decision:

- Do not promote. This is still a research-side OOS pilot, not official Step4
  promotion.
- Prioritize a longer OOS validation for V18a only, especially
  `fixed_small_20`, `middle_10_80`, and `full`.
- Keep V15 as a companion feature for later model combination, but do not use it
  as the primary standalone long-side signal.

## Full OOS Validation: V18a Feature Evidence

Scope:

- This is a research-side feature validation, not a Factor Forge official
  promotion run.
- IS cutoff remains `2025-07-11`.
- OOS validation window is `2025-07-14` to `2026-05-26`.
- Law: `miller_flow_v18a_absolute_long_edge_gate_v1`.
- Cutoff: `14:50`.
- Horizon: `1d`.
- Universes: `full`, `middle_10_80`, `fixed_small_20`.

Run evidence:

- Worker: `i-02cc0b6e93856fbb4`.
- Initial full build SSM: `bf3454ea-4ba8-42a9-bb28-c54afd4587a0`.
- Resume SSM that produced an invalid tail-only result:
  `579f12b3-71ff-40bc-9915-ed65d7fe95dc`.
- True full rebuild SSM: `67158dc2-3fe0-4d67-b718-59260e0f6efd`.
- Final append-and-validate SSM: `6a1fbe7f-3484-42fd-a28e-5055845c3026`.
- S3 result root:
  `s3://yufan-data-lake/factorforge/tmp/moneyflow_v18_20260613/oos_feature_validation_full_v18a_results/`.
- Local result cache:
  `/tmp/moneyflow_oos_feature_validation_full_v18a_20260614_results/`.
- Result files:
  - `/tmp/moneyflow_oos_feature_validation_full_v18a_20260614_results/results/moneyflow_feature_validation_metrics.csv`
  - `/tmp/moneyflow_oos_feature_validation_full_v18a_20260614_results/results/moneyflow_feature_validation_summary.json`
  - `/tmp/moneyflow_oos_feature_validation_full_v18a_20260614_results/results/moneyflow_feature_validation_top.md`
  - `/tmp/moneyflow_oos_feature_validation_full_v18a_20260614_results/moneyflow_oos_feature_validation_full_v18a_append_validate_summary.json`

Coverage proof:

- Requested OOS dates: `209`.
- Loaded OOS dates: `209`.
- Metric dates: `208`, because `horizon=1d` requires one next-day return.
- Missing dates: `0`.
- Daily panel rows: `949,801`.
- Distribution-moment rows after cutoff state load: `1,139,921`.
- Side effects:
  - `clean_data_started=false`
  - `search_worker_started=false`
  - `official_promotion_started=false`
  - `factor_forge_artifacts_written=false`
  - `formal_catalog_modified=false`

Full OOS metrics:

| universe | raw rank IC | raw t | Pearson IC | signal-resid rank IC | signal-resid t | both-resid rank IC | both-resid t | raw top-decile excess | resid top-decile excess |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| full | 0.036921 | 8.712851 | 0.011770 | 0.009171 | 2.817877 | 0.008427 | 2.752937 | -0.000154 | -0.000077 |
| middle_10_80 | 0.044834 | 9.765862 | 0.014611 | 0.008916 | 2.864377 | 0.008078 | 2.632222 | -0.000206 | -0.000237 |
| fixed_small_20 | 0.042088 | 8.926607 | 0.018113 | 0.006231 | 1.561462 | 0.006766 | 1.736872 | 0.000033 | 0.000176 |

Interpretation:

1. V18a OOS ordinal information survives. Raw rank IC is positive and
   statistically strong in all three universes:
   - `full`: `0.036921`, t `8.712851`
   - `middle_10_80`: `0.044834`, t `9.765862`
   - `fixed_small_20`: `0.042088`, t `8.926607`
2. After residualizing signal and next-day return on `log_circ_mv`,
   `turnover_rate_f`, `volume_ratio`, and `pct_chg`, residual rank IC remains
   positive but much smaller:
   - `full`: `0.008427`, t `2.752937`
   - `middle_10_80`: `0.008078`, t `2.632222`
   - `fixed_small_20`: `0.006766`, t `1.736872`
3. The weak point is still long-side payoff. Top-decile excess is negative in
   `full` and `middle_10_80`; `fixed_small_20` is positive but very small. This
   means the feature has ranking information, but the current direct long-only
   top-decile mapping is not strong enough for standalone promotion.
4. Compared with the OOS pilot, the longer OOS sample is more conservative:
   V18a still passes as an alpha feature candidate, but the pilot's long-side
   payoff strength does not fully persist.

Research decision:

- Do not official-promote V18a as a standalone factor.
- Keep V18a in the research factor library as an OOS-positive feature candidate
  for model combination, monotone calibration, or multi-factor portfolio
  construction.
- Treat V15 as a companion ranking/diagnostic feature, not as the standalone
  long-side signal.
- Next expression work should focus on converting ranking information into
  long-end payoff, not merely increasing raw IC. Candidate directions:
  - combine V15 direction-change information with V18a absorption/repair gate;
  - add monotone calibration before top-bucket construction;
  - test signal-weighted and cost-aware portfolio mappings separately from
    expression-level changes;
  - use the future `intraday_value_occupation_state_v1` first-passage state to
    improve target/barrier quality.

Runner lessons:

- The first full OOS build timed out because AWS `AWS-RunShellScript` default
  command execution timeout is about one hour. CLI `--timeout-seconds` only
  changes command delivery/wait behavior; long shell commands also need document
  parameter `executionTimeout`.
- One resume attempt produced a `31`-date tail-only result because the resume
  builder used `--overwrite` on the full moments root. That result is invalid
  for full OOS conclusions and should not be compared with pilot/full metrics.
- The safe append pattern is:
  1. build missing partitions into a temporary append root;
  2. copy only the missing `trade_date=*` partitions into the main moments root;
  3. run validation over the whole requested OOS window.
- Do not kill or inspect unrelated long-running research processes on the
  worker. During this validation, an unrelated VP18 stream process was present
  and left untouched.

## OOS Combo Follow-up: V15 + V18a Calibration Check

Scope:

- This is a research-side OOS follow-up, not an official Factor Forge
  promotion run.
- Objective: test whether V15 direction-change information can repair V18a's
  weak long-end payoff without losing the OOS ordinal signal.
- IS cutoff remains `2025-07-11`.
- OOS validation window is `2025-07-14` to `2026-05-26`.
- Cutoff: `14:50`.
- Horizon: `1d`.
- Universes: `full`, `middle_10_80`, `fixed_small_20`.
- Laws:
  - `miller_flow_v15_repair_confirmed_absorption_fp_v1`
  - `miller_flow_v18a_absolute_long_edge_gate_v1`
  - `miller_flow_v18b_first_passage_repair_edge_v1`

Run evidence:

- Worker: `i-02cc0b6e93856fbb4`.
- SSM: `750e3db4-8795-4b9e-bb86-4a1d23f6ad93`.
- S3 result root:
  `s3://yufan-data-lake/factorforge/tmp/moneyflow_v18_20260613/oos_combo_validation_v15_v18a_results/`.
- Local result cache:
  `/tmp/moneyflow_oos_combo_validation_20260615_results/`.
- Result files:
  - `/tmp/moneyflow_oos_combo_validation_20260615_results/moneyflow_feature_validation_metrics.csv`
  - `/tmp/moneyflow_oos_combo_validation_20260615_results/moneyflow_feature_validation_summary.json`
  - `/tmp/moneyflow_oos_combo_validation_20260615_results/moneyflow_feature_validation_top.md`
  - `/tmp/moneyflow_oos_combo_validation_20260615_results/moneyflow_oos_feature_validation_run_summary.json`

Coverage proof:

- Verdict: `ACCEPT`.
- Daily panel rows: `949,801`.
- Distribution-moment rows after cutoff state load: `1,139,921`.
- Loaded OOS dates: `209`.
- Missing dates: `0`.
- Index universe profile: `loaded`.
- Side effects:
  - `clean_data_started=false`
  - `search_worker_started=false`
  - `official_promotion_started=false`
  - `factor_forge_artifacts_written=false`

Candidate combo definitions:

$$
\mathrm{Combo}_{15+18a}
= z_{15} + z_{18a}
$$

$$
\mathrm{Combo}_{18a\mid 15^+}
= z_{18a}\left(1 + 0.35\cdot \mathrm{clip}(z_{15},0,3)\right)
$$

$$
\mathrm{Combo}_{\min(15,18a)}
= \min(z_{15}, z_{18a})
$$

$$
\mathrm{Combo}_{15^+\times 18a^+}
= \mathrm{clip}(z_{15},0,3)\cdot \mathrm{clip}(z_{18a},0,3)
$$

$$
\mathrm{Combo}_{18a-\mathrm{bad}15}
= z_{18a} - 0.5\cdot \mathrm{clip}(-z_{15},0,3)
$$

Key OOS metrics:

| feature | universe | raw rank IC | raw t | both-resid rank IC | both-resid t | raw top-decile excess | resid top-decile excess |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| V18a | full | 0.036921 | 8.712851 | 0.008427 | 2.752937 | -0.000154 | -0.000077 |
| V18a | middle_10_80 | 0.044834 | 9.765862 | 0.008078 | 2.632222 | -0.000206 | -0.000237 |
| V18a | fixed_small_20 | 0.042088 | 8.926607 | 0.006766 | 1.736872 | 0.000033 | 0.000176 |
| V18b | full | 0.033719 | 6.604780 | 0.004178 | 1.095480 | 0.000014 | 0.000347 |
| V18b | middle_10_80 | 0.041204 | 7.780840 | 0.003041 | 0.803708 | -0.000042 | 0.000329 |
| V18b | fixed_small_20 | 0.039290 | 7.874460 | 0.004618 | 1.102180 | 0.000282 | 0.000669 |
| Combo_V15_plus_V18a | full | 0.042648 | 9.434660 | 0.004994 | 1.800120 | -0.000225 | -0.000345 |
| Combo_V15_plus_V18a | middle_10_80 | 0.050182 | 10.452470 | 0.005758 | 1.965290 | -0.000212 | -0.000466 |
| Combo_V15_plus_V18a | fixed_small_20 | 0.044309 | 9.372290 | 0.003154 | 0.884030 | 0.000001 | -0.000198 |
| Combo_V15V18a_agreement_min | full | 0.046517 | 10.651380 | 0.004608 | 1.562310 | -0.000452 | -0.000470 |
| Combo_V15V18a_agreement_min | middle_10_80 | 0.053680 | 11.394040 | 0.006704 | 2.196530 | -0.000330 | -0.000484 |
| Combo_V15V18a_agreement_min | fixed_small_20 | 0.047409 | 10.107490 | 0.003497 | 0.931430 | -0.000036 | -0.000300 |
| Combo_V15V18a_positive_product | full | 0.023997 | 5.451140 | -0.013010 | -5.768210 | -0.000412 | -0.000632 |
| Combo_V15V18a_positive_product | middle_10_80 | 0.031384 | 6.548390 | -0.013695 | -5.759560 | -0.000442 | -0.000683 |
| Combo_V15V18a_positive_product | fixed_small_20 | 0.028876 | 6.000090 | -0.011855 | -3.819490 | -0.000179 | -0.000345 |

Interpretation:

1. Simple V15 + V18a combination improves raw ordinal ranking in several
   universes, but it does not repair long-end payoff. In particular,
   `Combo_V15V18a_agreement_min` has the best raw rank IC among tested
   combinations, but top-decile excess becomes worse.
2. The positive-tail intersection is explicitly falsified. The product feature
   has negative residual IC in all three universes and negative residual
   top-decile excess. This means "both V15 and V18a are high" is not a reliable
   long-side absorption state.
3. V18a remains the stronger residual-ranking feature. V18b remains the more
   interesting long-side payoff branch because its residual top-decile excess is
   positive in all three universes, although its residual IC is weaker and less
   statistically stable.
4. V15 is still useful as a companion/diagnostic feature, but not through this
   naive z-score intersection or additive calibration.

Research decision:

- Do not promote any V15/V18a combo as a standalone factor.
- Keep V18a as an OOS-positive feature-library candidate for model combination.
- Keep V18b as the next long-side mechanism branch to refine, because it better
  matches the first-passage payoff objective even though its ranking IC is
  weaker than V18a.
- The next expression-level work should focus on target/barrier quality and
  payoff-shape calibration, not on adding more z-score combinations.

Runner lessons:

- Worker stop/start cleared `/tmp`, including the previous OOS moment root and
  script staging directory. The rerun therefore rebuilt threshold base,
  prior-threshold state, and OOS distribution moments before validation. This
  is valid but slow.
- Durable research roots should be S3-backed or worker-persistent paths, not
  `/tmp`-only, when the user may stop the worker between research loops.
