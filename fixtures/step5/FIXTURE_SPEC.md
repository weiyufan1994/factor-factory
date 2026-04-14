# Step 5 fixture spec

## Purpose
Provide the smallest committed input package that lets Bernard/Mac exercise Step 5 closure logic without relying on private runtime outputs.

## Minimum fixture contents
- one tiny `factor_run_master` sample object
- one tiny `factor_spec_master` sample object
- one tiny `data_prep_master` sample object
- one tiny `handoff_to_step5` sample object
- optional tiny evaluation payload surrogate if the code path requires it

## Required fields that must remain truthful
- `report_id`
- `factor_id`
- run status / evaluation status boundary fields used by Step 5 rules
- archive decision inputs required by current code path

## Acceptable fixture form
- synthetic but schema-truthful JSON
- tiny optional evaluation payloads
- small enough to commit safely

## Not acceptable as fixture
- copying full `archive/{report_id}` trees into git as reproducibility substrate
- copying full `objects/` runtime state without curating the minimum required inputs
- using private EC2 runtime outputs as if they were formal fixture design

## Future target files
- `fixtures/step5/factor_run_master__sample.json`
- `fixtures/step5/factor_spec_master__sample.json`
- `fixtures/step5/data_prep_master__sample.json`
- `fixtures/step5/handoff_to_step5__sample.json`

## Success criterion linkage
This fixture must be sufficient for the sample command in `scripts/run_step5_sample.sh` to generate the Step 5 output artifact class set described in `docs/contracts/step5-contract.md`.
