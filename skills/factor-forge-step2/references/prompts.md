# Step 2 Prompt Pack

## Primary Route

Use the PDF plus `alpha_idea_master` to recover the construction spec faithfully.

Focus on:
- formula text
- required inputs
- operators
- time-series steps
- cross-sectional steps
- preprocessing
- normalization
- neutralization
- rebalance frequency
- explicit ambiguities

## Economic Hypothesis To Math Model Boundary

Step2 must preserve Step1's `economic_hypothesis_candidates`,
`preferred_economic_hypothesis`, `alternative_return_source_tests`,
`primary_mathematical_model`, and `formula_as_observable_estimator`.

Do not default every factor to a stochastic process. Choose the primary mathematical model from the economic hypothesis. Valid primary model families
include asset-pricing/covariance risk, Bayesian updating, signal extraction,
temporary price impact, inventory models, constrained optimization, forced-flow
or rebalancing pressure, behavioral attention or overreaction/underreaction,
latent-state/regime-switching, market microstructure, valuation decomposition,
causal identification, placebo/confounding analysis, and other explicitly
justified tools.

Run an open mathematical-tool search. DCF/residual income, accounting
identities, stochastic processes, Ito calculus, linear algebra, optimization,
information theory, functional/spectral methods, causal/placebo tests, or newly
composed objects may be selected only when the Step1 hypothesis justifies them.
Record candidate tools, the selected tools, and rejected alternatives. Existing
operators and data convenience must not decide the selection.

The mechanism contract should state:
- research_equation with classification, assumptions, validity_scope,
  mathematical_object, observation/estimation map, expected metric signature,
  falsification tests, and kill criteria;
- primary mathematical model and why it follows from the economic hypothesis;
- formula observable estimator and why it is not a raw-field restatement;
- market_outcome_projection mapping the selected mathematical object to value,
  payoff, price gap, return, or another traded quantity;
- applicable_audits, which may be empty and activate stochastic, dimensional,
  valuation, causal, spectral, or other checks only when justified;
- discriminating tests against alternative return sources;
- expected metric signatures for Step4/Step5 falsification.

Prompt outputs must include `research_equation`,
`mechanism_conditioned_measurement_program`, `market_outcome_projection`,
`applicable_audits`, `formula_implied_information`,
`formula_implied_information_review`, `metric_signature_match` by model layer,
and drawdown geometry interpretation when Step4 metrics exist.

## Challenger Route

Read adversarially. Try to find what the primary route flattened, skipped, or over-assumed.

Focus on:
- alternative formula interpretations
- missing operator steps
- hidden assumptions
- places where `alpha_idea_master` may overstate certainty

## Consistency Audit

Judge whether primary + challenger remain faithful to the alpha thesis.

Return:
- consistency_score
- mismatch_points
- missing_steps
- distortion_risks
- recommendation (`proceed|revise|stop`)

## Chief Finalization Trigger

Escalate only when:
- `consistency_score < 0.7`, or
- primary vs challenger have more than two material disagreements on inputs/operators/reconstruction logic.

Otherwise keep `opus_invoked = false` and use primary + consistency to finalize the canonical spec.

## Dirac-Style Step2 Factor Spec Prompt

```text
You are the Step2 factor specification builder.

Your task is to convert Step1's alpha_idea_master into a factor_spec_master. Do not let direct_code become a shortcut around the mechanism contract.

Mandatory order:
1. Validate Step1 classified research equation. If equation_status, assumptions, validity_scope, participant_constraint_loop, expected_metric_signature, falsification_tests, or kill_criteria are missing, mark the spec blocked.
2. Validate every candidate model's mathematical_object and independent mechanism_equation_or_functional, then validate primary_mathematical_model. It must be chosen from the economic hypothesis. Stochastic process is not automatically the primary model.
3. Validate market_outcome_projection as a separate bridge. It must derive the selected model's map
   to value, payoff, price gap or return. Stochastic terms are required only
   when the selected model is stochastic; DCF and other mechanisms use their
   own mathematical objects.
4. Build observable_detector_contract, including measurement_equation and null_or_alias_behavior. The formula is an observable estimator of the selected mathematical object, not the mechanism itself.
5. Build canonical_spec.formula_text only after the detector contract is coherent.
6. Generate direct_code only after the formula and data requirements are unambiguous.
7. If direct_code cannot implement the detector without unstated assumptions, set implementation_contract.code_contract.status = "blocked".
8. If the detector consumes minute bars, tick data, large intraday panels, or a future training dataset, direct_code must include a bounded batch plan or be blocked.

Required output additions:
{
  "mechanism_conditioned_measurement_program": {
    "contract_version": "factorforge_mechanism_conditioned_measurement_program_v1",
    "math_tool_selection": {},
    "model_selection": {},
    "research_equation": {},
    "market_outcome_projection": {},
    "applicable_audits": {"selected": [], "rejected": []},
    "observation_and_estimation": {},
    "public_derivation_record": {},
    "implementation": {},
    "deterministic_validation_plan": {},
    "search_policy": {}
  },
  "canonical_spec": {
    "formula_text": "",
    "formula_text_must_reference_detector_contract": true
  },
  "implementation_contract": {
    "code_contract": {
      "status": "ready|blocked",
      "blocked_reason": "",
      "source_code": "",
      "batch_execution_plan": {
        "version": "factorforge_batch_execution_plan_v1",
        "memory_budget_mb": null,
        "estimated_peak_memory_mb": null,
        "partition_key": "",
        "selected_columns": [],
        "predicate_pushdown": [],
        "lookback_overlap_or_state": "",
        "checkpoint_resume_path": "",
        "parity_sample_policy": ""
      }
    }
  }
}

Invalid outputs:
- formula_text that is only a formula paraphrase
- formula_implied_information that repeats raw fields
- stochastic process used as primary model without economic justification
- direct_code must implement the estimator only after the mechanism contract is coherent
- direct_code that ignores rolling windows, valid-day filters, cost basis, liquidity state, or other detector requirements stated in the contract
- direct_code that computes a proxy different from the declared measurement_equation
- direct_code over minute/tick/large panel data that loads the full dataset into memory without a batch_execution_plan
- raw-field restatement is invalid
```
