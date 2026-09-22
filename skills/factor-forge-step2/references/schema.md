# Step 2 Schemas

## Current Step2 source-subject inputs

Before Step2 scoring, the Step2 researcher authors the source-subject comparison
and the existing approved intake producer lands it at the **top level of
`alpha_idea_master`**, in the active workspace's
`objects/alpha_idea_master/alpha_idea_master__<report_id>.json`. These are inputs
to `run_step2.py`, not fields supplied only in a later canonical spec or journal.
Preserve the source/producer contract; do not relabel a producer or backfill
historical research. This section is the field-location authority for the prompts.

Set `research_subject_mode` explicitly for newly scored studies:

- `report_replication`: require `source_baseline_reference` with nonempty
  `source_construction_id`, `selected_construction_id`, and
  `relation=selected_baseline`. Require an actual `source_semantic_review`
  against the selected construction, as described below.
- `source_extension`: require the same reference fields with
  `relation=source_extension`. `source_semantic_review` is optional; when supplied
  as an object its status must use the allowed values below. An extension does
  not claim paper replication or require a fabricated semantic match.
- `independent_hypothesis`: omit both report-specific reference/review objects;
  do not invent a paper baseline for the user's hypothesis.

`source_baseline_reference.selected_construction_id` must equal the **actual
primary raw spec's `construction_id`, falling back to its `factor_id`**. Other
declared AIM selected identities must agree. Merely referencing an AIM label or
mentioning source formulas elsewhere does not bind the implemented construction.

For replication, `source_semantic_review` contains
`status=match|mismatch|unassessed`, a nonempty `reviewer_basis` with source
locations and the decisive comparison, nonempty `compared_source_components`
and `compared_selected_components` arrays, and a `material_deviations` array.
Compare signs, windows, aggregation order and normalization, not only names.
`match` requires no material deviations; unresolved meaning stays `unassessed`
or `mismatch` as warranted and cannot be reported as a source match. A declared
match selects a baseline not yet evaluated; a mechanical score is not semantic
proof or successful replication. The consumer checks these declarations in
`run_step2.py:_source_subject_routing`; it does not perform the research review.

## factor_spec_raw

```json
{
  "factor_id": "string",
  "report_id": "string",
  "route": "primary|challenger",
  "raw_formula_text": "string",
  "operators": ["string"],
  "required_inputs": ["string"],
  "time_series_steps": ["string"],
  "cross_sectional_steps": ["string"],
  "preprocessing": ["string"],
  "normalization": ["string"],
  "neutralization": ["string"],
  "rebalance_frequency": "string",
  "explicit_items": ["string"],
  "inferred_items": ["string"],
  "ambiguities": ["string"]
}
```

## factor_consistency

```json
{
  "factor_id": "string",
  "report_id": "string",
  "consistency_score": 0.0,
  "matches_core_driver": true,
  "mismatch_points": ["string"],
  "missing_steps": ["string"],
  "distortion_risks": ["string"],
  "recommendation": "proceed|revise|stop"
}
```

## factor_spec_master

```json
{
  "factor_id": "string",
  "linked_idea_id": "string",
  "report_id": "string",
  "canonical_spec": {
    "formula_text": "string",
    "required_inputs": ["string"],
    "operators": ["string"],
    "time_series_steps": ["string"],
    "cross_sectional_steps": ["string"],
    "preprocessing": ["string"],
    "normalization": ["string"],
    "neutralization": ["string"],
    "rebalance_frequency": "string"
  },
  "thesis": {
    "alpha_thesis": "string",
    "target_prediction": "string",
    "economic_mechanism": "string"
  },
  "math_discipline_review": {
    "mathematical_object": "string",
    "target_statistic": "string",
    "information_set_legality": "string",
    "expected_failure_modes": ["string"]
  },
  "learning_and_innovation": {
    "similar_case_lessons_imported": ["string"],
    "innovative_idea_seeds": ["string"],
    "reuse_instruction_for_future_agents": ["string"]
  },
  "research_contract": {
    "target_statistic": "string",
    "economic_mechanism": "string",
    "economic_hypothesis": "object",
    "math_hypothesis_candidates": ["object"],
    "expected_failure_modes": ["string"],
    "innovative_idea_seeds": ["string"],
    "reuse_instruction_for_future_agents": ["string"]
  },
  "ambiguities": ["string"],
  "human_review_required": false,
  "chief_decision": "string|null",
  "opus_invoked": false
}
```

## Current formal additions and compatibility

The compact examples above are field guides, not complete runnable formal inputs.
Use [the source/producer contract](../../../docs/contracts/step2-contract.md) for
identity, producer, source type, mode and spec hashes, and
[the measurement program](../../../docs/contracts/mechanism_conditioned_measurement_program_v1.zh-CN.md)
for the exact current mathematical record carried into the Step3 handoff.

Preserve `economic_hypothesis`, `math_hypothesis_candidates`,
`factor_knowledge_context` and `knowledge_reference_contract` under the existing
`research_contract` / `learning_and_innovation` paths. Fresh malformed provenance
blocks. Only old artifacts may use
`legacy_artifact_without_retrieval_provenance` based on actual imported lessons.

The existing `research_quality_gate` carries `economic_mechanism_contract`,
`mathematical_object_contract`, `alias_elimination_matrix`, `falsification_plan`,
`claim_level_assessment`, and `reviewer_attack_memo`. A `narrative_only` record
normally routes to `miner_only` or `stop`; exploratory formal passage needs
`math_framed`, frozen trials and a valid pre-Council protocol. Missing applicable
economic/measurement/observation/alias/falsifier evidence is a quality BLOCK.

`opus_invoked` is a legacy provider-specific field, not a generic chief flag.
True requires an actual Opus adjudication. The current runner writes false by
default and does not capture all real calls. `chief_decision` is used as a
pending-review diagnostic; the formal master gate requires null on PASS. Keep
completed adjudication and actual invocations in the journal or source-semantic
review. Neither field nor a score proves a review occurred. Existing conservative
score-triggered review flags remain; do not bypass them after semantic review.

## Historical math v2 only

Preserve/validate the following shape only when already present upstream. Do not
copy it into a new study or force a latent-state interpretation. Read the legacy
v2 contract only for that compatibility task.

```json
{
  "mechanism_math_contract_v2": {
    "market_process_thesis": {
      "return_source_family": "risk_premium|information_advantage|market_structure_arbitrage|constraint_driven_arbitrage|mixed",
      "alternative_return_source_tests": [{
        "alternative_source": "string",
        "why_not_primary": "string",
        "discriminating_test": "string",
        "expected_signature_if_alternative_true": "string"
      }]
    },
    "formula_implied_information": {
      "structural_constraints": ["string"],
      "latent_state_inferred_by_formula": "string",
      "estimator_interpretation": "string",
      "why_not_raw_field_restatement": "string",
      "price_process_connection": "string"
    }
  }
}
```
