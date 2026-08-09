# VP V18 Linear Incremental Partial OOS Note

Date: 2026-06-15

## Scope

This note records a partial OOS incremental-information diagnostic for the V18 value-occupation signal family.

Important data boundary: the OOS value-occupation state covers 2025-07-14 to 2026-06-12, but the local `daily_clean.parquet` available on Mac only covers through 2026-04-24. Therefore this diagnostic uses 190 merged OOS dates and must not be treated as final promotion evidence for the full 2025-07-14 to 2026-06-12 window.

Artifacts:

- Script: `factor_research/vp_v18_value_occupation_20260614/scripts/research_vp_v18_incremental_linear_eval.py`
- Core-control output: `/tmp/vp18_incremental_linear_core_20260615`
- State-control output: `/tmp/vp18_incremental_linear_state_controls_partial_20260615`
- OOS state local cache: `/tmp/vp18_oos_state_20260614`

S3 Select on the full daily-clean parquet was attempted and rejected with `MethodNotAllowed`. The S3 daily-clean object is a single 1.4 GiB parquet, not a partitioned datamart. The openclaw EC2 instance has the latest file, but its default Python environments do not have a parquet reader available. A full-window final rerun needs either a partitioned/sliced daily-clean datamart or a temporary EC2 parquet runtime.

## Economic Hypothesis

The V18 thesis is a mixed market-structure and behavioral-repair hypothesis.

The price-axis occupation measure approximates where recent traded value is concentrated. When current price is below recent cost and there is meaningful lower support mass, the stock may be in a repair state: prior sellers have already transferred inventory, marginal liquidation pressure is lower, and small positive drift confirmation suggests the barrier is being defended.

The counterparty paying the return is not a permanent risk-premium payer. It is the short-horizon inventory/liquidity imbalance created by forced sellers, stale holders, and late repair chasers. This makes the signal naturally short-horizon and fragile at extremes.

The OOS evidence suggests a crucial refinement: the state variable may contain linear ranking information, but the extreme top bucket is not a clean long basket. In other words, "repair state" is useful as a weak drift feature, not as a monotone "higher score means buy more" rule.

## Math Mechanism

Use a simple controlled semimartingale interpretation:

```text
dP_i(t) / P_i(t) = mu_i(t, I_t) dt + sigma_i(t, I_t) dW_i(t) + dJ_i(t)
```

V18 is not a theorem about the true drift. It is a state statistic intended to estimate the residual conditional drift after common controls:

```text
S_i,t = z_cs(below_cost_depth_i,t) + z_cs(lower_support_mass_i,t)
        + 0.35 * z_cs(mom_3d_to_cutoff_i,t)
        - 0.25 * z_cs(vol_20d_i,t)
```

The linear test is:

```text
rank_z(r_i,t+h) = alpha_t + beta_t rank_z(S_i,t) + gamma_t' rank_z(C_i,t) + epsilon_i,t+h
```

Controls `C` are size, turnover, volatility, 1D drift-to-cutoff, 5D momentum, and 20D momentum. The stricter test also controls for the state components: below-cost depth, lower support, and support-minus-overhang.

This is intentionally simple. Nonlinear bucket results are diagnostics for tradability and monotonicity, not the factor definition.

## Partial OOS Linear Results

### Core Controls

Controls: `ln_total_mv`, `turnover_rate`, `vol_20d`, `drift_1d_to_cutoff`, `mom_5d_to_cutoff`, `mom_20d_to_cutoff`.

For `v18_repair_drift_score`:

| universe | horizon | raw IC | partial IC | partial IC t | FM beta t | delta R2 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| full | 1D | 0.040706 | 0.020590 | 6.999448 | 7.008613 | 0.001764 |
| full | 3D | 0.040621 | 0.021120 | 7.271445 | 7.140287 | 0.001800 |
| full | 5D | 0.038566 | 0.017573 | 5.539074 | 5.456479 | 0.001929 |
| middle_20_90 | 1D | 0.044844 | 0.022379 | 7.136606 | 7.116317 | 0.002056 |
| middle_20_90 | 3D | 0.046948 | 0.023517 | 7.593435 | 7.429627 | 0.002111 |
| middle_20_90 | 5D | 0.044809 | 0.019326 | 5.826897 | 5.769778 | 0.002152 |

### Stricter State Controls

Additional controls: `below_cost_depth_score_raw`, `lower_support_mass`, `support_minus_overhang`.

For `v18_repair_drift_score`:

| universe | horizon | raw IC | partial IC | partial IC t | FM beta t | delta R2 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| full | 1D | 0.040706 | 0.014728 | 4.964126 | 4.848591 | 0.001579 |
| full | 3D | 0.040621 | 0.012814 | 4.107342 | 3.771624 | 0.001740 |
| full | 5D | 0.038566 | 0.007061 | 2.163860 | 1.762118 | 0.001760 |
| middle_20_90 | 1D | 0.044844 | 0.017694 | 5.604982 | 5.396201 | 0.001884 |
| middle_20_90 | 3D | 0.046948 | 0.015339 | 4.612600 | 4.310090 | 0.002048 |
| middle_20_90 | 5D | 0.044809 | 0.009166 | 2.600073 | 2.254526 | 0.002089 |

Interpretation: V18 has linear incremental information in this partial OOS sample, especially in full and middle_20_90 universes. The effect weakens materially at 5D and is not robust in largest_10 or smallest_20 after controlling for the underlying state variables.

## Bucket Diagnostics

For `v18_repair_drift_score`, the buckets do not support a simple top-bucket long rule.

In full universe:

- 1D bucket 5 excess: 0.000004, t 0.016620
- 3D bucket 5 excess: -0.000252, t -0.719291
- 5D bucket 5 excess: -0.000629, t -1.348448

In middle_20_90:

- 3D bucket 3 excess: 0.000364, t 2.049392
- 5D bucket 3 excess: 0.000508, t 2.247629
- 5D bucket 5 excess: -0.000412, t -0.848242

This supports the earlier OOS finding: V18 is better treated as a linear feature or a middle-state tilt than as an extreme top-decile selector.

## Control Overlap

For full universe, `v18_repair_drift_score` has meaningful overlap with:

- `lower_support_mass`: rank corr 0.525413
- `support_minus_overhang`: rank corr 0.467496
- `mom_20d_to_cutoff`: rank corr -0.379705
- `vol_20d`: rank corr -0.316882
- `turnover_rate`: rank corr -0.216995

This confirms the economic interpretation: V18 is not a pure new anomaly. It is a compact repair-state statistic that mixes value-domain support with negative long-horizon drift and lower volatility/liquidity pressure.

## Decision

Do not promote V18 as a standalone factor or a top-decile long signal.

Keep V18 as a candidate simple linear feature for alpha-composite testing:

- use the linear `v18_repair_drift_score` or a residualized version;
- do not add more gates unless they are needed for risk control;
- do not optimize nonlinear forms on this partial sample;
- test middle-bucket or exposure-capped usage in the optimizer, not pure top-decile long;
- require a full-window rerun before any official factor-library decision.

## Next Requirement

To finalize the OOS incremental test, the research side needs a narrow daily-clean slice or partitioned daily-clean access for 2025-06-01 to 2026-06-12. The current S3 daily-clean object is a single 1.4 GiB parquet, which is inconvenient for Mac-side targeted research.
