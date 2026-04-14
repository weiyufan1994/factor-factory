# Step 1 reproducibility card

## Current judgment
Step 1 is the closest module to Bernard/Mac reproducible-level because the repository already contains both:
- engineering implementation layer
- skill wrapper layer

It is not yet fully formalized, but it is the right first module to harden.

## Engineering implementation already in repo
- `modules/report_ingestion/**`
- `prompts/step1_*`
- `schemas/report_map.schema.json`

## Skill wrapper already in repo
- `skills/factor-forge-step1.skill`
- `skills/factor-forge-step1/**`

## Stable execution entry already in repo
Primary code entry:
- `modules/report_ingestion/orchestration/run_step1.py`

Key callable:
- `run_step1_for_html(project_root, html_path)`

Pipeline wiring:
- `modules/report_ingestion/orchestration/wiring.py`
- `modules/report_ingestion/orchestration/step1_pipeline.py`

## Current reproducibility substrate
The repo already shows a sample-report lineage around:
- `objects/report_maps/report_map__RPT_html_5c40499c_sample_factor_report__primary.json`
- `objects/report_maps/report_map__RPT_html_5c40499c_sample_factor_report__challenger.json`
- `objects/validation/report_map_validation__RPT_html_5c40499c_sample_factor_report.json`

This proves that Step 1 already has at least one sample-shaped path in the repository history.

## What is still missing for Bernard/Mac direct reproduction
1. one tiny committed HTML fixture under `fixtures/step1/`
2. one exact sample run command that does not depend on hidden runtime state
3. one explicit success criterion
4. one explicit environment declaration (`requirements.txt` / `pyproject.toml` or equivalent)

## Minimum reproducible push requirement
For Step 1 to be honestly called Bernard/Mac reproducible-level, the repository should contain all of these simultaneously:
- engineering implementation layer
- skill wrapper layer
- tiny fixture input
- exact sample command
- explicit success criterion

## Proposed immediate fixture strategy
Use a tiny local HTML sample under:
- `fixtures/step1/sample_factor_report.html`

Then define one deterministic sample command via:
- `scripts/run_step1_sample.sh`

## Proposed success criterion
A Step 1 sample run should be judged successful only if it produces all of the following from the fixture path:
- intake-like validation artifact
- report_map artifact
- alpha_thesis artifact
- ambiguity_review artifact

## Current blocker
The main blocker is no committed tiny fixture yet. The code and packaging layers are already much stronger than later steps.
