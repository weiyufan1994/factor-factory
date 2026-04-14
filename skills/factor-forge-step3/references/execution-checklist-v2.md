# Step 3 Execution Checklist (v2)

## Before run
- [ ] `factor_spec_master__{report_id}.json` exists
- [ ] `alpha_idea_master__{report_id}.json` exists
- [ ] target `report_id` is internally consistent across filename + JSON payload
- [ ] decide explicitly whether this is `sample` or `full` scope

## Step 3A
- [ ] run_step3.py executed
- [ ] data_prep_master written
- [ ] qlib_adapter_config written
- [ ] data_feasibility_report written
- [ ] local execution snapshots written when available
- [ ] minute/daily snapshot scope is internally consistent
- [ ] validate_step3.py returns PASS

## Step 3B
- [ ] run_step3b.py executed
- [ ] implementation_plan_master written
- [ ] factor code artifact written under `factorforge/generated_code/{report_id}/`
- [ ] qlib_expression_draft written
- [ ] hybrid_execution_scaffold written
- [ ] if Step 3A local snapshots exist, first-run `factor_values` artifacts are written under `factorforge/runs/{report_id}/`
- [ ] no accidental full-minute + sample-daily mixed package
- [ ] validate_step3b.py returns PASS

## Final handoff
- [ ] handoff_to_step4 exists
- [ ] execution mode is explicit
- [ ] artifact paths in handoff are real
- [ ] no placeholder residue remains
- [ ] handoff references real implementation / factor-value artifacts when available

## Release gate for ClawHub
- [ ] SKILL.md matches actual script behavior
- [ ] references describe current contracts, not stale ones
- [ ] Step 3 can be understood under low context
