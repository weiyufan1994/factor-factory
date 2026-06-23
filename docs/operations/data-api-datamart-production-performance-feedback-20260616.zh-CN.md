# Data API Datamart 生产加速与持久化反馈

Date: 2026-06-16

Audience: Data API team / Data engineering / Data API reviewer

Scope: 只反馈数据生产和 datamart 工程问题，不评价 Moneyflow V20 因子结论；不要求启动 Factor Forge production loop、clean data、search_worker 或 official promotion。

## 1. 结论

Moneyflow V20 这类分钟因子慢，不是因为单个公式特别复杂，而是因为它已经从“研究公式”进入了“多年全市场分钟状态生产”的数据工程问题。

Factor value 每轮 revision 都可能要重算，这是合理的；但 raw minute derived state 不应在 Factor Forge Step4 中反复临时生产。Data API 侧需要把可复用状态变量沉淀为正式 datamart，并提供 catalog、QA、coverage、read smoke、worker performance proof。

本反馈聚焦三个问题：

1. Data API 已经生产了哪些可复用 datamart，是否持久保存。
2. 后续 datamart 生产如何避免重复、如何版本化。
3. datamart backfill 如何在 IO、operator、调度和语言层面加速。

## 2. 当前已知 datamart / 状态层

根据近期研究和 Data API closeout，以下状态层应视为可复用数据产品或候选数据产品：

| Dataset | 作用 | 状态判断 |
|---|---|---|
| `daily_basic_backtest_base_is` | 市值、流动性、turnover、universe、基础回测 controls | 已进入 backtest base 复用方向 |
| `intraday_flow_state_v2` | cutoff 前资金流状态，prior-date threshold，无未来分钟 | 已用于 Moneyflow V7/V9/V10 方向 |
| `intraday_flow_distribution_moments_v1` | 资金流分布形状，如 skewness/kurtosis/tail | 已用于 V10/V11 方向 |
| `intraday_pseudo_dollar_bar_v1` | 基于 1m bar 的 pseudo dollar bar | 可用但必须标注不是 true tick dollar bar |
| `intraday_value_occupation_state_v1` | 价格轴 occupation measure / POC / HVN / LVN / VA | Data API 已有交付记录，研究侧使用前仍应查 active catalog |
| `moneyflow_v20_slow_state_v1` | V20 event-triggered slow-state | 以 Data API request 状态为准，ACCEPT 前不得正式使用 |

建议 Data API 侧提供一个稳定的 datamart registry / inventory，明确：

- dataset_id
- schema_version
- producer_version
- source datasets
- output root
- catalog path
- QA path
- coverage
- duplicate key count
- lookahead policy
- supported cutoffs / parameters
- latest reviewer verdict
- deprecation status

## 3. 持久化原则

正式 datamart 不应作为研究临时文件删除。

建议原则：

1. Production datamart immutable
   - `dataset_id + schema_version + producer_version + parameter_hash` 唯一确定数据产品。
   - 新版本另开 `v2/v3` 或新 producer_version，不覆盖旧数据。

2. Catalog-first
   - Factor Forge 只通过 Data API catalog 消费，不直接猜路径。
   - catalog 必须指向 QA ACCEPT 的 root。

3. Tombstone not delete
   - 废弃 datamart 应标记 deprecated / tombstoned，不物理删除。
   - 保留旧研究 lineage 可复现。

4. Research artifact 与 Data product 分离
   - Data API P0 datamart 只放 state variables / sufficient statistics。
   - `support_minus_overhang`、`below_cost_guarded_support`、alpha score 这类组合分数属于研究侧，不应进入 P0 schema。

## 4. Datamart 生产为何慢

### 4.1 数据规模

2016-01-04 到 2025-07-11 大约 2313 个交易日。全市场 5000 多只股票，每天约 240 根分钟线，原始规模是十亿级 instrument-minute rows。

任何每轮从 raw minute 重扫的方案都会慢。

### 4.2 状态变量不是简单 sum

V20 这类状态通常需要：

- cutoff 前分钟路径；
- prior-date rolling threshold；
- event-triggered transition；
- per-instrument state carry；
- no future intraday minutes；
- 和 daily_basic / universe / return 合并。

这比普通 `sum(amount)` 或 `mean(ret)` 贵，因为它包含 rolling、stateful、path-dependent 逻辑。

### 4.3 IO 常常比计算更贵

如果每次 cold read S3 raw minute partition，瓶颈会落在：

- S3 list / metadata;
- 小文件过多；
- cold download；
- 读取不必要列；
- 读取不必要日期；
- 重复读取周末 / 缺失 partition；
- Mac/worker cache 不持久。

## 5. IO 加速建议

P0 建议：

1. Parquet-first
   - 所有正式 derived datamart 用 parquet。
   - 不用 CSV 作为生产主格式。

2. Partition pruning
   - 至少按 `trade_date` 分区。
   - 对非常大的数据集可考虑 `year/month/trade_date` 多级分区，避免单目录过大。

3. Column projection
   - 构建 moneyflow state 时只读必要列：
     - `ts_code`
     - `trade_date`
     - `trade_time`
     - `open/high/low/close`
     - `vol`
     - `amount`
     - 必要 proxy fields
   - 禁止无条件读全 schema。

4. Local persistent cache
   - worker 上使用 NVMe / EBS 本地 cache。
   - cache key 包含 source root、partition、etag/mtime 或 manifest version。

5. Negative cache
   - 对周末、非交易日、确实缺失日期写 negative marker。
   - 避免每轮重复探测 S3。

6. Manifest-first coverage
   - 不要每次通过 S3 list 推断 coverage。
   - Data API 应有 source coverage manifest。

## 6. Operator 层加速建议

P0:

- 禁止多年全市场 production backfill 使用 Python per-stock loop。
- 优先 Polars / DuckDB / PyArrow compute / pandas vectorized groupby。
- 所有 rolling threshold 先转成 prior-date threshold table，不在主状态构建中反复算。

P1:

- 对 distribution moments 使用 sufficient statistics：

$$
n,\quad \sum x,\quad \sum x^2,\quad \sum x^3,\quad \sum x^4
$$

由这些量推出 mean、variance、skewness、kurtosis，避免重复扫描。

- 对 rolling window 使用 prefix / cumulative statistics。
- 对 event state 使用 by-date batch + previous state join。
- 对 cutoff state 复用同一日分钟 scan，一次生成多个 cutoff：
  - `10:30`
  - `11:30`
  - `14:00`
  - `14:30`
  - `14:50`
  - `14:55`

P1:

- 对 pseudo dollar bar 这种高行数产品，先明确消费场景：
  - 如果研究只需要 bucket-level summary，不要持久化所有中间字段。
  - 如果需要全量 bucket，则必须有 compact schema 和 partition plan。

## 7. 调度 / Backfill 加速建议

Datamart full-window backfill 应作为 Data API 生产任务，而不是研究线程前台任务。

建议引入 shard 级调度：

```text
build_spec -> shard by trade_date/month -> per-shard QA -> resumable manifest -> final QA -> catalog publish
```

每个 shard 应记录：

- shard id
- source partitions
- input row count
- output row count
- duplicate key count
- compute seconds
- read seconds
- write seconds
- status
- retry count
- error message

失败后只重跑失败 shard，不重跑全窗口。

## 8. 是否需要 Java / C++ / Rust

暂时不建议把“换语言”作为第一优先级。

更优先的顺序是：

1. Parquet + Arrow 格式正确。
2. 减少 IO：projection、partition pruning、persistent cache。
3. 减少重复：manifest、negative cache、state reuse。
4. 向量化算子：Polars / DuckDB / PyArrow compute。
5. 并行 shard + resumable backfill。
6. 只有确认某个 kernel 仍是瓶颈，再考虑 Rust / C++ / Numba。

原因：

- 很多慢点来自 S3 cold read、小文件、重复扫描、Python loop，而不是 Python 语言本身。
- Polars/DuckDB 已经使用 Rust/C++ vectorized engine，通常足够。
- 直接上 Java/C++ 会增加部署、调试、schema、catalog、CI 复杂度。

如果后续 profiling 证明某个核心 kernel 极慢，例如：

- pseudo dollar bucket construction；
- complex event state transition；
- value occupation binning；
- rolling first-passage state；

则可以对该 kernel 单独写 Rust/C++ extension，而不是重写整个 Data API。

## 9. 建议的 Data API contract

每个 derived datamart closeout 应包含：

```json
{
  "dataset_id": "moneyflow_v20_slow_state_v1",
  "schema_version": "...",
  "producer_version": "...",
  "source_datasets": ["minute_bar", "daily_basic"],
  "source_coverage": {
    "start": "20160104",
    "end": "20250711",
    "missing_dates": []
  },
  "output_coverage": {
    "date_count": 2313,
    "row_count": 0,
    "duplicate_key_count": 0
  },
  "lookahead_contract": {
    "no_future_intraday_minutes": true,
    "threshold_source": "prior_dates"
  },
  "performance_profile": {
    "read_seconds": 0,
    "compute_seconds": 0,
    "write_seconds": 0,
    "warm_read_seconds_representative": 0
  },
  "qa_path": "...",
  "catalog_path": "...",
  "worker_smoke_path": "...",
  "verdict": "ACCEPT"
}
```

## 10. 推荐 BLOCK token

- `BLOCK_DATA_API_SOURCE_COVERAGE_INCOMPLETE`
- `BLOCK_DATA_API_DERIVED_DATAMART_QA_FAILED`
- `BLOCK_DATA_API_DERIVED_DATAMART_DUPLICATE_KEYS`
- `BLOCK_DATA_API_LOOKAHEAD_CONTRACT_MISSING`
- `BLOCK_DATA_API_WORKER_READ_SMOKE_MISSING`
- `BLOCK_DATA_API_BACKFILL_NOT_RESUMABLE`
- `BLOCK_DATA_API_PRODUCTION_CATALOG_NOT_PUBLISHED`
- `BLOCK_DATA_API_TRUE_DOLLAR_BAR_REQUIRES_TICK_DATA`

## 11. 给数据组的优先级建议

P0:

- 提供 datamart inventory / registry。
- 确认正式 datamart 持久化，不被研究 artifact 清理误删。
- 对 `moneyflow_v20_slow_state_v1` 这类 request 输出 ACCEPT/BLOCK closeout。
- 每个 closeout 必须有 catalog、QA、worker read smoke。

P1:

- 建立 shard-level resumable backfill framework。
- 给每个 datamart 输出 read/compute/write performance profile。
- 对 common operators 建立 sufficient statistics / reusable base。

P2:

- 对 pseudo dollar bar、value occupation、event state transition 做 kernel profiling。
- 如果 vectorized Polars/DuckDB 仍不足，再评估 Rust/C++ extension。

## 12. 对 Data API team 的结论

Factor Forge 研究侧会不断提出新因子、新 revision，这是正常的。Data API 不需要为每个 alpha score 建一个 datamart，但需要沉淀可复用的“市场状态观测量”。

建议边界如下：

```text
Data API owns:
  raw data -> reusable state variables -> QA/catalog/worker smoke

Factor Forge owns:
  economic hypothesis -> math mechanism -> factor law -> score composition -> evaluation
```

只有这个边界清楚，后续 V20/V21/V22 才不会每轮都重新扫十年 raw minute。
