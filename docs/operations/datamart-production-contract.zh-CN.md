# Data API Datamart Production Contract

Date: 2026-06-16

Scope: Data API 只负责 reusable data product，不负责 alpha 结论、Factor Forge production loop、clean data、search_worker 或 official promotion。

执行层必须同时遵守：

```text
docs/operations/data-api-production-execution-standard.zh-CN.md
```

该标准约束 IO、磁盘、S3 spill、local cleanup、hot path 向量化、numba、并行、batch resume、worker read smoke 和 performance proof。

## 1. 边界

Data API owns:

- raw/source data 读取合同；
- reusable state variables / sufficient statistics；
- production parquet datamart；
- catalog、QA、coverage、worker read smoke、performance proof；
- shard/resume/retry 生产记录。

Factor Forge owns:

- economic hypothesis；
- factor law / score composition；
- factor_values 计算；
- Step4/Step5 evaluation；
- Council revision 和 official promotion 决策。

Data API P0 schema 不应包含 `support_minus_overhang`、`below_cost_guarded_support`、组合 alpha score 这类研究侧字段。它应沉淀可复用观测量、状态量和 sufficient statistics。

## 2. Production Datamart 原则

正式 datamart 不删除，废弃时 tombstone。

唯一身份：

```text
dataset_id + dataset_schema_version + producer_version + parameter_hash
```

新算法、新字段或新参数应生成新版本或新 producer，不覆盖旧数据。Factor Forge 只通过 Data API catalog 读取 QA ACCEPT 的 datamart，不直接猜路径。

## 3. Inventory

Data API 提供 catalog-first inventory：

```bash
python3 scripts/datamart_contract.py inventory \
  --catalog factorforge/data/catalog/data_catalog.json \
  --output factorforge/data/proofs/datamart_inventory.json
```

inventory 字段包括：

- `dataset_id`
- `schema_version`
- `producer_version`
- `source_datasets`
- `uri`
- `storage`
- `format`
- `partition_columns`
- `unique_key`
- `coverage`
- `qa_path`
- `lookahead_policy`
- `supported_cutoff_times`
- `latest_reviewer_verdict`
- `deprecation_status`

## 4. Closeout

每个 production datamart 的 ACCEPT/BLOCK 都必须写 `datamart_closeout_v1`。

生成 skeleton：

```bash
python3 scripts/datamart_contract.py closeout-skeleton \
  --dataset-id moneyflow_v20_slow_state_v1 \
  --source-datasets intraday_flow_distribution_moments_v1,daily_basic_backtest_base \
  --unique-key ts_code,trade_date,cutoff_time,lambda \
  --producer-version moneyflow_v20_slow_state_builder_20260616 \
  --dataset-schema-version moneyflow_v20_slow_state_v1_schema_v1 \
  --verdict BLOCK \
  --output /tmp/moneyflow_v20_slow_state_v1.closeout.json
```

校验：

```bash
python3 scripts/datamart_contract.py validate-closeout /tmp/moneyflow_v20_slow_state_v1.closeout.json
```

ACCEPT 必须满足：

- `catalog_path` 非空；
- `datamart_path` 非空；
- `qa_path` 非空；
- `worker_smoke_path` 非空；
- `worker_read_smoke.verdict=ACCEPT`；
- `output_coverage.row_count > 0`；
- `output_coverage.date_count > 0`；
- `output_coverage.duplicate_key_count = 0`；
- `output_coverage.missing_dates = []`；
- `lookahead_contract.no_future_intraday_minutes = true`；
- `performance_profile` 包含 read/compute/write/qa/warm-read 秒数；
- `performance_profile` 说明 hot path 是否使用 vectorized / numpy / numba / duckdb / polars；
- `execution_profile` 或等价字段说明 `workers`、`batch_size`、`max_local_cache_gb`、`spill_to_s3`、`cleanup_local_after_upload`；
- 本地临时目录已清理，或说明保留理由和过期策略；
- `output_identity.immutable = true`；
- `output_identity.tombstone_not_delete = true`。

BLOCK 必须使用标准 token：

- `BLOCK_DATA_API_SOURCE_COVERAGE_INCOMPLETE`
- `BLOCK_DATA_API_DERIVED_DATAMART_QA_FAILED`
- `BLOCK_DATA_API_DERIVED_DATAMART_DUPLICATE_KEYS`
- `BLOCK_DATA_API_LOOKAHEAD_CONTRACT_MISSING`
- `BLOCK_DATA_API_WORKER_READ_SMOKE_MISSING`
- `BLOCK_DATA_API_BACKFILL_NOT_RESUMABLE`
- `BLOCK_DATA_API_DISK_BUDGET_INSUFFICIENT`
- `BLOCK_DATA_API_HOT_PATH_NOT_VECTORIZED`
- `BLOCK_DATA_API_PARALLELIZATION_UNSAFE`
- `BLOCK_DATA_API_PRODUCTION_CATALOG_NOT_PUBLISHED`
- `BLOCK_DATA_API_TRUE_DOLLAR_BAR_REQUIRES_TICK_DATA`

## 5. Shard Manifest

多年全市场分钟 backfill 必须 shard/resume/retry，不能把一次前台运行当作唯一 proof。

生成 skeleton：

```bash
python3 scripts/datamart_contract.py shard-manifest-skeleton \
  --dataset-id intraday_flow_distribution_moments_v1 \
  --shard-id 2020-01 \
  --output /tmp/intraday_flow_distribution_moments_v1.shards.json
```

校验：

```bash
python3 scripts/datamart_contract.py validate-shard-manifest /tmp/intraday_flow_distribution_moments_v1.shards.json
```

每个 shard 至少记录：

- `shard_id`
- `source_partitions`
- `input_row_count`
- `output_row_count`
- `duplicate_key_count`
- `read_seconds`
- `compute_seconds`
- `write_seconds`
- `status`
- `retry_count`
- `error_message`

失败后只重跑失败 shard，不重跑全窗口。

## 6. V20 当前应用

`moneyflow_v20_slow_state_v1` 在 ACCEPT 前不得作为 Factor Forge production dataset 使用。Data API closeout 应先证明上游 datamart 可读，尤其是：

- `intraday_flow_distribution_moments_v1`
- `daily_basic_backtest_base` 或等价 daily basic/backtest base 字段

如果上游不存在，应写 BLOCK closeout，而不是让研究员在 Step4 重扫多年 raw minute。
