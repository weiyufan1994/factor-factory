# Step 2 Schemas

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
    "step1_random_object": "string",
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
