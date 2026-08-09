# Alpha019 Long-Lookback Rerun Knowledge

Report ID: `ALPHA019_SIGN_REVERSAL_WINNER_STATE_20160101`

Repo SHA: `3cd50eadfcfa0ca4de78a01411610ee4338974db`

Wrapper verdict: `PASS`

## Formula

$$
S_{i,t}
=
-\operatorname{sign}
\left[
(C_{i,t}-C_{i,t-7})+\Delta_7 C_{i,t}
\right]
\left(
1+\operatorname{rank}_t
\left[
1+\sum_{k=0}^{249} r_{i,t-k}
\right]
\right)
$$

## Economic Hypothesis

Alpha019 is a slow-winner-state and short-horizon threshold-repair factor.

- The 250-day return sum estimates a persistent winner/attention state.
- The 7-day sign term estimates a short-horizon threshold displacement.
- The interaction says that recent threshold moves inside a prior winner state may overreact or repair.
- The likely payer is a delayed updater or short-horizon liquidity/dislocation trader that reacts to the recent move before the slow state is fully repriced.

The intended conditional-return object is:

$$
\mathbb{E}
\left[
r_{i,t+1}
\mid
\mathcal{F}_t,
M_{i,t},
B_{i,t}
\right]
=
\beta_0+\beta_M M_{i,t}+\beta_B B_{i,t}+\beta_{MB}M_{i,t}B_{i,t}.
$$

Here:

- $M_{i,t}$: slow winner state from the 250-day return sum.
- $B_{i,t}$: short threshold displacement from the 7-day sign state.
- $M_{i,t}B_{i,t}$: the interaction Alpha019 is trying to estimate.

## Evidence

Full IS window: `2016-01-04` to `2025-07-11`

Formal signal coverage:

- raw non-null coverage: `84.72%`
- warmup-adjusted non-null coverage: `90.93%`
- formula max lookback: `250`
- warmup skipped dates: `249`
- coverage target window: `2017-01-10` to `2025-07-11`
- coverage verdict: `PASS`

Step4 / Step6 metrics:

- Rank IC mean: `0.02859`
- Rank IC IR: `0.28093`
- Pearson IC mean: `0.02526`
- Long-side annual return: `7.06%`
- Long-side Sharpe: `0.31`
- Long-side max drawdown: `-48.83%`
- Long-side recovery days: `1826`
- Daily turnover: `30.69%`
- Cost-adjusted annual return: `-16.13%`
- Cost-adjusted long-side Sharpe: `-0.71`
- Cost-adjusted max drawdown: `-84.50%`
- Cost-adjusted recovery days: `3048`
- Qlib native status: `native_backtest_success`

## Judgment

Decision: `iterate`, not promote.

Alpha019 contains weak but real positive information:

$$
\operatorname{RankIC} > 0,
\qquad
\mathbb{E}[r_{\text{top decile}}] > 0.
$$

But the current expression is not a standalone long-only alpha:

$$
\text{CostAdjustedReturn}
=
\text{GrossReturn}
-
\text{Turnover}\times\text{Cost}
<0.
$$

The top decile gross return is positive, but the long-side Sharpe is below the candidate threshold, drawdown is too deep, recovery is too slow, and turnover consumes the edge.

Keep Alpha019 as a `feature_candidate / needs_revision`, not an official factor.

## Framework Lessons

This run exposed and closed three general framework issues:

1. Step3A proof windows must expand with formula lookback. A 250-day formula cannot be validated on a 147-trading-day sample.
2. Step3B sample limiting must preserve enough historical rows per instrument. Tail-row sampling can select recently listed stocks and make long-lookback formulas all-null.
3. Step4 formal coverage must distinguish raw coverage from warmup-adjusted coverage. Long-window formulas naturally have null warmup periods; coverage gates should evaluate the post-warmup formal target window.

## Next Research Direction

Do not attempt to rescue Alpha019 by changing portfolio policy, decile trading, or rebalance throttling alone.

Valid expression-level directions:

1. Replace the hard sign with a smoother signed magnitude or persistence-confirmed state.
2. Test whether the 250-day winner state has independent long-side value through ablation.
3. Add hysteresis around the 7-day threshold so daily churn is reduced by the factor expression itself.
4. Kill standalone promotion if revisions cannot lift long-side Sharpe and reduce drawdown without adding unjustified complexity.
