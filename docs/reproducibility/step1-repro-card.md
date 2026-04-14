> [中文版本](step1-repro-card.zh-CN.md)

# Step 1 reproducibility card

## Current judgment
Step 1 is now the first module with a concrete tiny committed reproducibility substrate in repository form.

## Engineering implementation already in repo
- `skills/factor_forge_step1/modules/report_ingestion/**`
- `skills/factor_forge_step1/prompts/step1_*`
- `skills/factor_forge_step1/schemas/report_map.schema.json`

## Skill wrapper already in repo
- `skills/factor-forge-step1.skill`
- `skills/factor-forge-step1/**`

## Stable execution entry already in repo
Primary code entry:
- `skills/factor_forge_step1/modules/report_ingestion/orchestration/run_step1.py`

Minimal committed reproducibility runner:
- `scripts/run_step1_sample.sh`
- `scripts/run_step1_sample.py`

## Current committed fixture
- `fixtures/step1/sample_factor_report.html`
- `fixtures/step1/sample_intake_response.json`

## Current path exercised
This reproducibility substrate intentionally exercises the smallest stable Step 1 path:
1. local HTML source normalization
2. structured intake parsing
3. report_map build + schema validation
4. alpha_thesis writeout
5. ambiguity_review writeout

## Current success criterion
A Step 1 sample run is acceptable only if it produces artifact classes equivalent to:
- intake validation artifact
- report_map artifact
- alpha_thesis artifact
- ambiguity_review artifact

## Current limitation
This is a tiny schema-truthful reproducibility substrate, not a full production report reproduction pack.
It is designed to prove that Bernard/Mac can reproduce the Step 1 artifact class flow without relying on private runtime caches or giant PDFs.
