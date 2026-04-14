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
- schema field expected in plan / handoff when local snapshots exist:
  - `first_run_outputs.status`
  - `first_run_outputs.output_paths`
  - `first_run_outputs.run_metadata_path`
  - `first_run_outputs.producer`

## First-run factor value outputs (mandatory when Step 3A local snapshots exist)
- `factorforge/runs/{report_id}/factor_values__{report_id}.parquet`
- `factorforge/runs/{report_id}/factor_values__{report_id}.csv`
- `factorforge/runs/{report_id}/run_metadata__{report_id}.json`

## Contract integrity rules
- `report_id` must agree across filename, JSON payload, and handoff refs
- local input snapshot scope must be internally consistent across minute/daily layers
- a Step 3B PASS without factor values is only acceptable when no Step 3A local execution snapshots exist
- qlib-facing outputs should preserve a stable semantic mapping for:
  - `instrument` ↔ raw code field (e.g. `ts_code`)
  - `datetime` ↔ raw date/time fields (e.g. `trade_date`, `trade_time`)
  - append-only feature columns
- Python factor implementations may stay imperative/custom, but their outputs should be transformable into qlib-friendly signal tables without ad-hoc per-factor schema invention
