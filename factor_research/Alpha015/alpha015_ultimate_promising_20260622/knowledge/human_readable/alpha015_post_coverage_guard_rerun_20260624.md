# Alpha015 Post Coverage-Guard Rerun

Date: 2026-06-24

Repo SHA: `ff62325f39690e680e3b80b17098845a93f625ba`

Workspace:

`factor_research/Alpha015/alpha015_ultimate_promising_20260622`

## What Changed

The earlier Alpha015 formal evidence had a full-window row shell but only about
1.15% non-null `factor_value` coverage. Step4 now carries a formal signal
coverage gate, and the Alpha015 parent was rerun through the official
Factor Forge wrapper from Step3B through Step6.

The coverage problem is fixed for the parent:

```text
report_id: ALPHA015_SWEEP_TURNPEN_A040_20160101
run_status: success
validator: PASS
formal_signal_coverage: 99.2156%
nonnull_date_count: 2301
nonnull_start: 20160120
nonnull_end: 20250711
```

This means the old sparse-signal blocker no longer invalidates the parent run.

## Parent Result

The parent is now a real candidate-level Alpha101 result, not just a broken
artifact:

```text
RankIC mean: 0.060225
RankIC IR: 0.541872
long annual return: 22.2511%
long Sharpe: 0.9382
max drawdown: -39.54%
recovery days: 704
daily turnover: 24.49%
cost-adjusted annual return: 3.7472%
cost-adjusted Sharpe: 0.1579
cost-adjusted max drawdown: -61.16%
```

Interpretation:

- The signal has meaningful ordinal information.
- The long end works on a gross basis.
- The current expression still fails promotion-quality capital efficiency
  because drawdown, recovery, and cost-adjusted Sharpe are weak.

## LOOP01 Result

`ALPHA015_SWEEP_TURNPEN_A040_20160101__LOOP01__ALPHA015_PRESSURE_REPAIR_PERSISTENCE_SYNTHESIS_V1`
was rerun through the same official wrapper.

```text
formal_signal_coverage: 99.1565%
validator: PASS
RankIC mean: 0.064207
RankIC IR: 0.600301
long annual return: 20.0961%
long Sharpe: 0.8557
max drawdown: -39.44%
recovery days: 714
daily turnover: 24.47%
cost-adjusted annual return: 1.6077%
cost-adjusted Sharpe: 0.0684
cost-adjusted max drawdown: -66.79%
```

LOOP01 improves RankIC and RankIC IR, but it worsens the economic objective:
lower gross long return, lower gross Sharpe, worse recovery, worse cost-adjusted
Sharpe, and worse cost-adjusted drawdown. Treat this child as not improved.

## LOOP02 Result

`ALPHA015_SWEEP_TURNPEN_A040_20160101__LOOP01__ALPHA015_PR__f726ea84d6__LOOP02__ALPHA015_TURNOVER_FRICTION_GATE_REPAIR_V2`
was also rerun through the official wrapper.

```text
formal_signal_coverage: 99.1565%
validator: PASS
RankIC mean: 0.056898
RankIC IR: 0.541325
long annual return: 19.9593%
long Sharpe: 0.8440
max drawdown: -40.03%
recovery days: 714
daily turnover: 24.13%
cost-adjusted annual return: 1.7282%
cost-adjusted Sharpe: 0.0731
cost-adjusted max drawdown: -67.06%
```

LOOP02 slightly reduces turnover versus the parent, but it gives up RankIC,
long-side return, Sharpe, drawdown, recovery, and cost-adjusted quality. It is
also not improved.

## Current Research Judgment

Alpha015 should remain a `candidate / feature_candidate / needs_revision`
rather than official standalone alpha. Among the current formal branches, the
parent is the best branch. LOOP01 and LOOP02 are falsified as improvements.

The mechanism is still useful:

$$
f_{i,t}
=
-\sum_{k=0}^{6}
\operatorname{rank}
\left(
\operatorname{corr}_{7}
(
\operatorname{rank}(H_{i,t-k}),
\operatorname{rank}(V_{i,t-k})
)
\right)
\cdot \operatorname{rank}(A_{i,t})
\cdot
\left(0.4 + 0.6(1-\operatorname{rank}(T_{i,t}))\right)
$$

where:

- $H_{i,t}$ is high price.
- $V_{i,t}$ is volume.
- $A_{i,t}$ is amount / participation.
- $T_{i,t}$ is turnover.

Economic hypothesis:

> Persistent negative high-volume/high-price rank-correlation, when confirmed by
> sufficient participation and moderated by turnover, captures an active
> liquidity pressure state. Other participants are paying because their
> liquidity demand, mandate pressure, or attention-driven execution creates
> predictable price-volume pressure.

The current failure is not lack of signal; it is poor capital path geometry.
The next revision should target drawdown/recovery and regime timing directly,
not blindly maximize RankIC.

## Do Not Repeat

- Do not reuse the old sparse formal artifact.
- Do not treat LOOP01 as better merely because RankIC increased.
- Do not treat LOOP02 as better merely because turnover is slightly lower.
- Do not repair the factor through portfolio mechanics, decile trading, or
  short-leg reliance.
- Do not add complexity unless it improves long-side OOS/cost-adjusted evidence
  enough to pay for the complexity penalty.

## Next Research Direction

The next legitimate Alpha015 revision should change the factor expression or
state estimator to reduce drawdown/recovery without destroying the gross
long-side information. Good directions:

1. Regime stability guard tied to liquidity/volatility state, but only if it is
   mathematically motivated and not a fitted scalar gate.
2. Horizon repair: smooth persistent pressure state so daily turnover falls
   without collapsing the high-score long basket.
3. Component validation: explicitly test whether `amount` confirmation and
   turnover shrinkage are adding information or only reducing/reshaping risk.
4. OOS and IS subsample checks before any promotion discussion.

Promotion remains blocked until the factor clears drawdown/recovery and
cost-adjusted long-side quality.
