# Step 4 contract

## Current judgment
Step 4 now has a first tiny committed reproducibility substrate design centered on a truthful partial-window sample.

## Current committed reproducibility inputs
- `fixtures/step4/factor_spec_master__sample.json`
- `fixtures/step4/data_prep_master__sample.json`
- `fixtures/step4/handoff_to_step4__sample.json`
- `fixtures/step4/minute_input__sample.csv`
- `fixtures/step4/daily_input__sample.csv`
- `fixtures/step4/factor_impl__sample.py`

## Current committed sample runner
- `scripts/run_step4_sample.sh`
- `scripts/run_step4_sample.py`

## Input class
- factor spec
- data prep master
- handoff_to_step4
- tiny local minute/daily inputs
- runnable implementation file

## Output class
- `factor_run_master__{report_id}.json`
- `factor_run_diagnostics__{report_id}.json`
- sample run outputs under `runs/{report_id}/`
- evaluation payload(s)
- `handoff_to_step5__{report_id}.json`

## Reproducibility warning
This tiny fixture is deliberately a partial-window sample. It proves truthful Step 4 partial execution rather than pretending full-window success.
