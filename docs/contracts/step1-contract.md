> [中文版本](step1-contract.zh-CN.md)

# Step 1 contract

## Input class
A normalized report source consumed through the Step 1 ingestion pipeline.

## Current committed reproducibility input
- `fixtures/step1/sample_factor_report.html`
- `fixtures/step1/sample_intake_response.json`

## Current committed sample runner
- `scripts/run_step1_sample.sh`
- `scripts/run_step1_sample.py`

## Output class
A successful Step 1 sample run should materialize artifacts equivalent in class to:
- intake validation artifact
- report_map artifact
- alpha_thesis artifact
- ambiguity_review artifact

## Engineering dependency layer
- `skills/factor_forge_step1/modules/report_ingestion/**`
- `skills/factor_forge_step1/prompts/step1_*`
- `skills/factor_forge_step1/schemas/report_map.schema.json`

## Skill wrapper layer
- `skills/factor-forge-step1*`

## Reproducibility warning
This tiny fixture proves the Step 1 artifact-class flow on Bernard/Mac, but it is not a claim that full production report complexity is reproduced.
