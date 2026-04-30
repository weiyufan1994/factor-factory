> [中文版本](step5-contract.zh-CN.md)

# Step 5 contract

## Purpose
Step 5 is the first case-closure and evidence-quality gate after Step 4. It must not judge alpha quality from malformed Step 4 outputs. If Step 4 evidence is missing, internally inconsistent, or obviously buggy, Step 5 must mark the case as failed/blocked and send it back for Step 4 repair.

## Inputs
- `factor_run_master__{report_id}.json`
- `factor_spec_master__{report_id}.json`
- `data_prep_master__{report_id}.json`
- `handoff_to_step5__{report_id}.json`
- Step 4 backend `evaluation_payload.json` files
- Step 4 factor values and run metadata needed for archive/case closure

## Outputs
- `factor_case_master__{report_id}.json`
- `factor_evaluation__{report_id}.json`
- archive bundle under `archive/{report_id}/`
- copied `step4_quality_gate` in both evaluation and case master

## Mandatory Step4 quality gate
Step 5 must run `step4_quality_gate` before writing a validated or partial research conclusion. The gate is an evidence-integrity check, not alpha judgment.

Blocking conditions include:

- no backend payloads despite a material Step 4 run
- backend claims success/partial but payload is missing or unreadable
- `self_quant_analyzer.standard_metric_contract` missing or blocking
- any mandatory self-quant artifact missing or empty
- `rank_ic_timeseries.png`, `pearson_ic_timeseries.png`, or `coverage_by_day.png` missing
- malformed decile return/NAV/count CSV tables
- malformed long-short return/NAV CSV tables
- NaN/Inf IC, return, count, or NAV values
- decile NAV or long-short NAV not normalized to 1.0 at the first observation
- non-positive or explosively large NAV values
- empty decile groups
- successful qlib backend missing required qlib artifacts

## Blocking semantics
If `step4_quality_gate.verdict == BLOCK`, Step 5 must:

- set `final_status = failed`
- write `bug_hypotheses`
- set `rerun_required = true`
- write a next action directing the agent to fix/re-run Step 4
- avoid treating the evidence as alpha evidence for Step 6 promotion

## Reproducibility warning
Tiny fixtures may still prove object-shape closure, but official research cases require Step 4 evidence-quality validation before Step 5/6 interpretation.
