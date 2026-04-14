# Step 1 reproducibility card

## Current judgment
Near reproducible-level, but not yet fully formalized.

## Already in repo
- engineering implementation layer under `modules/report_ingestion/**`
- prompts under `prompts/step1_*`
- schema under `schemas/report_map.schema.json`
- skill wrapper under `skills/factor-forge-step1*`

## Still needed for Bernard/Mac direct reproduction
- one tiny committed fixture input
- one exact run command card
- one success criterion card
- one environment declaration (`requirements.txt` or equivalent)

## Minimum reproducible push requirement
- keep current engineering layer
- keep skill wrapper
- add tiny fixture under `fixtures/step1/`
- add one sample run command in `scripts/run_step1_sample.sh`

## Current blocker
Fixture layer is not yet formalized.
