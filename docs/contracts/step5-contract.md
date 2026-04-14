# Step 5 contract

## Current judgment
Step 5 now has a first tiny committed reproducibility substrate design centered on a truthful partial-status closure sample.

## Current committed reproducibility inputs
- `fixtures/step5/factor_run_master__sample.json`
- `fixtures/step5/factor_spec_master__sample.json`
- `fixtures/step5/data_prep_master__sample.json`
- `fixtures/step5/handoff_to_step5__sample.json`
- `fixtures/step5/factor_run_diagnostics__sample.json`
- `fixtures/step5/evaluation_payload__sample.json`
- `fixtures/step5/factor_values__sample.csv`
- `fixtures/step5/run_metadata__sample.json`

## Current committed sample runner
- `scripts/run_step5_sample.sh`
- `scripts/run_step5_sample.py`

## Input class
- factor_run_master
- factor_spec_master
- data_prep_master
- handoff_to_step5
- tiny evaluation payload
- tiny run outputs needed for archive/case closure

## Output class
- `factor_case_master__{report_id}.json`
- `factor_evaluation__{report_id}.json`
- archive bundle under `archive/{report_id}/`

## Reproducibility warning
This tiny fixture is deliberately a partial-status closure sample. It proves truthful Step 5 closure instead of pretending validated/full-window success.
