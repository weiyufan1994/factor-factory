# Minute Backfill Job Spec

更新日期：2026-06-15

## 目标

分钟数据研究的核心原则：

```text
研究员验证想法，data worker 生产成品，Data API 统一消费。
```

对新的分钟因子或分钟 state，不要求一开始就上 AWS Batch。第一阶段先把任务写成统一 job spec，使它可以在以下执行器之间迁移：

- `research_worker`: 当前按需开关的 factor research worker。
- `aws_batch_spot`: 后续可选的 AWS Batch + EC2 Spot 多机执行。
- `local_debug`: Mac 或本地小样本调试，只允许小窗口。

这样既不浪费现有研究机，也避免以后被单机瓶颈锁死。

分钟 backfill job spec 通常由标准 data request 触发。研究员只写需求 artifact，Data API / data 组把它转成可执行 job spec 并关闭 resolution。

```text
docs/operations/data-request-inbox-contract.zh-CN.md
```

## 默认决策

| 场景 | 默认执行器 | 理由 |
| --- | --- | --- |
| Step3 小样本验证 | `local_debug` 或 `research_worker` | 验证公式、字段、信息集，不做全窗口 |
| 1 天到 1 个月试算 | `research_worker` | 成本低、调试快、无需 Batch 工程开销 |
| 每日增量 | `research_worker` | 单日任务短，Batch 未必省钱 |
| 预计 2-4 小时以内 | `research_worker` | 按需开关更简单 |
| 预计 6-8 小时以上 | 准备 `aws_batch_spot` | 多日期并行节省研究等待时间 |
| full-window 2016-2025 minute backfill | 优先评估 `aws_batch_spot` | 单机 OOM/排队/等待风险高 |
| 多个分钟因子排队 | `aws_batch_spot` | 横向扩展比单机排队更适合 |

触发 Batch 的硬条件：

- 单机 OOM 或需要把 `max_workers` 降到极低才能稳定。
- 研究员等待 full-window proof 超过半天。
- 同一类 minute state 会被多次复用。
- 需要同时跑多个 report / branch。
- 单机任务预计成本不高但 wall time 影响研究节奏。

## Job Spec Schema

每个分钟 backfill 任务必须能表示成一个 JSON spec。

```json
{
  "schema_version": "minute_backfill_job_spec_v1",
  "job_id": "intraday_flow_distribution_moments_v1__202401",
  "dataset_id": "intraday_flow_distribution_moments_v1",
  "research_context": {
    "report_id": "optional",
    "owner": "data-api",
    "purpose": "production_datamart|research_candidate|benchmark"
  },
  "source": {
    "dataset_id": "minute_bar",
    "uri": "s3://yufan-data-lake/tushares/分钟数据/raw/stk_mins_1min/",
    "required_columns": ["ts_code", "trade_time", "trade_date", "open", "high", "low", "close", "vol", "amount"]
  },
  "window": {
    "start_date": "20240102",
    "end_date": "20240131",
    "research_window": "IS|OOS|SMOKE"
  },
  "partitioning": {
    "unit": "trade_date",
    "max_dates_per_task": 1,
    "output_partition_column": "trade_date"
  },
  "information_set": {
    "cutoff_times": ["10:30", "11:30", "14:00", "14:30", "14:50", "14:55"],
    "no_future_intraday_minutes": true,
    "threshold_source": "prior_dates",
    "lookback_days": [20, 60]
  },
  "executor": {
    "preferred": "research_worker",
    "allowed": ["research_worker", "aws_batch_spot"],
    "max_workers": 4,
    "memory_limit_gb": 24
  },
  "cost_guardrail": {
    "max_estimated_usd": 10.0,
    "max_wall_clock_hours": 8.0,
    "require_manual_approval_above_usd": 10.0,
    "spot_allowed": true
  },
  "output": {
    "uri": "s3://yufan-data-lake/factorforge/datamart/intraday_flow_distribution_moments_v1/is",
    "format": "parquet",
    "mode": "append_partitions",
    "unique_key": ["ts_code", "trade_date", "cutoff_time"]
  },
  "checkpoint": {
    "uri": "s3://yufan-data-lake/factorforge/checkpoints/minute_backfill/intraday_flow_distribution_moments_v1__202401/",
    "per_partition_status": true,
    "rerun_failed_only": true
  },
  "qa": {
    "required": true,
    "checks": ["row_count", "missing_dates", "duplicate_keys", "null_ratio", "read_smoke"],
    "proof_uri": "s3://yufan-data-lake/factorforge/proofs/minute_backfill/intraday_flow_distribution_moments_v1__202401.qa.json"
  }
}
```

## Required Runtime Metrics

每个 job run 必须输出 runtime proof，不能只说成功。

```json
{
  "job_id": "...",
  "executor": "research_worker|aws_batch_spot",
  "instance_type": "r7i.xlarge",
  "spot": false,
  "date_range": "20240102-20240131",
  "partitions_attempted": 0,
  "partitions_completed": 0,
  "partitions_failed": 0,
  "input_bytes": 0,
  "output_bytes": 0,
  "rows": 0,
  "read_seconds": 0.0,
  "compute_seconds": 0.0,
  "write_seconds": 0.0,
  "qa_seconds": 0.0,
  "total_seconds": 0.0,
  "peak_memory_gb": 0.0,
  "estimated_compute_cost_usd": 0.0,
  "estimated_s3_cost_usd": 0.0,
  "estimated_total_cost_usd": 0.0,
  "verdict": "ACCEPT|BLOCK"
}
```

成本敏感原则：

- `estimated_total_cost_usd` 必须写入 proof。
- 超过 `cost_guardrail.max_estimated_usd` 必须 BLOCK 或等待人工批准。
- AWS Batch job 不允许无上限 `max_vcpus`。
- Spot worker 必须 checkpoint；中断后只能重跑失败 partition。
- 长驻服务和临时 batch 必须分开计费和记录。

## Research Worker First

研究机是第一执行器，不是废弃路径。

推荐研究机 runner 行为：

```text
1. 读取 job spec。
2. 展开 trade_date partition list。
3. 跳过 checkpoint 已完成 partition。
4. 按 max_workers 并发执行。
5. 每个 trade_date 单独写 parquet。
6. 每个 trade_date 单独写 status。
7. 完成后写 coverage QA。
8. 用 Data API 做 read smoke。
9. 输出 runtime proof。
```

研究机 runner 禁止：

- 与 Factor Forge production loop 混跑。
- 写 `factorforge/objects`、`runs`、`evaluations`、`archive`。
- 在未确认内存前一次 concat 多年分钟数据。
- 失败后覆盖已有 ACCEPT partition。

## AWS Batch Upgrade Path

只有当 research worker proof 显示单机成为瓶颈时，才升级 Batch。

Batch 化要求：

- job spec 已存在。
- 每个 partition 可独立重跑。
- 输出只写 S3 datamart/checkpoint/proof。
- Docker image 已固定 dependency。
- IAM role 只授予必要 S3 prefix。
- `max_vcpus`、Spot 策略、预算阈值已写入 plan。
- 先跑 1 个月 bounded proof，再考虑 full-window。

Batch proof 必须额外记录：

```json
{
  "batch_job_queue": "...",
  "batch_job_definition": "...",
  "compute_environment": "...",
  "allocation_strategy": "SPOT_PRICE_CAPACITY_OPTIMIZED",
  "max_vcpus": 0,
  "container_image": "...",
  "cloudwatch_log_group": "...",
  "interrupted_tasks": 0,
  "retry_count": 0
}
```

## Done Definition

一个分钟 backfill 任务只有同时满足以下条件，才算对研究员可用：

- parquet partition 已写入目标 datamart。
- catalog metadata 已注册或 sidecar catalog 已存在。
- QA verdict 为 `ACCEPT`。
- duplicate key 为 0 或符合 dataset contract。
- missing dates 为空，或明确列为非交易日/源数据缺失。
- Data API read smoke 能读代表日期。
- runtime proof 写明 read/compute/write/QA seconds 和估算成本。
- 研究员消费的是成品 dataset，不直接扫 raw minute。
