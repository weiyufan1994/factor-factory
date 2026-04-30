---
name: factor-forge-research-brain
description: Apply the Factor Forge research logic during Step5/Step6 review and revision. Use when the goal is to interpret metrics through return-source logic, objective constraints, math discipline, program-search policy, and produce a better revision proposal.
---

# Factor Forge Research Brain

## What This Skill Does

This skill adds the **investment logic layer** on top of the Factor Forge pipeline.
It is not a raw execution step. It is the thinking framework that should guide:
- Step5 case closing,
- Step6 reflection,
- Step6 revision proposals,
- and promote / iterate / reject decisions.

Use this skill when a factor already has Step4 evidence and we need to answer:
1. how the factor is supposed to make money,
2. whether the edge is risk premium, information advantage, or constraint-driven arbitrage,
3. what objective constraints force the other side to behave predictably,
4. and what kind of revision would strengthen the real return source rather than cosmetically improving metrics.

## Core Philosophy

Always reason in this order:
1. identify the return source,
2. identify the objective constraints,
3. interpret the metrics,
4. run the math discipline check,
5. extract transferable lessons and idea seeds,
6. separate macro/micro/portfolio revisions from stop-or-kill decisions,
7. choose a program-search mode when iteration is needed,
8. then decide promote / iterate / reject.

Do **not** start from IC/backtest metrics alone.

## Current Trading Mandate

The current Factor Forge mandate is **long-only**:
- no short selling,
- no direct buying/selling of deciles,
- no adoption based on long-short spread,
- no revision by changing portfolio expression, rebalance mechanics, or decile trading.

Deciles are allowed only as diagnostics for:
- whether higher factor values map monotonically to higher future returns,
- whether the high-score long side earns positive return,
- whether the expression direction is economically coherent.

If a factor is monotonic only because the short side loses money, it is not adoptable. If the long side is weak or negative, revise the factor expression/Step3B code or reject the factor.

## Long-Side Performance Economics

Treat each factor like a small business when deciding admission or iteration:

- `revenue`: long-side expected return / risk premium.
- `COGS`: explicit trading cost. When no better cost model exists, use `turnover * 0.3%`.
- `volatility`: operating instability / risk-capital driver, not direct COGS.
- `volatility_drag`: for log/geometric growth use `-0.5 * sigma^2`, not `-0.5 * sigma`.
- `gross_profit_proxy`: long-side mean return minus volatility drag.
- `capital_expenditure`: maximum drawdown, because the factor must survive capital impairment before the recovery arrives.
- `depreciation_or_payback`: drawdown recovery time.
- `risk_budget`: determined by Sharpe, max drawdown, recovery time, correlation/capacity, and confidence in repeatability.

Admission is no longer based on raw positive long-side return alone. The primary objective is:

`long_side_risk_adjusted_alpha`

Default working thresholds:

- candidate: long-side Sharpe >= `0.50`
- official: long-side Sharpe >= `0.80`
- drawdown soft limit: max drawdown no worse than `-35%`
- recovery soft limit: recovery days no longer than one trading year (`252`)

These thresholds are research governance defaults, not eternal truths. They may be tightened by asset class, liquidity bucket, turnover, or portfolio context. A positive-return factor with low Sharpe, high volatility drag, deep drawdown, or slow recovery should be iterated or rejected, not promoted.

## Canonical Return Sources

1. `risk_premium`
- The strategy is paid for bearing a recurring systematic risk or unpopular exposure.

2. `information_advantage`
- The strategy is earlier or cleaner than consensus in interpreting company-specific signals.

3. `constraint_driven_arbitrage`
- The strategy harvests recurring, not fully risk-free, opportunities created by objective constraints:
  - exchange rules,
  - benchmark/mandate pressure,
  - insurance/public-fund behavior,
  - liquidity and execution frictions,
  - transfer or conversion mechanisms,
  - repeated institutional action patterns.

4. `mixed`
- More than one source is active and should be recorded as such.

## Review Checklist

A proper review should answer:
1. Is this factor mainly risk premium, information advantage, or constraint-driven arbitrage?
2. Why does the other side behave predictably?
3. Are the current metrics supporting the return source itself, or only a fragile implementation?
4. Is this already a reusable factor, or still only a locally effective feature set?
5. What are the failure regimes, crowding risk, capacity limits, and implementation risks?
6. What does this attempt add to the experience chain, including failed branches?
7. Is the next step an exploit branch, an explore branch, or both?

## Revision Principles

A proper revision proposal should answer:
1. Which return source is this modification trying to strengthen?
2. Which objective constraints is it exploiting or adapting to?
3. Why does the revised factor expression map more linearly/monotonically to risk-adjusted long-side expected returns?
4. What is the `revision_operator` and why should it improve generalization?
5. What are the `overfit_risk` and `kill_criteria`?
6. Should the next loop use genetic formula mutation, Bayesian parameter search, RL-policy advisory, or multi-agent parallel exploration?
7. Confirm that the proposal changes the factor expression or Step3B code itself, not portfolio mechanics.

## Program Search Policy

Step6 may borrow search methods from program-level factor mining:
- `genetic_algorithm`: mutate/crossover formula programs, operators, signs, lags, windows, transforms, and neutralization choices.
- `bayesian_search`: tune windows, thresholds, clipping, decay, bucket counts, rebalance settings, and other bounded parameters.
- `reinforcement_learning`: learn a revise/promote/reject policy from accumulated trajectories; advisory until the knowledge base is large enough.
- `multi_agent_parallel_exploration`: assign independent branches to separate agents when multiple plausible explanations exist.

For a single cold-start factor, prefer controlled genetic/Bayesian/multi-branch search over automatic RL. RL becomes meaningful only after many saved trajectories.

Do not use DD-view-edge-trade in Factor Forge. That framework is for individual-stock diligence, not the factor-mining control loop.

## Math Discipline

When reviewing Step5/Step6 output, require `math_discipline_review`:
- `step1_random_object`
- `target_statistic`
- `information_set_legality`
- `spec_stability`
- `signal_vs_portfolio_gap`
- `revision_operator`
- `generalization_argument`
- `overfit_risk`
- `kill_criteria`

If these cannot be answered, do not promote the factor.

Use repo reference:
- `docs/operations/factorforge-math-research-discipline.zh-CN.md`

## Learning And Innovation

The knowledge base is not an archive only. Every serious case should improve future researchers.

Require Step6 to extract:
- transferable patterns,
- anti-patterns,
- similar-case lessons,
- innovative idea seeds,
- reuse instructions for future agents.

Do not merely say “factor failed” or “factor passed”. Explain how Bernard, Humphrey, or a future Codex should reason differently next time.

## Recommended Pairing

This skill is usually paired with:
- `factor-forge-step5`
- `factor-forge-step6`

Typical usage pattern:
1. run Step4 to get evidence
2. run Step5 to close the case
3. apply this skill while running Step6 review / proposal generation
4. only after that, decide whether to promote, iterate, or reject

## References

- `references/framework.md`
- `references/step6-contract.md`
- `references/playbook.md`
