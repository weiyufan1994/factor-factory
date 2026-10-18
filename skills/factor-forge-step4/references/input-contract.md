# Step 4 Input Contract
- required: factor_spec_master
- required: data_prep_master
- required: handoff_to_step4
- optional but recommended in handoff / plan: `evaluation_plan`
- if no explicit `evaluation_plan` is provided, Step 4 may default to a visible backend plan (e.g. `self_quant_analyzer` quick pass)
- if any required file is missing, run_status must be failed with exact reason
- Step 4 must preserve compatibility with old execution-shell inputs while upgrading to backend-driven evaluation
- Formal local IS may consume a reviewed research-side derivative of standard
  Data API inputs through the existing prepared-state controller. Follow
  [research-derived inputs](research-derived-inputs.md) for source/code/schema
  binding, timing, preparation and replay; a shared dataset name is not a
  substitute for estimator compatibility.
