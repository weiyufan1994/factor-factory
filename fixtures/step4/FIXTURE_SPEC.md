# Step 4 fixture spec

## Purpose
Provide the smallest committed input package that lets Bernard/Mac exercise Step 4 execution/diagnostic logic without huge local data packages.

## Minimum fixture contents
- one tiny `factor_spec_master` sample object
- one tiny `data_prep_master` sample object
- one tiny `handoff_to_step4` sample object
- if Step 4 requires value-level input, use a tiny controlled sample dataset rather than production parquet

## Required fields that must remain truthful
- `report_id`
- `factor_id`
- execution-path fields required by the runner
- enough evaluation-plan / handoff detail for visible backend decisions

## Acceptable fixture form
- synthetic but schema-truthful JSON
- tiny tabular sample if strictly needed
- small enough to commit safely

## Not acceptable as fixture
- full minute parquet snapshots
- private local run outputs copied from EC2 and called fixture
- giant evaluations directory used as a stand-in for reproducibility

## Future target files
- `fixtures/step4/factor_spec_master__sample.json`
- `fixtures/step4/data_prep_master__sample.json`
- `fixtures/step4/handoff_to_step4__sample.json`
- optional tiny tabular sample in csv/json form

## Success criterion linkage
This fixture must be sufficient for the sample command in `scripts/run_step4_sample.sh` to generate the Step 4 output artifact class set described in `docs/contracts/step4-contract.md`.
