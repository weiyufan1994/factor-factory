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
- alpha_idea_master with research discipline fields

## Research discipline fields
Step 1 must preserve the original report thesis while adding enough structure for downstream review:
- `research_discipline.step1_random_object`
- `research_discipline.target_statistic_hint`
- `research_discipline.information_set_hint`
- `research_discipline.initial_return_source_hypothesis`
- `research_discipline.what_must_be_true`
- `research_discipline.what_would_break_it`
- `research_discipline.similar_case_lessons_imported`

The compatibility aliases `math_discipline_review.step1_random_object` and `learning_and_innovation.similar_case_lessons_imported` should be present for Step2/5/6 consumption.

## Engineering dependency layer
- `skills/factor_forge_step1/modules/report_ingestion/**`
- `skills/factor_forge_step1/prompts/step1_*`
- `skills/factor_forge_step1/schemas/report_map.schema.json`

## Skill wrapper layer
- `skills/factor-forge-step1*`

## Reproducibility warning
This tiny fixture proves the Step 1 artifact-class flow on Bernard/Mac, but it is not a claim that full production report complexity is reproduced.
