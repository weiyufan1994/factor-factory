---
name: factor-forge-step6
description: Step 6 of the Factor Forge pipeline — research reflection, library writeback, and loop control. Consumes Step 4/5 evidence, writes experiment/library/knowledge records, and decides whether to promote, iterate, or reject a factor.
---

# Factor Forge Step6 Legacy Operations Reference

> Compatibility boundary: this file documents historical schemas and operating
> modes. It is not the current math authority. For new research use
> `mechanism_conditioned_measurement_program_v1`. Historical random-object,
> stochastic-benchmark, unit/dimension, or claim-stage fields are validated only
> when an upstream artifact already contains them; never synthesize them as
> universal requirements.

## What This Skill Does

Step 6 is the **research reflection + loop controller** layer.
It does not generate raw metrics itself. Instead it:
1. reads Step 4 / Step 5 evidence,
2. retrieves similar historical cases from the structured library,
3. judges the factor,
4. writes back experiment/library/knowledge records,
5. and decides whether Step 3B should be modified and rerun.

## Inputs

- `factorforge/objects/factor_run_master/factor_run_master__{report_id}.json`
- `factorforge/objects/factor_case_master/factor_case_master__{report_id}.json`
- `factorforge/objects/validation/factor_evaluation__{report_id}.json`
- required for formal runs: `factorforge/objects/handoff/handoff_to_step6__{report_id}.json`
- legacy debug-only fallback: `factorforge/objects/handoff/handoff_to_step5__{report_id}.json` with `FACTORFORGE_ALLOW_LEGACY_STEP6_HANDOFF=1`; this path cannot be used to claim official completion or promotion
- optional backend payloads under `factorforge/evaluations/{report_id}/{backend}/`

## Outputs

- `factorforge/objects/research_iteration_master/research_iteration_master__{report_id}.json`
- mandatory user-facing loop research brief:
  - `factorforge/objects/research_iteration_master/loop_research_brief__{report_id}__iter{iteration_no}.md`
  - `factorforge/objects/research_iteration_master/loop_research_brief__{report_id}__iter{iteration_no}.json`
- `factorforge/objects/factor_library_all/factor_record__{report_id}.json`
- optional `factorforge/objects/factor_library_official/factor_record__{report_id}.json`
- one or more knowledge records under `factorforge/objects/research_knowledge_base/`
- optional `factorforge/objects/handoff/handoff_to_step3b__{report_id}.json`
- optional `factorforge/objects/research_iteration_master/revision_proposal__{report_id}.json`
- optional `factorforge/objects/research_iteration_master/program_search_plan__{report_id}.json`
- optional `factorforge/objects/research_iteration_master/search_branch_ledger__{report_id}.json`
- optional `factorforge/objects/research_iteration_master/search_branch_result__{report_id}__{branch_id}.json`
- optional `factorforge/objects/research_iteration_master/program_search_merge__{report_id}.json`

For formal factor research, replace the legacy `factorforge/...` prefix above with
`<factor_workspace>/...`. Step6/Council/knowledge writes must stay inside the
factor workspace by default. Repo-root `knowledge/因子工厂` is an explicit
export/vault target only and requires an export manifest; it is not a production
default write path.

## Core rules

1. Step 6 is responsible for reflection and decision, not raw metric generation.
2. Every attempt must enter the full experiment library.
3. Only explicitly promoted factors may enter the official library.
4. If the decision is `iterate`, Step 6 must point back to Step 3B with explicit modification targets.
5. Step 6 must preserve failed lessons, not only successful ones.
6. Step 6 should prefer structured retrieval before proposing modifications and should surface similar historical cases in the proposal.
7. Step 6 must emit a concrete `research_memo`: formula understanding, return-source hypothesis, metric interpretation, evidence quality, failure/risk analysis, decision rationale, and next research tests.
8. `research_memo` must include `math_discipline_review`: random object, target statistic, information-set legality, spec stability, signal-vs-portfolio gap, revision operator, generalization argument, overfit risk, and kill criteria.
9. `research_memo` must include `learning_and_innovation`: transferable patterns, anti-patterns, similar-case lessons, innovative idea seeds, and reuse instructions for future agents.
10. `research_memo` must include `experience_chain`, `revision_taxonomy`, `program_search_policy`, and `diversity_position`.
11. Do not use or emit `dd_view_edge_trade`; that belongs to individual-stock diligence, not Factor Forge.
12. Backend success is not enough for official promotion. If IC/group diagnostics are positive but native portfolio/account evidence is weak, Step 6 should usually choose `iterate` and explain the monetization gap.
13. Step 6 is the research analyst agent of the pipeline. It must behave like an independent PM/researcher: form a thesis, challenge it, compare it with prior cases, preserve lessons, and hand Step 3B a concrete revision brief when iteration is warranted.
14. Step6 may borrow search methods from program-level factor mining: genetic formula mutation, Bayesian parameter search, reinforcement-learning policy learning, and multi-agent parallel exploration.
15. Reinforcement learning is not the first automatic tool for a cold-start factor; treat it as an advisory policy learner until enough iteration trajectories exist in the knowledge base.
16. If `decision=iterate`, Step6 must propose exploration branches and keep a human approval gate before any code modification.
17. `validate_step6.py` is a strict gate. A Step6 output that lacks a substantive `research_memo`, `math_discipline_review`, `learning_and_innovation`, or `program_search_policy` must fail validation even if all files exist.
18. If `factorforge/objects/research_iteration_master/researcher_memo__{report_id}.json` exists, Step6 must preserve it under `research_memo.researcher_agent_memo`.
19. If `factorforge/objects/research_journal/research_journal__{report_id}.json` exists, Step6 must preserve it under `research_memo.researcher_journal`.
20. Normal research validation requires external researcher context: either a full-workflow researcher journal or a Step6 researcher memo. Pure script-only Step6 analysis is not sufficient for real factor research.
21. `validate_step6.py` must report `PASS|WARN|BLOCK`; `BLOCK` means the factor cannot claim promote, archive final, or closed-loop completion.
22. `information_set_legality=illegal*`, missing `kill_criteria`, missing `reuse_instruction_for_future_agents`, or unknown overfit risk under `promote_official` are governance blocks, not cosmetic validation failures.
23. Program search is a supplement to researcher judgment, not a replacement. Search branches must start from Step6 return-source analysis, market-structure hypothesis, knowledge-base priors, and falsification tests before any GA/Bayesian/multi-agent execution.
24. Current mandate is long-only. Step6 must not use short selling, long-short spread, or direct decile trading as an adoption basis.
25. Decile/quantile outputs are diagnostics only: use them to inspect monotonicity and top-group long-side behavior, never as a proposed trading instrument.
26. Revision must modify the factor expression and Step3B implementation itself. Do not “fix” a weak factor by changing portfolio expression, short-leg exposure, rebalance mechanics, or decile trading.
27. Official promotion requires risk-adjusted positive long-side evidence. If a factor is strictly monotonic but the high-score long side does not make money with acceptable Sharpe/drawdown/recovery, Step6 must choose `iterate` or `reject`, not `promote_official`.
28. Preferred revision direction is economic linearity: make higher factor values correspond more directly and monotonically to the economic state expected to earn risk-adjusted long-side returns.
29. Treat every factor like a business: long-side return is revenue, trading COGS defaults to `turnover * 0.3%`, volatility is operating instability/risk-capital pressure, `-0.5 * sigma^2` is volatility drag on geometric growth, max drawdown is capital impairment, and recovery time is payback/depreciation. Risk budget follows Sharpe, drawdown, recovery, capacity, and confidence. However, trading cost is a tradability and promotion gate, not a one-vote veto on whether the factor contains useful pre-cost information.
30. Default Step6 promotion objective is `long_side_risk_adjusted_alpha`: candidate Sharpe >= `0.50`, official Sharpe >= `0.80`, max drawdown no worse than `-35%`, and recovery days preferably <= `252`.
30a. For current minute-factor research, Step6 must preserve the Step4
`research_window_contract`: in-sample ends at `2025-07-11` by default and later
data is OOS holdout. OOS evidence may diagnose degradation or robustness, but
Step6 and Council must not repeatedly fit revisions on OOS metrics. If Step4
blocked because `minute_derived_flow_state_v1` is missing, incomplete, or
identity-mismatched, treat that as a production-path infrastructure BLOCK, not a
mechanism reject.
30b. Step6 must apply a factor-complexity penalty when comparing revisions. Do
not enforce an arbitrary hard cap on primitives or math tools; instead score
each candidate by OOS long-side edge, residual IC, risk/cost evidence, and a
complexity cost for added primitives, interactions, free parameters, data
dependencies, and nonlinear gates:

$$
\mathcal{J}(f)
=
\mathrm{OOSLongEdge}(f)
+ \alpha IC_{\mathrm{resid}}(f)
- \lambda_C \mathrm{Complexity}(f)
$$

Every added term must name the economic state or mathematical object it
represents, such as drift, volatility, barrier distance, hitting probability,
occupation mass, latent state, or constraint pressure. If added complexity only
improves in-sample raw IC, or cannot be linked to OOS long-side/residual
evidence, Step6 must classify it as overfit risk and prefer a simpler
expression.
30c. Before rejecting a high-turnover factor, Step6 must complete a pre-cost
information assessment. It must classify return source as `risk_premium`,
`information_advantage`, `constraint_driven_arbitrage` /
`market_structure_arbitrage`, or `mixed`; state the economic logic and profit
payer; inspect IC/rank IC, grouped gross returns, long-end gross return, and
Fama-MacBeth or cross-sectional regression evidence where available; assess
monotonicity stability across full IS, IS subsamples, OOS diagnostics,
liquidity buckets, and regimes; and attribute volatility/max drawdown to
continuous sigma exposure, jump/tail events, regime transitions, liquidity
crunch, crowding, or implementation noise. Cost can block official promotion,
but if pre-cost premium and mechanism evidence are real, preserve the factor as
`feature_candidate`, `state_descriptor`, `needs_horizon_repair`, or
`execution_research_needed` rather than calling it no-information.
30d. Evidence standards depend on return source. `risk_premium` requires strict
monotonicity and Fama-MacBeth / cross-sectional regression support, because the
premium should be priced broadly and stably. `information_advantage` may have
weaker monotonicity, but the long end must show significant gross and
risk-adjusted return. `constraint_driven_arbitrage` requires clear
constraint/payer logic and evidence concentrated where the constraint binds.
31. Every successful formal Step6 loop must write `loop_research_brief__<report_id>__iter<n>.md/json` and link it from `research_iteration_master.loop_research_brief`. The brief must answer economic interpretation, metrics/chart evidence, metric analysis, knowledge comparison, next research direction, and final loop conclusion. Missing brief, missing core metrics, missing required chart keys, or long-short chart evidence not labeled `diagnostic_only` is a validation block.
32. Step6 must carry the `mechanism_math_contract` into `mechanism_analysis`,
revision hypotheses, and the loop research brief. The math contract is an
explanatory and revision-discipline layer only: it must not replace Step4/5
evidence, bypass provenance gates, justify promotion on its own, or authorize
canonical Step3B changes without the existing loop authorization.
33. For `math_model_status=specified`, the contract must state a testable
process hypothesis, latent state, observable estimator, conditional
distribution hypothesis, relationship shape, metric-signature match, and
mechanism falsification tests. Price-volume covariance/correlation/rank-
dependence formulas must be treated as `price_volume_microstructure` unless
the formula itself contains explicit projection/residualization/neutralization
operators.
34. If human mechanism context exists under
`objects/research_iteration_master/revision_council/<report_id>/supplemental_context/`
or `knowledge/因子工厂/知识库/*MECHANISM*`, the Revision Council packet must
include it and propagate it into agentic taskbooks.
35. Step6 mechanism analysis must include a formula-specific public derivation:
economic hypothesis -> payer/constraint -> selected baseline mathematical model
-> formula-specific model mutation -> observable estimator mapping -> expected
metric signature and falsification. Generic mechanism text that contradicts
formula fields or operators is invalid; for example, a formula with no volume
input must not claim price-volume dependence unless a structured justification
is present and validated.
35a. Step6 analysis and Revision Council must keep the same research rigor as
Step1/Step2: economic_hypothesis selects the primary mathematical model after an
open tool search. DCF/residual income, accounting identities, stochastic
processes, linear algebra, optimization, information theory, spectral/
functional methods and causal/placebo tests are used only when justified. The
selected object must map to a tradeable value, payoff, price gap or return;
stochastic and dimensional audits are optional, mechanism-specific tools.
Council proposals must state which economic hypothesis, primary mathematical
model, observable estimator, benchmark test, and falsification signature they
are revising. They must also state the complexity delta: which terms, gates,
parameters, interactions, or data dependencies are added or removed, why the
expected marginal benefit is worth the complexity penalty, and what evidence
would remove the added complexity in the next loop.
Step6 `mechanism_analysis` must include `research_equation_review` with metric
links for rank IC, long-side return, cost-adjusted return, turnover,
volatility drag, max drawdown, recovery days, and drawdown geometry when
available. Revision Council proposals must include
`research_equation_revision` and target the failed equation component.
Before writing Step6 final recommendations, use the Dirac-Style Step6 Council Prompt in references/prompts.md. When asked for new ideas, use the Equation-To-Factor Discovery Prompt.
When a report suggests a market structure relation, first identify the research
equation or quasi-equation, then derive one or more observable detector
candidates. A detector candidate is not an approved factor. It must state
source_equation_id, observable_inputs, measurement_equation,
market_outcome_projection_terms, expected_metric_signature,
expected_cost_risk_profile, falsification_tests, and branch_action.
No equation-derived candidate may launch Step2/Step3/Step4 automatically. Candidate packets are advisory until the existing run loop or a human-approved branch request starts a formal factor run.
36. Before any Revision Council packet or agentic dispatch is built, Step6 must
write a current-agent mechanism questionnaire:
`objects/research_iteration_master/main_agent_mechanism_questionnaire__<report_id>.json`
and `.md`. The agent currently invoking the skill (Codex, Bernard, Humphrey, or
another runtime main agent) must then answer the questionnaire as a free-form
main-agent mechanism memo:
`objects/research_iteration_master/main_agent_mechanism_memo__<report_id>.json`
and `.md`. The Python layer may extract formula facts and validate the answer,
but it must not silently replace the main agent with a deterministic mechanism
template. If the memo is missing, Step6 must pause with
`AWAITING_MAIN_AGENT_MECHANISM_MEMO` before final Step6 writeback or Step3B
handoff exposure. If the memo is present but generic, canonical-write-enabled,
execution-enabled, formula-detached, or operator-contradictory,
`validate_step6.py` must block it.
37. Advisory Council revision law is not executable by itself. After Council
finalization and before any child Step3B materialization, the current main agent
must write an orchestration synthesis:
`objects/research_iteration_master/revision_council/<report_id>/main_agent_council_synthesis__<report_id>.json`
and `.md`, contract version `factorforge_main_agent_council_synthesis_v1`.
This synthesis must select one executable revision law and include
`selected_revision.law_id`, `selected_revision.child_formula`,
`expected_metric_signature`, `falsification_tests`, and `kill_criteria`.
Council templates, generic modification text, or a `handoff_to_step3b` without
this synthesis are advisory-only and must not be materialized. The materializer
must BLOCK with a precise token instead of inferring a fallback such as
`negate(parent_formula)`.
After the synthesis is written and approved, run
`skills/factor-forge-step6/scripts/approve_main_agent_council_synthesis.py`.
That bridge validates the synthesis, records the approval artifact, updates
`final_revision_strategy.loop_authorization=approved_for_step3b_handoff`, writes
the active `handoff_to_step3b`, refreshes the loop brief Council section, and
runs `validate_step6.py`. Without this approval bridge, a completed Council plus
synthesis remains advisory and the ultimate loop must not materialize a child.
38. When the ultimate loop receives an approved Step3B handoff and a valid main
agent Council synthesis, Step6 child materialization must write
`objects/research_iteration_master/executable_revision_spec__<child_report_id>.json`
before the child Step3B run. The spec must contain implementation mode,
parent/child formulas or direct-code law statements, formula/code-law hashes,
selected revision law ids, expected metric signature, falsification tests, kill
criteria, the source synthesis path/hash, and write/execute permissions.
Non-audit child revisions must change the formula hash or code-law hash;
otherwise the materializer or Step3B must BLOCK instead of rerunning the parent
implementation.
The child materializer must also write a child-local
`qlib_adapter_config__<child_report_id>.json`: copy and re-identify the parent
adapter config when qlib is supported, or write
`qlib_native_status=not_applicable` with reason
`direct_code_derived_state_not_supported_by_qlib` when the child is a
direct-code derived-state law that qlib should skip. Missing qlib config is a
framework defect, not a valid child qlib failure.
38a. Direct-code and native intraday revisions are valid Step6 outputs, but only
as executable mutation contracts. If the parent factor is `direct_code` or
`hybrid`, the main-agent Council synthesis must preserve that mode unless it
explicitly proves an operator conversion with Formula-IR parity. A direct-code
child spec must include `direct_code_revision_contract`: target function or
block, required fields, information-set/timing contract, state features,
formula law, code mutation scope, and code-law hash. Step6 must not coerce an
intraday moneyflow/state-space revision into an unrelated parseable operator
formula such as `rank(close)`.
39. Child materialization must copy report-local Step3A daily snapshots
(Parquet preferred, CSV audit when present) into the child run directory and
rewrite child data-prep paths accordingly. A child `--start-step 3b` run must
never depend on the parent report id's local snapshot path.
40. When a child revision reaches Step6, the next Revision Council packet must
include `prior_revision_memory`: parent report id, child report id,
parent/child formula hashes, executable derivation rule, parent-vs-child metric
deltas, and an outcome of `falsified`, `improved`, or `inconclusive`. If the
prior executable revision worsened key evidence, agentic task packets must
require `prior_revision_outcome_review` and `repeated_revision_guard`, and must
forbid repeating the falsified executable revision rule or re-creating an
ancestor formula hash. A Council that ignores the previous failed child run is
not allowed to authorize another executable loop.
41. If a completed real-agent Council collection unanimously recommends
terminal rejection and no main-agent synthesis selects an executable child
formula, Step6 may close the branch through
`skills/factor-forge-step6/scripts/close_terminal_council_rejection.py`. That
bridge must write
`objects/research_iteration_master/revision_council/<report_id>/terminal_council_rejection__<report_id>.json`,
set the research iteration decision to `reject`, keep
`final_revision_strategy.loop_authorization=advisory_only`, keep active
`handoff_to_step3b` absent, refresh the loop brief Council section, and rerun
`validate_step6.py`. Terminal rejection is a stop condition, not permission to
materialize another child.
42. Council synthesis may be prepared in multi-branch form before multi-child
execution is attempted. The artifact is
`objects/research_iteration_master/revision_council/<report_id>/main_agent_multibranch_synthesis__<report_id>.json`
and `.md`, contract version `factorforge_main_agent_multibranch_synthesis_v1`.
It is an orchestration contract: it must not materialize children by itself, and
must not write clean data, official records, or generated code. Validate it with
`skills/factor-forge-step6/scripts/validate_main_agent_multibranch_synthesis.py`.
The validator requires exactly one exploit branch, at most two exploration
branches, non-duplicate child formula hashes, no parent/forbidden formula
repeats, no repeated falsified revision law, and a real mechanism difference for
each exploration branch.
43. The ultimate loop may consume a validated multi-branch synthesis through the
guarded production bridge. First,
`approve_main_agent_multibranch_synthesis.py` writes the approval artifact and
per-branch single-synthesis adapters, then
`materialize_step6_multibranch_children.py` invokes the existing child
materializer once per selected branch. This P2 bridge must preserve safe
permissions, verify the source synthesis hash, preserve child-local Step3A
snapshots, and write branch context into each child executable revision spec.
44. After more than one child has run, the ultimate loop must build
`objects/research_iteration_master/branch_comparison__<parent_report_id>__loopNN.json`
and `.md` with `build_branch_comparison.py`, then validate it with
`validate_branch_comparison.py`. The comparison must cover every sibling child,
parent-vs-child metric deltas, branch outcome, and the selected next-parent
child. If a multi-branch child has `branch_group_id` / `sibling_branch_count>1`
but no valid comparison exists, `build_revision_council_packet.py` must BLOCK
with `BLOCK_FACTORFORGE_BRANCH_COMPARISON_MISSING`. When the comparison exists,
the next Council packet must include `sibling_branch_memory` so the selected
exploit path retains exploration evidence and cannot repeat falsified sibling
laws or formula hashes without explicit new evidence. This path does not write
clean data or official records, and generated code writes are limited to the
child reports that are explicitly materialized and executed.
45. Knowledge writeback is a continuation gate, not an end-of-project courtesy.
Before Step6 authorizes another loop, branch, child materialization, portfolio
policy test, or formal follow-on run, it must preserve the current round's
knowledge in the research journal, research knowledge base, or a human-readable
operations/research note. This record must include evidence paths, factor/run
identity, economic hypothesis, math mechanism, executable formula or law id,
universe, cost policy, IS/OOS boundary, key metrics, what improved, what failed,
what was falsified, forbidden repeats, and next questions. Runs whose latest
evidence only lives in `/tmp`, worker scratch directories, temporary S3
prefixes, or untracked scripts are not fully deposited and must be marked as
such before the agent continues.
46. Formal Step6 must run a research-quality gate in addition to artifact
validation. Step6 may be engineering-complete but research-quality-blocked. The
research memo, researcher memo, or Council synthesis must declare
`mechanism_claim_level`, `evidence_tier_map`, `economic_payer_hypothesis`,
`math_object_contract`, `component_validation`, `falsification_design`, and
`overclaim_guard`.
47. `mechanism_claim_level` must be one of `none`, `narrative_only`,
`math_framed`, `metric_consistent`, `component_validated`,
`stochastic_validated`, or `payer_validated`. Step6 must not promote a
`narrative_only`, `math_framed`, or merely `metric_consistent` mechanism into a
validated research claim.
48. If Step6 or Council uses stochastic-process language, it must declare
`stochastic_process_status=not_used|framing_only|validated`. Validated status
requires state space, conditional return distribution, transition persistence
or half-life, barrier/tail-risk test, and revision state-information delta.
Otherwise the claim is framing only.
49. If Step6 or Council claims Dirac-style induction, symbolic law discovery,
or reusable atomic law, it must reference
`dirac_induction_memo__<report_id>.json/md` with atomic state, invariant,
estimator law, deleted-information audit, at least three limiting cases,
falsification design, reuse boundary, and overclaim guard.
50. Every evidence artifact used in Step6 must be classified as
`promotion_gate_evidence`, `robustness_evidence`, `diagnostic_evidence`,
`window_contract_evidence`, or `exploratory_evidence`. Promotion decisions may
use only promotion-gate evidence. Supplemental window or diagnostic evidence
cannot overwrite weak or missing Step4 promotion evidence.
51. Step6 must close the universal `research_quality_gate`, not merely produce
process-complete artifacts. The final memo must restate the
`economic_mechanism_contract`, `mathematical_object_contract`,
`alias_elimination_matrix`, `falsification_plan`, `claim_level_assessment`, and
`reviewer_attack_memo`, then mark which parts are proven, weakened, rejected,
or still missing. If the run only reached `narrative_only`, `math_framed`, or
`metric_candidate`, Step6 must not recommend promotion and must not send a
Step3B revision as if the mechanism were validated. If the run reached only
`metric_consistent`, it may recommend further component, alias, stochastic, or
payer validation, but the final label remains `research_quality_blocked` for
promotion.

## Research Analyst Standard

Treat Step 6 as a durable research brain, not a logger.
Every serious Step6 run should answer:

1. What is this factor trying to monetize: risk premium, information advantage, constraint-driven arbitrage, or a mixture?
2. Why should the other side behave predictably, and what objective constraints make the pattern repeatable?
3. Do the Step4 metrics support the return-source thesis, or only a fragile implementation?
4. Is this factor reusable enough for a library, or still a local feature experiment?
5. What exactly should be learned, written to the knowledge base, and reused by future agents?
6. If iterating, what should Step3B change and why is that change economically/research-wise justified?
7. What mathematical object and target statistic does the factor claim to predict?
8. What transferable pattern, anti-pattern, or innovative idea seed should future agents reuse?
9. Which search mode is appropriate next: genetic expression mutation, Bayesian parameter search, mechanism challenge, or multi-agent parallel exploration?
10. Is the next loop exploiting a promising current thesis, exploring a nearby family, or both?

## Recommended execution chain

```bash
cd /home/ubuntu/.openclaw/workspace
python3 repos/factor-factory/scripts/run_factorforge_ultimate.py --report-id <report_id> --start-step 5 --end-step 6
python3 skills/factor-forge-step6/scripts/build_program_search_plan.py --report-id <report_id>
python3 skills/factor-forge-step6/scripts/validate_program_search_plan.py --report-id <report_id>
# after the user approves a branch direction:
python3 skills/factor-forge-step6/scripts/approve_program_search_branch.py --report-id <report_id> --branch-id <branch_id> --decision approve --notes '<human notes>'
python3 skills/factor-forge-step6/scripts/prepare_approved_search_branch.py --report-id <report_id> --branch-id <branch_id>
# audit branches may be executed by the built-in local evidence-chain auditor:
python3 skills/factor-forge-step6/scripts/run_program_search_audit_worker.py --report-id <report_id> --branch-id audit_evidence_and_thesis
# after approved branch work is completed:
python3 skills/factor-forge-step6/scripts/record_search_branch_result.py --report-id <report_id> --branch-id <branch_id> ...
python3 skills/factor-forge-step6/scripts/validate_search_branch_result.py --report-id <report_id> --branch-id <branch_id>
python3 skills/factor-forge-step6/scripts/merge_program_search_branches.py --report-id <report_id>
```

Direct `run_step6.py`, `validate_step6.py`, and `run_step6_controller.py` calls are debug-only. Official agent runs must produce the `ultimate_run_report__<report_id>.json` proof emitted by `scripts/run_factorforge_ultimate.py`.

Deep researcher-agent path:

```bash
python3 skills/factor-forge-researcher/scripts/build_researcher_dossier.py --report-id <report_id>
# researcher agent updates factorforge/objects/research_journal/research_journal__<report_id>.json
python3 skills/factor-forge-step6-researcher/scripts/build_researcher_packet.py --report-id <report_id>
# researcher agent writes factorforge/objects/research_iteration_master/researcher_memo__<report_id>.json
python3 repos/factor-factory/scripts/run_factorforge_ultimate.py --report-id <report_id> --start-step 6 --end-step 6
python3 skills/factor-forge-step6/scripts/build_program_search_plan.py --report-id <report_id>
python3 skills/factor-forge-step6/scripts/validate_program_search_plan.py --report-id <report_id>
```

`--report-id` remains accepted for legacy/manual debugging, but official agent-led runs should use `--manifest` so Step6 consumes the exact Step5 evidence bundle selected by the orchestrator.

## Program Search Engine V1

`build_program_search_plan.py` converts Step6 researcher judgment into an approval-gated search plan. It does not run algorithms, modify Step3B, or touch shared data.

The plan must keep the research hierarchy:

1. Step6 explains return source: `risk_premium`, `information_advantage`, `constraint_driven_arbitrage`, or `mixed`.
2. Step6 states the market-structure / objective-constraint mechanism and expected failure regimes.
3. Step6 retrieves prior knowledge and anti-patterns.
4. Only then may the plan propose search branches.

Default branch roles:

- `audit`: check whether the iterate decision is caused by evidence, data, contract, or implementation bugs.
- `exploit`: Bayesian-style local parameter search that preserves the current thesis.
- `explore`: genetic-style nearby formula mutation that must preserve or explicitly challenge the thesis.
- `macro`: challenge or sharpen the return-source / market-structure hypothesis.

Every branch must carry a research question, hypothesis, knowledge priors, success criteria, falsification tests, budget, hard guards, and expected outputs. Human approval is required before any branch executes code changes.

Branch execution reports are recorded with `record_search_branch_result.py`. A branch result must include its research assessment, falsification result, overfit assessment, evidence or failure signature, and recommendation. `merge_program_search_branches.py` only writes an advisory merge report; it never updates Step3B or canonical code by itself.

`approve_program_search_branch.py` and `prepare_approved_search_branch.py` create the safe handoff for Humphrey/Bernard. The taskbook gives each branch an isolated write scope under `factorforge/research_branches/{report_id}/{branch_id}/` and explicitly forbids editing canonical Step3B handoffs or shared clean data.

`run_program_search_audit_worker.py` is the first concrete branch worker. It does not need external web research. It checks local Factor Forge evidence: Step4/5/6 objects, handoffs, backend payloads, first-run outputs, referenced data/code contracts, information-set legality, and legacy out-of-contract fields. It writes a normal `search_branch_result` and updates the branch ledger.

`run_program_search_bayesian_worker.py` is the second concrete branch worker. It only runs after a `bayesian_search` / `exploit` branch has been approved and prepared. It performs bounded, thesis-preserving local parameter search over existing first-run factor values and Step3A daily snapshots. It may test delay, smoothing, winsorization, direction, and cross-sectional transform choices, but it must not rewrite canonical Step3B, handoffs, shared clean data, portfolio expression, short-leg mechanics, or direct decile trading. Its output is advisory until Step6 merge and human approval.

Bayesian branch usage:

```bash
python3 skills/factor-forge-step6/scripts/approve_program_search_branch.py \
  --report-id <report_id> \
  --branch-id exploit_parameter_tuning \
  --decision approve \
  --notes "bounded parameter search only; preserve current thesis"

python3 skills/factor-forge-step6/scripts/prepare_approved_search_branch.py \
  --report-id <report_id> \
  --branch-id exploit_parameter_tuning

python3 skills/factor-forge-step6/scripts/run_program_search_bayesian_worker.py \
  --report-id <report_id> \
  --branch-id exploit_parameter_tuning \
  --max-trials 12

python3 skills/factor-forge-step6/scripts/validate_bayesian_search_trials.py \
  --report-id <report_id> \
  --branch-id exploit_parameter_tuning
```

Automatic loop runner (Step4 -> Step5 -> Step6 -> apply Step3B refinement -> repeat):

Official loop execution must enter through `scripts/run_factorforge_ultimate.py`. `run_step6_autoloop.py` is a developer-debug orchestrator only and must not be used by Bernard/Humphrey for formal factor research or for canonical writes.

Human approval gate for automatic modification:

```bash
# 1) generate proposal and stop for review
python3 repos/factor-factory/scripts/run_factorforge_ultimate.py --report-id <report_id> --start-step 6 --end-step 6

# 2) after human review, explicitly approve or reject
python3 skills/factor-forge-step6/scripts/approve_step6_revision.py --report-id <report_id> --decision approve --notes "focus on robustness first"

# 3) apply approved revision only through the ultimate wrapper
python3 repos/factor-factory/scripts/run_factorforge_ultimate.py --report-id <report_id> --apply-approved-revision --start-step 4 --end-step 6
```

Optional manual retrieval check:

```bash
python3 scripts/query_factorforge_retrieval_index.py --query "factor monotonicity partial validation" --top-k 5
python3 scripts/retrieve_factor_knowledge_context.py --text "<mechanism or factor terms>" --top-k 5
```

## References

- `references/input-contract.md`
- `references/output-contract.md`
- `docs/contracts/step6-contract.zh-CN.md`
- `docs/operations/factor-research-loop.zh-CN.md`
- `docs/operations/factorforge-math-research-discipline.zh-CN.md`
## Implementation and Factor Isolation Discipline

- Every formal factor artifact must carry `artifact_identity`.
- Every formal run must carry `manifest_identity`.
- `implementation_mode` is restricted to `operator`, `direct_code`, or `hybrid`.
- Artifacts must not be reused across mode, factor, report, branch, or run unless identity/hash lineage matches explicitly.
- Formal execution must consume manifest-specified paths only; do not pick files by `glob`, mtime, or "latest" guesses.
- If `report_id`, `factor_id`, `source_type`, `implementation_mode`, `branch_id`, `spec_hash`, or formula/code/hybrid hash does not match, BLOCK.
- Direct generated implementation files belong to one factor identity; shared helpers may be reused, factor-specific generated code may not be silently copied.

## Correctness Over Completion

Step6 treats failure as research knowledge. Knowledge/library writeback must preserve factor/report/branch/run identity and must not promote or generalize lessons across factors unless provenance explicitly shows a matched identity or a similar-case import.

## Provenance Strengthening

- No evidence identity, no promotion: `research_iteration_master`, `factor_library_all`, `factor_library_official`, and `research_knowledge_base` must preserve `artifact_identity`, `evidence_identity`, `source_case_identity`, `implementation_mode_decision`, `decision_lineage`, and `knowledge_provenance`.
- Official promotion requires `factor_case_master.final_status=validated`, verified identity chain, successful required Step4 evidence, long-side risk-adjusted metrics, and no unresolved correctness risk.
- Similar case knowledge is not same-factor evidence. Knowledge records must declare `knowledge_scope` as `same_factor`, `similar_case`, `general_methodology`, or `anti_pattern`, and same-factor scope requires matching factor identity.
- Structured factor knowledge graph nodes are analogy-only by default. Step6 `build_retrieval_context` appends `factor_knowledge_context_v1` from `knowledge/因子工厂/graph/` and maps graph nodes into `similar_cases` as `factor_knowledge_graph_node` records, but these records may only guide mechanism analysis, anti-pattern checks, or revision design. They cannot bypass evidence/provenance gates or become same-factor proof unless artifact identity/hash lineage matches independently.
- Iterate creates a child branch and never overwrites main. `handoff_to_step3b` must carry `parent_identity`, `new_branch_id`, `parent_run_id`, `must_preserve`, `must_change`, and `forbidden_changes`.
- The provenance gate runs before any `research_iteration_master`, library, knowledge, official, or Step3B handoff write. If the gate fails, Step6 writes only `objects/validation/step6_prewrite_block__<report_id>.json`.

## Research Intelligence Contract

Step6 `research_memo` must include:

- `evidence_audit`
- `mechanism_analysis`
- `case_comparison`
- `revision_strategy`
- `search_policy_decision`

`evidence_audit` decides whether Step4/5 evidence is usable before Step6 reasons
about promotion or revision. It must include backend integrity, metric
consistency, factor value health, long-side evidence quality, cost/turnover
risk, data or implementation suspicions, and `evidence_verdict`.

Official promotion is forbidden when evidence is blocked, return source is
unknown, or mechanism fit is contradicted. Iteration must propose expression or
Step3B code changes and must not repair results through portfolio expression,
short-leg adoption, decile trading, rebalance mechanics, or shared clean-data
mutation.

## Mechanism Reasoner And Case Comparator

Step6 must explain the return source before interpreting metrics. `mechanism_analysis`
must classify the factor family, return source, mechanism fit, necessary
conditions, observed-vs-expected metric signature, failure regimes,
classification evidence, and classification uncertainty. Positive IC or
long-short spread alone is never mechanism proof.

`case_comparison` must use retrieval results as judgment inputs, not as a pasted
list. It must separate `same_factor`, `similar_case`, `general_methodology`, and
`anti_pattern` lessons. Same-factor lessons require matching identity/hash
lineage; similar cases are analogy only and cannot support official promotion.
If retrieval is empty, Step6 must record a knowledge gap and treat the case as a
future retrieval anchor.

## Revision Strategist

`revision_strategy` is an expression-level research plan, not a portfolio repair
plan. It must classify the primary failure signature as one of
`cost_too_high`, `long_side_negative`, `non_monotonic`, `unstable_regime`,
`implementation_suspect`, `mechanism_unclear`, `same_factor_identity_mismatch`,
or `none`.

If `revision_quality=actionable`, every hypothesis must include a unique
`hypothesis_id`, mechanism target, expression or Step3B-code change, at least two
expected metric changes, at least two falsification tests, at least two kill
criteria, overfit risk, and an explicit `why_not_portfolio_fix`. It must carry
all four forbidden changes:

- `no_portfolio_expression_repair`
- `no_short_leg_adoption`
- `no_decile_trading`
- `no_shared_clean_data_mutation`

`implementation_suspect` and `same_factor_identity_mismatch` are blocked
revision states: do not generate normal expression mutations until evidence or
provenance is repaired. A valid promote decision should normally have
`revision_needed=false`, no revision hypotheses, and `revision_quality=not_needed`.

## Agentic Revision Council

Step6 is the investment-committee and loop-control layer. When evidence supports
`iterate` but the revision direction is non-obvious, the main agent should form
a Revision Council from the Step1-5 record instead of privately inventing a
single change.

The main agent owns the council. It builds the read-only packet, defines an
exploration graph, delegates independent directions to subagents when the
runtime supports it, keeps dependent directions sequential, validates every
proposal, and merges the final advisory conclusion. Subagents never own the
formal Factor Forge loop.

Council roles are role-based and runtime-agnostic. A main agent may perform them
itself or dispatch subagents. Typical roles are:

- `symbolic_law_discovery`
- `evidence_auditor`
- `economic_mechanism`
- `formula_engineer`
- `cost_turnover`
- `regime_robustness`
- `knowledge_retrieval_critic`

Each role receives the same read-only council packet and writes at most one
isolated proposal under:

- `objects/research_iteration_master/revision_council/{report_id}/`

Council proposals must never write or modify:

- `objects/handoff/handoff_to_step3b__{report_id}.json`
- `generated_code/{report_id}/`
- `objects/factor_library_official/`
- `data/clean/`
- `runs/`, `evaluations/`, or `archive/`
- canonical factor expressions or Step3B implementations

### Wrapper Attachment Mode

The official wrapper may explicitly request Council-primary revision attachment
with `--council-mode off|auto|scaffold|agentic`. `auto` is the wrapper default
for formal runs; `off` leaves Step6 behavior unchanged for explicit debug or
legacy reproducibility checks. `scaffold` runs packet generation, deterministic
proposal generation, merge, attach, and `validate_step6.py` after Step6 core.
`auto` must not silently use that deterministic scaffold as formal agentic
research. With `--auto-council-policy dispatch_manifest` (default), auto builds
the agentic dispatch package and returns `awaiting_agent_results` as a machine
checkpoint. A main agent using this skill must continue by writing valid
Council result artifacts, collecting/finalizing them, and resuming the loop
unless the user explicitly requested a pause. Use
`--auto-council-policy scaffold` only for explicit smoke/fallback runs; use
`--auto-council-policy block_without_agentic` to hard-block when formal agentic
research is required but not available. `agentic` requires
`--agentic-council-executor`. `none` blocks with
`BLOCK_REVISION_COUNCIL_AGENTIC_EXECUTOR_REQUIRED`; `real_agent` blocks with
`BLOCK_REVISION_COUNCIL_REAL_AGENT_NOT_IMPLEMENTED`; `local_mock` runs the
Phase K.1 artifact contract path without spawning real subagents.
`dispatch_manifest` writes dispatch-ready task packets and, with
`--agentic-dispatch-adapter manual_file`, a manual assignment bundle. It does
not merge, attach, import results, or call real agent APIs.

`awaiting_main_agent_mechanism_memo` and `awaiting_agent_results` are not normal
user-handoff states. If the main-agent memo is missing, the runtime main agent
must answer the questionnaire, validate the memo, and resume. If agentic
Council results are missing, the runtime main agent must read the task packets,
delegate independent roles to available subagents or perform them sequentially
itself, write `status=final` / `producer=real_agent` result JSON files to the
exact expected paths, run collection validation and finalize, then continue the
official loop. Do not ask the user to manually advance the next command unless
valid Council output cannot be produced in the current runtime.
When the loop legitimately pauses at
`awaiting_main_agent_mechanism_memo`, `awaiting_agent_results`,
`awaiting_main_agent_council_synthesis`, or `awaiting_next_derivation`, it must
write `paused_research_note__<report_id>.json` and `.md` under
`objects/research_iteration_master/`. The note must preserve pause state,
reason, backend/metric status when known, evidence paths, lessons, and the next
questions needed to resume. A paused run without durable knowledge writeback is
not production-complete.

Agentic dispatch artifacts must include
`runtime_dispatch_policy.policy_version=factorforge_runtime_dispatch_policy_v1`.
Factor Forge remains provider-agnostic: `provider_required_by_factor_forge`
must be false, subagents inherit the main runtime model/provider by default,
and provider/model override is allowed only when explicitly requested by the
user. Codex runtime may spawn Codex subagents directly and must not choose
external providers. OpenClaw runtime may spawn OpenClaw subagents using the
main provider/model by default. Manual-file dispatch accepts only validator
passing result JSON; provider/model identity is not sufficient for acceptance.

Attached Council output sets `final_revision_strategy.source=revision_council`
but remains `loop_authorization=advisory_only` unless a separate human-approved
Step3B path exists. The wrapper must guard forbidden side effects around
handoff, generated code, official library, and clean data artifacts.

### Explicit Research Derivation Requirement

Every council proposal must include a public, auditable `derivation_record`.
This is not hidden model chain-of-thought. It is the research artifact that lets
future agents and reviewers understand what was assumed, derived, rejected, and
learned.

A valid `derivation_record` must include:

- `research_question`
- explicit `assumptions`, each with status, why it is needed, and how to
  falsify it
- `mathematical_objects` with meaning, unit or dimension, and information set
- `selected_tools` with why each tool was selected, what it can answer, and what
  it cannot answer
- optional `rejected_tools` with reasons
- ordered `derivation_steps`, including formulas or symbolic relations when a
  formula is claimed
- `derived_implications` tied to expected metric signatures
- `revision_hypotheses` with expression direction, expected metric changes,
  falsification tests, and kill criteria
- `confidence_and_limits`, including mathematical confidence, empirical
  confidence, known gaps, and an overclaim guard

No explicit derivation record means no valid council proposal. No valid council
proposal means no branch template. No accepted derivation means no Step3B
revision brief.

Every Council result must also declare `research_depth`:

```text
contract_placeholder_result
deterministic_scaffold
main_agent_sequential_result
independent_agent_result
human_reviewed_result
```

Only `independent_agent_result` and `human_reviewed_result` may support a formal
research-quality claim. `deterministic_scaffold` and
`contract_placeholder_result` may prove artifact shape only. A
`main_agent_sequential_result` is useful research material, but it must not be
described as independent Council validation.

Each role must state what information the current formula preserves, deletes,
or aliases; which metric should move if the claim is true; what observation
would kill the claim; and whether it has a `dirac_atomic_law_candidate`.

### Council As Math-Mechanism Derivation Engine

Revision Council is a derivation engine, not a verdict engine. A Council result
may reject a branch, formula, tool, or derivation rule, but before the configured
loop cap it must not terminally reject the whole factor instance unless it
provides validated proof that no legal, executable, formula-mappable
mathematical revision remains, or the user explicitly approves early stop.

Every `producer=real_agent` Council result must include:

- `economic_hypothesis_review`: broad-direction preservation, refined second
  layer mechanism, updated payer/counterparty, and what Step4/5 evidence changed
  in the hypothesis
- `math_mechanism_derivation`: selected tool with rationale, rejected tools,
  baseline model, model mutation, mathematical objects, derivation steps,
  derived state variables, observable estimators, expected metric signature, and
  falsification tests
- `model_to_formula_translation`: candidate formula or explicit
  `research_hold` / `operator_block` / `no_derived_revision_with_proof`
  disposition, operator support status, model-term to formula-component mapping,
  and information-set legality
- `candidate_revision_laws[].revision_kind`: one of parameter repair, estimator
  repair, model-term repair, model-family shift, or economic-hypothesis
  refinement

If a child revision fails, record it as `revision_branch_only` falsification by
default. The next Council must diagnose which model component failed and derive a
distinct mathematical mechanism or return `BLOCK_NO_DERIVED_REVISION_WITH_PROOF`.
Do not convert one failed child branch into factor-level rejection before max
loops unless terminal proof authority is explicit and validated.

After Council merge, the agent must build a user-facing derivation appendix:

```bash
python3 skills/factor-forge-step6/scripts/build_council_derivation_appendix.py --report-id <report_id>
```

The appendix must write:

- `objects/research_iteration_master/revision_council/{report_id}/council_derivation_appendix__{report_id}.json`
- `objects/research_iteration_master/revision_council/{report_id}/council_derivation_appendix__{report_id}.md`

This appendix consolidates the selected Council outputs' public derivation
records: assumptions, mathematical objects, selected tools, formula claims,
derivation steps, limiting cases, falsification tests, kill criteria, and
candidate revision laws. It remains advisory-only and must not write Step3B
handoffs, generated code, official library records, clean data, runs,
evaluations, or archives.

### Symbolic Law Discovery Role

`symbolic_law_discovery` treats the formula as a mathematical object, not just
an implementation string. It may choose any justified mathematics, including
unit and dimensional analysis, scaling laws, invariance, limiting cases,
perturbation reasoning, stochastic processes, stochastic calculus, jump
processes, natural market time, Fourier/spectral analysis, robust statistics,
tail distributions, linear projection, functional analysis, dynamical systems,
stopping-time reasoning, information theory, or market microstructure theory.
It must not mechanically apply every tool. It must explain why each selected
tool is relevant and what it rules out. It may also say the current information
is under-specified and refuse to derive a confident mechanism.

Mathematical plausibility is hypothesis generation only. It cannot promote a
factor, authorize Step3B modification, replace Step4/5 evidence, or bypass
provenance and human-approval gates.

### Deterministic Scaffold Status

The deterministic local council is a scaffold for smoke tests and a fallback for
low-depth advisory output. It is not the full agentic research mode. If a
proposal is scaffold-generated, record `producer=deterministic_scaffold` and
`research_depth=low`. Formal research should prefer agentic council reasoning
when the runtime supports main-agent or subagent proposal generation.

## Mechanism Math Contract v2

Step6 must interpret metrics against the model layers: economic_hypothesis,
primary_mechanism_model, market_outcome_projection, observable_estimator, and
implementation_contract. A revision proposal is incomplete unless it states
which layer is being revised and how the expected metric signature would
change. Council output remains advisory-only and cannot bypass evidence,
provenance, human approval, or promotion gates.
