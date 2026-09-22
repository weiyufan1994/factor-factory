> [中文版本](step3-gap-card.zh-CN.md)

# Step 3 gap card

## Current judgment
Step 3 has now advanced beyond pure documentation: it has a first tiny committed fixture bundle design.
It is still not as clean as Step 1 because the current Step 3 scripts expect object-path installation plus local input snapshots.

## Already in repo
- skill wrapper under `skills/factor-forge-step3*`
- scripts: `run_step3.py`, `run_step3b.py`, `validate_step3.py`, `validate_step3b.py`
- contracts / reproducibility docs / sample command cards
- first tiny fixture bundle under `fixtures/step3/`

## Remaining reproducibility gaps
- current sample path still installs fixture files into runner-expected object locations instead of consuming a direct fixture namespace
- Step 3 validation is tightly coupled to local-input snapshot presence
- environment/runtime declaration still needs formalization

## Next hardening step
Refactor Step 3 scripts or add a cleaner repo-native wrapper so committed fixture paths can be consumed directly without object-path copying and monkeypatching.
