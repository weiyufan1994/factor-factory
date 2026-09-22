# Step 3 Execution Checklist (v2)

Use the active Ultimate wrapper; the Step script names below identify internal
work, not direct formal entrypoints.

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
- [ ] when a Data API sample contract and executable code exist, only bounded non-formal `step3b_sample_factor_values` and sample metadata are written; formal values remain Step4-owned
- [ ] no accidental full-minute + sample-daily mixed package
- [ ] direct_code/hybrid child revisions preserve implementation mode and include executable mutation contracts
- [ ] minute/tick/large-panel direct_code includes `batch_execution_plan.version=factorforge_batch_execution_plan_v1`
- [ ] prior OOM/exit-137/Killed evidence is handled by batch mode or `BLOCK_MEMORY_PRESSURE_BATCH_REQUIRED`, not blind retry
- [ ] validate_step3b.py returns PASS

## Final handoff
- [ ] handoff_to_step4 exists
- [ ] execution mode is explicit
- [ ] artifact paths in handoff are real
- [ ] no placeholder residue remains
- [ ] handoff references exact implementation and non-formal sample artifacts when available
- [ ] before Step4 release: Step2 reviewed actual code/helpers, Step3 fixed and Step2 re-reviewed, then deterministic/parity tests passed on the reviewed version

## Release gate for ClawHub
- [ ] SKILL.md matches actual script behavior
- [ ] references describe current contracts, not stale ones
- [ ] Step 3 can be understood under low context
