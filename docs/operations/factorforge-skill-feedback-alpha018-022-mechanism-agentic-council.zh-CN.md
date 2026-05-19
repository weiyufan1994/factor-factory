# Factor Forge Ultimate 问题反馈：Alpha018-022 机制数学推导与 Agentic Council 闭环缺口

Date: 2026-05-18

Audience: Factor Forge Architect

Related cases:

- `ALPHA018_CANONICAL_FORMULA_20160101`
- `ALPHA019_CANONICAL_FORMULA_20160101`
- `ALPHA020_CANONICAL_FORMULA_20160101`
- `ALPHA021_CANONICAL_FORMULA_20160101`，未正式执行，因生产公式引擎不支持条件比较语义
- `ALPHA022_CANONICAL_FORMULA_20160101`

Key proof paths:

- `objects/runtime_context/ultimate_run_report__ALPHA018_CANONICAL_FORMULA_20160101.json`
- `objects/runtime_context/ultimate_run_report__ALPHA019_CANONICAL_FORMULA_20160101.json`
- `objects/runtime_context/ultimate_run_report__ALPHA020_CANONICAL_FORMULA_20160101.json`
- `objects/runtime_context/ultimate_run_report__ALPHA022_CANONICAL_FORMULA_20160101.json`
- `objects/research_iteration_master/loop_research_brief__ALPHA019_CANONICAL_FORMULA_20160101__iter1.json`
- `objects/research_iteration_master/revision_council/ALPHA019_CANONICAL_FORMULA_20160101/revision_council_summary__ALPHA019_CANONICAL_FORMULA_20160101.json`
- `objects/research_iteration_master/revision_council/ALPHA019_CANONICAL_FORMULA_20160101/council_derivation_appendix__ALPHA019_CANONICAL_FORMULA_20160101.json`

## Summary

This Alpha018-022 run exposed two architecture-level gaps in the current Factor Forge Ultimate workflow.

First, the pipeline produced schema-valid `economic_hypothesis`, `math_hypothesis_candidates`, `mechanism_math_summary`, and `math_discipline_review` fields, but the contents were too generic and in at least one case materially inconsistent with the actual formula. The current implementation can pass validation while failing the intended research standard: the main researcher should derive a formula-specific mathematical hypothesis from the economic hypothesis, choose an appropriate model class, state the assumed stochastic process or conditional distribution, explain who pays, and provide falsifiable metric signatures.

Second, the Revision Council path was triggered but only through deterministic scaffold mode. It did not run true agentic council research, did not produce real agent results, and did not enter a multi-loop revision process. This conflicts with the desired Factor Forge Ultimate behavior: if a factor is not promoted and the evidence supports further research, the system should automatically enter agentic council, generate validated revision hypotheses, and continue bounded child-report revision loops until promotion, rejection, exhaustion, awaiting agent results, or the loop cap.

## What Happened

The user requested research on Alpha018, Alpha019, Alpha020, Alpha021, and Alpha022 using the latest Factor Forge Ultimate.

The assistant:

1. verified the installed `factor-forge-ultimate` skill matched the repo copy;
2. generated Step1 canonical formula intake for Alpha018, Alpha019, Alpha020, and Alpha022;
3. ran each executable case through the formal wrapper:

```bash
python3 scripts/run_factorforge_ultimate.py \
  --report-id <REPORT_ID> \
  --start-step 2 \
  --end-step 6 \
  --council-mode auto
```

4. blocked Alpha021 before formal execution because the production formula path cannot correctly evaluate the canonical conditional expression requiring `where` / `less` / `greater_equal`.

The wrapper passed for Alpha018, Alpha019, Alpha020, and Alpha022. No clean data rebuild command, search worker, official promotion, or forbidden writeback was observed.

## Observed Outcomes

| Factor | Step6 decision | Rank IC mean | G10 annual return | Cost-adjusted annual return | Main issue |
|---|---:|---:|---:|---:|---|
| Alpha018 | `iterate` | `0.047054` | `-6.69%` | `-54.86%` | IC positive but long side fails; best buckets are middle/high-middle, not G10 |
| Alpha019 | `iterate` | `0.028642` | `+8.81%` | `-14.53%` | Gross long side is weakly positive, but turnover/cost/drawdown break economics |
| Alpha020 | `reject` | `-0.007879` | `-36.70%` | `-95.09%` | Long side is catastrophic; reject is appropriate |
| Alpha022 | `iterate` | `0.012423` | `-4.28%` | `-41.80%` | Weak signal, long side fails after costs |

Alpha019 was the only case with plausible further research value, but even Alpha019 did not receive a sufficiently formula-specific automatic mechanism/math analysis.

## Issue 1: Mechanism Math Exists As Fields, But Not As Research

### User requirement

The intended Factor Forge Ultimate standard is not merely to copy the factor expression into a field called `math_hypothesis`.

The main researcher must:

1. start from an economic hypothesis;
2. identify the plausible payer or counterparty;
3. choose a mathematical model suitable for that economic mechanism, including but not limited to stochastic processes;
4. state the latent state, random object, target functional, information set, and conditional distribution;
5. show why the factor formula is an estimator of that latent state;
6. state what metric signature would confirm or falsify the hypothesis;
7. pass this formula-specific reasoning into Step6 and Council.

Expected structure:

```text
economic hypothesis
-> selected math model / stochastic process / distributional hypothesis
-> formula-specific estimator mapping
-> expected long-side metric signature
-> falsification and kill criteria
```

### Current artifact behavior

The artifacts contain the required fields, but the contents are generic.

For Alpha019, Step1 and Step2 produced broad fields like:

```text
macro_return_source = mixed
model_family = ranked_price_state_process
process_or_distribution_hypothesis =
  price contains a latent short-horizon state whose conditional drift depends on ranked recent price movement
```

Step6 then classified Alpha019 as:

```text
factor_family = liquidity_shock
mechanism_hypothesis =
  The factor appears to monetize a liquidity or turnover shock...
```

The `mechanism_math_summary` used a generic price-volume microstructure model:

```text
model_family = price_volume_microstructure
factor_as_estimator =
  rank and rolling dependence transforms estimate price-volume co-movement
observable_estimator =
  rolling rank covariance/correlation/dependence between price-level or return ranks and volume/liquidity ranks
```

This is materially wrong or at least not formula-specific for Alpha019.

Alpha019 formula:

```text
multiply(
  negate(sign(plus(minus(close, delay(close, 7)), delta(close, 7)))),
  plus(1, rank(plus(1, sum(returns, 250))))
)
```

This formula uses `close` and `returns`. It does not use `high`, `volume`, rolling covariance, or price-volume dependence. Any Step6 mechanism that describes Alpha019 as a price-volume dependence estimator is not a valid research explanation.

### Correct Alpha019 mechanism direction

A formula-specific economic and mathematical hypothesis for Alpha019 should look closer to this:

```text
Economic hypothesis:
  Long-term winners that suffer a short-horizon selloff may earn a liquidity
  provision or behavioral reversal premium.

Likely payer:
  short-horizon liquidity-demand sellers, panic sellers, redemption/rebalance
  sellers, or short-horizon extrapolators who sell into temporary pressure.

Price process:
  log P_i,t = M_i,t + U_i,t + epsilon_i,t

  M_i,t = slow trend / persistent 250-day winner state
  U_i,t = short-horizon temporary dislocation or liquidity shock
  epsilon_i,t = idiosyncratic noise

State dynamics:
  U_i,t+1 = rho U_i,t + eta_i,t+1, with 0 < rho < 1 under mean reversion

Formula estimator:
  rank(sum(returns, 250)) estimates high M_i,t
  -sign(close_t - close_{t-7}) estimates whether recent U_i,t is negative
  high score approximates high M_i,t and negative U_i,t

Target functional:
  E[r_i,t+1:t+h | M_i,t high, U_i,t negative]

Expected metric signature:
  G10 should earn positive long-side return after cost;
  turnover should be consistent with the decay horizon of U;
  long-side drawdown/recovery should be acceptable;
  economics should not rely on the short leg or long-short diagnostic.
```

This is the level of reasoning the skill should force before Step6/Council.

### Why this matters

The current validator can pass while the research conclusion is under-derived or wrong. This creates a false sense of rigor:

- The schema says mechanism/math exists.
- The text is plausible-sounding.
- But the actual formula was not analyzed at the right level.

This is especially dangerous for Alpha101-style formulaic factors because many formulas share superficial operator families while having very different economic hypotheses.

## Issue 2: Council Was Triggered, But Only As Scaffold

### User requirement

The desired behavior is:

```text
not promoted
-> automatic agentic council
-> role-specific research and derivations
-> validated revision hypothesis
-> child report revision loop
-> repeat until promote / reject / exhausted / awaiting_agent_results / max loops
```

The Council should be a real research engine, not a deterministic placeholder.

### Current proof behavior

For Alpha019, wrapper proof shows:

```text
requested_mode = auto
effective_mode = scaffold
executor = none
dispatch_adapter = none
selection_source = deterministic_scaffold
deterministic_fallback_used = true
valid_agent_results = 0
execution_allowed_by_default = false
human_approval_required = true
```

The wrapper did run Council-related commands:

```text
build_revision_council_packet
run_revision_council
merge_revision_council
build_council_derivation_appendix
attach_revision_council_to_step6
validate_step6_after_council_attach
```

But this was deterministic scaffold output. It did not run true agentic Council, did not collect agent results, and did not continue to a revision loop.

### Current skill / implementation conflict

The current skill text says:

- formal research should prefer agentic council reasoning when the environment supports it;
- deterministic local council is only scaffold/smoke/fallback;
- default research objective is to continue through guarded child-report revision loops until a stop condition is reached.

However, the current wrapper behavior is:

- `--council-mode auto` silently falls back to scaffold;
- `--council-mode agentic --agentic-council-executor real_agent` is explicitly not implemented;
- `dispatch_manifest` can stop at `awaiting_agent_results`, but does not itself complete agentic research;
- `run_factorforge_ultimate_loop.py` can continue only when a validated `handoff_to_step3b__<report_id>.json` explicitly authorizes a child revision;
- current Council attachment disables provisional Step3B handoff and leaves advisory-only output.

Therefore the current system cannot satisfy the requested closed-loop behavior by default.

## Required Architecture Changes

### A. Mechanism and math hypothesis quality gate

Add a strict quality gate before Step6 can treat mechanism/math output as research-valid.

Minimum required fields should include:

```json
{
  "economic_hypothesis": {
    "return_source_class": "risk_premium | information_advantage | market_structure_arbitrage | mixed",
    "payer_or_counterparty": "...",
    "why_they_pay": "...",
    "necessary_market_structure": "..."
  },
  "math_hypothesis": {
    "selected_model_family": "...",
    "why_this_model_not_generic_template": "...",
    "random_object": "...",
    "latent_state": "...",
    "process_or_distribution": "...",
    "target_functional": "...",
    "formula_as_estimator": "...",
    "expected_metric_signature": "...",
    "falsification_tests": [],
    "kill_criteria": []
  }
}
```

The `process_or_distribution` field should not be allowed to merely restate the formula. It must state an actual model or distributional assumption when the economic hypothesis implies one, for example:

- transient-impact process;
- state-space model;
- jump process;
- stopping-time or threshold model;
- tail-risk distribution;
- cointegration / mean-reversion process;
- copula / rank-dependence model;
- projection / residualization model;
- scaling law or dimensional relation.

### B. Formula-field consistency validator

Add a validator that checks mechanism text against formula fields and operators.

Examples:

- If formula has no `volume`, Step6 should not claim the factor is a price-volume dependence estimator unless it explicitly justifies the absence of volume.
- If formula has no `high`, mechanism text should not refer to high-volume covariance.
- If formula uses `sign`, Step6 should discuss discontinuity and turnover implications.
- If formula uses raw additive terms with mixed dimensions, Step6 should discuss normalization or dimension mismatch.
- If formula uses a short rolling correlation/delta, Step6 should discuss estimator noise and sampling error.

This validator does not need to understand all finance. It can start with field/operator consistency and a required explanation when mechanism text introduces variables absent from the formula.

### C. Formula-specific derivation requirement

For each formal factor, Step6 should produce a public derivation record before Council:

```text
1. Parse formula into economic components.
2. Identify which component estimates which latent state.
3. State the assumed process/distribution.
4. Derive expected sign and monotonicity.
5. Compare expected signature with Step4 evidence.
6. State revision implication or kill condition.
```

For Alpha019, the derivation should identify:

- `rank(sum(returns,250))` as slow winner/trend state;
- `-sign(close_t - close_{t-7})` as short-horizon reversal state;
- the near-duplication of `minus(close, delay(close,7))` and `delta(close,7)`;
- the discontinuous `sign` transform as a turnover driver;
- cost-adjusted failure as the main monetization problem.

### D. Council mode default should not silently downgrade

Change formal research behavior:

```text
if formal_research and council needed:
    if agentic council available:
        run agentic council
    elif dispatch mode available:
        emit awaiting_agent_results
    else:
        BLOCK or mark outcome as scaffold_only_not_formal_council
```

`auto` should not silently become `scaffold` for formal research unless the user explicitly requests scaffold or smoke.

### E. Agentic Council contract

Required behavior when `decision=iterate` and evidence is not blocked:

1. Build council packet.
2. Build agentic taskbook.
3. Dispatch role-specific tasks.
4. Stop at `awaiting_agent_results` if the runtime cannot complete them inline.
5. Validate returned agent results.
6. Merge only valid derivation-backed proposals.
7. Produce a final revision strategy.
8. Generate a child revision handoff only after validator and human approval.

If real subagents are unavailable, the run should report that state explicitly. It should not use deterministic scaffold as a substitute for formal agentic research.

### F. Multi-loop revision orchestrator

`run_factorforge_ultimate_loop.py` should be the default path for full research loops when the objective is not just one pass.

Expected loop:

```text
root report
-> wrapper Step2-6
-> agentic council
-> validated revision handoff
-> child report id: {parent}__LOOPNN__{revision_id}
-> wrapper Step3B/4/5/6 or Step2-6 as required
-> repeat until stop condition
```

Stop conditions:

- promoted;
- rejected / kill;
- exhausted / no material improvement path;
- awaiting agent results;
- evidence/prewrite blocked;
- max loop count reached.

The loop proof should make clear whether it stopped because of true exhaustion or because the system was awaiting agentic Council outputs.

## Acceptance Tests

### Mechanism math acceptance

Create a smoke or real-case test using Alpha019:

```text
Formula has no volume.
Step6 must not classify it as price-volume dependence unless explicitly justified.
Step6 must identify the 250-day trend state and 7-day short-horizon reversal state.
Step6 must discuss sign discontinuity and turnover.
Step6 must state a stochastic process or conditional distribution tied to the economic mechanism.
```

The test should fail if `mechanism_math_summary` contains generic `price-volume dependence estimator` for Alpha019.

### Council acceptance

Run:

```bash
python3 scripts/run_factorforge_ultimate_loop.py \
  --report-id ALPHA019_CANONICAL_FORMULA_20160101_AGENTIC_LOOP_TEST \
  --start-step 2 \
  --max-loops 10 \
  --council-mode agentic \
  --agentic-council-executor dispatch_manifest \
  --agentic-dispatch-adapter codex
```

Expected if inline real agents are not available:

```text
final_outcome = awaiting_agent_results
agentic_taskbook exists
dispatch_manifest exists
manual/codex assignments exist if adapter supports them
no deterministic scaffold is presented as formal Council
no generated_code mutation
no clean data mutation
no official promotion
```

Expected when agentic results are available:

```text
valid_agent_result_count > 0
all accepted proposals have derivation_record
final_revision_strategy.source = revision_council
child revision handoff exists only after approval/validator
loop proceeds to child report id
```

### Loop acceptance

Use a controlled fixture or small report-local case where Council returns a valid revision handoff.

Expected:

```text
ultimate_loop_report__<root>.json records multiple loop items
each loop calls scripts/run_factorforge_ultimate.py
child report ids preserve parent lineage
forbidden side effects remain false
stop reason is explicit
```

## Recommended Priority

P0:

- Prevent formal research from silently treating deterministic scaffold as agentic Council.
- Add clear outcome labels: `scaffold_only`, `awaiting_agent_results`, `agentic_completed`, `loop_exhausted`.
- Add field/operator consistency checks for mechanism math.

P1:

- Implement formula-specific mechanism derivation requirements.
- Make Alpha019 a regression test for non-volume formula misclassified as price-volume.
- Ensure Council packet includes the formula-specific derivation, not just generic Step6 text.

P2:

- Complete real agentic Council execution or codex/manual dispatch finalization.
- Allow loop runner to continue through approved child revisions under strict validator and human approval gates.

## Bottom Line

The Alpha018-022 run should be recorded as:

```text
Formal Step2-6 execution succeeded for Alpha018/019/020/022.
Alpha021 correctly blocked due to unsupported conditional operators.
Step6 mechanism/math artifacts were schema-valid but not research-valid enough.
Council ran only deterministic scaffold, not true agentic Council.
The run did not satisfy the desired full Factor Forge Ultimate agentic multi-loop research contract.
```

