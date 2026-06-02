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

Use stochastic return projection, Ito calculus, linear algebra, optimization,
information theory, and causal/placebo tests as `benchmark_math_tools`: they
may support projection, diagnostic, derivation, or falsification, but they do
not replace the primary model unless the Step1 hypothesis specifically selects
them. `benchmark_math_tools` must explain what each tool rules in, rules out,
or reveals about the model.

The mechanism contract should state:
- research_equation with classification, assumptions, validity_scope,
  latent_state, observable_estimator, expected metric signature,
  falsification tests, and kill criteria;
- primary mathematical model and why it follows from the economic hypothesis;
- formula observable estimator and why it is not a raw-field restatement;
- t0_t1_stochastic_benchmark showing whether the estimator affects drift,
  diffusion, jump, friction, regime transition, or observation equation;
- stochastic return projection or other testable implication under `F_t`;
- discriminating tests against alternative return sources;
- expected metric signatures for Step4/Step5 falsification.

Prompt outputs must include `research_equation`,
`t0_t1_stochastic_benchmark`, `formula_implied_information`,
`formula_implied_information_review`, `metric_signature_match` by model layer,
and drawdown geometry interpretation when Step4 metrics exist.

## Standard Formula Fields Contract

For Formula-IR/operator or hybrid formulas that reference Alpha101-style
semantic fields, Step2 must write a concrete `standard_formula_fields_contract`
instead of relying on Step3B/Step4 alias guessing.

Required standard fields include `volume`, `returns`, `vwap`, and `advN`
(`adv20`, `adv60`, etc.). The contract must state:

- `required_standard_formula_fields`
- per-field `source_candidates`
- per-field derivation rules
- per-field leakage policy
- `block_if_unavailable=true`

Minimum derivation rules:

- `volume <- vol`
- `returns <- pct_chg / 100`, or `close / pre_close - 1` when `pct_chg` is absent
- `vwap <- amount / volume` with unit policy recorded
- `advN <- rolling mean(volume, N)` with no-future-data window policy

Invalid output:

- vague text such as "derive if needed"
- `advN` without a volume source
- `vwap` without amount and volume sources
- any standard field without leakage policy

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
1. Validate Step1 classified research equation. If equation_status, assumptions, validity_scope, participant_constraint_loop, expected_metric_signature, or falsification_tests are missing, mark the spec blocked.
2. Validate primary_mathematical_model. It must be chosen from the economic hypothesis. Stochastic process is not automatically the primary model.
3. Validate t0_t1_stochastic_benchmark. For price-predictive factors, it must explain affected_terms among drift, diffusion, jump, friction, regime_transition, observation_equation.
4. Build observable_detector_contract. The formula is an observable estimator of a latent state, not the mechanism itself.
5. Build canonical_spec.formula_text only after the detector contract is coherent.
6. Generate direct_code only after the formula and data requirements are unambiguous.
7. If direct_code cannot implement the detector without unstated assumptions, set implementation_contract.code_contract.status = "blocked".

Required output additions:
{
  "mechanism_math_contract_v2": {
    "research_equation": {},
    "equation_quality": {},
    "primary_mathematical_model": {},
    "t0_t1_stochastic_benchmark": {},
    "formula_implied_information": {},
    "formula_implied_information_review": {},
    "observable_detector_contract": {"measurement_equation": "", "null_state_behavior": ""},
    "expected_metric_signature": [],
    "falsification_tests": [],
    "kill_criteria": []
  },
  "canonical_spec": {
    "formula_text": "",
    "formula_text_must_reference_detector_contract": true,
    "standard_formula_fields_contract": {
      "required_standard_formula_fields": ["volume", "returns", "vwap", "adv20"],
      "source_field_candidates": {
        "volume": ["vol"],
        "returns": ["pct_chg", "close", "pre_close"],
        "vwap": ["amount", "vol", "volume"],
        "adv20": ["volume"]
      },
      "lookback_policy": "no future data; rolling fields may use data up to factor timestamp only",
      "block_if_unavailable": true
    }
  },
  "implementation_contract": {
    "code_contract": {
      "status": "ready|blocked",
      "blocked_reason": "",
      "source_code": ""
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
- raw-field restatement is invalid
```
