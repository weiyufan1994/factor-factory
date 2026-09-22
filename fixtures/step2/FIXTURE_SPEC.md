> [中文版本](FIXTURE_SPEC.zh-CN.md)

# Step 2 fixture spec

## Purpose
Provide the smallest committed input package that lets Bernard/Mac exercise Step 2 without relying on hidden runtime state or giant report assets.

## Current committed fixture bundle
- `alpha_idea_master__sample.json`
- `report_map_validation__sample__alpha_thesis.json`
- `report_map_validation__sample__challenger_alpha_thesis.json`
- `report_map__sample__primary.json`
- `sample_report_stub.pdf`

## Why this bundle is larger than Step 1
The current Step 2 runner consumes a real upstream object bundle, not just one semantic input file.
So the honest tiny fixture for Step 2 must reflect that dependency surface.

## Required fields that must remain truthful
- `report_id`
- factor identity fields
- assembly / thesis fields required by Step 2 logic
- unresolved ambiguities if they are part of decision flow

## Acceptable fixture form
- synthetic but schema-truthful JSON
- tiny local stub for path resolution only
- small enough to commit safely

## Not acceptable as fixture
- full research PDF when a tiny surrogate will do
- private runtime cache copied from local machine and called fixture
- giant upstream object bundle beyond the minimum required set
- outputs from Step 2 relabeled as inputs

## Success criterion linkage
This fixture must be sufficient for the sample command in `scripts/run_step2_sample.sh` to generate the Step 2 output artifact class set described in `docs/contracts/step2-contract.md`.
