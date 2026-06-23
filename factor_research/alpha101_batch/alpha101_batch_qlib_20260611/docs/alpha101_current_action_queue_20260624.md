# Alpha101 Current Action Queue

Date: 2026-06-24

Scope: Factor Forge Alpha101 workspaces under `factor_research/Alpha*/`.

This note updates the Alpha101 queue after the Alpha015 coverage-guard rerun
and the Alpha019 long-lookback rerun. It is a coordination and knowledge
artifact, not standalone promotion evidence.

## Current Queue Decision

The next actionable Alpha101 research branch is:

```text
Alpha019 LOOP01: smoothed pullback persistence child
status: pending human approval before Step3B execution
```

The approval packet already exists at:

```text
factor_research/Alpha019/alpha019_sign_reversal_winner_state_ultimate_20260623/docs/alpha019_next_branch_approval_packet_20260623.zh-CN.md
```

Do not run the Alpha019 child until approval is explicit, because the parent
Council and loop artifacts carry `human_approval_required=true` and no active
`handoff_to_step3b` exists.

## Current Evidence Table

| Factor / branch | Rank IC | Rank IC IR | Long Ann. | Long Sharpe | Max DD | Recovery | Turnover | Cost Adj. Ann. | Reading |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---|
| `Alpha015` parent | 0.0602 | 0.5419 | 22.25% | 0.938 | -39.54% | 704 | 24.49% | 3.75% | strongest current Alpha101 candidate; candidate/feature, not clean official |
| `Alpha015` LOOP01 | 0.0642 | 0.6003 | 20.10% | 0.856 | -39.44% | 714 | 24.47% | 1.61% | higher IC but worse economics than parent |
| `Alpha015` LOOP02 | 0.0569 | 0.5413 | 19.96% | 0.844 | -40.03% | 714 | 24.13% | 1.73% | worse than parent; stop this repair path |
| `Alpha040` parent | 0.0546 | 0.4402 | 7.76% | 0.347 | -48.81% | 1771 | 29.51% | -14.54% | positive information, weak long-side economics |
| `Alpha040` LOOP01 | 0.0414 | 0.3020 | 6.65% | 0.309 | -45.51% | 1755 | 10.75% | -1.48% | feature/state descriptor, not standalone |
| `Alpha040` LOOP02 | 0.0471 | 0.3555 | 8.87% | 0.407 | -48.16% | 1755 | 15.46% | -2.82% | better gross but still not standalone |
| `Alpha044` parent | 0.0469 | 0.6800 | 7.26% | 0.316 | -43.11% | 1813 | 52.68% | -32.54% | information exists but turnover destroys it |
| `Alpha044` LOOP01 | 0.0429 | 0.6016 | 12.25% | 0.535 | -36.29% | 1544 | 35.85% | -14.83% | better long-side than parent, still cost/drawdown blocked |
| `Alpha083` parent | 0.0395 | 0.3129 | 8.72% | 0.435 | -40.85% | 1327 | 52.80% | -31.18% | positive IC, high turnover/cost |
| `Alpha083` LOOP01 | 0.0297 | 0.2840 | 8.85% | 0.389 | -42.33% | 1760 | 17.24% | -4.18% | retained feature-state only |
| `Alpha019` parent | 0.0286 | 0.2809 | 7.06% | 0.310 | -48.83% | 1826 | 30.69% | -16.13% | weak positive signal; best next child because mechanism is clean |
| `Alpha013` parent | 0.0529 | 0.7548 | -0.25% | -0.010 | -61.16% | 3153 | 44.55% | -33.91% | directionality problem; no standalone long-side |
| `Alpha007` best IC branch | 0.0439 | 0.4077 | 0.38% | 0.016 | -56.87% | 3153 | 60.34% | -45.21% | positive IC but long side fails |
| `Alpha005` parent | 0.0234 | 0.1569 | -1.12% | -0.053 | -59.53% | 3149 | 2.73% | -3.19% | low turnover but negative long side |
| `Alpha042` parent | 0.0230 | 0.1501 | -4.49% | -0.209 | -64.62% | 3061 | 3.01% | -6.77% | ordinal information but wrong long-side direction |

## Why Alpha019 Is Next

Alpha019 has weaker headline strength than Alpha040 or Alpha044, but it has a
cleaner repair hypothesis. The parent can be written as:

$$
S_{i,t}=B_{i,t}(1+M_{i,t}),
$$

where:

$$
B_{i,t}
=-\operatorname{sign}(C_{i,t}-C_{i,t-7}),
$$

and:

$$
M_{i,t}
=
\operatorname{rank}_t
\left(
1+\sum_{k=0}^{249} r_{i,t-k}
\right).
$$

The parent evidence supports weak positive information, but the hard sign
boundary makes the signal churn:

$$
\operatorname{NetEdge}
=
\operatorname{GrossEdge}
-
\operatorname{Turnover}\times\operatorname{Cost}
<0.
$$

The proposed child replaces the hard threshold with continuous pullback
intensity:

$$
P_{i,t}
=
\operatorname{rank}_t
\left(
\frac{C_{i,t-7}-C_{i,t}}{C_{i,t-7}}
\right),
$$

then smooths it:

$$
\bar{P}_{i,t}
=
\operatorname{mean}_5(P_{i,t}),
$$

and tests:

$$
F^{019,\mathrm{child}}_{i,t}
=
\bar{P}_{i,t}(1+M_{i,t}).
$$

This is an expression-level repair, not a portfolio-policy repair.

## Execution Boundary

Do:

1. Ask for or receive explicit approval for Alpha019 LOOP01.
2. If approved, materialize the child through the formal Factor Forge revision
   path and run Step3B through Step6.
3. Deposit the child evidence and any negative result before starting another
   Alpha101 branch.

Do not:

1. Run the child from the disabled provisional handoff.
2. Change portfolio policy, rebalance frequency, decile trading, or short-leg
   extraction to rescue Alpha019.
3. Reopen Alpha005, Alpha007, Alpha013, Alpha042, or Alpha083 standalone forms
   without a new economic mechanism.
4. Spend more Alpha015 loops on the tested turnover-friction repair path; the
   parent remains the current best Alpha015 branch.
