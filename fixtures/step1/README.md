> [中文版本](README.zh-CN.md)

# Step 1 fixtures

## Current committed fixture set
- `sample_factor_report.html`
- `sample_intake_response.json`

## Purpose
These files provide the first tiny committed Step 1 reproducibility substrate for Bernard/Mac.

## Current path exercised
- local HTML ingestion path
- structured intake parsing path
- report_map / validation artifact writing path

## Current runner
- `scripts/run_step1_sample.sh`
- `scripts/run_step1_sample.py`

## Success expectation
A successful sample run should materialize Step 1 artifact classes equivalent to:
- intake validation artifact
- report_map artifact
- alpha_thesis artifact
- ambiguity_review artifact

## Important boundary
This fixture is intentionally tiny and schema-truthful. It is not meant to represent full production report complexity.
