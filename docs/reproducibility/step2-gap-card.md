> [中文版本](step2-gap-card.zh-CN.md)

# Step 2 gap card

## Current judgment
Step 2 has now advanced beyond pure documentation: it has a first tiny committed fixture bundle design.
It is still not as clean as Step 1 because the current runner expects multiple upstream object files in fixed runtime paths.

## Already in repo
- skill wrapper under `skills/factor-forge-step2*`
- executable entry script `skills/factor-forge-step2/scripts/run_step2.py`
- contracts / reproducibility docs / sample command cards
- first tiny fixture bundle under `fixtures/step2/`

## Remaining reproducibility gaps
- the current sample path still installs fixture files into runner-expected object locations instead of consuming a clean fixture namespace directly
- engineering layer is still primarily skill-packaged
- environment/runtime declaration still needs formalization

## Next hardening step
Refactor Step 2 runner or add a thin repo-native wrapper so fixture paths can be consumed directly without object-path copying.
