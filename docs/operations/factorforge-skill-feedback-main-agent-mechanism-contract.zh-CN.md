# Factor Forge Ultimate 问题反馈：主 Agent 公式特异机制推导合同缺失

Date: 2026-05-18

Audience: Factor Forge Architect

Related runs:

- `ALPHA019_CANONICAL_FORMULA_20160101_AGENTIC_AUTO_RETEST_P1C_FINAL_20260518_111713`
- `ALPHA030_CANONICAL_FORMULA_20160101_AGENTIC_LOOP_20260518_112707`

Key proof paths:

- `objects/runtime_context/ultimate_loop_report__ALPHA019_CANONICAL_FORMULA_20160101_AGENTIC_AUTO_RETEST_P1C_FINAL_20260518_111713.json`
- `objects/runtime_context/ultimate_run_report__ALPHA019_CANONICAL_FORMULA_20160101_AGENTIC_AUTO_RETEST_P1C_FINAL_20260518_111713.json`
- `objects/runtime_context/ultimate_loop_report__ALPHA030_CANONICAL_FORMULA_20160101_AGENTIC_LOOP_20260518_112707.json`
- `objects/runtime_context/ultimate_run_report__ALPHA030_CANONICAL_FORMULA_20160101_AGENTIC_LOOP_20260518_112707.json`
- `objects/research_iteration_master/revision_council/ALPHA030_CANONICAL_FORMULA_20160101_AGENTIC_LOOP_20260518_112707/revision_council_packet__ALPHA030_CANONICAL_FORMULA_20160101_AGENTIC_LOOP_20260518_112707.json`
- `objects/research_iteration_master/revision_council/ALPHA030_CANONICAL_FORMULA_20160101_AGENTIC_LOOP_20260518_112707/agentic_taskbook__ALPHA030_CANONICAL_FORMULA_20160101_AGENTIC_LOOP_20260518_112707.json`

## Summary

Recent fixes improved two important areas:

1. Alpha019-like formulas are no longer allowed to claim a price-volume mechanism when the formula has no volume input.
2. `--council-mode auto` now routes formal iterate cases to `agentic_dispatch_manifest` and stops at `awaiting_agent_results` instead of treating deterministic scaffold as formal Council.

However, the Alpha030 production-loop test exposed a remaining architecture gap:

```text
The main agent still does not have a hard pre-Council contract to produce a formula-specific economic and mathematical mechanism memo.
```

This is not just a prompt-polish problem. The current skill text says the right thing at a high level, but the wrapper artifacts and validators do not force the main agent to complete the research derivation before Council. As a result, Step1 can produce a reasonable initial thesis, Council dispatch can work, and validators can pass, while Step2/Step6 still carry generic or partially mismatched mechanism language into the Council packet.

Council should critique and improve the main agent's mechanism. It should not be used as a substitute for the main agent doing the first-principles formula-specific mechanism work.

## User Requirement

The intended standard is:

```text
economic hypothesis
-> selected mathematical model / stochastic process / distributional assumption
-> formula component mapping
-> target functional
-> expected metric signature
-> falsification and kill criteria
-> Council critique / revision
```

The `math_hypothesis` is not supposed to copy or re-label the factor expression. It must be selected from the economic hypothesis and must explain why this formula should estimate a tradable latent state.

Examples of acceptable mathematical tools include, but are not limited to:

- stochastic process / transient-impact process;
- state-space model;
- jump process;
- threshold or stopping-time model;
- cointegration / mean-reversion model;
- copula / rank-dependence model;
- projection / residualization model;
- dimensional or scaling analysis;
- spectral / Fourier / wavelet model when justified.

The main agent must choose the tool because it fits the payer, market structure, and formula, not because a template matched a broad factor family.

## What The Current Skill Says

The latest `factor-forge-ultimate` skill already contains the right high-level direction.

Relevant excerpts:

```text
Step1:
- economic_hypothesis must classify the broad source and state the second-layer mechanism and likely counterparty paying the return.
- math_hypothesis_candidates must map the economic mechanism to report-specific mathematical tools.
- Do not use fixed mappings like "price-volume means microstructure".

Step6:
- reflect on the evidence;
- require a deep memo from metrics, charts, and prior cases;
- classify the return source;
- run math_discipline_review.
```

The gap is that this guidance is not yet enforced as a concrete artifact contract and validator.

## Evidence From Alpha019 P1C Retest

Alpha019 fresh retest passed the newly fixed behavior:

```text
final_outcome = awaiting_agent_results
wrapper status = PASS
Council effective_mode = agentic_dispatch_manifest
deterministic_scaffold_used = false
```

Its Step1 and Step2 mechanism also improved materially:

```text
subtype = slow_winner_state_short_horizon_reversal_or_threshold_migration
model_family = stochastic_process
state_or_object = slow winner state interacting with short-horizon reversal/dislocation threshold state
```

This shows the positive Alpha019-like mechanism fix works for the targeted case.

## Evidence From Alpha030 Production Loop

Alpha030 was used as a new production-level test:

```text
report_id = ALPHA030_CANONICAL_FORMULA_20160101_AGENTIC_LOOP_20260518_112707
final_outcome = awaiting_agent_results
wrapper status = PASS
Council effective_mode = agentic_dispatch_manifest
deterministic_scaffold_used = false
```

The Council dispatch path worked. But the mechanism quality still exposed a main-agent contract gap.

### Alpha030 Formula

```text
plus(
  plus(
    negate(rank(plus(plus(sign(delta(close,1)), sign(delta(delay(close,1),1))), sign(delta(delay(close,2),1))))),
    1
  ),
  multiply(1, divide(sum(volume,5), sum(volume,20)))
)
```

A formula-specific decomposition should be:

```text
S_i,t = sign(r_i,t) + sign(r_i,t-1) + sign(r_i,t-2)
V_i,t = Sum(volume_i,t-4:t) / Sum(volume_i,t-19:t)
A_i,t = -Rank(S_i,t) + 1 + V_i,t
```

Economic reading:

```text
High score = weak recent signed price state plus high relative volume participation.
```

Plausible economic hypothesis:

```text
The factor is trying to monetize high-participation short-horizon weakness:
late trend followers, attention-driven retail flow, mandate-constrained liquidity demand,
or other liquidity-demand traders may create temporary impact that later reverts.
```

Formula-specific mathematical mechanism:

```text
P_i,t = F_i,t + I_i,t + epsilon_i,t

I_i,t is transient price pressure / liquidity shock.
S_i,t estimates the direction and persistence of recent short-horizon price pressure.
V_i,t estimates participation intensity or crowded attention.
Target functional:
  E[r_i,t+1 | S_i,t low, V_i,t high]
```

Expected metric signature:

```text
G10 should earn positive long-side return after cost.
Turnover should be consistent with the decay horizon of I_i,t.
G10 should not be worse than G9 if the high-score state is truly monotone.
```

### What The Artifacts Produced

Step1 was directionally reasonable:

```text
factor_intuition =
  price_volume_crowding_and_short_horizon_reversal;
  payer: late trend followers, attention-driven retail flow,
  and mandate-constrained liquidity demand...
```

But Step2/Step6 still carried generic price-volume language:

```text
model_family = price_volume_microstructure
factor_as_estimator =
  rank and rolling dependence transforms estimate price-volume co-movement
observable_estimator =
  rolling rank covariance/correlation/dependence between price-level or return ranks and volume/liquidity ranks
```

This is not formula-specific enough for Alpha030.

Alpha030 does use volume, so the previous field-consistency validator correctly does not block. But the formula does not contain rolling correlation, rolling covariance, or any explicit price-volume dependence estimator. It is a short-horizon signed price-state plus volume-ratio additive state. The mechanism should not describe it as rolling rank covariance/correlation/dependence.

## Why This Is Not Only A Prompt Problem

The issue is broader than "make the prompt clearer".

### 1. Skill guidance is high-level, not a hard output contract

The skill says to map economics to math tools and avoid fixed mappings, but it does not force a structured output such as:

```text
formula component
-> observable estimator
-> economic state
-> mathematical object
-> process/distribution
-> target functional
-> expected metric signature
```

Without this table, a generator can produce broad but weak language.

### 2. Step1/2 are intake/spec layers, not final mechanism adjudication

Step1/2 can form initial priors, but they happen before Step4 metrics. The real mechanism judgment must be updated after evidence:

```text
Step1/2 mechanism prior
+ Step4 metrics/charts/NAV/cost evidence
-> Step6 main-agent mechanism judgment
```

The current Step6 behavior still falls back to broad family classification too easily.

### 3. Validators check existence and some field consistency, but not operator-claim consistency

Alpha019 now correctly blocks "no volume formula but price-volume claim".

Alpha030 shows the next required validator:

```text
If mechanism text claims covariance/correlation/dependence, the formula must contain covariance/correlation/dependence operators or the memo must explicitly justify the claim.
```

Similarly:

- If formula uses `sign`, mechanism must discuss discontinuity, threshold migration, bucket churn, and turnover.
- If formula uses `sum(volume,5)/sum(volume,20)`, mechanism must discuss relative participation intensity or abnormal volume.
- If formula combines ranked sign state and volume ratio by addition, mechanism must discuss scale/monotonicity and whether the components are commensurable.

### 4. Council is being asked to repair what main agent should first state

Current agentic Council dispatch is useful. But the Council should receive a strong main-agent memo and critique it.

The desired flow:

```text
main agent formula-specific mechanism memo
-> Council packet
-> Council critique and alternative derivations
-> validated final revision strategy
```

The undesired flow:

```text
generic mechanism summary
-> Council is expected to discover the real mechanism from scratch
```

## Required Architecture Change

Add a mandatory `main_agent_formula_specific_mechanism_memo` artifact before Council dispatch.

Suggested path:

```text
objects/research_iteration_master/main_agent_mechanism_memo__<report_id>.json
objects/research_iteration_master/main_agent_mechanism_memo__<report_id>.md
```

It should be generated after Step4/5 evidence is available and before building the Council packet.

## Proposed Artifact Schema

```json
{
  "contract_version": "factorforge_main_agent_mechanism_memo_v1",
  "report_id": "...",
  "factor_id": "...",
  "formula": "...",
  "formula_component_map": [
    {
      "component_id": "short_signed_price_state",
      "formula_subexpression": "sign(delta(close,1)) + sign(delta(delay(close,1),1)) + sign(delta(delay(close,2),1))",
      "observable_estimator": "three-day signed price pressure state",
      "economic_state": "short-horizon weakness / reversal / continuation pressure",
      "mathematical_object": "discrete threshold state",
      "expected_role": "state direction and bucket migration"
    },
    {
      "component_id": "relative_volume_participation",
      "formula_subexpression": "sum(volume,5) / sum(volume,20)",
      "observable_estimator": "relative participation intensity",
      "economic_state": "attention / liquidity demand / crowded trading intensity",
      "mathematical_object": "positive scale state",
      "expected_role": "shock or crowding intensity"
    }
  ],
  "economic_hypothesis": {
    "return_source_class": "risk_premium | information_advantage | market_structure_arbitrage | mixed",
    "payer_or_counterparty": "...",
    "why_they_pay": "...",
    "necessary_market_structure": "..."
  },
  "math_hypothesis": {
    "selected_model_family": "stochastic_process | state_space | threshold_process | ...",
    "why_this_model": "...",
    "why_not_generic_template": "...",
    "random_object": "...",
    "latent_state": "...",
    "process_or_distribution": "...",
    "target_functional": "...",
    "formula_as_estimator": "...",
    "expected_metric_signature": {
      "rank_ic": "...",
      "long_side": "...",
      "cost_adjusted": "...",
      "monotonicity": "...",
      "turnover": "..."
    }
  },
  "evidence_comparison": {
    "observed_metrics": {},
    "mechanism_supported": "yes | partial | no",
    "contradictions": [],
    "revision_implications": [],
    "kill_criteria_triggered": []
  },
  "council_questions": [
    "Which assumption should Council challenge?",
    "Which alternative model family is plausible?",
    "Which ablation would distinguish reversal from continuation?"
  ]
}
```

## Validation Requirements

Add a validator for `main_agent_formula_specific_mechanism_memo`.

Minimum checks:

1. `formula_component_map` must cover all economically meaningful formula components.
2. Each component must cite an actual formula subexpression or operator family.
3. `math_hypothesis.process_or_distribution` must not merely restate the formula.
4. `target_functional` must include the future return object and information set.
5. `expected_metric_signature` must include long-side and cost-adjusted implications.
6. `evidence_comparison` must compare Step4 evidence to the expected signature.
7. If the memo claims correlation/covariance/dependence, the formula must include `correlation`, `covariance`, or a justified dependence estimator.
8. If the formula has `sign` or conditional thresholds, the memo must discuss discontinuity and turnover/bucket migration.
9. If the formula has volume ratio, the memo must discuss participation intensity, not just generic liquidity.
10. If the memo is missing, generic, or internally inconsistent, formal Step6 should BLOCK before Council dispatch.

## Council Packet Requirement

The Council packet should include this memo explicitly:

```json
{
  "main_agent_mechanism_memo_ref": "objects/research_iteration_master/main_agent_mechanism_memo__<report_id>.json",
  "main_agent_formula_component_map": {},
  "main_agent_math_hypothesis": {},
  "main_agent_evidence_comparison": {},
  "council_required_critiques": []
}
```

Council tasks should be instructed to critique this memo, not reconstruct basic mechanism from a generic summary.

## Acceptance Test

Use Alpha030 as the regression case.

Run:

```bash
python3 scripts/run_factorforge_ultimate_loop.py \
  --report-id ALPHA030_CANONICAL_FORMULA_20160101_MAIN_AGENT_MECH_TEST_<timestamp> \
  --start-step 2 \
  --max-loops 10 \
  --council-mode auto
```

Expected:

```text
wrapper status = PASS
final_outcome = awaiting_agent_results, unless promoted/rejected earlier
Council effective_mode = agentic_dispatch_manifest when iterate
main_agent_mechanism_memo exists
Council packet references main_agent_mechanism_memo
```

Mechanism-specific expected content:

```text
Formula components:
  short signed price state
  relative volume participation
  additive score / rank interaction

Must not claim:
  rolling rank covariance
  rolling correlation
  price-volume dependence estimator
unless it explicitly justifies why the additive sign/volume-ratio expression should be treated as such.

Must discuss:
  sign discontinuity
  threshold/bucket migration
  turnover caused by short horizon sign changes
  whether G10 underperformance and G9 > G10 falsify monotone high-score long-side payoff
```

Alpha030 current evidence that the memo must compare against:

```text
Rank IC mean = 0.015643
G10 annual return = -11.52%
Cost-adjusted annual return = -53.12%
Long-side max drawdown = -86.35%
Recovery = 3440 days
Daily turnover = 55.05%
G9 final NAV = 0.7180, G10 final NAV = 0.2480
```

Expected conclusion for the current Alpha030 evidence:

```text
The proposed reversal/crowding monetization mechanism is not supported for promotion.
High score appears to identify a bad or cost-destroyed state, not a tradable long-side recovery state.
Council may explore smoothing, sign threshold mutation, volume gate, or continuation-vs-reversal ablation,
but the main agent must state this contradiction before Council.
```

## Recommended Priority

P0:

- Add `main_agent_formula_specific_mechanism_memo` before Council dispatch.
- Add validator that blocks missing/generic/inconsistent mechanism memos.
- Ensure Council packet carries this memo.

P1:

- Add operator-claim consistency checks beyond field presence:
  - `correlation/covariance/dependence` claims require matching operators or explicit justification;
  - `sign` requires discontinuity/turnover discussion;
  - volume ratio requires participation-intensity discussion.

P2:

- Add Alpha030 as a production regression case for mechanism quality.
- Add Alpha019 as a regression case for no-volume formulas.

## Bottom Line

The current system now routes formal iterate cases correctly into agentic dispatch. That part is materially improved.

The remaining gap is research quality before Council:

```text
Step1/2 generate an initial mechanism prior.
Step4 provides real evidence.
Step6 main agent must produce a formula-specific economic and mathematical mechanism memo.
Council should critique that memo, not replace it.
```

Until that contract exists, Factor Forge can still pass wrapper and Council-dispatch tests while carrying a mechanism explanation that is too generic for formal factor research.

