> [中文版本](step2-contract.zh-CN.md)

# Step 2 contract

## Current judgment
Step 2 is the canonical spec gate. It consumes `alpha_idea_master` from the approved Step 1 intake layer and emits `factor_spec_master`, `handoff_to_step3`, and research context for Step3B.

## Current mechanism-conditioned measurement program
`factor_spec_master` and `handoff_to_step3` carry the exact `factorforge_mechanism_conditioned_measurement_program_v1`. Step2 freezes competing mathematical models, the mechanism-selected mathematical object, estimand, observation map, implementation binding, applicable audits, falsification tests, and search invariants for operator, direct-code, and hybrid routes. No mathematical family is universally mandatory. Legacy `mechanism_math_contract` and `mechanism_math_contract_v2` objects are preserved and validated only when already present upstream; Step2 never synthesizes them for a new run.

## Current committed reproducibility inputs
- `fixtures/step2/alpha_idea_master__sample.json`
- `fixtures/step2/report_map_validation__sample__alpha_thesis.json`
- `fixtures/step2/report_map_validation__sample__challenger_alpha_thesis.json`
- `fixtures/step2/report_map__sample__primary.json`
- `fixtures/step2/sample_report_stub.pdf`

## Runner status
Sample/debug runners are archived or debug-blocked for canonical writes. Formal Step2 execution must use the approved producer contract and must not be replaced by handwritten JSON.

## Input class
- `alpha_idea_master__{report_id}.json`
- primary alpha thesis artifact
- challenger alpha thesis artifact
- primary report_map artifact
- `source_type`: one of `pdf_report`, `paper_canonical_formula`, `natural_language_hypothesis`
- approved producer metadata

`pdf_report` may resolve report registry/PDF context. `paper_canonical_formula` and `natural_language_hypothesis` must not require a local PDF.

## Output class
- `factor_spec_master__{report_id}.json`
- primary raw spec artifact
- challenger raw spec artifact
- consistency audit artifact
- Step 3 handoff artifact

Both `factor_spec_master` and `handoff_to_step3` must include:
- `contract_version = factorforge_step2_source_contract_v2`
- `source_type`
- `producer`
- `upstream_producer`
- `implementation_mode = operator | direct_code | hybrid`
- `spec_hash`
- `artifact_identity`
- `research_contract`
- `math_discipline_review`
- `learning_and_innovation`

`artifact_identity` must include `report_id`, `factor_id`, `source_type`, `implementation_mode`, `contract_version`, `producer`, `upstream_producer`, `spec_hash`, `branch_id`, and `artifact_role`. Operator mode requires `formula_hash`; direct-code mode requires `code_hash` or `code_contract_hash`; hybrid mode requires `formula_hash` and `custom_block_hash`.

## Operator formula contract

For `implementation_mode=operator`, Step2 must parse `formula_text` into `formula_ir` using `factorforge_formula_ir_v1`. The spec must carry `formula_hash`, `operator_set`, `required_fields`, `resolved_fields`, `field_aliases`, and `parse_status`. `paper_canonical_formula` sources require successful Formula IR. Unknown operators, malformed syntax, negative windows, future-looking operators, and missing field aliases are BLOCK conditions.

The qlib expression bridge is explicit supported/unsupported metadata. Unsupported qlib operators must not be silently replaced by approximate expressions. Step3B uses the pandas reference evaluator as the parity oracle for generated operator code.

## Hybrid contract

`implementation_mode=hybrid` requires `factorforge_hybrid_contract_v1`. The contract must contain an `operator_subgraph` with Formula IR, nonempty `custom_blocks`, a boundary schema, and `formula_hash`, `custom_block_hash`, and `hybrid_hash`. Missing or mismatched fields are `BLOCK_INVALID_HYBRID_CONTRACT`.

Custom blocks must declare function name, input/output schema, required fields, forbidden patterns, and source code. Operator outputs are protected by default; custom code cannot overwrite them unless the boundary explicitly allows it.

## Research contract fields
Step 2 is the first canonical-spec gate. `factor_spec_master` must include:
- `thesis.alpha_thesis`
- `thesis.target_prediction`
- `thesis.economic_mechanism`
- `math_discipline_review.mathematical_object` (`step1_random_object` is a
  legacy read alias only)
- `math_discipline_review.target_statistic`
- `math_discipline_review.information_set_legality`
- `math_discipline_review.expected_failure_modes`
- `learning_and_innovation.similar_case_lessons_imported`
- `learning_and_innovation.innovative_idea_seeds`
- `learning_and_innovation.reuse_instruction_for_future_agents`

The Step 3 handoff must carry `research_contract`, `math_discipline_review`, and `learning_and_innovation` forward.

Step3B must build `step2_research_context` from these fields and reject missing sentinel values.

## Producer gate
Allowed Step2 producers:
- `step2_pdf_report`
- `step12_canonical_formula_intake`
- `step12_hypothesis_intake`

Source-to-producer mapping is strict:
- `pdf_report` -> `step2_pdf_report`
- `paper_canonical_formula` -> `step12_canonical_formula_intake`
- `natural_language_hypothesis` -> `step12_hypothesis_intake`

Producer fields must be nonempty and allowlisted at `factor_spec_master.producer`, `factor_spec_master.upstream_producer`, `factor_spec_master.research_contract.producer`, `handoff_to_step3.producer`, and `handoff_to_step3.research_contract.producer`. Any `manual`, `debug`, `fake`, `posthoc`, `unknown`, `adhoc`, or `ad_hoc` producer string blocks formal Step3.

## Current code layer in repo
- `skills/factor-forge-step2/scripts/run_step2.py`
- `skills/factor-forge-step2/**`

## Reproducibility warning
Step 2 tiny reproduction currently depends on copying fixture objects into the runner-expected object paths because the existing Step 2 runner is built around that object contract.
