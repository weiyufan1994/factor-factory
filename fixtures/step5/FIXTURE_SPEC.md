> [中文版本](FIXTURE_SPEC.zh-CN.md)

# Step 5 fixture spec

## Purpose
Provide the smallest committed input package that lets Bernard/Mac exercise Step 5 closure logic without relying on private runtime outputs.

## Current committed fixture bundle
- `factor_run_master__sample.json`
- `factor_spec_master__sample.json`
- `data_prep_master__sample.json`
- `handoff_to_step5__sample.json`
- `factor_run_diagnostics__sample.json`
- `evaluation_payload__sample.json`
- `factor_values__sample.csv`
- `run_metadata__sample.json`

## Why this fixture is intentionally partial-status
The tiny sample inherits a truthful partial Step 4 handoff. That is deliberate: Step 5 should prove honest closure over partial status rather than fake validated/full-window completion.

## Acceptable fixture form
- synthetic but schema-truthful JSON
- tiny csv/parquet run outputs
- tiny evaluation payload
- small enough to commit safely

## Not acceptable as fixture
- copying full archive trees from EC2 and calling them fixture design
- full private runtime output bundles when a tiny truthful closure sample will do

## Success criterion linkage
This fixture must be sufficient for the sample command in `scripts/run_step5_sample.sh` to generate the Step 5 output artifact class set described in `docs/contracts/step5-contract.md`.
