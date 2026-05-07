# Factor Data API Architecture

## Purpose

`factor_factory.data_api` is an independent read-only data access package for factor research. It is intentionally separate from Factor Forge Step3 and can be imported by Factor Forge, Bernard, Humphrey, Codex, notebooks, or future agents.

The API answers one question:

```text
Given dataset + date range + stock universe + fields, return a validated DataFrame and metadata.
```

It does not write Factor Forge artifacts and does not mutate clean data.

## Public API

```python
from factor_factory.data_api import DataApiClient, DataQuery

client = DataApiClient.from_default_catalog()
result = client.fetch(
    DataQuery(
        dataset="clean_daily_bar",
        start_date="20160101",
        end_date="20260424",
        universe="a_share_all",
        fields=["open", "high", "low", "close", "vol", "amount"],
        frequency="daily",
    )
)

frame = result.frame
schema = result.schema
coverage = result.coverage
```

Supported constructors:

```python
DataApiClient.from_default_catalog()
DataApiClient.from_catalog("/path/to/data_catalog.json")
DataApiClient.from_env()
```

Convenience wrappers are available:

```python
client.get_daily_bars(...)
client.get_daily_basic(...)
client.get_minute_bars(...)
```

## Catalog Resolution

Catalog lookup order:

1. `FACTORFORGE_DATA_CATALOG`
2. `$FACTORFORGE_ROOT/data/catalog/data_catalog.json`
3. repo-local `factorforge/data/catalog/data_catalog.json`, only when safely inferable

If no catalog can be found, the API raises `DataCatalogNotFound`.

The catalog supports local and S3 datasets with CSV or parquet format. S3 partitioned parquet uses an explicit partition schema so minute partitions such as `trade_date=20160104` do not conflict with string `trade_date` fields stored inside parquet files.

## Result Contract

`DataApiResult` always contains:

- `frame`: dataset-native column names
- `query`: normalized `DataQuery`
- `schema`: `DataSchema`
- `coverage`: `DataCoverage`
- `source`: `DataSourceRef`
- `freshness`: `DataFreshness`
- `warnings`
- `status`: `ready`, `proxy_ready`, or `blocked`
- `blocked_reason`
- `resolved_fields`
- `proxy_rules`

A bare DataFrame is not considered a complete Data API result.

## Field Resolution

Aliases are explicit. For example, requesting `volume` from `clean_daily_bar` resolves to native column `vol`; the output frame keeps `vol`, and `schema.logical_fields` plus `result.resolved_fields` record `volume -> vol`.

Missing fields produce `status=blocked` with `coverage.missing_fields` populated. The API does not guess paths, rebuild datasets, or silently substitute fields.

Proxy fields are allowed only when explicitly configured in the catalog. For example, `market_cap -> total_mv` returns `status=proxy_ready` and records a `ProxyRule`.

## Validation Contract

Use:

```python
from factor_factory.data_api import validate_data_api_result
report = validate_data_api_result(result)
```

The validator checks:

- legal status
- schema presence
- required date and symbol columns
- requested fields present
- nonzero rows unless blocked
- duplicate key count
- explicit alias resolution
- explicit proxy rules
- no unsupported silent fallback

Duplicate keys default to BLOCK unless the query explicitly allows duplicate keys.

## v1 Dataset Scope

v1 supports the contracts for:

- `clean_daily_bar`
- `daily_basic`
- `minute_bar`

If a dataset is not registered in the active catalog, `fetch()` returns `status=blocked`. `daily_basic` is not silently derived from `clean_daily_bar`.

## Factor Forge Boundary

This package is infrastructure. It does not assume:

- `report_id`
- Step1/2/3/4/5/6
- Factor Forge wrapper
- Factor Forge canonical paths

It must not write:

```text
data/clean/
objects/
runs/
evaluations/
generated_code/
archive/
```

Step3A can later consume `DataApiResult` and write `data_prep_master`, local snapshots, and handoff artifacts. That integration is out of scope for this package phase.

## Smoke

Run isolated smoke tests with:

```bash
python3 scripts/run_data_api_smoke.py --fresh
```

The smoke root must be under `/tmp`. It verifies daily, daily_basic, minute, alias, proxy, blocked, universe filtering, duplicate detection, and no clean-data/canonical mutation.
