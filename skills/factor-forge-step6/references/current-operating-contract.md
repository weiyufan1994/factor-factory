# Factor Forge Step6 Current Operating Contract

This reference preserves the complete current normative and CLI contract. Read it
in full before producing Step6 judgment, launching or continuing Council work,
admitting an EVO V2 revision, approving a child, or performing writeback.

## Contents

- [Required Inputs](#required-inputs)
- [Research Judgment](#research-judgment)
- [EVO V2 Pre-OOS Contradiction Path](#evo-v2-pre-oos-contradiction-path)
- [Factor Proof Policy](#factor-proof-policy)
- [Dynamic Council](#dynamic-council)
- [Terminal Council Rejection](#terminal-council-rejection)
- [Root Synthesis](#root-synthesis)
- [Revision Rules](#revision-rules)
- [Validation and Writeback](#validation-and-writeback)
- [On-Demand Reference](#on-demand-reference)

## Required Inputs

- factor run/case/spec masters and formal Step5 handoff;
- Step4/5 metric, chart and backend evidence;
- researcher journal or independent researcher memo;
- knowledge-reference provenance;
- research state, conjecture and approach registry;
- before revision: proof-obligation and counterexample ledgers;
- before promotion/final approval: factor proof certificate.

Missing formal evidence is BLOCK, not a fixture or narrative fallback.

## Research Judgment

Step6 must state:

1. Step 6 is responsible for reflection and decision, not raw metric generation.
2. Every attempt must enter the full experiment library.
3. Only explicitly promoted factors may enter the official library.
4. If the decision is `iterate`, Step 6 must point back to Step 3B with explicit modification targets.
5. Step 6 must preserve failed lessons, not only successful ones.
6. Step 6 should prefer structured retrieval before proposing modifications and should surface similar historical cases in the proposal.
7. Step 6 must emit a concrete `research_memo`: formula understanding, return-source hypothesis, metric interpretation, evidence quality, failure/risk analysis, decision rationale, and next research tests.
8. `research_memo` must include `math_discipline_review`: selected mathematical object, target statistic or functional, information-set legality, spec stability, signal-vs-portfolio gap, revision operator, generalization argument, overfit risk, and kill criteria.
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

Step6 interprets evidence against the frozen math-first chain, not the reverse.
Before Council or revision, read
`docs/contracts/mechanism_conditioned_measurement_program_v1.zh-CN.md` as the
current authority. Read `docs/contracts/mechanism_math_contract_v2.zh-CN.md`
only when validating an artifact that already carries that legacy contract;
never synthesize it for new research.
Metrics may falsify or localize a model, but they may not retroactively redefine
the economic hypothesis, estimand, units or observation equation.

## EVO V2 Pre-OOS Contradiction Path

When the conjecture enables EVO V2, read
`docs/contracts/factorforge-epistemic-evolution-v2.zh-CN.md` and do not apply
the normal post-Step5 revision flow to that parent. Run revision Council only
after the Host admits `QUALIFIED_CONTRADICTION`, using the purged-IS checkpoint
and canonical feedback ledger. Require `uses_oos=false`, `PURGED_IS_ONLY`,
complete lower-layer clearance, a preregistered materiality breach,
multiplicity/trial-budget compliance, and at least two rival models. A large
residual, high IC/Sharpe, historical score, or Council majority is not
qualification.

Maintain a tension ledger instead of one scalar score. Preserve predicted and
observed signatures, mismatch vector, failure layer, rival explanations, next
discriminating test, `what_survived`, and `what_failed`. Keep a Rank IC that
survived distinct from after-cost long-side economics that failed.

For a qualified contradiction, accept exactly one of:

- `MINIMAL_MECHANISM_DELTA`: add one smallest identifiable object, show
  zero-extension recovery, preserved/broken invariants, information deleted,
  a unique prediction, distinguishing test, complexity cost, and why larger
  extensions were rejected; then backproject it to actor, action, constraint,
  payer, receiver, payoff/profit transfer, persistence, capacity, proxy,
  negative control, counterfactual and disappearance condition;
- `NO_DERIVED_LAW`: state the identification/budget blocker and terminate the
  branch without a child.

Do not force DCF or any other model family. Select DCF, residual income,
accounting identities, stochastic, spectral, causal, functional,
microstructure, optimization, or a new composition only when the frozen
economic hypothesis requires it.

Keep Council output review-only. The Host advances lifecycle and staged CAS;
Council Agents cannot write canonical EVO artifacts. Run
`scripts/write_factorforge_evo_v2.py --stage admit-council-outcome` only after
the signed lifecycle reaches `MINIMAL_MECHANISM_DELTA` or `NO_DERIVED_LAW`.
Never prewrite transfer/use artifacts to make a future-stage validator pass.

Retrieve experience only after blind derivation, using the mechanism
fingerprint rather than historical return, market-state label, or event name
as the ranking key. Require structural-isomorph, cross-math analogy, near-miss,
counterexample and episode-context lanes plus source-to-target mappings. State
and events are falsification/stress coordinates only unless state dependence
was frozen in the current economic model. Do not claim transfer use until a
Host receipt binds the actual before/after research questions or tests.

Every revision must carry a knowledge-reference trail. Step6/Council retrieval
context must record the retrieval index path, availability, query terms, and
similar cases; if no case is found, the memo must state a cold-start knowledge
gap rather than silently proceeding. Child revision materialization must inherit
this context from Step6 artifacts or block with
`BLOCK_FACTORFORGE_REVISION_KNOWLEDGE_CONTEXT_MISSING`.
Retrieved cases are advisory priors, counterexamples and tool candidates only;
they cannot outrank the current mathematical contract or count as proof.
26. Revision must modify the factor expression and Step3B implementation itself. Do not “fix” a weak factor by changing portfolio expression, short-leg exposure, rebalance mechanics, or decile trading.
27. Official promotion requires risk-adjusted positive long-side evidence. If a factor is strictly monotonic but the high-score long side does not make money with acceptable Sharpe/drawdown/recovery, Step6 must choose `iterate` or `reject`, not `promote_official`.
28. Preferred revision direction is economic linearity: make higher factor values correspond more directly and monotonically to the economic state expected to earn risk-adjusted long-side returns.
29. Treat every factor like a business: long-side return is revenue, trading COGS defaults to `turnover * 0.3%`, volatility is operating instability/risk-capital pressure, `-0.5 * sigma^2` is volatility drag on geometric growth, max drawdown is capital impairment, and recovery time is payback/depreciation. Risk budget follows Sharpe, drawdown, recovery, capacity, and confidence.
30. Default Step6 promotion objective is `long_side_risk_adjusted_alpha`: candidate Sharpe >= `0.50`, official Sharpe >= `0.80`, max drawdown no worse than `-35%`, and recovery days preferably <= `252`.
30a. For current minute-factor research, Step6 must preserve the Step4
`research_window_contract`: in-sample ends at `2025-07-11` by default and later
data is OOS holdout. OOS evidence may diagnose degradation or robustness, but
Step6 and Council must not repeatedly fit revisions on OOS metrics. If Step4
blocked because `minute_derived_flow_state_v1` is missing, incomplete, or
identity-mismatched, treat that as a production-path infrastructure BLOCK, not a
mechanism reject.
30b. Council and child revisions must write
`revision_data_plan.contract_version=factorforge_revision_data_plan_v1`. The
plan must distinguish formula changes, state-variable changes, and
portfolio-only changes. If a revision needs a new state datamart, it must set
`new_state_required=true` and `data_request_required=true`; it must not authorize
Step4 to scan full-window raw minute data. If a revision only changes holding,
rebalance, or portfolio policy, it should set
`factor_value_recompute_required=false` and reuse existing factor values.
31. Every successful formal Step6 loop must write `loop_research_brief__<report_id>__iter<n>.md/json` and link it from `research_iteration_master.loop_research_brief`. The brief must answer economic interpretation, metrics/chart evidence, metric analysis, knowledge comparison, next research direction, and final loop conclusion. Missing brief, missing core metrics, missing required chart keys, or long-short chart evidence not labeled `diagnostic_only` is a validation block.
32. Step6 must carry the exact
`mechanism_conditioned_measurement_program` into `mechanism_analysis`, revision
hypotheses, and the loop research brief. The program is an explanatory and
revision-discipline layer only: it must not replace Step4/5 evidence, bypass
provenance gates, justify promotion on its own, or authorize canonical Step3B
changes without the existing loop authorization. A legacy
`mechanism_math_contract_v2` is preserved and validated only when it already
exists upstream.
33. For a specified current program, the research record must state a testable
economic hypothesis, competing mathematical models, the selected mechanism,
market-outcome projection, observable estimator, expected metric signature,
and falsification tests. Latent states, conditional distributions, stochastic
transitions, dimensional audits, or valuation identities are required only
when the selected mechanism uses them. Formula classification is a diagnostic
prior, not a rule that fixes the mathematical model.
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
Before writing Step6 final recommendations, use the Dirac-Style Step6 Council Prompt in references/prompts.md. When asked for new ideas, use the Equation-To-Factor Discovery Prompt.
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
The preceding command and `--approval-source` are only for the legacy/post-Step6
path. Do not use them for an EVO V2 pre-OOS revision. An EVO V2 pre-OOS
`MINIMAL_MECHANISM_DELTA` is not approvable yet: first require the signed
lifecycle to reach `TRANSFER_RECORDED` or `COLD_START_RECORDED` and require the
staging manifest to contain the exact four-event sequence through `record-use`.
Then use `scripts/approve_factorforge_pre_oos_child.py`. That bridge replays the
canonical pre-OOS outcome, selected raw Agent result, staged delta and economic
backprojection, external Ed25519 receipt, trust-manifest pin and fresh child OOS
registry allocation without requiring or fabricating a Step5/6 research
iteration. It writes the closed approval, handoff and child-intent semantic
projections plus a Host-signed non-ready authorization ticket for the isolated
authoring/preregistration chain. A `MATERIALIZATION_READY` ticket is permitted
only when a complete child preregistration receipt already exists and passes
strict replay. Neither ticket materializes or executes the child. The external
human receipt must bind the selected law, delta/backprojection, exact child
identity and a Host-provisioned fresh sealed OOS allocation; the repository
validates it but does not generate the human key or signature.
The Host invocation must also pass `--incident-trust-root` and
`--incident-installation-id`; they must exactly equal the canonical
`--host-trust-root` and `--installation-id` binding so one live guard covers
lineage validation, projection writes, ticket signing, and readback.
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

Allowed claim levels rise only with evidence:

```text
narrative_only
-> math_framed
-> metric_candidate
-> metric_consistent
-> component_validated
-> stochastic_validated | payer_validated
```

`metric_consistent` requires an accepted factor-proof certificate.
`component_validated` additionally requires verified measurement-validity and
component-ablation obligations from
`factorforge_component_obligation_verifier_v1`. Stochastic and payer claims
require their own trusted executable verifiers; until such a verifier exists,
retain the evidence as falsifiable research and do not label the obligation
`passed`. This is not a mandatory linear path through
`stochastic_validated`: non-stochastic mechanisms never need that qualifier.

## Factor Proof Policy

Read `docs/contracts/factorforge-factor-proof-certificate-v2.zh-CN.md`.

Common proof obligations:

- IC and ICIR, with conventions and arithmetic reconciliation;
- realized volatility drag and half-variance benchmark;
- gross-to-net transaction-cost reconciliation;
- maximum drawdown and recovery geometry;
- executable after-cost long-end return;
- metric-matching evidence file, exact metric-payload equality, verifier and
  SHA256 binding;
- one shared dataset-snapshot and window hash across required metrics;
- actual observed OOS dates and at least 60 daily periods;
- `verification_scope=production` plus an explicit calendar snapshot id bound
  to the approved trusted-registry Git commit/blob; `SMOKE` naming is never an
  authority;
- frozen search-trial ledger, locked threshold registration and one-time OOS
  release manifest in strict sequence;
- trusted metric-verifier identity and verifier-report contract;
- locked threshold-file hash bound to factor/report/claim/window and search
  ledger identity before the OOS panel is bound;
- one verdict rule on a core decision field per required metric family, and an
  automatically derived verdict.

Formal `promote_official` is blocked before official writeback unless the
certificate verdict is `ACCEPT`.

Build required evidence from the frozen OOS panel with
`scripts/build_factorforge_metric_verifier_reports.py`; its bundle is the
source of certificate metrics and evidence bindings. Researcher-written metric
JSON or Council prose is not a trusted verifier report.

Before that verifier, use
`scripts/write_factorforge_evaluation_release_chain.py` in this exact order:
`freeze-search`, `register-threshold`, `release-oos`. Formal threshold
registration must not use `--identity-only` to inspect the OOS panel. The
release command binds its actual dates, period count and dataset hash. This is a
local tamper-evident chain, not an external trusted timestamp.

For `measurement_validity` and `component_ablation`, freeze a same-window panel
containing full signal, ablated signal and legal forward return, register the
delta rules, and run:

```bash
python3 scripts/build_factorforge_component_obligation_report.py \
  --workspace-root <factor_workspace> \
  --panel <full_vs_ablated_oos_panel> \
  --spec <component_obligation_spec.json> \
  --host-trust-root <host_private_trust_root> \
  --installation-id <host_installation_id>
```

Formal release, metric/component verifier, and factor-proof validation CLIs
must receive the same explicit Host `--host-trust-root` and
`--installation-id`. Agent-side/identity-only replay is structural diagnostic
evidence only and cannot set `formal_proof_eligible=true`.

Both metric and component evidence are replayed from their panel/spec by the
final kernel. A copied verifier ID, source hash, or hand-authored PASS file is
not proof.

Only `claim_class=risk_premium` requires Fama-MacBeth risk-price evidence and
quintile/decile monotonicity. Do not reject an event, threshold, liquidity-rent
or information-rent factor merely because all buckets are not monotonic.
Long-short spread and the short leg never substitute for long-end admission.
Formal long-end admission uses net geometric return and positive wealth, not
the arithmetic gross-minus-cost reconciliation. Ties may not be broken by asset
order to manufacture full quantile buckets.

## Dynamic Council

Council tasks must be generated from open approach-registry routes. Required
route families include economic game, latent-state measurement and null/alias
attack. Add cost, regime, implementation, data or symbolic-law routes when the
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
the signed external-human receipt and out-of-band trust-manifest pin. Approval
on the legacy/post-Step6 path must pass both `validate_step6.py` and the research
protocol verifier before a Step3B handoff remains active. The EVO V2 pre-OOS
bridge instead requires the exact qualified pre-OOS verifier, transfer/use
staging, signed lifecycle and fresh OOS controls above; it must not invent a
Step6 iteration merely to satisfy the legacy gate.

## Revision Rules

An `iterate` decision may propose one bounded mechanism-linked revision:

- preserve parent formula/code/data identity;
- name the mathematical object being changed;
- state expected metric signature, ablations, falsifiers and kill criteria;
- allocate a fresh trial budget;
- keep OOS sealed;
- require human approval before code mutation.

For EVO V2, preregister the child as a new identity before materialization and
bind a fresh sealed OOS allocation in the Host append-only registry. Missing
child conjecture/approaches/trial ledger/threshold/allocation must return
`WAITING_DATA_FRESH_SEALED_OOS_ALLOCATION`. Never copy or overlap an ancestor or
sibling OOS token/window, and never reuse consumed OOS under a new name.

Do not let the Host fabricate the child research semantics. An isolated Agent
must author research state, conjecture, approaches, base trial ledger and the
report-scoped Web plan; Host admission and preregistration may only perform
closed-schema validation and deterministic projection. Before a READY ticket,
require the signed authoring admission, independent revision-child assurance,
strict preregistration receipt and exact frozen refs. Production execution must
then pass the seven signed stages `AUTHORING_ADMITTED -> CHILD_PREREGISTERED ->
MATERIALIZATION_READY -> CHILD_MATERIALIZED -> POST_MATERIALIZATION_ADMITTED ->
CONTAINER_ADMITTED -> CHILD_EXECUTION_READY`.

Each descendant repeats the same pre-OOS gate and receives a fresh allocation.
Recursive execution must persist and replay every signed `HOST_CHILD_HANDOFF`
phase receipt and the complete root-to-active lineage; a mutable current-row
pointer is not lineage authority. Container command recovery and finalizer-only
recovery are Host runtime concerns and may not be inferred from a Council
decision or a merely present child workspace.

An unauthorized read or local computation that overlaps frozen OOS is a
permanent negative authority event, not an informal warning. Record it through
`scripts/record_factorforge_oos_exposure_incident.py`, then bind the public
create-only marker into the Host-private signed append-only incident registry.
Any marker entry—even malformed or symlinked—and every registered incident on
the root-to-active lineage blocks child allocation/preregistration and all OOS
release/finalizer/consume paths. Deleting or repairing the public file never
restores eligibility. A successful validator only authenticates the negative
record; it cannot issue release, consumption, `ACCEPT`, or `REJECT` authority.

The formal incident command must include the exact Host identity and fixed
incident time:

```bash
python3 scripts/record_factorforge_oos_exposure_incident.py \
  --workspace-root <factor_workspace> --report-id <report_id> \
  --factor-id <factor_id> \
  --frozen-oos-start <YYYY-MM-DD> --frozen-oos-end <YYYY-MM-DD> \
  --frozen-oos-release-token-sha256 <sha256> \
  --exposed-overlap-start <YYYY-MM-DD> --exposed-overlap-end <YYYY-MM-DD> \
  --exposed-row-count <count> --exposed-period-count <count> \
  --source-path <source> --panel-path <panel> \
  --metrics-path <metrics> --runner-path <runner> \
  --host-trust-root <host_private_trust_root> \
  --installation-id <host_installation_id> \
  --incident-at <UTC_ISO8601_Z>
```

If a pre-existing public marker was created before durable Host registration,
bind it to the external signed negative registry without rewriting the marker:

```bash
python3 scripts/register_factorforge_oos_exposure_incident_host_private.py \
  --workspace-root <factor_workspace> --report-id <report_id> \
  --trust-root <host_private_trust_root> \
  --installation-id <host_installation_id>
```

If the original runner bytes were not frozen, keep the incident immutable and
append the explicit reconstruction-only correction. Reuse the fixed timestamp
for exact idempotent replay:

```bash
python3 scripts/record_factorforge_oos_exposure_provenance_addendum.py \
  --workspace-root <factor_workspace> --report-id <report_id> \
  --correction-at <UTC_ISO8601_Z>
```

Both recovery commands preserve `NEGATIVE_EVIDENCE_ONLY` and
`formal_oos_eligible=false`; neither restores release, consumption or factor
verdict authority.

The same explicit Host pair is replayed at each current-authority boundary
from `AUTHORING` through `PREREGISTERED`, `READY`, allocation, release/consume
and terminal closure. Agent structural replay remains non-formal and reports
`current_formal_authority_verified=false`.

For standalone Host debugging of the child preregistration boundary, formal
`validate`, `materialize`, and `validate-receipt` require the incident-specific
pair explicitly; projection subcommands remain structural-only:

```bash
python3 scripts/preregister_factorforge_evo_child.py <validate|materialize|validate-receipt> \
  --workspace-root <factor_workspace> \
  --parent-report-id <parent_report_id> \
  --child-report-id <child_report_id> \
  --expected-host-trust-manifest-sha256 <out_of_band_sha256> \
  --incident-trust-root <host-private-incident-trust-root> \
  --incident-installation-id <host-installation-id> \
  <subcommand-specific-control-arguments>
```

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

## Validation and Writeback

Before Council:

```bash
python3 scripts/validate_factorforge_research_protocol.py \
  --workspace-root <factor_workspace> \
  --report-id <report_id> \
  --stage pre_council
```

Before revision:

```bash
python3 scripts/validate_factorforge_research_protocol.py \
  --workspace-root <factor_workspace> \
  --report-id <report_id> \
  --stage pre_revision
```

Before any official write, including a no-revision promotion:

```bash
python3 scripts/validate_factorforge_research_protocol.py \
  --workspace-root <factor_workspace> \
  --report-id <report_id> \
  --stage pre_promotion
```

Final synthesis approval runs `--stage final`.

Every attempt enters the full experiment library. Only verified promotion enters
the official library. Rejections and blocked routes still write workspace-local
knowledge with identity, evidence boundary, anti-pattern and reopen condition.
Repo-root knowledge is an explicit audited export only.

Keep terminal meanings disjoint: research-protocol PASS, staged EVO PASS,
Council proposal validity, factor-proof `ACCEPT|REJECT|BLOCK`, memory review,
canonical-memory promotion, external-human approval and child execution are
separate gates. `EVO_V2_TERMINAL_NO_DERIVED_LAW` is a valid research stop with
factor verdict `NOT_ISSUED`, not a factor-proof ACCEPT or REJECT.

After the Ultimate Host has attested the terminal outcome, reusable cross-factor
lessons may enter `factor-forge-researcher-memory` review. Step6 may supply
public evidence and a concise candidate, but it cannot approve or promote that
candidate. Preserve the distinction between factor verdict, protocol status,
memory-review decision, and canonical-memory generation. Only normalized
terminal `ACCEPT/REJECT` outcomes are admissible; `ACCEPT` requires formal proof
eligibility, while an evidence-bound `REJECT` may teach a bounded failure mode.
The independent reviewer must have a different session, an adapter-signed exact
claim receipt, a current canonical role-memory snapshot, and a Host
countersignature. The signed review parent/generation must still match at
promotion. Step6's own session cannot self-review its candidate, and an operator
label or direct review-CLI call is not independence proof.

## On-Demand Reference

Read `references/legacy-operations-reference.md` only for historical schemas,
legacy Council modes, detailed field lists or compatibility debugging.
