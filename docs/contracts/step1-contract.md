# Step 1 contract

## Input class
A normalized report source consumed through the Step 1 ingestion pipeline.

## Recommended minimal reproducibility input
A tiny local HTML file routed through:
- `run_step1_for_html(project_root, html_path)`

## Output class
A successful Step 1 run should materialize artifacts equivalent in class to:
- intake validation artifact
- report_map artifact
- alpha_thesis artifact
- ambiguity_review artifact

## Engineering dependency layer
- `modules/report_ingestion/**`
- `prompts/step1_*`
- `schemas/report_map.schema.json`

## Skill wrapper layer
- `skills/factor-forge-step1*`

## Reproducibility warning
Skill visibility alone is not enough. Bernard/Mac direct reproduction requires the engineering layer, a tiny committed fixture, and an exact sample run command.
