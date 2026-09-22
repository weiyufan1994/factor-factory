# Council records, synthesis and bounded revisions

Read when Council/revision is active, alongside [Ultimate orchestration](../../factor-forge-ultimate/references/council-orchestration.md). The existing field/count constraints are listed in [compatibility constraints](../../factor-forge-ultimate/references/compatibility-constraints.md); do not invent branches to satisfy them. The terminal-certificate rule below is the formal Council route, not the existing local terminal-rejection exception in [current-operating-contract.md](current-operating-contract.md).

Every revision must carry a knowledge-reference trail. Step6/Council retrieval
context must record the retrieval index path, availability, query terms, and
similar cases; if no case is found, the memo must state a cold-start knowledge
gap rather than silently proceeding. Child revision materialization must inherit
this context from Step6 artifacts or block with
`BLOCK_FACTORFORGE_REVISION_KNOWLEDGE_CONTEXT_MISSING`.
Retrieved cases are advisory priors, counterexamples and tool candidates only;
they cannot outrank the current mathematical contract or count as proof.

30b. Council and child revisions must write
`revision_data_plan.contract_version=factorforge_revision_data_plan_v1`. The
plan must distinguish formula changes, state-variable changes, and
portfolio-only changes. If a revision needs a new state datamart, it must set
`new_state_required=true` and `data_request_required=true`; it must not authorize
Step4 to scan full-window raw minute data. If a revision only changes holding,
rebalance, or portfolio policy, it should set
`factor_value_recompute_required=false` and reuse existing factor values.

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
Step1/Step2: `economic_hypothesis` selects the primary mathematical model after
an open tool search. DCF/residual income, accounting identities, stochastic
processes, Ito calculus, linear algebra, optimization, information theory,
spectral/functional methods, causal/placebo tests, or other tools are used only
when justified. Do not default every failed factor to a stochastic-process
story, a dimensional-analysis exercise, or a generic payer narrative.
Factor Forge uses a Dirac-style research discipline: the classified research
equation must map the selected mathematical object to a tradeable value, payoff,
price gap or return quantity, then to an observable estimator, expected metric
signature and falsification tests. A stochastic benchmark is required only when
the selected claim is stochastic.
Council proposals must state which economic hypothesis, primary mathematical
model, observable estimator, benchmark test, and falsification signature they
are revising.
Step6 `mechanism_analysis` must include `research_equation_review` with metric
links for rank IC, long-side return, cost-adjusted return, turnover,
volatility drag, max drawdown, recovery days, and drawdown geometry when
available. Revision Council proposals must include
`research_equation_revision` and target the failed equation component.
Use [prompts.md](prompts.md) as a review aid for this Council task. Use its discovery section only when new ideas are requested or warranted; it does not require a new factor seed.
When a report suggests a market structure relation, first identify the research
equation or quasi-equation, then derive one or more observable detector
candidates. A detector candidate is not an approved factor. It must state
`source_equation_id`, `observable_inputs`, `measurement_equation`,
`market_outcome_projection_terms`, `expected_metric_signature`,
`expected_cost_risk_profile`, `falsification_tests`, and
`branch_action=review_only|human_approval_required`.
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
New memos use `mathematical_object_answer`, `observation_mapping_answer`,
`math_hypothesis.mathematical_object`,
`math_hypothesis.mechanism_equation_or_functional`,
`math_hypothesis.target_functional`,
`math_hypothesis.market_outcome_projection`,
`math_hypothesis.observation_mapping`, and the top-level
`mathematical_object_mapping`. The target functional is the mechanism's
estimand, not universally a conditional return. The separate market-outcome
projection binds that estimand to the frozen tradeable payoff. Old
`formula_state_answer`, `estimator_mapping_answer`, `random_object`,
`latent_state`, `process_or_distribution`, `formula_as_estimator`, and
`formula_state_estimator` fields are read only as compatibility aliases for
existing artifacts; never synthesize them for a new memo.
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

38. When the ultimate loop receives an approved Step3B handoff and either a
valid legacy main-agent Council synthesis or an exact validated pre-OOS root
synthesis, Step6 child materialization must write
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

## Dynamic Council

Council tasks must be generated from open approach-registry routes. Current validator-required route families include economic game,
mechanism-object measurement (legacy alias: latent-state measurement) and
null/alias attack; this does not require a latent-state model. Add cost, regime, implementation, data or symbolic-law routes when the
actual gaps require them.

At least two early routes must be blind to the favored thesis. Each dispatch and
result binds task ID, route ID/family, route fingerprint, blind-context hash,
expected agent identity, task-packet SHA256 and result SHA256. Reusing one agent
identity across supposedly independent blind routes is invalid.

Council results must contain:

- assumptions and attempted derivation;
- proof obligations addressed;
- counterexample attack;
- candidate executable law or exact blocker;
- evidence references and uncertainty;
- no canonical write permission.

Every source result selected by root synthesis is re-run through the formal
Council result validator against its dispatch/task packet. Matching hashes alone
are insufficient. A local contract mock is labeled `contract_mock_completed`
and is never independent-agent research evidence.

## Terminal Council Rejection

Council may close a rejected branch only when all of the following hold:

- every required dispatch route returns one result whose exact recommendation is
  in the terminal enum (`reject`, `kill`, `stop`, `terminal_reject`,
  `no_revision`, `no_derived_revision`); do not infer terminal intent from prose
  or substrings;
- no distinct mechanism derivation remains within the registered route/trial
  budget;
- the workspace contains a validated factor-proof certificate with derived
  verdict `REJECT`;
- the terminal-rejection artifact binds the dispatch manifest, Council summary,
  result collection, every selected raw result, proof certificate and iteration
  decision by path and SHA256; final replay must recompute the required task set,
  collection counts and result identities from the dispatch manifest;
- the final research-protocol validator accepts those semantic bindings.

If another mathematically distinct route remains, write the bounded
branch-falsification record and next-derivation questionnaire and return
`awaiting_next_derivation`. If Council is not unanimous, return
`awaiting_main_agent_council_synthesis`. Neither state is formal proof eligible,
and neither may be presented as a completed factor decision.

## Root Synthesis

The main agent must cover every registered route and state:

- disposition and exact gap/closed obligation;
- incompatible assumptions;
- discriminating evidence;
- dissent resolution;
- selected route/result hashes and law hash;
- open proof obligations;
- why the next action is exploit, explore, audit or stop.

Majority vote and automatic approval are forbidden. An explicit
`--approval-source` is required for the legacy path. EVO V2 instead requires
the signed external-human receipt and out-of-band trust-manifest pin described in [EVO and child authority](evo-and-child-authority.md). Approval
on the legacy/post-Step6 path must pass both `validate_step6.py` and the research
protocol verifier before a Step3B handoff remains active. The EVO V2 pre-OOS
bridge instead requires the exact qualified pre-OOS verifier, transfer/use
staging, signed lifecycle and fresh OOS controls in
[EVO and child authority](evo-and-child-authority.md); it must not invent a
Step6 iteration merely to satisfy the legacy gate.

## Revision Rules

An `iterate` decision may propose one bounded mechanism-linked revision:

- preserve parent formula/code/data identity;
- name the mathematical object being changed;
- state expected metric signature, ablations, falsifiers and kill criteria;
- allocate a fresh trial budget;
- keep OOS sealed;
- require human approval before code mutation.

The revision must first identify the failed layer:
`economic_hypothesis`, `primary_math_mechanism`, `market_outcome_projection`,
`applicable_audits`, `observation_equation`, `measurement_program`,
`implementation`, or `empirical_regime`. It must preserve unaffected
invariants and publish the revised definitions, equations, measurement
semantics, component
bindings, expected signatures and falsifiers. Changing the estimand creates a
new hypothesis branch; it is not an implementation repair.

Council's `public_derivation_record` is an auditable derivation summary for
reproduction and challenge. It must not request, expose or claim to expose
private chain-of-thought.

Forbidden repairs:

- portfolio-expression tuning;
- adopting the short leg;
- decile trading as factor logic;
- implicit clean-data or baseline Step3 mutation;
- reopening a blocked route without new mechanism, data, invariant or
  counterexample evidence.
