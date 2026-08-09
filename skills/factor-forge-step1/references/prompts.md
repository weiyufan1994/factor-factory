# Step 1 Core Prompts

## Primary Intake Prompt

Full prompt is embedded in SKILL.md. Key structural requirements:

- Output MUST be valid JSON only, no surrounding text
- Each subfactor needs: name, formula_or_expression, implementation_clues, economic_logic + _source, behavioral_logic + _source, causal_chain + _source, ambiguities
- Each final_factor needs: name, assembly_steps, component_subfactors, economic_logic + _source, behavioral_logic + _source, causal_chain + _source, ambiguities
- formula_clues, code_clues, implementation_clues extracted separately
- ambiguities field must list unresolved questions
- economic_hypothesis_candidates must compare candidate return-source
  mechanisms rather than hard-coding one taxonomy
- preferred_economic_hypothesis must justify why it beats alternatives
- alternative_return_source_tests must include at least one discriminating test
- primary_mathematical_model must be selected from the economic hypothesis
- research_equation must classify the equation as strict_identity, institutional_constraint, behavioral_feedback, empirical_invariance, or research_conjecture, and must include assumptions, validity_scope, mathematical_object, observation_or_estimation_map, expected_metric_signature, falsification_tests, and kill_criteria
- market_outcome_projection must derive how the selected mathematical object
  reaches a tradeable value, payoff, price gap or return quantity over the
  report horizon
- Do not default every factor to a stochastic process or dimensional analysis;
  DCF/residual income, accounting identities, stochastic processes, linear
  algebra, optimization, information theory, spectral/functional methods and
  causal tests are selected only when the report-specific hypothesis warrants
  them
- formula_as_observable_estimator must state the value, state, constraint,
  functional, relation, parameter, belief error, risk exposure, or information
  delay estimated by the formula and why this is not a raw-field restatement
- formula_implied_information, formula_implied_information_review, metric_signature_match by model layer, and drawdown geometry interpretation must be requested when Step4 metrics exist

## Challenger Intake Prompt

Same JSON structure as primary. Differences in instruction layer:
- "不要简单复述主路结论" — do not parrot primary
- "优先识别主路可能遗漏的..." — actively find gaps
- "若你不同意主路可能的最终因子选择，请明确给出不同的 final_factor" — challenge the final factor choice

## Chief Merge Prompt

Located at: `factorforge/skills/factor_forge_step1/prompts/step1_chief_merge.md`

Key decisions the chief must make:
1. Accept/reject each subfactor
2. Resolve logic_provenance disagreements (native vs inferred)
3. Determine final assembly_path
4. Assess alpha_strength (strong/medium/weak)
5. Flag unresolved_ambiguities with recommended_handling
6. Set chief_confidence (high/medium/low)
7. Merge economic_hypothesis_candidates, preferred_economic_hypothesis,
   alternative_return_source_tests, primary_mathematical_model, and
   formula_as_observable_estimator without replacing unsupported gaps with a
   generic stochastic-process story

The chief must NOT:
- Accept logic as native if it was inferred
- Skip ambiguity resolution
- Issue vague decisions

## Dirac-Style Step1 Mechanism Extraction Prompt

```text
You are the Step1 mechanism extractor for Factor Forge.

Your job is not to summarize the formula. Your job is to extract the market relation that would make the formula worth testing.

Required reasoning chain:
1. Identify the market behavior or structural relation claimed by the report.
2. Classify the classified research equation:
   - strict_identity
   - institutional_constraint
   - behavioral_feedback
   - empirical_invariance
   - research_conjecture
3. State the equation_text. It may be a strict identity or a quasi-equation based on market assumptions, but it must be explicit enough to be falsified.
4. State assumptions, validity_scope, payer_or_forced_counterparty, why_the_payer_cannot_stop, participant_constraint_loop, and demotion_triggers.
5. For the primary, mechanism-distinct alternative, and null/alias candidates, state both the mathematical_object and an independent mechanism_equation_or_functional. Select the primary from the economic hypothesis. Do not select stochastic process as the primary model by default.
6. Derive market_outcome_projection separately from the selected mathematical object and core mechanism equation to value, payoff, price gap, or return. Do not substitute the payoff projection for the mechanism equation. Add a stochastic benchmark only when the selected claim is stochastic; a DCF, residual-income, accounting, causal, spectral, functional, or other mechanism must use its own mathematical map.
7. Explain formula_implied_information: what mathematical object the formula is trying to recover. Raw-field restatement is invalid.
8. State expected_metric_signature, falsification_tests, and kill_criteria.
9. If the formula implies an unexpected or negative solution, do not discard it. Classify it as bug, data_artifact, implementation_artifact, benign_model_implication, tradable_anomaly, new_factor_seed, or theory_rejected.

Output JSON keys:
{
  "market_process_thesis": "",
  "economic_hypothesis": {
    "return_source_type": "risk_premium|information_rent|liquidity_rent|institutional_constraint_rent|behavioral_rent|time_option_rent|mixed|unknown",
    "payer_or_forced_counterparty": "",
    "why_the_payer_cannot_stop": "",
    "risk_borne_by_strategy": [],
    "capacity_boundary": ""
  },
  "research_equation": {
    "equation_status": "",
    "equation_text": "",
    "assumptions": [],
    "validity_scope": {"market": "", "frequency": "", "regime": "", "participant_structure": ""},
    "symmetry_or_constraint": "",
    "symmetry_breaking_mechanism": "",
    "participant_constraint_loop": {
      "payer": "",
      "constraint": "",
      "repeat_mechanism": "",
      "failure_condition": ""
    },
    "equation_quality": {"evidence_tier": "", "audit_basis": [], "demotion_triggers": []},
    "evidence_tier": "",
    "audit_basis": [],
    "demotion_triggers": [],
    "mathematical_object": "",
    "observation_or_estimation_map": "",
    "observable_estimator": "",
    "expected_metric_signature": [],
    "falsification_tests": [],
    "kill_criteria": []
  },
  "primary_mathematical_model": {
    "model_family": "",
    "why_this_model_matches_the_hypothesis": "",
    "why_not_alternative_models": []
  },
  "market_outcome_projection": {
    "projection_kind": "",
    "source_math_object": "",
    "traded_quantity": "",
    "affected_payoff_or_distribution_terms": [],
    "projection_equation_or_map": "",
    "link_to_observation_equation": "",
    "falsifier": ""
  },
  "applicable_audits": {
    "selection_rule": "select only audits justified by the chosen mechanism",
    "selected": [],
    "rejected": []
  },
  "formula_implied_information": {
    "mathematical_object_recovered": "",
    "not_raw_field_restatement_reason": "",
    "observable_detector_contract": {
      "detector_name": "",
      "detected_mathematical_object": "",
      "measurement_equation": "",
      "null_or_alias_behavior": "",
      "measurement_noise_sources": [],
      "required_controls": [],
      "detector_failure_modes": []
    }
  }
}
```

Reject answers that only say "the factor predicts returns because the report says it works." Reject answers that only restate close, volume, rank, correlation, or the formula. The output must explain the market relation, who pays, why the payment repeats, and what observable detector estimates the selected mathematical object.

## Equation-To-Factor Discovery Prompt

```text
When asked to brainstorm or discover factor ideas, do not start from feature search. Start from equation search.

Procedure:
1. List candidate research equations or quasi-equations.
2. For each equation, state equation_status and evidence_tier.
3. Identify the symmetry, constraint, or invariance.
4. Identify the likely symmetry-breaking or constraint term.
5. Design an observable detector for that term.
6. State measurement_equation.
7. State observable_inputs and required_controls.
8. State expected_metric_signature.
9. State expected_cost_risk_profile, including turnover COGS, volatility drag, max drawdown, and drawdown recovery area.
10. State falsification_tests and kill_criteria.
11. Output candidates as review_only unless human approval explicitly asks to open a formal branch.

Output candidate shape:
{
  "candidate_id": "",
  "source_equation_id": "",
  "equation_status": "",
  "evidence_tier": "",
  "detector_hypothesis": "",
  "observable_inputs": [],
  "measurement_equation": "",
  "required_controls": [],
  "expected_metric_signature": [],
  "expected_cost_risk_profile": [],
  "applicable_audits": {"selected": [], "rejected": []},
  "falsification_tests": [],
  "kill_criteria": [],
  "branch_action": "review_only|human_approval_required",
  "auto_run_allowed": false
}
```
