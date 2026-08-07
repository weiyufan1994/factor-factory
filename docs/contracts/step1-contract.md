> [中文版本](step1-contract.zh-CN.md)

# Step 1 contract

## Input class
Step 1 is the research source intake layer. It converts any approved research source into `alpha_idea_master`.

Approved `source_type` values:
- `pdf_report`: local PDF/HTML/report registry source.
- `paper_canonical_formula`: published or canonical formula source such as Alpha101, with source metadata and formula text.
- `natural_language_hypothesis`: user-authored research hypothesis that must be structured before Step 2.

## Current committed reproducibility input
- `fixtures/step1/sample_factor_report.html`
- `fixtures/step1/sample_intake_response.json`

## Runner status
Sample/debug runners are archived or isolated debug helpers. Formal Step1/2 intake must use an approved producer and must not hand-write downstream Step3 artifacts.

## Output class
A successful Step 1 sample run should materialize artifacts equivalent in class to:
- intake validation artifact
- report_map artifact
- alpha_thesis artifact
- ambiguity_review artifact
- alpha_idea_master with research discipline fields

`alpha_idea_master` must include:
- `source_type`
- `producer`
- `contract_version`

## Research discipline fields
Step 1 must preserve the original report thesis while adding enough structure for downstream review:
- `research_discipline.step1_mathematical_object`
- `research_discipline.target_statistic_hint`
- `research_discipline.information_set_hint`
- `research_discipline.initial_return_source_hypothesis`
- `research_discipline.what_must_be_true`
- `research_discipline.what_would_break_it`
- `research_discipline.similar_case_lessons_imported`

Current artifacts expose `math_discipline_review.mathematical_object` and
`learning_and_innovation.similar_case_lessons_imported` for Step2/5/6. Read
`step1_random_object` only as a legacy alias; do not require it in new research.

## Producer gate
Formal Step2 may only consume Step1 output from approved producers. `manual`, `debug`, `fake`, `posthoc`, `unknown`, `adhoc`, or `ad_hoc` producer strings are never allowed into formal Step3.

## Engineering dependency layer
- `skills/factor_forge_step1/modules/report_ingestion/**`
- `skills/factor_forge_step1/prompts/step1_*`
- `skills/factor_forge_step1/schemas/report_map.schema.json`

## Skill wrapper layer
- `skills/factor-forge-step1*`

## Reproducibility warning
This tiny fixture proves the Step 1 artifact-class flow on Bernard/Mac, but it is not a claim that full production report complexity is reproduced.
