# Step 2 contract

## Current judgment
Step 2 is code-visible and skill-visible, but not yet Bernard/Mac directly reproducible-level.

## Input class
- `alpha_idea_master__{report_id}.json`
- optional Step 1 handoff / registry context
- report PDF or equivalent source-trace path

## Output class
- `factor_spec_master__{report_id}.json`
- primary raw spec artifact
- challenger raw spec artifact
- consistency audit artifact
- Step 3 handoff artifact

## Current code layer in repo
- `skills/factor-forge-step2/scripts/run_step2.py`
- `skills/factor-forge-step2/**`

## Current reproducibility gap
- no tiny committed fixture under `fixtures/step2/`
- no exact sample run command proven against committed fixture
- engineering layer is still primarily skill-packaged, not clearly separated into repo-native source + fixture + runner
- skill text still contains path/structure assumptions that should be reconciled with current repository state before calling it reproducible-level

## Minimum reproducible push requirement
- stable code layer
- tiny committed Step 2 input fixture
- exact sample run command
- explicit success criterion
- environment/runtime declaration
