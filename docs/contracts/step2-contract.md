> [中文版本](step2-contract.zh-CN.md)

# Step 2 contract

## Current judgment
Step 2 now has a first tiny committed reproducibility substrate design, but it is still more upstream-artifact-dependent than Step 1.

## Current committed reproducibility inputs
- `fixtures/step2/alpha_idea_master__sample.json`
- `fixtures/step2/report_map_validation__sample__alpha_thesis.json`
- `fixtures/step2/report_map_validation__sample__challenger_alpha_thesis.json`
- `fixtures/step2/report_map__sample__primary.json`
- `fixtures/step2/sample_report_stub.pdf`

## Current committed sample runner
- `scripts/run_step2_sample.sh`
- `scripts/run_step2_sample.py`

## Input class
- `alpha_idea_master__{report_id}.json`
- primary alpha thesis artifact
- challenger alpha thesis artifact
- primary report_map artifact
- path resolution substrate sufficient for current runner

## Output class
- `factor_spec_master__{report_id}.json`
- primary raw spec artifact
- challenger raw spec artifact
- consistency audit artifact
- Step 3 handoff artifact

## Research contract fields
Step 2 is the first canonical-spec gate. `factor_spec_master` must include:
- `thesis.alpha_thesis`
- `thesis.target_prediction`
- `thesis.economic_mechanism`
- `math_discipline_review.step1_random_object`
- `math_discipline_review.target_statistic`
- `math_discipline_review.information_set_legality`
- `math_discipline_review.expected_failure_modes`
- `learning_and_innovation.similar_case_lessons_imported`
- `learning_and_innovation.innovative_idea_seeds`
- `learning_and_innovation.reuse_instruction_for_future_agents`

The Step 3 handoff must carry `research_contract`, `math_discipline_review`, and `learning_and_innovation` forward.

## Current code layer in repo
- `skills/factor-forge-step2/scripts/run_step2.py`
- `skills/factor-forge-step2/**`

## Reproducibility warning
Step 2 tiny reproduction currently depends on copying fixture objects into the runner-expected object paths because the existing Step 2 runner is built around that object contract.
