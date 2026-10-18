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

For a research-side transformation of supported Data API inputs, use the
[research-derived input route](../../factor-forge-step4/references/research-derived-inputs.md).
Bind the transformation's actual observation schema and reviewed code, rather
than selecting a generic derived dataset because the factor uses minute bars.
The source API catalog remains the data authority; a study-local derived
artifact need not be published as a shared Data API product.

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
