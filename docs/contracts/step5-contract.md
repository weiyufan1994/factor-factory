# Step 5 contract

## Current judgment
Step 5 has meaningful closure/evaluation code, but is not yet Bernard/Mac directly reproducible-level.

## Input class
- `factor_run_master__{report_id}.json`
- `factor_spec_master__{report_id}.json`
- `data_prep_master__{report_id}.json`
- `handoff_to_step5__{report_id}.json`

## Output class
- `factor_case_master__{report_id}.json`
- `factor_evaluation__{report_id}.json`
- archive bundle under `archive/{report_id}/`

## Current code layer in repo
- `skills/factor-forge-step5/scripts/run_step5.py`
- `skills/factor-forge-step5/scripts/validate_step5.py`
- `skills/factor-forge-step5/modules/*.py`
- `skills/factor_forge_step5/modules/*.py`

## Current reproducibility gap
- no tiny committed fixture under `fixtures/step5/`
- no stable committed Step 4 handoff fixture designed for Mac-side reproduction
- no exact sample run command proven against tiny fixture
- environment/runtime declaration not formalized

## Minimum reproducible push requirement
- stable code layer
- tiny committed Step 5 fixture
- exact sample run command
- explicit success criterion
- environment/runtime declaration
