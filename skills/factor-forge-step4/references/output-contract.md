# Step 4 Output Contract
- main: `factorforge/objects/factor_run_master/factor_run_master__{report_id}.json`
- diagnostics: `factorforge/objects/validation/factor_run_diagnostics__{report_id}.json`
- handoff: `factorforge/objects/handoff/handoff_to_step5__{report_id}.json`
- optional backend payload root: `factorforge/evaluations/{report_id}/{backend}/`
- allowed run_status values: `success|partial|failed`
- `factor_run_master` should expose:
  - `evaluation_plan`
  - `evaluation_results.backend_runs`
- Step 4 standardizes the run envelope, not a frozen universal metric list
