> [中文版本](FIXTURE_SPEC.zh-CN.md)

# Step 3 fixture spec

## Purpose
Provide the smallest committed input package that lets Bernard/Mac exercise Step 3A/3B without private runtime state or giant data payloads.

## Current committed fixture bundle
- `factor_spec_master__sample.json`
- `alpha_idea_master__sample.json`
- `minute_input__sample.csv`
- `daily_input__sample.csv`
- `factor_impl__sample.py`

## Why this bundle is heavier than Step 1/2
The current Step 3 validators require real local input snapshots, and Step 3B requires first-run outputs when those snapshots exist.
So the honest tiny fixture for Step 3 must include both object inputs and small tabular local inputs.

## Acceptable fixture form
- synthetic but schema-truthful JSON
- tiny csv local inputs
- tiny runnable implementation file
- small enough to commit safely

## Not acceptable as fixture
- giant minute/daily snapshots
- production parquet bundles
- runtime-generated outputs relabeled as fixture inputs

## Success criterion linkage
This fixture must be sufficient for the sample command in `scripts/run_step3_sample.sh` to generate the Step 3 output artifact class set described in `docs/contracts/step3-contract.md`.
