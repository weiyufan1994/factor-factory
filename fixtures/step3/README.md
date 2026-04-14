> [中文版本](README.zh-CN.md)

# Step 3 fixtures

## Current committed fixture set
- `factor_spec_master__sample.json`
- `alpha_idea_master__sample.json`
- `minute_input__sample.csv`
- `daily_input__sample.csv`
- `factor_impl__sample.py`

## Purpose
These files provide the first tiny committed Step 3 reproducibility substrate for Bernard/Mac.

## Current runner
- `scripts/run_step3_sample.sh`
- `scripts/run_step3_sample.py`

## Important boundary
Step 3 is the first module whose tiny fixture must include small tabular local inputs, because current validators require real `local_input_paths` and Step 3B must emit first-run factor values when local snapshots exist.
