# Step 3 fixture spec

## Purpose
Provide the smallest committed input package that lets Bernard/Mac exercise Step 3A/3B without private runtime state or giant data payloads.

## Minimum fixture contents
- one tiny `factor_spec_master` sample object
- one tiny `alpha_idea_master` sample object if still required by current Step 3 scripts
- optional tiny `handoff_to_step3` sample

## Required fields that must remain truthful
- `report_id`
- `factor_id`
- canonical spec fields needed by Step 3A/3B
- enough sample window / input contract fields to let the runner make deterministic decisions

## Acceptable fixture form
- synthetic but schema-truthful JSON
- tiny enough to commit safely
- sufficient to test code-path correctness even if not representative of full-scale production data

## Not acceptable as fixture
- giant minute/daily data snapshots
- runtime-generated Step 3 outputs relabeled as inputs
- hidden local-only handoff dependencies

## Future target files
- `fixtures/step3/factor_spec_master__sample.json`
- optional `fixtures/step3/alpha_idea_master__sample.json`
- optional `fixtures/step3/handoff_to_step3__sample.json`

## Success criterion linkage
This fixture must be sufficient for the sample command in `scripts/run_step3_sample.sh` to generate the Step 3 output artifact class set described in `docs/contracts/step3-contract.md`.
