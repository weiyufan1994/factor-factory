> [中文版本](step3-contract.zh-CN.md)

# Step 3 contract

## Current judgment
Step 3 now has a first tiny committed reproducibility substrate design, but it is more demanding than Step 1/2 because current validation requires local input snapshots and Step 3B must emit first-run outputs when they exist.

## Current committed reproducibility inputs
- `fixtures/step3/factor_spec_master__sample.json`
- `fixtures/step3/alpha_idea_master__sample.json`
- `fixtures/step3/minute_input__sample.csv`
- `fixtures/step3/daily_input__sample.csv`
- `fixtures/step3/factor_impl__sample.py`

## Current committed sample runner
- `scripts/run_step3_sample.sh`
- `scripts/run_step3_sample.py`

## Input class
- `factor_spec_master__{report_id}.json`
- `alpha_idea_master__{report_id}.json`
- tiny local minute/daily sample inputs
- runnable implementation file for Step 3B first-run generation

## Output class
- `data_prep_master__{report_id}.json`
- `qlib_adapter_config__{report_id}.json`
- `implementation_plan_master__{report_id}.json`
- generated/editable code artifacts
- first-run factor-value outputs
- `handoff_to_step4__{report_id}.json`

## Reproducibility warning
Step 3 tiny reproduction currently relies on a thin wrapper that installs fixture files into the runner-expected object and local-input paths, because the existing Step 3 scripts are built around that object contract.
