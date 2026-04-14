# Step 3 Execution Checklist

## Before run
- [ ] `factor_spec_master__{report_id}.json` exists
- [ ] `alpha_idea_master__{report_id}.json` exists
- [ ] target report_id is correct

## Step 3A
- [ ] run_step3.py executed
- [ ] data_prep_master written
- [ ] qlib_adapter_config written
- [ ] data_feasibility_report written
- [ ] validate_step3.py returns PASS

## Step 3B
- [ ] run_step3b.py executed
- [ ] implementation_plan_master written
- [ ] factor code artifact written under `factorforge/generated_code/{report_id}/`
- [ ] qlib_expression_draft written
- [ ] hybrid_execution_scaffold written
- [ ] validate_step3b.py returns PASS

## Final handoff
- [ ] handoff_to_step4 exists
- [ ] execution mode is explicit
- [ ] artifact paths in handoff are real
- [ ] no placeholder residue remains

## Release gate for ClawHub
- [ ] SKILL.md matches actual script behavior
- [ ] references describe current contracts, not stale ones
- [ ] Step 3 can be understood under low context
