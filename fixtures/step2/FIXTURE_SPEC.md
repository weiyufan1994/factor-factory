# Step 2 fixture spec

## Purpose
Provide the smallest committed input package that lets Bernard/Mac exercise Step 2 without relying on hidden runtime state or giant report assets.

## Minimum fixture contents
- one tiny `alpha_idea_master` sample object
- one tiny source-trace pointer or tiny report excerpt surrogate sufficient for deterministic spec extraction logic tests
- optional tiny registry/handoff stub only if the runner requires path resolution

## Required fields that must remain truthful
- `report_id`
- factor identity fields
- assembly / thesis fields required by Step 2 logic
- unresolved ambiguities if they are part of decision flow

## Acceptable fixture form
- synthetic but schema-truthful JSON
- tiny local sample source file if needed
- small enough to commit safely

## Not acceptable as fixture
- full research PDF when a tiny surrogate would do
- private runtime cache copied from local machine and called fixture
- giant upstream object bundle
- outputs from Step 2 relabeled as inputs

## Future target files
- `fixtures/step2/alpha_idea_master__sample.json`
- optional `fixtures/step2/source_trace__sample.json` or small text surrogate

## Success criterion linkage
This fixture must be sufficient for the sample command in `scripts/run_step2_sample.sh` to generate the Step 2 output artifact class set described in `docs/contracts/step2-contract.md`.
