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
1. freeze the economic hypothesis, estimand, payer and information set,
2. search an open mathematical-tool space, compare mechanism-distinct models,
   and select one from the economic hypothesis,
3. derive the mechanism-specific mathematical object, its market-outcome map,
   observation equation, and only the specialized audits that apply,
4. bind a mechanism-conditioned measurement program and implementation route,
5. interpret metrics as tests of the pre-registered mathematical claims,
6. extract transferable lessons and idea seeds,
7. localize any failure before choosing a bounded search/revision mode,
8. then decide promote / iterate / reject.

Do **not** start from IC/backtest metrics alone.
Do not start from an available operator and reverse-engineer an economic story,
or change the estimand because a convenient field is available.

Every completed Step6 loop must also leave a user-facing `loop_research_brief`
artifact in Markdown and JSON. The brief is not a chat summary: it is the
durable research note that explains economic interpretation, metric/chart
evidence, knowledge comparison, next research direction, and the final loop
conclusion. Long-short and decile evidence must be labeled diagnostic-only, and
the next direction must explain why portfolio-expression repair is forbidden.

## Research Quality Claim Ladder

The research brain must grade every mechanism claim. Do not let a fluent
explanation masquerade as validation.

Use this ordered ladder:

```text
none
narrative_only
math_framed
metric_consistent
component_validated
payer_validated
```

`narrative_only` is a story. `math_framed` names a mathematical object or tool.
`metric_consistent` requires an accepted, replayable factor-proof certificate;
aggregate IC/NAV/group evidence without that certificate remains
`metric_candidate`. `component_validated` requires the trusted full-versus-
ablated verifier, not a narrative ablation claim.
`payer_validated` requires a falsifiable counterparty or payer proxy.
`stochastic_validated` remains an optional protocol qualifier only when the
selected mechanism actually makes a stochastic-process claim; it requires
state, conditional return distribution, transition/persistence, or
barrier/tail evidence. It is not a stage that fundamental, valuation, causal,
spectral, functional or other non-stochastic factors must pass.

For a formal claim, `component_validated` specifically requires the replayable
full-versus-ablated panel verifier. Joint buckets or regime splits remain useful
diagnostics unless a trusted verifier contract covers them. The current v1
kernel does not mechanically certify payer or stochastic claims, so do not use
those labels merely because the memo contains the corresponding fields.

Every serious review must also produce an evidence tier map:

- `promotion_gate_evidence`
- `robustness_evidence`
- `diagnostic_evidence`
- `window_contract_evidence`
- `exploratory_evidence`

Promotion can use only promotion-gate evidence. Diagnostic, supplemental, and
window-contract evidence can explain or falsify, but cannot be promoted into
adoption proof.

Promotion-gate metrics require the frozen-search -> locked-threshold ->
one-time-OOS-release chain. The release binds actual panel dates, at least 60
daily periods and the panel hash. Formal long-end judgment uses net geometric
return and positive terminal/minimum wealth; arithmetic return is only the
gross-to-cost reconciliation.

Do not interpret an overlapping `t+5` forward-return panel as 217 independent
daily portfolio returns. Formal verifier v2 supports only a disjoint one-day
return path with execution equal to label start. It must verify actual label
start/end dates and prices against the full
`factorforge_data_access.trade_cal_csv` calendar independently resolved
outside the factor workspace. Its normalized open-date snapshot must match the
explicit snapshot id in the Git-anchored trusted calendar registry, and the
proof binds `verification_scope=production`, the raw file, normalized snapshot,
registry SHA, anchor commit/blob, and snapshot id before recomputing the return.
A narrative horizon, workspace-provided or unregistered sparse calendar, or
renamed `fwd_ret_5d` column is not proof. Neither a `SMOKE` name nor a modified
worktree registry changes this authority. Multi-day labels remain
predictive diagnostics until a valid daily cohort/NAV path or supported
non-overlapping stride contract exists.

If the review invokes stochastic processes, stopping times, hidden states, or
barriers, explicitly state whether the claim is `framing_only` or `validated`.
If it is validated, name the state space, conditional drift/return
distribution, transition persistence or half-life, barrier/tail test, and what
information each revision preserves or deletes.

If the review claims Dirac-style induction or a reusable symbolic law, require a
public memo with atomic state, invariant, estimator law, deleted-information
audit, limiting cases, falsification design, reuse boundary, and overclaim
guard. Without that artifact, call it a hypothesis, not an induction result.

## Current Trading Mandate

The current Factor Forge mandate is **long-only**:
- no short selling,
- no direct buying/selling of deciles,
- no adoption based on long-short spread,
- no revision by changing portfolio expression, rebalance mechanics, or decile trading.

For non-risk-premium claims, deciles are allowed only as diagnostics for:
- whether higher factor values map monotonically to higher future returns,
- whether the high-score long side earns positive return,
- whether the expression direction is economically coherent.

If a factor is monotonic only because the short side loses money, it is not adoptable. If the long side is weak or negative, revise the factor expression/Step3B code or reject the factor.
For `risk_premium`, quintile/decile monotonicity is a formal obligation. Use
value-based quantiles and BLOCK if ties collapse the required 5/10 buckets;
never split ties by asset order.

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

## Pre-Cost Information First

Do not let turnover or trading cost make the research decision before the
factor's information content is understood. Cost can block official promotion;
it should not automatically block learning, feature retention, or slower-horizon
repair.

Use a two-layer judgment:

1. **Information layer:** decide whether the factor contains a pre-cost premium
   and what market process produces it.
2. **Tradability layer:** decide whether the current expression, horizon,
   turnover, drawdown, and capacity can become a live long-only factor.

The information layer must inspect:

- return source: `risk_premium`, `information_advantage`,
  `constraint_driven_arbitrage`, or `mixed`;
- profit payer / counterparty: why the payer exists, why the behavior repeats,
  and which observation would falsify the payer;
- pre-cost premium: IC/rank IC, grouped gross returns, long-end gross return,
  and Fama-MacBeth or cross-sectional regression where available;
- monotonicity: shape, direction, and stability across full IS, IS subsamples,
  OOS diagnostics, liquidity buckets, and regimes;
- stochastic risk source: whether volatility and max drawdown come from
  continuous sigma exposure, jump/tail events, regime switching, liquidity
  crunch, crowding, or implementation noise.

Tighten evidence by return source:

- `risk_premium`: require strong monotonicity and Fama-MacBeth /
  cross-sectional regression support, because compensation should be priced
  broadly and stably.
- `information_advantage`: allow weaker monotonicity if the long end has
  significant gross and risk-adjusted return; the edge may be concentrated in
  the highest-information tail.
- `constraint_driven_arbitrage`: require clear constraint/payer logic and
  evidence that the premium appears when the constraint binds.

These standards are enforced through the factor proof certificate:

- every claim class must reconcile IC, ICIR, volatility cost, transaction
  cost, maximum drawdown and executable long-end return;
- Fama-MacBeth and quintile/decile monotonicity are acceptance obligations only
  for `claim_class=risk_premium`;
- for all other claim classes, monotonicity is diagnostic and cannot be marked
  as universal promotion-gate evidence;
- every passed result must bind a workspace-local evidence file, verifier ID
  and SHA256, with thresholds registered before evaluation;
- formal metric proof must come from the deterministic frozen-panel verifier,
  not a researcher-authored JSON carrying a trusted verifier name.
- formal component proof must come from the deterministic component-obligation
  verifier and be replayable against its source panel/spec.

If cost overwhelms net performance but the information layer is strong, classify
the result as `feature_candidate`, `state_descriptor`, `needs_horizon_repair`,
or `execution_research_needed`. Do not call it no-information unless the
pre-cost evidence and mechanism also fail.

## Factor Complexity Penalty

Do not impose a hard limit such as "at most three primitives." A factor may be
mathematically richer when the economic hypothesis requires it. But every added
state, interaction, threshold, nonlinear gate, data dependency, or free
parameter must pay a complexity cost.

Use this research objective when comparing revisions:

$$
\mathcal{J}(f)
=
\mathrm{OOSLongEdge}(f)
+ \alpha\,IC_{\mathrm{resid}}(f)
- \lambda_C\,\mathrm{Complexity}(f)
$$

where complexity should increase with:

$$
\mathrm{Complexity}(f)
=
aN_{\mathrm{primitive}}
+ bN_{\mathrm{interaction}}
+ cN_{\mathrm{free\ parameter}}
+ dN_{\mathrm{data\ dependency}}
+ eN_{\mathrm{nonlinear\ gate}}
$$

This is a soft penalty, not a style preference. A complex factor can win if it
delivers durable OOS long-side improvement, residual IC, lower drawdown, or a
clearer economic mapping. A complex factor should lose if it only improves
in-sample raw IC, adds opaque gates, or hides overfit behind mathematical
language.

For every proposed revision, state:
- which economic state or stochastic-process component the new term represents
  (`drift`, `volatility`, `barrier distance`, `hitting probability`, or another
  named object),
- why the added complexity improves generalization rather than backtest fit,
- what metric improvement must appear for the added complexity to be worth it,
- and which term, gate, or parameter should be removed if the improvement does
  not appear.

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
3. Why should the revised factor expression improve the claim-specific
   long-side return shape? Require broad monotonicity only for risk-premium
   claims; for other claims state the predicted tail, threshold or regime
   shape instead.
4. What is the `revision_operator` and why should it improve generalization?
5. What are the `overfit_risk` and `kill_criteria`?
6. What complexity was added or removed, and is the marginal benefit worth the
   complexity penalty?
7. Should the next loop use genetic formula mutation, Bayesian parameter search, RL-policy advisory, or multi-agent parallel exploration?
8. Confirm that the proposal changes the factor expression or Step3B code itself, not portfolio mechanics.

## Program Search Policy

Step6 may borrow search methods from program-level factor mining:
- `genetic_algorithm`: mutate/crossover formula programs, operators, signs, lags, windows, transforms, and neutralization choices.
- `bayesian_search`: tune windows, thresholds, clipping, decay, bucket counts, rebalance settings, and other bounded parameters.
- `reinforcement_learning`: learn a revise/promote/reject policy from accumulated trajectories; advisory until the knowledge base is large enough.
- `multi_agent_parallel_exploration`: assign independent branches to separate agents when multiple plausible explanations exist.

For a single cold-start factor, prefer controlled genetic/Bayesian/multi-branch search over automatic RL. RL becomes meaningful only after many saved trajectories.

Search is subordinate to the mathematical contract. Its neighborhood must be
defined in terms of model assumptions, state variables, estimators and preserved
invariants before formula/operator/code mutation begins. A candidate that
changes the estimand is a new hypothesis branch, not a parameter mutation.

Do not use DD-view-edge-trade in Factor Forge. That framework is for individual-stock diligence, not the factor-mining control loop.

## Math Discipline

Read and apply:

- `docs/contracts/mechanism_conditioned_measurement_program_v1.zh-CN.md`
- `docs/operations/factorforge-math-research-discipline.zh-CN.md`

`docs/contracts/mechanism_math_contract_v2.zh-CN.md` is legacy compatibility
material only. Read it when an existing artifact already carries v2; do not
synthesize v2 for current research.

Require `math_discipline_review` to bind the mathematical object, estimand,
information set, selected/competing models, measurement semantics and any
mechanism-applicable audits, observation equation,
measurement program, generalization argument, overfit risk and kill criteria.
`under_specified` is valid; invented certainty is not. The contracts discipline
research but never replace Step4/5 evidence or promotion gates.

## Learning And Innovation

The knowledge base is not an archive only. Every serious case should improve future researchers.

Prior cases remain `advisory_prior`, `counterexample`, or `tool_candidate`.
They may broaden model selection and expose failed measurements, but they cannot
override the current derivation or serve as current-factor proof.

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
## Implementation and Factor Isolation Discipline

- Every formal factor artifact must carry `artifact_identity`.
- Every formal run must carry `manifest_identity`.
- `implementation_mode` is restricted to `operator`, `direct_code`, or `hybrid`.
- Artifacts must not be reused across mode, factor, report, branch, or run unless identity/hash lineage matches explicitly.
- Formal execution must consume manifest-specified paths only; do not pick files by `glob`, mtime, or "latest" guesses.
- If `report_id`, `factor_id`, `source_type`, `implementation_mode`, `branch_id`, `spec_hash`, or formula/code/hybrid hash does not match, BLOCK.
- Direct generated implementation files belong to one factor identity; shared helpers may be reused, factor-specific generated code may not be silently copied.

## Step6 Research Intelligence

When reviewing Step6 output, require `research_memo` to carry:

- `evidence_audit`
- `mechanism_analysis`
- `case_comparison`
- `revision_strategy`
- `search_policy_decision`

`evidence_audit` is the first gate: all-skipped backends, missing self-quant
long-side evidence, missing long-side risk metrics, invalid factor values, or
identity failures make evidence unusable. Long-short or short-side diagnostics
may explain failure but cannot justify adoption.

`revision_strategy` must target factor expression or Step3B code. It must state
why the fix is not a portfolio-expression, short-leg, decile-trading, rebalance,
or clean-data mutation workaround. Program search remains approval-gated and
must serve the research hypothesis.

## Mechanism Reasoner And Case Comparator

Step6 reasoning must first identify the return source and factor family, then
ask whether the observed long-side evidence matches the expected mechanism
signature. IC, long-short spread, or a weak short side cannot establish a
mechanism.

Case comparison must actively use retrieval. Same-factor cases require matching
factor identity and hash lineage. Similar cases, general methodology, and
anti-patterns may inform judgment, but must not be treated as same-factor
evidence or promotion support. Empty retrieval is a cold-start knowledge gap and
should be written as a future retrieval anchor when provenance gates pass.

## Revision Strategist

Step6 revision proposals must be falsifiable factor-expression or Step3B-code
changes. They must not repair adoption by changing portfolio expression,
short-leg exposure, decile trading, rebalance mechanics, or shared clean data.

Actionable revision hypotheses must name the failure signature, mechanism
target, expression change, expected metric changes, falsification tests, kill
criteria, overfit risk, and why the change is not a portfolio fix. Evidence or
provenance failures such as `implementation_suspect` and
`same_factor_identity_mismatch` should block normal expression revision until
the upstream issue is repaired. A clean promotion should not invent a revision:
`revision_needed=false`, no hypotheses, and `revision_quality=not_needed`.

## Revision Council Discipline

The Revision Council is Step6's investment-committee method for difficult
iterate decisions. It is not tied to named agents. Any main agent using Factor
Forge Ultimate may run the council itself or delegate role-specific proposals to
subagents when the runtime supports safe delegation.

Use council output only as advisory research material. Council proposals can
challenge symbolic laws, evidence quality, mechanism fit, expression design,
cost/turnover behavior, regime robustness, and retrieval lessons. They cannot
promote a factor, approve execution, write `handoff_to_step3b`, modify
generated code, mutate shared clean data, or write official-library records.

The main agent must define an exploration graph. Independent hypotheses may be
explored in parallel; dependent hypotheses must be explored sequentially. For
example, evidence-audit concerns should be resolved before expression mutation,
and symbolic-law findings should be checked by formula feasibility before any
Step3B revision brief is accepted.

Every council proposal must include an explicit `derivation_record`: research
question, assumptions, mathematical objects, selected and rejected tools,
formula or symbolic derivation steps, derived implications, revision
hypotheses, expected metric changes, falsification tests, kill criteria,
confidence limits, and an overclaim guard. This is a public research artifact
for knowledge-base learning, not hidden chain-of-thought. A proposal without a
substantive derivation record is invalid.

The symbolic-law role should treat the factor formula as a mathematical object:
state variable, estimator mapping, target functional, invariance or scaling
claim, limiting cases, mechanism-specific structure, and falsification tests.
It may use DCF, residual income, accounting identities, dimensional analysis,
stochastic calculus, spectral analysis, projection, robust statistics,
functional analysis, causal models, dynamical systems, stopping time,
information theory, optimization, a composition of tools, or another justified
method. It should select tools based on the factor and evidence, not apply a
fixed checklist. Mathematical
plausibility is not evidence and must be checked against Step4/5/6 evidence and
provenance gates before any future human-approved implementation work.

Council is route-based, not title-based. Generate routes from the active
approach registry; preserve at least one blind null/alias attack; bind each
dispatch/result to route fingerprint, blind-context hash, expected agent
identity and packet/result hashes. Root synthesis compares incompatible
assumptions and discriminating evidence. Majority vote cannot choose a law.
