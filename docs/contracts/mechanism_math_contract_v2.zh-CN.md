# Mechanism Math Contract v2

`mechanism_math_contract_v2` defines the positive modelling chain for a Factor
Forge factor:

```text
market behavior -> economic hypothesis -> primary mechanism model
-> stochastic price-process projection -> formula observable estimator
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
- `formula_component_mapping`
- `expected_metric_signature`
- `falsification_tests`
- `revision_operators`
- `kill_criteria`

Validators must block decorative generic SDE language when it is not tied to
state variables, observable proxies, formula components, and falsification.

Block tokens:

- `BLOCK_MECHANISM_MATH_V2_MISSING_PRIMARY_MODEL`
- `BLOCK_MECHANISM_MATH_V2_EMPTY_STOCHASTIC_PROJECTION`
- `BLOCK_MECHANISM_MATH_V2_FORMULA_MAPPING_MISSING`
- `BLOCK_MECHANISM_MATH_V2_VAGUE_SDE`

Legacy `factorforge_mechanism_math_contract_v1` remains accepted where older
artifacts are explicitly being validated.
