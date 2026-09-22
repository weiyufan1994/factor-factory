# Step 3 Output Contract

## Step 3A
- main: `factorforge/objects/data_prep_master/data_prep_master__{report_id}.json`
- adapter: `factorforge/objects/data_prep_master/qlib_adapter_config__{report_id}.json`
- validation: `factorforge/objects/validation/data_feasibility_report__{report_id}.json`
- allowed feasibility values: `ready|proxy_ready|blocked`
- Step 3A should prefer a qlib-friendly normalized data contract so later Step 4 evaluators can reuse qlib operator / strategy / backtest interfaces with minimal reshaping.
- preferred normalized semantics:
  - primary entity key: `instrument`
  - primary time key: `datetime`
  - source aliases may remain in raw snapshots (`ts_code`, `trade_date`) but adapter config must declare the mapping explicitly
  - feature columns are append-only and extensible; adding fields like `pe`, `pb`, `market_cap`, `industry_code`, or custom risk/alpha columns should not require contract redesign

## Step 3B
- plan: `factorforge/objects/implementation_plan_master/implementation_plan_master__{report_id}.json`
- code: `factorforge/generated_code/{report_id}/factor_impl__{report_id}.py` (preferred) or `factor_impl_stub__{report_id}.py`
- draft expression: `factorforge/generated_code/{report_id}/qlib_expression_draft__{report_id}.json`
- execution scaffold: `factorforge/generated_code/{report_id}/hybrid_execution_scaffold__{report_id}.json`
- handoff: `factorforge/objects/handoff/handoff_to_step4__{report_id}.json`
- Step2 research context carried into all Step3B artifacts:
  - `step2_research_context.target_statistic`
  - `step2_research_context.economic_mechanism`
  - `step2_research_context.expected_failure_modes`
  - `step2_research_context.reuse_instruction_for_future_agents`
  - `step2_research_context.implementation_invariants`
- schema field expected in plan / handoff when local snapshots exist:
  - `first_run_outputs.status`
  - `first_run_outputs.output_paths`
  - `first_run_outputs.run_metadata_path`
  - `first_run_outputs.producer`

## Non-formal sample proof (when a sample query and executable code exist)
- `factorforge/runs/{report_id}/step3b_sample_factor_values__{report_id}.parquet`
- optional CSV under the explicit output policy
- `factorforge/runs/{report_id}/step3b_sample_run_metadata__{report_id}.json`
- metadata: `is_formal_factor_values=false`, `purpose=step3_executability_proof`, `formal_factor_values_owner=Step4`
- sample fields above and `first_run_outputs` are not formal execution completion
- formal `factor_values` / metrics / NAV / plots remain Step4-owned

## Contract integrity rules
- `report_id` must agree across filename, JSON payload, and handoff refs
- Step3B must consume Step2's `factor_spec_master` plus optional `handoff_to_step3`; it must not strip the research contract down to only a formula
- `step2_research_context` must be identical across implementation plan, qlib expression draft, hybrid scaffold, and Step4 handoff
- `missing_*` Step2 research-context sentinel values are validation failures, not acceptable defaults
- local input snapshot scope must be internally consistent across minute/daily layers
- missing sample proof needs an explicit reason; a plan-only PASS does not establish sample executability, and sample proof never releases Step4 without Step2 review and post-review tests
- qlib-facing outputs should preserve a stable semantic mapping for:
  - `instrument` ↔ raw code field (e.g. `ts_code`)
  - `datetime` ↔ raw date/time fields (e.g. `trade_date`, `trade_time`)
  - append-only feature columns
- Python factor implementations may stay imperative/custom, but their outputs should be transformable into qlib-friendly signal tables without ad-hoc per-factor schema invention

## Data and downstream continuity

Normalize supported source dates (`YYYYMMDD`, `YYYY-MM-DD`, Timestamp) to stable
`YYYYMMDD`-compatible output keys through the shared date contract. Preserve
`implementation_mode_decision` in plan, generated-code metadata, handoff, sample
metadata when generated and the Ultimate report.

Where present, retain the downstream surfaces `standard_formula_fields_contract`,
`acceptance_summary`, `qlib_native_status`, `evidence_status`,
`formula_implied_information`, `metric_anomaly_review`,
`model_linked_metric_signature`, `volatility_drag`, `drawdown_recovery_area`,
`component_ablation`, and `direction_losing_transform_review`. They are not
permission for Step3B to generate Step4 metrics or invent unavailable evidence.
