# Step 3A Data API / qlib Normalization Contract

## Goal
Provide a stable, factor-agnostic data service layer for Step 4.

## Required outputs
1. `data_prep_master__{report_id}.json`
2. `qlib_adapter_config__{report_id}.json`
3. `data_feasibility_report__{report_id}.json`
4. `handoff_to_step4__{report_id}.json`

## Data API doctrine
Step 4 must not read raw Tushare/S3 paths directly when Step 3A exists.
Step 4 should consume Step 3A output objects:
- logical dataset name
- normalized field names
- sample window
- proxy rules
- qlib-compatible field mapping

Step 3A must resolve every data leg through the FactorForge Data API catalog when a catalog is published:

- default catalog: `$FACTORFORGE_ROOT/data/catalog/data_catalog.json`
- override: `FACTORFORGE_DATA_CATALOG`
- canonical daily mart: `clean_daily_bar`
- canonical minute mart: `minute_bar`
- stable dataset schema fields: `dataset_id`, `uri`, `format`, `storage`, `columns`, `date_column`, `symbol_column`, `qlib_field_map`, `freshness`, `metadata`

During migration, if no catalog file exists, Step 3A may fall back to the existing shared clean layer and must record
`data_api_resolution.status=catalog_absent_legacy_shared_clean_fallback`. If a catalog exists but the required dataset
or fields are missing, Step 3A must not guess or rebuild data; it must write
`objects/data_requirements/factorforge_data_requirement__{report_id}.json` and mark `data_prep_master.feasibility=blocked`.
This applies to daily-only, CPV, minute/high-frequency, and daily_basic-style valuation or market-cap fields.

## qlib-normalized field expectations
- instrument -> `ts_code`
- datetime/date -> `trade_date`
- open -> `open`
- high -> `high`
- low -> `low`
- close -> `close`
- volume -> `vol`
- amount/value -> `amount`
- return_daily -> `pct_chg`

## Allowed feasibility values
- `ready`: exact fields available
- `proxy_ready`: runnable with explicit proxy substitutions
- `blocked`: critical field unavailable without acceptable substitute

## Required Data API fields

When `data_api_resolution.status=ready`, Step 3A artifacts must include:

- `data_prep_master.data_api_resolution`
- `qlib_adapter_config.data_api_resolution`
- `handoff_to_step4.data_api_resolution`
- report-scoped `runs/{report_id}/step3a_local_inputs/daily_input__{report_id}.csv`

When the Data API blocks, artifacts must include:

- `data_prep_master.data_requirement_ref`
- `qlib_adapter_config.data_requirement_ref`
- `handoff_to_step4.data_requirement_ref`
- `objects/data_requirements/factorforge_data_requirement__{report_id}.json`
