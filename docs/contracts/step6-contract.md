> [中文版本](step6-contract.zh-CN.md)

# Step 6 Contract

## Current Judgment

Step 6 is the **research-loop controller** layer.
It is not another execution backend. It consumes Step 4/5 evidence, decides whether a factor should be promoted, iterated, or rejected, writes that decision into reusable libraries, and if needed sends the workflow back to Step 3B for another implementation round.

## Mechanism Math Contract
Step6 preserves `mechanism_math_contract` under `research_memo.mechanism_analysis`, uses it to make revision hypotheses target specific mathematical objects, and includes `mechanism_math_summary` in each loop research brief. `math_model_status=invalid` blocks official promotion. `under_specified` requires an explicit reason and next human research question. The math layer is explanatory only and cannot bypass evidence audit, case comparison, search policy, loop authorization, provenance, or promotion gates.

For `math_model_status=specified`, the mechanism math contract must include a
testable `process_hypothesis`, `latent_state`, `observable_estimator`,
`conditional_distribution_hypothesis`, `relationship_shape`,
`metric_signature_match`, and `mechanism_falsification_tests`. Price-volume
covariance/correlation/rank-dependence formulas must be classified as
`price_volume_microstructure` unless the formula itself contains explicit
projection, residualization, or neutralization operators. Revision Council
packets must ingest human supplemental mechanism context from
`objects/research_iteration_master/revision_council/<report_id>/supplemental_context/`
and matching `knowledge/因子工厂/知识库/*MECHANISM*` notes, then propagate that
context into agentic taskbooks.

## Purpose

Step 6 exists to make the factor factory cumulative rather than forgetful.
It is the layer that turns one-off factor experiments into:
- a full experiment library,
- an official factor library,
- a reusable research knowledge base,
- and an iteration policy that can loop until promotion or abandonment.

## Inputs

- `factorforge/objects/factor_run_master/factor_run_master__{report_id}.json`
- `factorforge/objects/factor_case_master/factor_case_master__{report_id}.json`
- `factorforge/objects/validation/factor_evaluation__{report_id}.json`
- preferred:
  - `factorforge/objects/handoff/handoff_to_step6__{report_id}.json`
- backward-compatible fallback:
  - `factorforge/objects/handoff/handoff_to_step5__{report_id}.json`
- optional backend payloads under:
  - `factorforge/evaluations/{report_id}/{backend}/`
- optional prior iteration object:
  - `factorforge/objects/research_iteration_master/research_iteration_master__{report_id}.json`

## Outputs

- `factorforge/objects/research_iteration_master/research_iteration_master__{report_id}.json`
- mandatory loop research brief:
  - `factorforge/objects/research_iteration_master/loop_research_brief__{report_id}__iter{iteration_no}.md`
  - `factorforge/objects/research_iteration_master/loop_research_brief__{report_id}__iter{iteration_no}.json`
- `factorforge/objects/factor_library_all/factor_record__{report_id}.json`
- optional official promotion record:
  - `factorforge/objects/factor_library_official/factor_record__{report_id}.json`
- one or more knowledge writebacks under:
  - `factorforge/objects/research_knowledge_base/`
- optional next-loop handoff for Step 3B refinement:
  - `factorforge/objects/handoff/handoff_to_step3b__{report_id}.json`
- optional program-search objects:
  - `factorforge/objects/research_iteration_master/program_search_plan__{report_id}.json`
  - `factorforge/objects/research_iteration_master/search_branch_ledger__{report_id}.json`
  - `factorforge/objects/research_iteration_master/search_branch_result__{report_id}__{branch_id}.json`
  - `factorforge/objects/research_iteration_master/program_search_merge__{report_id}.json`
  - `factorforge/objects/research_iteration_master/search_branch_taskbook__{report_id}__{branch_id}.json`
  - `factorforge/research_branches/{report_id}/{branch_id}/TASKBOOK.md`

Every Step6 writeback object must preserve:

- `artifact_identity`
- `evidence_identity`
- `source_case_identity`
- `implementation_mode_decision`
- `decision_lineage`
- `knowledge_provenance`

No evidence identity, no promotion. No run/branch identity, no knowledge writeback. Similar case knowledge is not same-factor evidence unless identity matches.

Official promotion requires:

- `factor_case_master.final_status == validated`
- `evidence_quality.identity_chain_verified == true`
- successful required Step4 evidence
- complete long-side risk-adjusted evidence
- Step3B `implementation_mode_decision`
- no stale/cross-branch/cross-run identity mismatch
- no unresolved correctness risk

Iterate decisions must create child-branch lineage and must not overwrite `main`. `handoff_to_step3b` must include `parent_identity`, `new_branch_id`, `parent_run_id`, `must_preserve`, `must_change`, and `forbidden_changes`.

The provenance gate must run before any canonical Step6 writeback. If it fails, Step 6 must write only `objects/validation/step6_prewrite_block__{report_id}.json` and must not write `research_iteration_master`, `factor_library_all`, `factor_library_official`, `research_knowledge_base`, or `handoff_to_step3b`.

After the provenance gate passes, every formal Step6 loop must write a
terminal-user-readable loop research brief and link it from
`research_iteration_master.loop_research_brief`. The brief must not be an empty
template. It must use actual Step4/5/6 evidence and must cover:

- decision snapshot;
- economic interpretation;
- evidence metrics;
- chart evidence;
- metric analysis;
- knowledge comparison;
- next research direction;
- final loop conclusion.

Core metric fields cannot be empty. Missing chart files must be represented as
`missing: <reason>` while preserving all required chart keys. Long-short and
decile evidence is diagnostic-only and must never be presented as an adoption
instrument.

## Core Decision States

Step 6 must classify each factor attempt into one of these loop states:
- `promote_official`
- `iterate`
- `reject`
- `needs_human_review`

These states are distinct from Step 4 `run_status` and Step 5 `final_status`.

## research_iteration_master schema

```json
{
  "report_id": "string",
  "factor_id": "string",
  "iteration_no": 0,
  "source_case_status": "validated|partial|failed",
  "evidence_summary": {
    "run_status": "success|partial|failed",
    "backend_statuses": {
      "self_quant_analyzer": "success",
      "qlib_backtest": "success"
    },
    "headline_metrics": {}
  },
  "research_judgment": {
    "decision": "promote_official|iterate|reject|needs_human_review",
    "thesis": "string",
    "strengths": ["string"],
    "weaknesses": ["string"],
    "risks": ["string"],
    "why_now": "string|null",
    "research_memo": {
      "math_discipline_review": {},
      "learning_and_innovation": {},
      "experience_chain": {},
      "revision_taxonomy": {},
      "program_search_policy": {
        "method_library": {
          "genetic_algorithm": {},
          "bayesian_search": {},
          "reinforcement_learning": {},
          "multi_agent_parallel_exploration": {}
        },
        "recommended_next_search": {
          "branches": [],
          "requires_human_approval_before_code_change": true
        }
      },
      "diversity_position": {}
    },
    "factor_investing_framework": {
      "factor_family": "string",
      "monetization_model": "risk_premium|information_advantage|constraint_driven_arbitrage|mixed",
      "program_search_axes": {},
      "review_checklist": ["string"],
      "revision_principles": ["string"]
    }
  },
  "knowledge_writeback": {
    "success_patterns": ["string"],
    "failure_patterns": ["string"],
    "modification_hypotheses": ["string"],
    "experience_chain": {},
    "revision_taxonomy": {},
    "program_search_policy": {},
    "diversity_position": {}
  },
  "loop_action": {
    "should_modify_step3b": true,
    "modification_targets": ["string"],
    "parallel_exploration_branches": [],
    "search_methods": ["genetic_algorithm", "bayesian_search", "reinforcement_learning", "multi_agent_parallel_exploration"],
    "requires_human_approval_before_code_change": true,
    "next_runner": "step3b|stop",
    "stop_reason": "string|null"
  },
  "loop_research_brief": {
    "markdown_path": "factorforge/objects/research_iteration_master/loop_research_brief__{report_id}__iter{iteration_no}.md",
    "json_path": "factorforge/objects/research_iteration_master/loop_research_brief__{report_id}__iter{iteration_no}.json",
    "brief_version": "factorforge_loop_research_brief_v1",
    "iteration_no": 1,
    "created_at_utc": "string"
  }
}
```

## Core Rules

1. Step 6 must not reinterpret missing Step 4 evidence as success.
2. Step 6 must always write a durable judgment object, even when the decision is `reject`.
3. Every factor attempt must enter the full experiment library.
4. Only factors with explicit `promote_official` judgment may enter the official factor library.
5. Knowledge writeback must capture both success and failure patterns.
6. If the decision is `iterate`, Step 6 must point back to Step 3B with explicit modification targets.
7. Step 6 should stop the loop when the factor is either clearly promotable or clearly exhausted.
8. Step 6 is responsible for reflection and decision policy, not raw metric generation.
9. Step 6 may recommend Step 3B changes, but Step 3B remains the layer that edits implementation code.
10. Step 6 must not emit `dd_view_edge_trade`; that framework belongs to fundamental equity diligence, not Factor Forge.
11. Step 6 must preserve an `experience_chain`, including failed branches, so future agents learn from the full search trajectory.
12. Step 6 must distinguish macro revision, micro revision, portfolio revision, and stop/kill decisions.
13. Step 6 must expose a program-search method library covering genetic algorithm mutation, Bayesian parameter search, reinforcement-learning policy learning, and multi-agent parallel exploration.
14. Reinforcement learning is advisory until enough revision trajectories exist; single-factor loops should prefer controlled genetic/Bayesian/multi-branch search.
15. Iterate decisions require nonempty exploration branches and a human-approval gate before code changes.
16. Program search supplements Step6 researcher judgment; it does not replace it. Every search branch must first state return source, market-structure or objective-constraint hypothesis, knowledge-base priors, success criteria, and falsification tests.
17. `validate_step6.py` must BLOCK if the linked loop research brief is missing, the brief JSON version is not `factorforge_loop_research_brief_v1`, any of the eight main sections is absent, core metrics are empty, required chart evidence keys are absent, the long-short chart is not labeled diagnostic-only, `why_not_portfolio_fix` is empty, or the final conclusion is empty.

## Program Search Plan

When Step6 needs iteration or human review over search direction, it may write `program_search_plan__{report_id}.json`.

Required structure:

```json
{
  "report_id": "string",
  "factor_id": "string",
  "producer": "program_search_engine_v1",
  "status": "pending_human_approval",
  "research_context": {
    "metric_verdict": "supportive|mixed|negative|inconclusive",
    "signal_vs_portfolio_gap": "string",
    "return_source": "risk_premium|information_advantage|constraint_driven_arbitrage|mixed",
    "market_structure": {},
    "knowledge_priors": {}
  },
  "branches": [
    {
      "branch_id": "string",
      "branch_role": "audit|exploit|explore|portfolio|macro",
      "search_mode": "research_audit|bayesian_search|genetic_algorithm|reinforcement_learning_advisory|multi_agent_parallel_exploration",
      "status": "proposed",
      "requires_human_approval_before_execution": true,
      "research_question": "string",
      "hypothesis": "string",
      "return_source_target": "string",
      "market_structure_hypothesis": {},
      "knowledge_priors": {},
      "modification_scope": ["string"],
      "budget": {},
      "success_criteria": ["string"],
      "falsification_tests": ["string"],
      "hard_guards": ["string"],
      "expected_outputs": ["string"]
    }
  ],
  "selection_protocol": {}
}
```

Rules:

1. The plan starts as `pending_human_approval`.
2. Branches must include `research_question`, `hypothesis`, `return_source_target`, `market_structure_hypothesis`, and `knowledge_priors`.
3. Branches must include both `success_criteria` and `falsification_tests`.
4. Audit branches check evidence, data, contract, and implementation bugs before formula search.
5. Exploit branches perform local parameter search without changing the thesis.
6. Explore branches may mutate formulas but must preserve or explicitly challenge the return-source thesis.
7. Portfolio branches repair monetization expression, costs, turnover, rebalance, or bucket construction; they should not rewrite the factor thesis.
8. Macro branches challenge return-source and market-structure hypotheses rather than tuning parameters.
9. Failed branch results must be kept in the ledger.
10. A branch must be explicitly approved by a human and prepared into an isolated taskbook before execution. Branch work must stay under `factorforge/research_branches/{report_id}/{branch_id}/` and must not overwrite canonical Step3B code or handoffs.

## Search Branch Result

Each branch must write `search_branch_result__{report_id}__{branch_id}.json` after completion, failure, block, or kill.

Required structure:

```json
{
  "report_id": "string",
  "branch_id": "string",
  "branch_role": "audit|exploit|explore|portfolio|macro",
  "search_mode": "string",
  "status": "completed|failed|killed|blocked|inconclusive",
  "outcome": "improved|not_improved|bug_found|thesis_rejected|needs_more_evidence|inconclusive",
  "recommendation": "use_branch_for_next_step3b|keep_exploring|kill_branch|repair_workflow_first|needs_human_review",
  "researcher_summary": "string",
  "research_assessment": {
    "return_source_preserved_or_challenged": "string",
    "market_structure_lesson": "string",
    "knowledge_lesson": "string",
    "anti_pattern_observed": "string|null",
    "overfit_assessment": "string",
    "falsification_result": "string"
  },
  "evidence": {
    "metric_delta": {},
    "step4_artifacts": ["string"],
    "validator_results": {},
    "failure_signatures": ["string"],
    "notes": ["string"]
  },
  "human_approval_required_before_canonicalization": true
}
```

Rules:

1. Branch results must assess falsification and overfit risk.
2. A branch recommending `use_branch_for_next_step3b` must provide real Step4 evidence or equivalent artifacts.
3. `program_search_merge__{report_id}.json` is advisory only and must not update Step3B or canonical code by itself.
4. If an audit branch finds a workflow/data/contract/evidence bug, repair workflow first and do not continue formula search.

## Audit Worker

`run_program_search_audit_worker.py` is the first built-in Program Search worker.

Responsibilities:

1. Check that Step4/5/6 core objects exist.
2. Check `factor_evaluation`, backend statuses, backend payload paths, and artifact paths.
3. Check first-run factor values and run metadata from `handoff_to_step4`.
4. Check data-prep, qlib adapter, implementation plan, factor spec, and factor implementation references.
5. Check Step6 `information_set_legality`.
6. Check for legacy out-of-contract fields such as `dd_view_edge_trade`.
7. Write a standard `search_branch_result` and update `search_branch_ledger`.

Boundaries:

- no web search,
- no optimization,
- no data mutation,
- no Step3B code modification,
- remote EC2 absolute paths that are unavailable on Mac are treated as local-verification warnings, not automatic proof of failure.

## Bayesian Parameter Worker

`run_program_search_bayesian_worker.py` is the second built-in Program Search worker.

Responsibilities:

1. Run only after a `bayesian_search` / `exploit` branch has been approved and prepared.
2. Read first-run factor values and the Step3A daily snapshot from `handoff_to_step4`.
3. Search bounded, thesis-preserving local parameters.
4. Default V1 parameters are `direction`, `delay`, `smooth_window`, `winsorize_q`, and `cross_section_transform`.
5. Record each trial's params, score, Rank IC, Pearson IC, long-short spread, coverage, and failure signature.
6. Write a standard `search_branch_result` and validate it with `validate_bayesian_search_trials.py`.

Boundaries:

- no shared clean data mutation,
- no canonical Step3B mutation,
- no direct handoff updates,
- no single-IC victory claims,
- no canonicalization without Step6 merge and human approval,
- if `sklearn` is unavailable, the worker may fall back to bounded randomized coverage but must record the `selection_mode`.

## Recommended Execution Order

1. Step 4 produces metrics / backtest evidence.
2. Step 5 writes `factor_case_master`, `factor_evaluation`, and `handoff_to_step6`.
3. Step 6 consumes the Step 5 handoff and writes judgment/library/knowledge objects.
4. If the decision is `iterate`, Step 6 also writes `handoff_to_step3b` and sends the workflow back for another implementation round.

## Library Doctrine

### Full Experiment Library
Purpose: keep **all attempts**, including failures, partial runs, and dead ends.

### Official Factor Library
Purpose: keep only factors explicitly judged worthy of production-style reuse.

### Unified Research Knowledge Base
Purpose: keep portable experience such as:
- what worked,
- what failed,
- why it failed,
- what modification pattern helped,
- when a family should be abandoned.

## Recommended Loop

`Step3B -> Step4 -> Step5 -> Step6 -> Step3B ...`

Stop when one of the following becomes true:
- official promotion threshold met,
- no meaningful improvement path remains,
- human review is required before continuing.

## Research Intelligence Contract

Formal Step6 output must include these five objects under
`research_judgment.research_memo`:

- `evidence_audit`
- `mechanism_analysis`
- `case_comparison`
- `revision_strategy`
- `search_policy_decision`

`evidence_audit` must judge backend integrity, metric consistency, factor value
health, long-side evidence quality, cost/turnover risk, implementation or data
suspicions, and an `evidence_verdict` of `usable`,
`usable_with_warnings`, or `blocked`.

`mechanism_analysis` must declare the return source, factor family,
mechanism hypothesis, necessary conditions, expected and observed metric
signatures, mechanism fit, failure regimes, and what would change the
research judgment. Official promotion is forbidden when the return source is
`unknown` or mechanism fit is `contradicted`.

`revision_strategy` must revise the factor expression or Step3B code, not
portfolio expression, short-leg exposure, decile trading, or rebalance
mechanics. `iterate` decisions require at least one hypothesis with
`expression_change`, expected metric change, overfit risk, kill criteria, and
`why_not_portfolio_fix`.

`search_policy_decision` must keep human approval required unless the mode is
`kill`, and must include:

- `no_portfolio_expression_repair`
- `no_short_leg_adoption`
- `no_decile_trading`
- `no_shared_clean_data_mutation`

If `evidence_audit.evidence_verdict=blocked`, Step6 validation must BLOCK
closed-loop completion and official promotion.

## Agentic Revision Council Contract

Revision Council artifacts are advisory-only Step6 research artifacts. They are
not required for normal Step6 validation and they must not change existing
Step6 promotion, writeback, or loop-control behavior unless the main agent later
selects an approved branch through the existing human-approval and wrapper path.

The council is role-based, not bound to specific named agents. The main agent
may generate proposals itself or delegate them to subagents. In both cases, the
same proposal schema, derivation requirements, and write-scope restrictions
apply.

Allowed council write scope:

- `objects/research_iteration_master/revision_council/{report_id}/revision_council_packet__{report_id}.json`
- `objects/research_iteration_master/revision_council/{report_id}/proposal__{report_id}__{agent_role}.json`
- `objects/research_iteration_master/revision_council/{report_id}/revision_council_summary__{report_id}.json`

Forbidden council write scope:

- `objects/handoff/handoff_to_step3b__{report_id}.json`
- `generated_code/{report_id}/`
- `objects/factor_library_official/`
- `data/clean/`
- `runs/`, `evaluations/`, `archive/`
- canonical Step3B implementations
- canonical factor expressions

Ultimate wrapper integration is opt-in. `run_factorforge_ultimate.py` defaults
to `--council-mode off`. `--council-mode scaffold` runs the deterministic
Council chain after successful Step6 core, attaches the merged Council summary
back to the Step6 iteration, and reruns `validate_step6.py`. `--council-mode
auto` runs only when Step6 already indicates revision need and the evidence and
case-comparison gates are not blocked. `--council-mode agentic` requires
`--agentic-council-executor`. `none` blocks with
`BLOCK_REVISION_COUNCIL_AGENTIC_EXECUTOR_REQUIRED`; `real_agent` blocks with
`BLOCK_REVISION_COUNCIL_REAL_AGENT_NOT_IMPLEMENTED`; `local_mock` runs the
Phase K.1 contract path that creates an agentic taskbook, local mock agent
results, validates them, merges them, attaches the summary, and reruns
`validate_step6.py`. `dispatch_manifest` writes dispatch-ready task packets and
stops with `status=awaiting_agent_results`; with
`--agentic-dispatch-adapter manual_file`, it additionally writes manual
assignment markdown and result dropbox templates without merge or attach.

Agentic Council dispatch is runtime-aware but provider-agnostic. The taskbook,
dispatch manifest, task packets, manual manifest, and assignment markdown must
carry `runtime_dispatch_policy` version
`factorforge_runtime_dispatch_policy_v1`. Allowed runtimes are `codex`,
`openclaw`, `manual_file`, and `unknown`. Subagents inherit the main
model/provider by default. Factor Forge must not require a provider or select an
external provider by itself. Provider/model overrides are valid only when
recorded as explicit user requests. Codex assignments state that Codex
subagents inherit the current Codex model and must not invoke external
providers. OpenClaw assignments state that subagents inherit the main
provider/model unless explicitly overridden. Manual-file assignments state that
provider/model identity is not sufficient; only validator-passing JSON counts.

The wrapper must preserve advisory-only semantics. Council attachment may set
`final_revision_strategy.source=revision_council`, but it must not write Step3B
handoff, official records, generated code, or clean data. The wrapper records
forbidden-artifact snapshots before and after the Council chain and blocks on
any side effect.

Council proposals must be advisory, require human approval before any future
execution, and keep `execution_allowed_by_default=false`. Mathematical and
symbolic-law arguments may propose falsifiable research directions, but they
are not evidence and cannot be used as a promotion shortcut.

Every council proposal must include `derivation_record`. The derivation record
is a public, auditable research artifact for future knowledge-base reuse. It is
not hidden model chain-of-thought. It must include:

- `research_question`
- assumptions with status, necessity, and falsification path
- mathematical objects with meaning, unit or dimension, and information set
- selected tools with reasons, scope, and limitations
- rejected tools when relevant
- ordered derivation steps with formulas or symbolic relations when claimed
- derived implications and expected metric signatures
- revision hypotheses with expression direction, expected metric changes,
  falsification tests, and kill criteria
- confidence limits and an overclaim guard

A proposal without a substantive derivation record must be invalid. A council
summary must not promote a proposal into `branch_templates` unless the proposal
passes schema validation, forbidden-change guards, derivation-record checks, and
write-scope checks. No accepted derivation means no Step3B revision brief.

After Council merge, formal Council runs must also write a public derivation
appendix:

- `objects/research_iteration_master/revision_council/{report_id}/council_derivation_appendix__{report_id}.json`
- `objects/research_iteration_master/revision_council/{report_id}/council_derivation_appendix__{report_id}.md`

The appendix consolidates selected Council results' assumptions, mathematical
objects, selected tools, formula claims, derivation steps, limiting cases,
falsification tests, kill criteria, and candidate revision laws. It is a
readable research artifact for users and future agents; it remains advisory-only
and cannot authorize canonical Step3B, generated-code, official-library, clean
data, run, evaluation, or archive writes.

`symbolic_law_discovery` may use any mathematically justified tools, including
dimensional analysis, scaling laws, stochastic processes, stochastic calculus,
jump processes, stopping-time reasoning, Fourier/spectral analysis, robust
statistics, tail distributions, projection geometry, functional analysis,
dynamical systems, information theory, or market microstructure theory. It must
select tools based on formula/evidence fit and may reject tools as unjustified;
it must not apply a fixed checklist mechanically.

The deterministic local council is a scaffold/smoke/fallback mode. Scaffold
proposals must be marked `producer=deterministic_scaffold` and
`research_depth=low`; they must not be presented as deep agentic research.

## Phase M Ultimate Loop Orchestrator

`scripts/run_factorforge_ultimate_loop.py` is a thin bounded loop orchestrator
above `scripts/run_factorforge_ultimate.py`. It does not replace Step6, Council,
or any existing validator. Every formal loop pass must invoke the official
ultimate wrapper and then classify the wrapper output.

The orchestrator writes an aggregate proof and brief under
`objects/runtime_context/`:

- `ultimate_loop_report__{root_report_id}.json`
- `ultimate_loop_brief__{root_report_id}.md`

Valid stop outcomes are `promoted`, `rejected`, `exhausted`,
`awaiting_agent_results`, `max_loops_reached`, `blocked`, and `failed`. A child
revision loop is allowed only when the parent Step6 pass produced an explicit
approved Step3B handoff. The orchestrator must not invent child formulas or
branch ids, and must isolate child report ids as
`{parent_report_id}__LOOPNN__{revision_id}`.

The orchestrator is not a writer of canonical research artifacts. It must not
write Step3B handoffs, generated code, official library records, clean data, or
search-worker outputs. It may only record loop proof/brief artifacts and must
block if a child loop mutates a parent `generated_code/{report_id}` directory or
if `data/clean` changes during the loop.

When a child revision returns to Step6, the next Council packet must include
`prior_revision_memory`: parent and child report ids, parent/child formula
hashes, the executable derivation rule, parent-vs-child metric deltas, and a
prior revision outcome of `falsified`, `improved`, or `inconclusive`. If the
child worsened key evidence, agentic task packets must require
`prior_revision_outcome_review` and `repeated_revision_guard`, and must forbid
repeating the falsified derivation rule or re-creating ancestor formula hashes.
