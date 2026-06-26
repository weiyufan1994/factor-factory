# Data API Production Execution Standard

更新日期：2026-06-18

适用范围：Data API / data 组生产 derived datamart、state datamart、minute feature base、warm cache 和 coverage repair。该标准不覆盖 alpha 结论、Factor Forge production loop、clean data、search_worker 或 official promotion。

## 1. 默认执行原则

Data API production job 必须默认满足：

- parquet-first / catalog-first / QA-first；
- S3-backed publication，正式产物不只保存在单台机器本地；
- batch/shard/resume/retry；
- local temp 可清理，不能依赖长期占满 worker 磁盘；
- hot path 禁止 pandas row apply 和 DataFrame 逐行循环；
- 递推、rolling state、survival product 等序列计算优先使用 numpy array / numba kernel；
- 可以并行时优先按股票、日期 shard 或 batch pipeline 并行；
- 并行度必须受 CPU、内存、磁盘余量、S3 IO 限流约束；
- ACCEPT 前必须有 catalog、QA、coverage、worker read smoke 和 performance proof。

## 2. IO 和磁盘标准

Production builder 不应让研究员或 Mac 承担多年分钟数据 IO。默认执行位置：

```text
research_worker / AWS Batch / close-to-S3 executor
```

本地 worker 只允许保留：

- 当前 batch 的临时输入；
- 当前 batch 的临时中间层；
- 当前 batch 的输出 staging；
- 必需 warm cache，例如 daily_basic/backtest_base；
- 小型 proof / manifest。

大中间层必须支持 spill to S3：

```text
local temp -> QA -> aws s3 sync/cp -> S3 proof or datamart root -> verify -> rm local temp
```

每个 job 必须提供或等价实现这些开关：

```text
--output-root
--proof-root
--spill-root
--batch-size
--skip-existing
--resume
--overwrite
--max-local-cache-gb
--cleanup-local-after-upload
```

如果本地磁盘低于安全阈值，runner 必须先清理可再生 cache 或 BLOCK，不得继续写爆磁盘。建议阈值：

```text
free_disk_gb < 10       WARN
free_disk_gb < 5        BLOCK unless current batch can finish safely
free_disk_percent < 8%  BLOCK unless explicit override
```

可删除对象：

- 已经上传到 S3 且通过 QA 的 batch temp；
- authoritative source 已经在 S3 的本地 mirror cache；
- 可由 catalog/S3 重新 materialize 的 local read cache。

不得删除对象：

- 正在运行进程使用的 active batch；
- 当前 job 依赖的 daily_basic/backtest_base warm cache；
- 尚未上传或尚未校验的 batch output；
- unresolved request 的唯一 proof。

## 3. 计算标准

Hot path 分三类处理。

### 3.1 列式聚合

适合：

- minute -> 5m/15m/30m interval；
- per-stock per-date amount/volume/return 聚合；
- distribution moments 的 sufficient statistics。

允许：

- pandas groupby/agg/merge；
- polars lazy/group_by；
- duckdb SQL over parquet；
- pyarrow dataset projection/filter。

禁止：

- `DataFrame.apply(axis=1)`；
- `iterrows()`；
- 对每行 Python object loop；
- 先全量读入再无投影过滤。

### 3.2 时序递推

适合：

- EMA slow state；
- H_t = lambda H_{t-1} + (1-lambda) S_t；
- survival product；
- rolling state with continuity。

默认实现：

```text
sort by ts_code, trade_date, cutoff/bucket
-> factorize ts_code/date
-> numpy contiguous arrays
-> numba njit kernel
-> write parquet partition
```

如果必须 chunk by date，必须显式传递上一 chunk final state，或使用 warmup 并丢弃 warmup metrics。不得每年独立 reset 后宣称 full-window proof。

### 3.3 Cross-sectional state

适合：

- market-date fallback；
- percentile/rank threshold；
- universe/investability screen。

默认实现：

- date shard；
- vectorized rank/quantile；
- explicit information-set metadata；
- 不允许用同日 cutoff 之后信息。

## 4. 并行标准

并行优先级：

1. 按 `ts_code` shard：适合时序递推和 rolling state。
2. 按 `trade_date` / month shard：适合无跨期状态的 interval/stat 聚合。
3. batch pipeline：一个 batch 读 S3，一个 batch compute，一个 batch upload/QA。
4. AWS Batch Spot：适合可重试、可切 shard 的多年分钟任务。

runner 必须显式记录：

```text
workers
cpu_count
memory_gb
max_local_cache_gb
batch_size
read_seconds
compute_seconds
write_seconds
qa_seconds
upload_seconds
```

不能盲目榨干 CPU。若瓶颈是 S3 read 或本地磁盘，过高并行度会更慢。生产 runner 应支持：

```text
--workers auto|N
--io-workers N
--compute-workers N
--s3-max-concurrency N
```

## 5. 产物标准

每个 production dataset 必须输出：

```text
datamart_root/
  trade_date=YYYYMMDD/part.parquet

proof_root/
  <dataset>.qa.json
  <dataset>.catalog.json
  <dataset>.read_smoke.json
  <dataset>.performance.json
  <dataset>.shard_manifest.json
  <dataset>.closeout.json
```

QA 必须包含：

- date_count；
- ticker_count；
- row_count；
- missing_dates；
- duplicate_key_count；
- null ratio；
- input/source coverage；
- unique key；
- schema version；
- producer version；
- parameter hash；
- information-set legality；
- no_future_data / no_future_intraday_minutes；
- representative worker read smoke；
- warm read seconds；
- total runtime seconds；
- estimated cost when applicable。

## 6. Request 必填执行偏好

`data_request_v1.execution_preference` 必须扩展或等价包含：

```json
{
  "preferred_executor": "research_worker|aws_batch_spot|local_debug",
  "batch_spot_allowed": true,
  "requires_cost_estimate_before_full_run": true,
  "requires_vectorized_or_numba_hot_path": true,
  "forbid_pandas_row_apply": true,
  "parallelization_required_when_safe": true,
  "spill_to_s3_required": true,
  "cleanup_local_after_upload": true,
  "max_local_cache_gb": 10,
  "resume_required": true
}
```

Data API resolution 必须说明是否满足这些偏好；若不满足，必须写原因和风险。

## 7. ACCEPT / BLOCK 规则

ACCEPT 必须满足：

- datamart 已发布到 S3 或明确 catalog 可访问位置；
- active local temp 已清理或有保留理由；
- duplicate key = 0；
- missing dates = []，或 request 明确允许 partial window；
- worker read smoke = ACCEPT；
- hot path 没有 pandas row apply / iterrows；
- performance profile 说明 IO、compute、write、QA 时间；
- 如果没有使用 numba/parallel，必须说明瓶颈不在该层或当前资源不允许。

标准 BLOCK token：

- `BLOCK_DATA_API_SOURCE_COVERAGE_INCOMPLETE`
- `BLOCK_DATA_API_DISK_BUDGET_INSUFFICIENT`
- `BLOCK_DATA_API_BACKFILL_NOT_RESUMABLE`
- `BLOCK_DATA_API_HOT_PATH_NOT_VECTORIZED`
- `BLOCK_DATA_API_PARALLELIZATION_UNSAFE`
- `BLOCK_DATA_API_WORKER_READ_SMOKE_MISSING`
- `BLOCK_DATA_API_DERIVED_DATAMART_QA_FAILED`

## 8. LCR Retained Chip 当前经验

LCR retained chip state 当前 production backfill 的正确方向是：

```text
worker reads minute_bar S3
worker reads local daily_basic warm cache
builds temporary 15m interval base per batch
builds retained chip state per target batch
uploads final state partitions to S3 datamart
uploads QA/proof to S3
removes local temp
```

这能稳定交付 full-window datamart，但还不是终极性能形态。后续优化优先级：

1. 把 minute -> interval base 做成可复用 production datamart。
2. 将 survival product / rolling retained state 写成 numpy + numba kernel。
3. 增加 ts_code shard parallel runner。
4. 在磁盘和 S3 限流允许时启用 batch pipeline。
