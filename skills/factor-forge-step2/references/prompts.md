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
- primary mathematical model and why it follows from the economic hypothesis;
- formula observable estimator and why it is not a raw-field restatement;
- stochastic return projection or other testable implication under `F_t`;
- discriminating tests against alternative return sources;
- expected metric signatures for Step4/Step5 falsification.

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
