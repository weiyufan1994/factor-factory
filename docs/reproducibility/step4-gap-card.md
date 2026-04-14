# Step 4 gap card

## Current judgment
Not yet Bernard/Mac reproducible-level.

## Already in repo
- skill wrapper under `skills/factor-forge-step4*`
- scripts: `run_step4.py`, `validate_step4.py`, `self_quant_adapter.py`, `qlib_backtest_adapter.py`
- input/output contract references

## Missing for reproducible push
- tiny committed fixture under `fixtures/step4/`
- sample run command that does not depend on huge minute parquet or private runtime outputs
- clearer separation between engineering layer and runtime artifact layer
- explicit environment/runtime declaration

## Current blocker
The code exists, but current execution semantics depend on local objects/data that are too heavy or too private to serve as Bernard/Mac reproducibility substrate.
