# Factor Forge Skill Feedback: Alpha016 Mechanism Math Gap

Date: 2026-05-15

Audience: Factor Forge Architect

Related case:

- `ALPHA016_CANONICAL_FORMULA_20160101`
- wrapper proof: `objects/runtime_context/ultimate_run_report__ALPHA016_CANONICAL_FORMULA_20160101.json`
- Step6 brief: `objects/research_iteration_master/loop_research_brief__ALPHA016_CANONICAL_FORMULA_20160101__iter1.md`
- supplemental context: `knowledge/因子工厂/知识库/ALPHA016_20160101_MECHANISM_CONTEXT.md`

## Summary

This Alpha016 run exposed a gap between the current Factor Forge Step6 / research-brain requirements and the actual depth of mechanism math produced by the pipeline.

The pipeline produced schema-valid Step6 artifacts and a mechanism math summary, but the summary was too generic and partly wrong for Alpha016. A precise economic and mathematical mechanism only emerged after the user challenged the assistant in conversation.

This means the current skill/validator stack can pass while still failing a senior research standard: it can record a broad factor family without forcing the agent to state the actual stochastic process, latent state, estimator, conditional distribution, and falsification logic implied by the formula.

## What Happened

### Initial formal run

The user asked to research Alpha016 using Factor Forge Ultimate.

The assistant:

1. verified there were no existing Alpha016 artifacts;
2. used canonical formula intake for Step1;
3. ran Step2-6 through:

```bash
python3 scripts/run_factorforge_ultimate.py \
  --report-id ALPHA016_CANONICAL_FORMULA_20160101 \
  --start-step 2 \
  --end-step 6
```

The wrapper passed.

Formal formula:

```text
(-1 * rank(covariance(rank(high), rank(volume), 5)))
```

Core evidence:

| Metric | Value |
|---|---:|
| Rank IC mean | `0.0533` |
| Rank IC IR | `0.7815` |
| G10 annual return | `3.84%` |
| G10 Sharpe | `0.169` |
| G10 max drawdown | `-51.26%` |
| G10 daily turnover | `48.64%` |
| cost-adjusted annual return | `-32.91%` |
| cost-adjusted Sharpe | `-1.450` |

Step6 decision was `iterate`, not promoted.

### User's first challenge

The user asked:

```text
这个单调性和IC也太好了吧？真的假的啊？不会有什么问题吧？
```

The assistant checked:

- generated factor implementation;
- Step4 evaluation alignment;
- forward-return construction;
- quantile NAV shape;
- exposure by group.

The assistant found:

- no obvious lookahead;
- Step4 uses next-day forward return;
- Rank IC is plausible, not obviously leakage-level;
- monotonicity is misleading because `G01` collapses and `G9 > G10`;
- the result is short-side dominated, not a strong long-only signal.

### User's second challenge

The user asked:

```text
那这个alpha016的数学和经济机制是什么？
```

The assistant answered with a more precise mechanism:

- Alpha016 is a price-volume rank-dependence state;
- high covariance between high-price rank and volume rank represents crowded price-volume confirmation;
- the factor seems to detect bad flow or transient price pressure;
- it is more of a bad-state detector than a good long-only selector.

### User's third challenge

The user asked:

```text
这个因子的经济机制是在假设股票服从什么process或者distribution呢？你有这种数学判断吗？
```

Only then did the assistant state the actual implied process:

```text
H_{i,t} = CSRank_t(high_{i,t})
V_{i,t} = CSRank_t(volume_{i,t})
C_{i,t} = Cov_5(H_{i,t}, V_{i,t})
A_{i,t} = -CSRank_t(C_{i,t})
```

and the process hypothesis:

```text
P_{i,t} = F_{i,t} + I_{i,t} + epsilon_{i,t}
I_{i,t+1} = rho * I_{i,t} + eta_{i,t+1}, 0 < rho < 1
```

with target functional:

```text
E[r_{i,t+1} | F_t, C_{i,t}]
```

and empirical relationship:

```text
E[r_{i,t+1} | high C_{i,t}] < E[r_{i,t+1} | mid/low C_{i,t}]
```

This is the correct level of mechanism math, but it was not produced by the formal Step6 artifact automatically.

### User's fourth challenge

The user asked:

```text
你的这个分析写在哪儿了？会给council看吗？
```

The assistant checked the existing artifacts and found:

- Step6 brief had generic `liquidity_shock` / `behavioral_microstructure` wording;
- researcher memo mentioned crowding / liquidity pressure only broadly;
- the exact rank-copula / transient-impact / conditional-distribution hypothesis was not present;
- the current revision council packet builder consumes Step6 iteration, case, evaluation, run, handoff, spec, and brief JSON, but does not automatically consume a later human mechanism note unless explicitly added to the Step6 artifacts or packet-building flow.

The assistant therefore acknowledged:

```text
如果现在直接开 council，它大概率看不到这段精化后的机制判断。
```

### User's fifth challenge

The user asked:

```text
这个精确的数学假设是我追问了你才写的，不是skill本身就要求你写的吗？
```

The assistant acknowledged:

- yes, the critique is valid;
- the skill and mechanism math contract do require this;
- the current Step6 output satisfied schema but not research depth;
- Alpha016's mechanism math summary was under-specified and partly wrong.

## Current Artifact Problem

In `loop_research_brief__ALPHA016_CANONICAL_FORMULA_20160101__iter1.md`, the mechanism summary includes:

```text
Model family: linear_factor_projection
State or object: orthogonalized residual signal state
Factor as estimator: the factor applies projection or residualization to estimate signal orthogonal to nuisance exposures
Target functional: E[r_{t+1:t+h} | F_t, residual_signal_t]
```

This is not the right mathematical model for Alpha016.

Alpha016 contains:

- `rank`
- `covariance`
- `high`
- `volume`
- rolling five-day dependence

It should be classified as:

```text
model_family: price_volume_microstructure
state_or_object: rolling price-volume rank-dependence / crowded confirmation state
factor_as_estimator: rolling covariance estimator of latent transient price-pressure or crowded-attention state
target_functional: E[r_{i,t+1} | F_t, Cov_5(CSRank(high), CSRank(volume))]
```

## Missing Requirements In Current Skill Behavior

The current skill text says to run `math_discipline_review` and carry a `mechanism_math_contract`, but the actual process does not force the agent to answer the following questions at enough precision:

1. What exact random object does the formula transform?
   - Example: joint rank process `{(H_{i,t-k}, V_{i,t-k})}` rather than generic price history.
2. What latent state is being estimated?
   - Example: crowded price-volume confirmation / transient impact state.
3. What process or conditional distribution is assumed?
   - Example: `P = F + I + epsilon`, `I_{t+1}=rho I_t + eta`, and `r_{t+1}|C_t`.
4. Is the target relationship linear, monotone, U-shaped, thresholded, or short-side dominated?
   - Example: Alpha016 evidence supports "high C is bad" more than "low C is best."
5. Does the observed metric signature match the mechanism?
   - Example: `G9 > G10` contradicts a strict long-side monotone story.
6. What evidence would falsify the mechanism?
   - Example: delay test kills IC, smoothing kills signal, G10 stays weak while G01 collapse drives all spread.
7. Will the revision council actually receive this mechanism context?
   - Current packet builder does not automatically ingest supplemental human mechanism notes.

## Skill / Architecture Gaps

### Gap 1: Schema validity is weaker than research validity

The validator requires fields like `model_family`, `state_or_object`, and `target_functional`, but it does not validate whether those fields are formula-specific and coherent.

Alpha016 passed with a residual/projection style summary even though the formula has no projection or residualization.

Recommendation:

- Add a coherence validator between formula operators/inputs and `mechanism_math_summary`.
- If formula contains price + volume + covariance/correlation/rank, model family should default to `price_volume_microstructure` unless explicitly challenged.
- If model family is `linear_factor_projection`, require projection/residual/neutralization/beta/PCA evidence in the formula or canonical spec.

### Gap 2: Covariance was not treated as dependence mechanism as strongly as correlation

The classifier has a direct `correlation/corr` rule for price-volume dependence, but covariance can be mishandled or overridden downstream.

Recommendation:

- Treat `covariance/cov` as a first-class price-volume dependence operator.
- For Alpha101 formulas, `covariance(rank(price_field), rank(volume_field), window)` should map to a rank-dependence / copula-like microstructure state.

### Gap 3: Mechanism math lacks process/distribution pressure

The current skill says "stochastic process" broadly, but it does not force the agent to state:

- process equation;
- conditional distribution or target conditional expectation;
- whether the state is permanent information, transient pressure, liquidity shock, or pure noise;
- how observed decile shape supports or contradicts the process.

Recommendation:

Add required Step6 fields:

```json
{
  "process_hypothesis": "...",
  "latent_state": "...",
  "observable_estimator": "...",
  "conditional_distribution_hypothesis": "...",
  "relationship_shape": "linear|monotone|threshold|U-shaped|bad-state-detector|unknown",
  "metric_signature_match": "...",
  "mechanism_falsification_tests": []
}
```

### Gap 4: Long-short dominance was detected but not connected back to mechanism math

Step4 warned `LONG_SHORT_NAV_EXTREME`, and the decile table showed `G01` collapse and `G9 > G10`. Step6 noted short-side dominance, but did not update the mechanism math accordingly.

Recommendation:

- If `G9 > G10` or high-score group is weak while low-score group collapses, mark relationship shape as `bad_state_detector` or `non_monotone_top_tail`.
- Force the revision strategy to explain how to convert a bad-state detector into a long-only selector.

### Gap 5: Council packet may miss post-hoc human mechanism insight

The current `build_revision_council_packet.py` packet includes:

- mechanism math contract;
- research memo;
- loop research brief;
- metrics;
- chart evidence;
- source paths.

It does not appear to automatically ingest later supplemental human mechanism notes.

Recommendation:

- Add a formal `supplemental_research_context` field in council packet.
- Search and attach files under:

```text
objects/research_iteration_master/revision_council/<report_id>/supplemental_context/
knowledge/因子工厂/知识库/*<report_id>*MECHANISM*
```

- Require council tasks to read that context before proposing revisions.

### Gap 6: Step6 should block or downgrade when mechanism math is generic

If the mechanism summary says only "generic systematic factor", "linear projection", or "liquidity shock" without stating the estimator/process/target conditional distribution, it should not be treated as council-ready.

Recommendation:

- Introduce a Step6 warning or block:

```text
BLOCK_MECHANISM_MATH_UNDER_SPECIFIED_FOR_COUNCIL
```

or at least:

```text
WARN_MECHANISM_MATH_GENERIC_COUNCIL_CONTEXT_WEAK
```

before creating agentic council tasks.

## Proposed Acceptance Criteria For Skill Fix

A future Alpha016 Step6 rerun should be considered improved only if the loop brief or mechanism analysis includes all of the following:

1. Formula-specific state:

```text
C_{i,t}=Cov_5(CSRank(high_{i,t}), CSRank(volume_{i,t}))
```

2. Process hypothesis:

```text
P_{i,t}=F_{i,t}+I_{i,t}+epsilon_{i,t}
I_{i,t+1}=rho I_{i,t}+eta_{i,t+1}
```

3. Target functional:

```text
E[r_{i,t+1} | F_t, C_{i,t}]
```

4. Relationship shape:

```text
high C is bad; low C is not proven to be best; top tail is non-monotone because G9 > G10
```

5. Mechanism-specific evidence:

- `G01` collapse;
- `G9 > G10`;
- high turnover;
- negative cost-adjusted G10;
- post-924 regime improvement but weak 2020-2024 long side.

6. Council-specific revision requirements:

- delay sanity;
- persistence smoothing;
- active-liquidity gate;
- no short-leg or decile-trading repair.

## Concrete Alpha016 Files Added After User Feedback

The assistant added:

- `knowledge/因子工厂/知识库/ALPHA016_20160101_MECHANISM_CONTEXT.md`
- `objects/research_iteration_master/revision_council/ALPHA016_CANONICAL_FORMULA_20160101/supplemental_context/human_mechanism_context__ALPHA016_CANONICAL_FORMULA_20160101.md`

These files contain the mechanism context that should be made visible to the next revision council.

## Bottom Line

The user's critique is correct.

The current skill says it requires mechanism math, but in practice it can produce and validate a generic mechanism summary that misses the actual mathematical object implied by the formula.

For Alpha016, that gap matters because the factor is not a clean long-only alpha. It is a price-volume rank-dependence bad-state detector. Without the precise process/distribution hypothesis, the council may optimize the wrong thing: it may smooth or tune metrics without understanding that the real challenge is converting short-side-dominant bad-flow detection into a long-only selector.
