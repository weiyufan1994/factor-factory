# Data Request Inbox Contract

更新日期：2026-06-15

## 目标

研究员发现数据缺口后，不应把需求发给用户再由用户转发给 Data API / data 组。

标准流程必须是：

```text
Factor Forge researcher writes data request
-> Data API consumes request inbox
-> Data API returns ACCEPT / BLOCK proof
-> Factor Forge resumes from Data API catalog
```

用户只负责决定是否批准高成本任务、是否接受降级口径，不负责搬运需求文本。

## Inbox 位置

研究侧 canonical request：

```text
/Users/humphrey/projects/factor-factory/objects/data_requests/data_request__<report_id>__<dataset_id>__<yyyymmddhhmmss>.json
```

Data API mirror / work queue：

```text
/Users/humphrey/projects/factor-factory-data-api/factorforge/data/requests/inbox/
```

可选 S3 共享队列：

```text
s3://yufan-data-lake/factorforge/data_requests/inbox/
s3://yufan-data-lake/factorforge/data_requests/resolved/
```

## Request Schema

执行要求必须遵守：

```text
docs/operations/data-api-production-execution-standard.zh-CN.md
```

尤其是：S3 spill / cleanup、batch resume、hot path 向量化或 numba、禁止 pandas row apply、安全并行、worker read smoke 和 performance proof。

```json
{
  "schema_version": "data_request_v1",
  "request_id": "ORIG_REPORT__moneyflow_v20_slow_state_v1__20260615143000",
  "created_at_utc": "2026-06-15T06:30:00Z",
  "created_by": "factorforge-researcher",
  "report_id": "ORIG_REPORT",
  "priority": "P0|P1|P2",
  "requested_dataset_id": "moneyflow_v20_slow_state_v1",
  "request_type": "new_datamart|coverage_repair|schema_addition|performance_acceleration|read_smoke",
  "research_need": {
    "economic_purpose": "short human-readable purpose",
    "formula_or_state": "H_t = lambda H_{t-1} + (1-lambda) S_t",
    "upstream_datasets": [
      "intraday_flow_distribution_moments_v1",
      "daily_basic_backtest_base"
    ]
  },
  "window": {
    "is_start": "20160104",
    "is_end": "20250711",
    "oos_start": "20250714",
    "research_window_rule": "OOS marked holdout; do not fit parameters on OOS"
  },
  "information_set": {
    "cutoff_times": ["14:50"],
    "no_future_data": true,
    "state_continuity_required": true
  },
  "unique_key": ["ts_code", "trade_date", "cutoff_time", "lambda"],
  "required_fields": [
    "ts_code",
    "trade_date",
    "cutoff_time",
    "lambda",
    "h_slow_state",
    "research_window"
  ],
  "qa_requirements": [
    "duplicate_key_count=0",
    "missing_dates=[]",
    "coverage_summary",
    "representative_read_smoke",
    "state_continuity_proof"
  ],
  "execution_preference": {
    "preferred_executor": "research_worker",
    "batch_spot_allowed": true,
    "requires_cost_estimate_before_full_run": true,
    "requires_vectorized_or_numba_hot_path": true,
    "forbid_pandas_row_apply": true,
    "parallelization_required_when_safe": true,
    "spill_to_s3_required": true,
    "cleanup_local_after_upload": true,
    "max_local_cache_gb": 10,
    "resume_required": true
  },
  "boundaries": {
    "do_not_start_clean_data": true,
    "do_not_start_search_worker": true,
    "do_not_start_official_promotion": true,
    "do_not_write_factor_forge_research_artifacts": true,
    "do_not_start_factor_loop": true
  }
}
```

## Data API Resolution Schema

Data API 关闭请求时必须写 resolution。

```json
{
  "schema_version": "data_request_resolution_v1",
  "request_id": "...",
  "resolved_at_utc": "2026-06-15T07:30:00Z",
  "resolved_by": "data-api",
  "verdict": "ACCEPT|BLOCK",
  "dataset_id": "moneyflow_v20_slow_state_v1",
  "catalog_path": "...",
  "datamart_path": "...",
  "qa_json_path": "...",
  "worker_read_smoke": {
    "instance_id": "i-...",
    "command": "python -m ...",
    "warm_read_seconds": 0.0,
    "verdict": "ACCEPT|BLOCK"
  },
  "coverage": {
    "start_date": "20160104",
    "end_date": "20250711",
    "rows": 0,
    "dates": 0,
    "tickers": 0,
    "missing_dates": [],
    "duplicate_key_count": 0
  },
  "runtime": {
    "executor": "research_worker|aws_batch_spot|local_debug",
    "read_seconds": 0.0,
    "compute_seconds": 0.0,
    "write_seconds": 0.0,
    "qa_seconds": 0.0,
    "total_seconds": 0.0,
    "estimated_total_cost_usd": 0.0
  },
  "notes": []
}
```

## Responsibilities

Factor Forge researcher:

- Must write a `data_request_v1` artifact when Step3/Step4 is blocked by data, slow reusable state, or missing Data API coverage.
- Must not ask the user to manually forward free-form requirements.
- Must not patch raw data, clean data, catalog, or production datamart.
- May continue only with sample/proxy research if the request explicitly allows a degraded research mode.

Data API / data group:

- Must treat the inbox as the source of data work.
- Must classify each request as existing dataset, coverage repair, schema addition, or new derived datamart.
- Must produce catalog, datamart, QA json, runtime proof, and worker read smoke before ACCEPT.
- Must follow `docs/operations/data-api-production-execution-standard.zh-CN.md` for IO, disk, vectorization, numba, parallelization, S3 spill, and cleanup.
- Must write BLOCK with concrete missing input, cost risk, or information-set issue when it cannot close.

User:

- Approves high-cost execution or research-scope downgrade.
- Does not manually translate researcher messages into data engineering tickets.

## Moneyflow V20 Example

`moneyflow_v20_slow_state_v1` should be represented as:

```text
request_type = new_datamart
upstream_datasets = intraday_flow_distribution_moments_v1, daily_basic_backtest_base
unique_key = ts_code + trade_date + cutoff_time + lambda
cutoff_time = 14:50
lambda = 0.70 / 0.85 / 0.93
state_source = prior_state_continuous
no_future_data = true
```

The resolution must include a state-continuity proof showing that chunked output matches single-series recurrence for sampled `ts_code`.

## CLI

Data API 侧提供 inbox 工具：

```bash
python3 scripts/data_request_inbox.py new \
  --report-id <report_id> \
  --dataset-id <dataset_id> \
  --request-type new_datamart \
  --unique-key ts_code,trade_date,cutoff_time \
  --required-fields ts_code,trade_date,cutoff_time,score \
  --output <request.json>
python3 scripts/data_request_inbox.py validate <request.json>
python3 scripts/data_request_inbox.py mirror <request.json>
python3 scripts/data_request_inbox.py list
python3 scripts/data_request_inbox.py claim <request_id> --claimed-by data-api
python3 scripts/data_request_inbox.py status <request_id>
python3 scripts/data_request_inbox.py resolution-skeleton <request.json> --verdict BLOCK
python3 scripts/data_request_inbox.py resolve <resolution.json>
```

Data API scanner:

```bash
python3 scripts/data_request_scanner.py once
python3 scripts/data_request_scanner.py watch --interval-seconds 30
```

`once` 适合 cron/手动触发；`watch` 适合临时常驻观察。scanner 只负责把有效 pending request 认领为 `IN_PROGRESS`，不会自动启动 clean data、search worker、official promotion 或 Factor Forge production loop。

默认路径：

```text
inbox    = factorforge/data/requests/inbox/
claimed  = factorforge/data/requests/claimed/
resolved = factorforge/data/requests/resolved/
```

`ACCEPT` resolution 必须包含非空 `catalog_path`、`datamart_path`、`qa_json_path`，worker read smoke 必须为 `ACCEPT`，coverage rows/dates 必须为正数。`BLOCK` resolution 可以没有这些路径，但必须说明 blocker。

研究员判断 Data API 是否完成时，只看：

```bash
python3 scripts/data_request_inbox.py status <request_id>
```

返回：

```text
PENDING   Data API 尚未关闭
IN_PROGRESS Data API 已认领并开始处理
ACCEPT    Data API 已交付 catalog/datamart/QA/worker smoke，可以恢复研究
BLOCK     Data API 已确认无法交付，返回 blocker
INVALID   request 或 resolution 不合规
NOT_FOUND request 未进入 inbox/resolved
```
