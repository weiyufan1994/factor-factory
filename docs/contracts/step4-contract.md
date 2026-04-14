# Step 4 contract

## Current judgment
Step 4 has real execution/evaluation code, but is not yet Bernard/Mac directly reproducible-level.

## Input class
- `factor_spec_master__{report_id}.json`
- `data_prep_master__{report_id}.json`
- `handoff_to_step4__{report_id}.json`

## Output class
- `factor_run_master__{report_id}.json`
- `factor_run_diagnostics__{report_id}.json`
- optional run artifacts under `runs/{report_id}/`
- optional backend outputs under `evaluations/{report_id}/{backend}/`
- `handoff_to_step5__{report_id}.json`

## Current code layer in repo
- `skills/factor-forge-step4/scripts/run_step4.py`
- `skills/factor-forge-step4/scripts/validate_step4.py`
- `skills/factor-forge-step4/scripts/self_quant_adapter.py`
- `skills/factor-forge-step4/scripts/qlib_backtest_adapter.py`

## Current reproducibility gap
- no tiny committed fixture under `fixtures/step4/`
- current practical execution paths still assume local objects/data beyond a formalized small fixture
- no exact committed minimal sample run command proven against a tiny fixture
- environment/runtime declaration not formalized

## Minimum reproducible push requirement
- stable code layer
- tiny committed Step 4 fixture
- exact sample run command
- explicit success criterion
- environment/runtime declaration
