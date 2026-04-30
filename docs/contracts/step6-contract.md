> [中文版本](step6-contract.zh-CN.md)

# Step 6 Contract

## Current Judgment

Step 6 is the **research-loop controller** layer.
It is not another execution backend. It consumes Step 4/5 evidence, decides whether a factor should be promoted, iterated, or rejected, writes that decision into reusable libraries, and if needed sends the workflow back to Step 3B for another implementation round.

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
