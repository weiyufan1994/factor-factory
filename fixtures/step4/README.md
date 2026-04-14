# Step 4 fixtures

## Current committed fixture set
- `factor_spec_master__sample.json`
- `data_prep_master__sample.json`
- `handoff_to_step4__sample.json`
- `minute_input__sample.csv`
- `daily_input__sample.csv`
- `factor_impl__sample.py`

## Purpose
These files provide the first tiny committed Step 4 reproducibility substrate for Bernard/Mac.

## Current runner
- `scripts/run_step4_sample.sh`
- `scripts/run_step4_sample.py`

## Important boundary
This sample is intentionally partial-window by construction. It is designed to yield a real `partial` Step 4 sample, not a fake `success` claim.
