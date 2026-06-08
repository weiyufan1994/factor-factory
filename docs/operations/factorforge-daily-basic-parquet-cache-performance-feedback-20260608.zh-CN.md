# Factor Forge daily_basic Parquet / Warm Cache 性能反馈

日期：2026-06-08

对象：架构师 / coder / reviewer

相关背景：

```text
moneyflow / Miller minute-derived production proof
root report:
ORIG_INTRADAY_FLOW_SP3_DRIFT_MINUS_NOISE_20240102_20260525_FULL_LOOP_20260606172221

current best child:
ORIG_INTRADAY_FLOW_SP3_DRIFT_MINUS_NOISE_20240102_2026__aec8b09a__3af1c2b277__LOOP01__MILLER_FLOW_POSTERIOR_HOLD_GATE_V3

falsified child:
ORIG_INTRADAY_FLOW_SP3_DRIFT_MINUS_NOISE_20240102_202__7dd47b42b2__LOOP01__MILLER_FLOW_SPARSE_POSTERIOR_COST_BOUNDARY_V4
```

## 一句话结论

`minute_derived_flow_state_v1` 已经解决了 moneyflow 分钟因子反复全量扫描 minute bars 的主要问题，但 Step4 仍暴露出新的通用瓶颈：日度控制变量 `daily_basic_incremental` 仍以 S3 CSV / per-day IO 方式被读取，导致 v3 / v4 Step4 的耗时主要卡在 daily_basic 读取与合并，而不是因子本身计算。

需要把 `daily_basic` 升级为正式 backtest base / Data API parquet datamart，并支持持久 warm cache 与 Step4 reuse proof。否则以后所有依赖市值、换手率、量比、流动性控制或 size neutralization 的因子都会重复付出相同 IO 成本。

## 当前观察

本轮 production proof 中：

1. moneyflow 因子已经改为 consume minute-derived daily state，不再默认走 generic full-window minute streaming。
2. Step4 仍然较慢，profiling 显示主要时间消耗不在 minute factor compute，而在 daily controls 路径，尤其是 `daily_basic_incremental`。
3. v3 / v4 都需要 lagged daily_basic controls：
   - `turnover_rate`
   - `volume_ratio`
   - `total_mv` / size proxy
   - lagged overheat / liquidity / size residual penalty
4. 当前研究结论不能简单归因于 minute data 性能；daily_basic 已成为新的公共基础设施瓶颈。

这说明 Step4 性能优化已经进入第二层：minute-derived datamart 解决了 intraday feature extraction，但 daily control surface 仍需要 parquet 化和 reuse 化。

## 为什么这是长期问题

`daily_basic` 不只是 moneyflow 使用。未来大量正式因子会使用：

```text
market cap / float cap
turnover
volume ratio
valuation filters
liquidity controls
size neutralization
risk bucket / Bayesian condition
small-cap subgroup test
cost and capacity proxy
```

如果这些字段每次都从 CSV 或 S3 cold path 读取并重复合并，那么即使 factor value 本身已经缓存，Step4 仍会在基础数据 IO 上反复浪费时间。

这会影响：

1. 新因子的 full Step4。
2. child revision 的 repeated Step4。
3. multibranch branch_comparison。
4. small-size / liquidity bucket subgroup test。
5. IS / OOS split 下的重复评估。
6. Council loop 中多方向 exploration / exploit 的吞吐。

## 建议目标架构

### 1. 发布 daily_basic parquet datamart

建议新增或正式发布：

```text
dataset_id: daily_basic
storage_format: parquet
partition: trade_date
grain: trade_date x ts_code
```

最低字段：

```text
trade_date
ts_code
turnover_rate
turnover_rate_f
volume_ratio
pe
pe_ttm
pb
ps
ps_ttm
dv_ratio
dv_ttm
total_share
float_share
free_share
total_mv
circ_mv
source_data_version
producer_version
artifact_hash
```

字段可以按 Data API 现有 schema 调整，但必须保证 Step4 常用 controls 不再从 raw CSV cold path 重复读取。

### 2. Data API 支持持久 warm cache

建议遵循 moneyflow parquet cache 的模式：

```bash
export FACTORFORGE_DATA_CACHE=/path/to/persistent/factorforge_data_api_cache
export FACTORFORGE_S3_REGION=ap-southeast-1
```

要求：

1. parquet partition 第一次读取后进入本地持久 cache。
2. 周末 / 非交易日 / 缺失日期支持 negative marker，避免重复探测 S3。
3. cache key 需要包含 dataset id、version、partition path/hash，避免 stale data 污染。
4. Step4 profile 必须区分 cold / warm 或至少记录 cache hit / miss。

### 3. Step4 使用 prepared backtest base

Step4 不应每个因子都重新构建 daily snapshot / controls。

建议增加或强化：

```text
backtest_base_daily_controls_v1
```

其中包含：

```text
trade_date
ts_code
forward_return_label
tradability flags
limit / ST filters
daily_basic controls
market cap / size bucket
industry / index membership if needed
cost proxy
```

因子 Step4 只需要把 `factor_values` 按 `trade_date, ts_code` merge 到这个 base 上。

### 4. Step4 validator 增加 daily_basic reuse proof

每次正式 proof 应输出：

```text
daily_basic_selected_format = parquet
daily_basic_cache_hit = true/false
daily_basic_cache_path = ...
daily_basic_rows = ...
daily_basic_dates = ...
daily_basic_tickers = ...
daily_basic_load_seconds = ...
backtest_base_reuse_hit = true/false
```

如果配置声明 parquet / reuse required，但实际 fallback 到 CSV，应 BLOCK：

```text
BLOCK_FACTORFORGE_DAILY_BASIC_PARQUET_REQUIRED
BLOCK_FACTORFORGE_BACKTEST_BASE_REUSE_REQUIRED
```

## 验收标准

### Smoke / synthetic

1. 新增或更新 Data API smoke：
   - 读取 `daily_basic` 一个短窗口；
   - 第一次允许 cold；
   - 第二次必须 warm cache 命中；
   - 行数、日期数、ticker 数非零；
   - schema 包含 Step4 常用字段。

2. 新增 Step4 smoke：
   - 同一 report / same window 跑两次 Step4；
   - 第一次可以 build base；
   - 第二次必须 `backtest_base_reuse_hit=true`；
   - 不写 full factor CSV；
   - validator PASS。

### Production proof

建议用一个已经有真实 Step4 压力的 report 做窄 proof，例如 moneyflow v3 或 Alpha037 类似 daily-control-heavy 因子。

验收字段：

```text
repo_sha
run_id
artifact_root
Step4 backend
daily_basic_selected_format
daily_basic_cache_hit
daily_basic_load_seconds
backtest_base_reuse_hit
factor_values_selected_format
full_factor_csv_written=false
validator verdict=PASS
no clean data processing
no search_worker
no official promotion
```

性能目标不应按全新冷机器首次拉 S3 定义，而应按持久 warm cache 定义。冷启动耗时可以记录，但不作为常规 Step4 SLA。

## 边界要求

本反馈不要求：

1. 改变因子研究结论。
2. 重跑 clean data。
3. 改写 moneyflow 因子公式。
4. 写 official promotion。
5. 启动 search worker。

本反馈只要求解决一个长期基础设施问题：

```text
daily_basic / daily controls should be parquetized, cached, reusable, and visible in Step4 proof.
```

## 研究员影响

修复后，研究员可以更高效地继续：

1. v3 moneyflow full sample / subgroup test。
2. small-size 20% bucket evaluation。
3. size-neutralized / liquidity-neutralized moneyflow residual。
4. v3 的 Bayesian threshold search。
5. Council multi-branch exploration。

否则这些研究都会把时间浪费在相同的 daily_basic IO 上，而不是花在真正的因子机制验证上。
