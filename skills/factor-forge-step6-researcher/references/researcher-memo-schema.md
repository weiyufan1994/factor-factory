# Researcher Memo Schema

Write JSON to:

```text
factorforge/objects/research_iteration_master/researcher_memo__<report_id>.json
```

Required shape:

```json
{
  "report_id": "string",
  "factor_id": "string",
  "researcher_decision": "promote_official|iterate|reject|needs_human_review",
  "executive_summary": "string",
  "formula_review": {
    "plain_language": "string",
    "expected_signal_direction": "string",
    "what_must_be_true": ["string"],
    "what_would_break_it": ["string"]
  },
  "return_source_review": {
    "primary_source": "risk_premium|information_advantage|constraint_driven_arbitrage|mixed",
    "objective_constraints": ["string"],
    "counterparty_behavior": "string",
    "why_repeatable": "string"
  },
  "metric_review": {
    "positive_evidence": ["string"],
    "negative_evidence": ["string"],
    "ambiguities": ["string"],
    "chart_observations": ["string"],
    "monetization_gap": "string|null"
  },
  "math_discipline_review": {
    "step1_random_object": "string",
    "target_statistic": "string",
    "information_set_legality": "string",
    "spec_stability": "string",
    "signal_vs_portfolio_gap": "string",
    "revision_operator": "string",
    "generalization_argument": "string",
    "overfit_risk": ["string"],
    "kill_criteria": ["string"]
  },
  "prior_case_review": {
    "similar_cases_used": ["string"],
    "lessons_imported": ["string"],
    "novelty_vs_library": "string"
  },
  "learning_and_innovation": {
    "transferable_patterns": ["string"],
    "anti_patterns": ["string"],
    "innovative_idea_seeds": ["string"],
    "reuse_instruction_for_future_agents": ["string"]
  },
  "experience_chain": {
    "current_attempt_summary": "string",
    "prior_cases_used": ["string"],
    "failed_branches_to_preserve": ["string"],
    "what_future_agents_should_retrieve": ["string"]
  },
  "revision_taxonomy": {
    "macro_revision_options": ["string"],
    "micro_revision_options": ["string"],
    "portfolio_revision_options": ["string"],
    "stop_or_kill_rules": ["string"]
  },
  "program_search_policy": {
    "recommended_methods": ["genetic_algorithm|bayesian_search|reinforcement_learning|multi_agent_parallel_exploration"],
    "exploit_branches": ["string"],
    "explore_branches": ["string"],
    "why_not_rl_first_if_applicable": "string",
    "human_approval_required": true
  },
  "diversity_position": {
    "novelty_vs_library": "string",
    "redundancy_risk": "string",
    "official_library_diversity_value": "string"
  },
  "risk_review": {
    "failure_regimes": ["string"],
    "crowding_capacity": "string",
    "implementation_risk": "string"
  },
  "revision_brief_to_step3b": {
    "should_modify": true,
    "hypothesis": "string",
    "specific_changes": ["string"],
    "expected_metric_movement": ["string"],
    "kill_criteria": ["string"]
  },
  "knowledge_to_write_back": {
    "success_lessons": ["string"],
    "failure_lessons": ["string"],
    "reusable_heuristics": ["string"]
  }
}
```

Quality bar:

- `executive_summary` must be a real judgment, not a generic status line.
- `metric_review` must discuss both signal metrics and tradability/portfolio metrics when available.
- `revision_brief_to_step3b.specific_changes` should be concrete enough for Step3B to implement or refuse.
- `math_discipline_review` must explain why a revision improves generalization rather than merely optimizing the last backtest.
- `learning_and_innovation` must make the next researcher smarter: extract transferable patterns, anti-patterns, and at least one new idea seed when evidence allows.
- Do not use `DD-view-edge-trade`; this memo is for Factor Forge search control, not individual-stock diligence.
- When recommending iteration, distinguish genetic formula mutation, Bayesian parameter search, RL-policy advisory, and multi-agent parallel exploration. RL should be advisory unless enough revision trajectories exist.
