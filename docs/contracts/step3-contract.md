# Step 3 contract

## Current judgment
Step 3 has substantial code and references, but is not yet Bernard/Mac directly reproducible-level.

## Input class
- `factor_spec_master__{report_id}.json`
- `alpha_idea_master__{report_id}.json`
- optional Step 2 handoff

## Output class
### Step 3A
- `data_prep_master__{report_id}.json`
- `qlib_adapter_config__{report_id}.json`
- feasibility/validation report

### Step 3B
- `implementation_plan_master__{report_id}.json`
- generated/editable code artifacts
- optional first factor-value run artifacts when local snapshots exist
- Step 4 handoff

## Current code layer in repo
- `skills/factor-forge-step3/scripts/run_step3.py`
- `skills/factor-forge-step3/scripts/run_step3b.py`
- `skills/factor-forge-step3/scripts/validate_step3.py`
- `skills/factor-forge-step3/scripts/validate_step3b.py`

## Current reproducibility gap
- no tiny committed fixture under `fixtures/step3/`
- no exact sample run path on committed small input
- code is still primarily packaged under skill-side scripts
- environment/runtime declaration is not formalized

## Minimum reproducible push requirement
- stable code layer
- tiny committed Step 3 fixture
- exact sample run command
- explicit success criterion
- environment/runtime declaration
