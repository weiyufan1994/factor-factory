> [中文版本](FIXTURE_SPEC.zh-CN.md)

# Step 4 fixture spec

## Purpose
Provide the smallest committed input package that lets Bernard/Mac exercise Step 4 execution/diagnostic logic without huge local data packages.

## Current committed fixture bundle
- `factor_spec_master__sample.json`
- `data_prep_master__sample.json`
- `handoff_to_step4__sample.json`
- `minute_input__sample.csv`
- `daily_input__sample.csv`
- `factor_impl__sample.py`

## Why this fixture is intentionally partial
The tiny local sample only covers two trade dates while the target window spans a larger period.
That is deliberate: it proves the `partial` branch honestly.

## Acceptable fixture form
- synthetic but schema-truthful JSON
- tiny csv local inputs
- tiny runnable implementation file
- small enough to commit safely

## Not acceptable as fixture
- giant minute parquet snapshots
- private EC2 runtime outputs passed off as fixture inputs
- fake success fixtures that erase the true partial-window nature of the tiny sample

## Success criterion linkage
This fixture must be sufficient for the sample command in `scripts/run_step4_sample.sh` to generate the Step 4 output artifact class set described in `docs/contracts/step4-contract.md`.
