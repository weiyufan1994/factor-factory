# Step 6 Input Contract
- required: factor_run_master
- required: factor_case_master
- required: factor_evaluation
- preferred: handoff_to_step6
- backward-compatible fallback: handoff_to_step5
- optional: backend payloads under evaluations/{report_id}/{backend}/
- optional: prior research_iteration_master for multi-round loop state
