# Mechanism Math Contract v2

`mechanism_math_contract_v2` defines the positive modelling chain for a Factor
Forge factor:

```text
market behavior -> economic hypothesis -> primary mechanism model
-> stochastic price-process projection -> formula-implied information
-> formula observable estimator
-> expected metric signature -> falsification / revision logic
```

The primary mechanism model is selected from the economic hypothesis. It is not
always a stochastic process. Valid model families include stochastic process,
microstructure response function, dimensional/scaling analysis, potential or
barrier models, entropy/information models, spectral/wavelet models,
copula/dependence models, regime switching, behavioral constraints, inventory
or execution models, and network/contagion models.

Every formal factor must still state a stochastic price-process projection:
given information set `F_t`, how does the signal change the conditional
distribution of `r_{t+1}`? The projection may affect drift, diffusion, jump
intensity, liquidity friction, regime transition, or the observation equation.

Required top-level sections:

- `market_process_thesis`
- `primary_mechanism_model`
- `stochastic_price_process_projection`
- `formula_implied_information`
- `formula_implied_information_review`
- `formula_component_mapping`
- `expected_metric_signature`
- `falsification_tests`
- `revision_operators`
- `kill_criteria`

`market_process_thesis` must classify the primary return source and include
`alternative_return_source_tests`. At least one test must name a non-primary
source such as risk premium, information advantage, market-structure arbitrage,
or constraint-driven arbitrage, explain why it is not primary, provide a
discriminating test, and state the metric signature that would support the
alternative.

`formula_implied_information` must explain what the formula reveals about the
market process:

- `structural_constraints`: constraints imposed by the formula/operator/input
  structure;
- `latent_state_inferred_by_formula`: the latent/model state recovered by the
  formula;
- `estimator_interpretation`: how the formula acts as an estimator;
- `why_not_raw_field_restatement`: why this is not merely `close`, `volume`, or
  another raw field;
- `price_process_connection`: how the inferred state changes drift, diffusion,
  jump intensity, friction, regime transition, or observation equation.

Validators must block decorative generic SDE language when it is not tied to
state variables, observable proxies, formula components, and falsification.
They must also block formula-implied-information sections that merely restate
raw fields or formula calls instead of naming a latent/model state.

`formula_implied_information_review` is the Dirac-style anomaly review layer.
It asks whether the formula structure or the evidence implies information that
was not explicit in the original economic hypothesis. It must not discard
unexpected or negative implications before classification. Each unexpected
implication must include:

- `implication`
- `why_unexpected`
- `source`: `formula_structure | metrics | implementation | data`
- `classification`: one of `implementation_bug`, `data_artifact`,
  `specification_ambiguity`, `economic_hypothesis_wrong`,
  `primary_model_wrong`, `stochastic_projection_wrong`,
  `observable_estimator_mismatch`, `tradable_anomaly`, `new_factor_seed`,
  `regime_specific_solution`, or `capacity_or_friction_bound_solution`
- `responsible_model_layer`
- `discriminating_test`
- `expected_signature_if_real`
- `expected_signature_if_artifact`
- `recommended_action`

If classification is `tradable_anomaly` or `new_factor_seed`, the Council
proposal must include a branch law, expected metric signature, and kill
criteria. If classification is `implementation_bug` or `data_artifact`, the
system must route to implementation/data audit rather than research promotion.

Block tokens:

- `BLOCK_MECHANISM_MATH_V2_MISSING_PRIMARY_MODEL`
- `BLOCK_MECHANISM_MATH_V2_EMPTY_STOCHASTIC_PROJECTION`
- `BLOCK_MECHANISM_MATH_V2_FORMULA_MAPPING_MISSING`
- `BLOCK_MECHANISM_MATH_V2_VAGUE_SDE`
- `BLOCK_MECHANISM_MATH_V2_RETURN_SOURCE_REVIEW_MISSING`
- `BLOCK_MECHANISM_MATH_V2_FORMULA_IMPLIED_INFORMATION_MISSING`
- `BLOCK_MECHANISM_MATH_V2_FORMULA_IMPLIED_INFORMATION_RESTATEMENT`
- `BLOCK_MECHANISM_MATH_V2_FORMULA_IMPLIED_REVIEW_MISSING`
- `BLOCK_COUNCIL_UNCLASSIFIED_UNEXPECTED_IMPLICATION`
- `BLOCK_COUNCIL_ANOMALY_BRANCH_LAW_MISSING`

Legacy `factorforge_mechanism_math_contract_v1` remains accepted where older
artifacts are explicitly being validated.
