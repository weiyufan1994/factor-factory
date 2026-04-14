# Step 4 gap card

## Current judgment
Step 4 has now advanced beyond pure documentation: it has a first tiny committed fixture bundle design centered on a truthful partial sample.

## Already in repo
- skill wrapper under `skills/factor-forge-step4*`
- run/validate scripts and backend adapters
- contracts / reproducibility docs / sample command cards
- first tiny fixture bundle under `fixtures/step4/`

## Remaining reproducibility gaps
- current sample path still installs fixture files into runner-expected object locations instead of consuming a direct fixture namespace
- backend diversity is not yet exercised in the tiny sample path (current tiny sample uses self_quant quick path)
- environment/runtime declaration still needs formalization

## Next hardening step
Refactor Step 4 runner or add a cleaner repo-native wrapper so committed fixture paths can be consumed directly without object-path copying.
