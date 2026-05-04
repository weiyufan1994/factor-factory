# FactorForge S3 Data API

## Intent

FactorForge should treat S3 as the durable data lake and EC2 as a compute node. Step3 should not hard-code raw Tushare paths or materialize full local CSV snapshots when a cataloged research dataset exists.

## Layers

- Raw lake: immutable or append-only Tushare downloads under S3.
- Data mart: cleaned, qlib-normalized, research-ready parquet datasets under S3.
- Catalog/API: dataset discovery, schema description, sliced loading, and explicit data requirements when a dataset is missing.

## API Contract

The stable Python entrypoints are:

- `list_datasets(catalog_path=None)`
- `describe_dataset(dataset_id, catalog_path=None)`
- `load_dataset(dataset_id, start=None, end=None, symbols=None, columns=None, catalog_path=None)`
- `build_data_requirement(...)`
- `write_data_requirement(requirement, output_path)`

The catalog defaults to `$FACTORFORGE_ROOT/data/catalog/data_catalog.json` when `FACTORFORGE_ROOT` is set, otherwise `factorforge/data/catalog/data_catalog.json` under the repo. It can be overridden with `FACTORFORGE_DATA_CATALOG`.

Each dataset entry must expose the stable Step3A contract fields:

- `dataset_id`
- `uri`
- `format`
- `storage`
- `columns`
- `date_column`
- `symbol_column`
- `qlib_field_map`
- `freshness`
- `metadata`

The canonical Step3A daily dataset is `clean_daily_bar`. The canonical Step3A minute dataset is `minute_bar`.

## CLI

```bash
python scripts/factorforge_data_api.py list
python scripts/factorforge_data_api.py describe clean_daily_bar
python scripts/factorforge_data_api.py sample clean_daily_bar --start 20250101 --end 20250131 --columns ts_code,trade_date,close,vol --limit 5
python scripts/factorforge_data_api.py request minute_bar --frequency 1min --reason "Alpha needs intraday volume imbalance" --columns ts_code,trade_time,open,high,low,close,vol,amount --output factorforge/objects/data_requirements/minute_bar_request.json
```

## Publishing The Current Clean Daily Layer

```bash
python scripts/factorforge_data_api.py publish-clean-daily \
  --s3-uri s3://yufan-data-lake/factorforge/datamart/clean_daily_bar/v1/daily_clean.parquet
```

This uploads `daily_clean.parquet` and its metadata, then registers the dataset in the catalog.

## Data Producer Contract

When Step3 cannot find a required dataset, it should emit a `factorforge_data_requirement` object. A data agent can consume that object, build the missing mart from raw S3 data, publish parquet to S3, and register it in the catalog. FactorForge then retries Step3 against the updated catalog.

Step3A integration rule:

- If `clean_daily_bar` resolves with all required fields, Step3A materializes only the report-scoped daily slice.
- If a factor needs minute or high-frequency data, Step3A must also resolve `minute_bar` through the catalog before writing executable snapshots.
- If no catalog exists yet, Step3A may temporarily fall back to the existing shared clean layer and must record `catalog_absent_legacy_shared_clean_fallback`.
- If a catalog exists but the dataset or fields are missing, Step3A must write `objects/data_requirements/factorforge_data_requirement__{report_id}.json` and mark `data_prep_master.feasibility=blocked`.
