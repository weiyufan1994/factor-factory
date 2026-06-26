# Factor Forge Data API 数据字典

更新日期：2026-06-26

本文档是 Data API 当前可用数据集、字段口径、使用方式和验收边界的维护入口。研究员、Factor Forge Step3/Step4、Manus、Codex 和 worker 侧都应优先按本文档理解数据契约；具体字段列表和路径仍以运行时 active catalog 为准。

## 状态入口

Data API 维护三类机器可读状态文件：

```text
docs/operations/feature-family-registry.v1.json
docs/operations/feature-precompute-registry.v1.json
docs/operations/data-team-daily-ops-checklist.v1.json
```

统一摘要可通过以下命令生成：

```bash
PYTHONPATH=. python3 scripts/build_data_api_status_report.py \
  --output /tmp/data_api_status_report.json \
  --markdown-output /tmp/data_api_status_report.md
```

这份 status report 只用于 handoff 和规划，不是 active production catalog。正式读取仍以运行时 catalog 为准。

如果需要把当前数据层状态转交给 Factor Forge 架构师或研究员，使用只读 handoff package：

```bash
PYTHONPATH=. python3 scripts/build_data_api_handoff_package.py \
  --output-dir /tmp/data_api_handoff_package
```

输出目录包含 `README.md`、`data_api_status_report.json`、`data_api_status_report.md`、registry validation proof 和 `handoff_summary.json`。这仍然不是 active production catalog，只表示当前 Data API registry/规划/验收边界。

如果只需要查看哪些时序 feature 值得预处理、Alpha360 应该如何定位、分钟数据优先做哪些 datamart，可以生成独立 decision report：

```bash
PYTHONPATH=. python3 scripts/build_feature_precompute_decision_report.py \
  --output /tmp/feature_precompute_decision_report.json \
  --markdown-output /tmp/feature_precompute_decision_report.md
```

当前口径：`daily_technical_state_v1` 优先生产化；`intraday_flow_distribution_moments_v1` 在 source datamart/worker proof 完成后生产化；`daily_alpha360_lite_v1` 属于模型特定的宽 lag tensor，适合 projection-first 使用，不应替代紧凑日度技术状态。`daily_alpha360_lite_v1` 已有 bounded proof 和 full IS worker-plan bundle，但在 full-window worker build/read-smoke 前仍不能进 active catalog。cross-sectional rank/zscore/neutralization 仍留在研究侧按 universe 和可投资性过滤后计算。

如果需要检查每个 feature datamart 当前到底缺哪个 proof、能否进入 worker closeout 或 active catalog review，使用 readiness report：

```bash
PYTHONPATH=. python3 scripts/build_datamart_readiness_report.py \
  --output /tmp/datamart_readiness_report.json \
  --markdown-output /tmp/datamart_readiness_report.md
```

readiness report 只检查 registry 和 proof 文件状态，不启动 worker，不写 catalog。

## 使用原则

Data API 是只读数据访问层。它只负责从已注册 catalog 中读取数据、做字段解析、覆盖检查和重复键检查，不负责启动 clean data、search worker、official promotion，也不写 Factor Forge research artifacts。

正式研究只应消费 `status in {"ready", "proxy_ready"}` 的结果。`blocked` 不是空数据容忍，而是数据契约未满足。

生产侧当前推荐使用 parquet-first / warm-cache datamart。raw S3 CSV 或未预热分钟数据可以读，但不应作为 full-window research loop 的默认路径。

## 因子库分层与维护责任

因子库按三层维护，不能混用：

| 层级 | 用途 | S3 canonical path | Data API catalog |
| --- | --- | --- | --- |
| 正式因子库 | 只放通过 Step6 / reviewer 明确准入的 official 因子，用于正式组合、正式对照和生产研究引用 | `s3://yufan-data-lake/factorforge/datamart/factor_library_registry/v1/`、`s3://yufan-data-lake/factorforge/datamart/factor_library_exposure_panel/v1/`、`s3://yufan-data-lake/factorforge/datamart/factor_library_factor_return_panel/v1/` | `factor_library_registry_v1`、`factor_library_exposure_panel_v1`、`factor_library_factor_return_panel_v1` |
| Candidate feature 库 | 保留没有被直接 reject、可作为特征/状态/对照使用的候选因子；不得等同 official | `s3://yufan-data-lake/factorforge/datamart/factor_library_candidate_feature/v1/` 或当前 bootstrap 过渡路径 | 进入 active catalog 前必须有 QA/read-smoke；bootstrap exposure 未完成 S3 发布时不得标记 production-ready |
| Research interim data 库 | 保留每个研究员研究过程中产出的 factor values、derived feature、state panel、smoke panel；用于复现和后续沉淀，不用于正式结论 | `s3://yufan-data-lake/factorforge/research_interim_datamart/<research_id>/<dataset_id>/v1/` | 默认不进 active catalog；只有经 closeout/reviewer 接受后才能提升到 candidate 或 official catalog |

维护责任：

- `data_api_oncall` 每日维护因子库 datamart/catalog/proof 层，确保 S3、active catalog、read smoke 和 duplicate-key QA 一致。
- 研究员 / Step6 只负责 alpha 结论、official/candidate/reject 判断和研究解释；Data API 不替研究员做 alpha promotion。
- 本地 Mac、worker、EC2 上产生的因子数据必须及时同步到 S3。Mac/local path 只能是临时 fallback，不算 production-ready。
- 每日维护任务登记在 `docs/operations/data-team-daily-ops-checklist.v1.json` 的 `factor_library_daily_refresh`；研究中间成果同步登记在 `research_interim_data_s3_sync`。

最低发布证明：

```text
registry_row_count / exposure_panel_row_count / factor_return_panel_row_count
duplicate_key_count = 0
s3_sync_summary
DataApiClient read_smoke = ready
official/candidate/interim status explicit
```

## 回测运行面：Qlib Provider

`qlib_daily_provider` 不是 Data API catalog dataset，而是由 `clean_daily_bar` 派生出来的 Microsoft Qlib provider，用于 Factor Forge Step4 qlib-native backtest 和 RD-Agent `fin_factor_lite`。

来源链路：

```text
Tushare daily_incremental + daily_basic_incremental
  -> clean_daily_bar parquet/meta
  -> clean_daily_bar catalog publish
  -> qlib_daily_provider cn_data
```

canonical provider 路径：

| 环境 | provider_uri |
| --- | --- |
| Mac | `/Users/humphrey/.qlib/qlib_data/cn_data` |
| EC2 / worker | `/home/ubuntu/.qlib/qlib_data/cn_data` |
| S3 | `s3://yufan-data-lake/factorforge/datamart/qlib_data/cn_data/` |

当前验收快照：

| 项 | 值 |
| --- | --- |
| calendar | `2010-01-04` 到 `2026-06-10` |
| rows | `11,720,015` |
| instruments | `5,184` |
| dates | `3,989` |
| feature files | `46,656` |
| instrument style | `legacy_qlib` |

使用规则：

- Factor Forge Step4 qlib adapter 优先使用 `QLIB_PROVIDER_URI`，未设置时 fallback 到 `cn_data`，legacy `cn_tushare_full_adj` 只能作为最后兼容路径。
- RD-Agent lite 必须显式设置 `QLIB_PROVIDER_URI=/home/ubuntu/.qlib/qlib_data/cn_data` 和 `FF_PROVIDER_URI=/home/ubuntu/.qlib/qlib_data/cn_data`。
- 每日 Tushare 更新完成后，维护 wrapper 必须同步刷新 `clean_daily_bar`、publish catalog、重建 qlib provider，并把 provider 同步回 S3 canonical path。
- Mac 或 EC2 本地 provider 若落后，应从 S3 canonical path 同步，不应回退到旧 `cn_tushare_full_adj`。

验收 smoke：

```python
import qlib
from qlib.data import D

qlib.init(provider_uri="/path/to/cn_data", region="cn")
calendar = D.calendar(freq="day")
values = D.features(["SH600000"], ["$close"], freq="day")
assert len(calendar) > 0 and len(values) > 0
```

## Python 入口

本 repo 内的稳定入口是：

```python
from factor_factory.data_api import DataApiClient, DataQuery, validate_data_api_result

client = DataApiClient.from_catalog("/path/to/data_catalog.json")
result = client.fetch(
    DataQuery(
        dataset="clean_daily_bar",
        start_date="20200102",
        end_date="20200131",
        universe="a_share_all",
        fields=["open", "high", "low", "close", "vol", "amount"],
        frequency="daily",
    )
)

report = validate_data_api_result(result)
assert result.status in {"ready", "proxy_ready"}, result.blocked_reason
df = result.frame
```

Catalog 查找顺序：

1. `FACTORFORGE_DATA_CATALOG`
2. `$FACTORFORGE_ROOT/data/catalog/data_catalog.json`
3. repo-local `factorforge/data/catalog/data_catalog.json`

true factor research worker 上，Moneyflow V9/V10 数据层最近一次验收使用的 catalog 是：

```text
/opt/factorforge/data-api-config/data_catalog.moneyflow_v9_v10_is.json
```

对应 closeout proof：

```text
/opt/factorforge/data-api-proofs/moneyflow-v9-v10-production/moneyflow_v9_v10_data_layer_closeout.json
```

## 查询模板

### 日线行情

```python
result = client.fetch(
    DataQuery(
        dataset="clean_daily_bar",
        start_date="20200102",
        end_date="20200131",
        universe=["000001.SZ", "600000.SH"],
        fields=["open", "high", "low", "close", "vol", "amount"],
        frequency="daily",
    )
)
```

### 日度基础数据 / 回测基础表

```python
result = client.fetch(
    DataQuery(
        dataset="backtest_base",
        start_date="20200102",
        end_date="20200131",
        universe="a_share_all",
        fields=[
            "circ_mv",
            "total_mv",
            "turnover_rate",
            "turnover_rate_f",
            "volume_ratio",
            "fixed_small_universe_flag",
        ],
        frequency="daily",
    )
)
```

### 标准全市场 universe

```python
result = client.fetch(
    DataQuery(
        dataset="standard_full_market_universe",
        start_date="20240110",
        end_date="20240110",
        universe="a_share_all",
        fields=["universe_name", "market_cap", "in_universe"],
        frequency="daily",
    )
)

standard_market_df = result.frame[result.frame["in_universe"]]
```

### 微盘 Small10 / Small20 universe

```python
result = client.fetch(
    DataQuery(
        dataset="microcap_universe",
        start_date="20240110",
        end_date="20240110",
        universe="a_share_all",
        fields=[
            "universe_id",
            "universe_name",
            "market_cap",
            "market_cap_source",
            "microcap_rank_asc_after_exclusion",
            "microcap_rank_pct_after_exclusion",
            "excluded_small_cap",
            "excluded_bottom_market_cap",
            "excluded_st",
            "excluded_new_stock",
            "excluded_untradable",
            "excluded_major_risk",
            "in_universe",
        ],
        frequency="daily",
    )
)

small10_df = result.frame[(result.frame["universe_id"] == "microcap_small10") & result.frame["in_universe"]]
small20_df = result.frame[(result.frame["universe_id"] == "microcap_small20") & result.frame["in_universe"]]
```

### 日度可投资性 flags

```python
result = client.fetch(
    DataQuery(
        dataset="tradability_risk_flags_daily",
        start_date="20240110",
        end_date="20240110",
        universe="a_share_all",
        fields=[
            "market_cap",
            "market_cap_source",
            "excluded_small_cap",
            "excluded_st",
            "excluded_new_stock",
            "excluded_untradable",
            "excluded_major_risk",
            "is_investable_core",
            "is_investable_500m",
        ],
        frequency="daily",
    )
)

flags_df = result.frame
```

### 中证指数成分 universe

```python
result = client.fetch(
    DataQuery(
        dataset="index_weight_universe",
        start_date="20240110",
        end_date="20240110",
        universe="a_share_all",
        fields=["universe_id", "index_code", "index_name", "source_weight_date", "weight", "in_universe"],
        frequency="daily",
    )
)

csi300_df = result.frame[result.frame["universe_id"] == "csi300"]
```

### 1 分钟 bar

```python
result = client.fetch(
    DataQuery(
        dataset="minute_bar",
        start_date="20240110",
        end_date="20240110",
        universe=["000001.SZ"],
        fields=["trade_time", "open", "high", "low", "close", "vol", "amount"],
        frequency="1min",
    )
)
```

### 盘中 flow state

短期建议显式请求 `cutoff_time`，避免调用方或 validator 只按 `ts_code + trade_date` 理解唯一键。

```python
result = client.fetch(
    DataQuery(
        dataset="intraday_flow_state_v2",
        start_date="20240110",
        end_date="20240110",
        universe="a_share_all",
        fields=[
            "cutoff_time",
            "signed_amount_sum",
            "gross_amount_sum",
            "large_net_flow_ratio_abs",
            "small_net_flow_ratio_abs",
            "amount_hhi",
            "flow_hhi",
            "threshold_source",
            "threshold_lookback_days",
            "no_future_intraday_minutes",
            "research_window",
        ],
        frequency="intraday",
    )
)
```

### 盘中 cutoff state pack

`intraday_cutoff_state_pack_v1` 是从 1 分钟 bar 生成的紧凑 cutoff 状态包，覆盖 cutoff 前 return、amount、volume、realized volatility、terminal 20m return/amount share 等通用状态。目前已有 builder/validator、2024-01-02 单日全市场 bounded proof、full IS worker-plan bundle；尚未跑 2016-01-04 到 2025-07-11 full-window worker build/read-smoke，因此还不是 production-ready datamart。

```python
result = client.fetch(
    DataQuery(
        dataset="intraday_cutoff_state_pack_v1",
        start_date="20240110",
        end_date="20240110",
        universe="a_share_all",
        fields=[
            "cutoff_time",
            "cutoff_ret",
            "cutoff_vwap",
            "amount_sum",
            "volume_sum",
            "realized_vol",
            "terminal_ret_20m",
            "terminal_amount_share_20m",
            "terminal_realized_vol_20m",
            "no_future_intraday_minutes",
            "research_window",
        ],
        frequency="intraday_cutoff",
    )
)
```

唯一键：`ts_code + trade_date + cutoff_time`

信息集限制：

- 每行只使用 `trade_time <= cutoff_time` 的分钟。
- terminal 20m 只在 cutoff 前样本内取最后窗口。
- 不使用当日全日 denominator，因此 10:30/11:30/14:00 等早盘 cutoff 不会偷看收盘后分钟。

### 盘中 EMA slow state

`intraday_ema_slow_state_v1` 是通用递推慢变量 datamart，从已验收的盘中 cutoff source datamart 读取一个 `signal_col`，按 `ts_code + cutoff_time + lambda` 连续递推：

```text
H[i,t,cutoff,lambda] = lambda * H[i,t-1,cutoff,lambda] + (1 - lambda) * signal[i,t,cutoff]
```

当前已有 builder/validator、bounded recurrence proof、DataApiClient read-smoke；尚未跑 full-window worker proof，也依赖 `intraday_flow_distribution_moments_v1` 等 source datamart 先 production-ready。

```python
result = client.fetch(
    DataQuery(
        dataset="intraday_ema_slow_state_v1",
        start_date="20250102",
        end_date="20250102",
        universe="a_share_all",
        fields=[
            "cutoff_time",
            "lambda",
            "signal_value",
            "ema_state",
            "source_signal_col",
            "state_source",
            "no_future_data",
            "research_window",
        ],
        frequency="intraday_cutoff",
    )
)
```

唯一键：`ts_code + trade_date + cutoff_time + lambda`

信息集限制：

- source datamart 必须已经满足 cutoff 信息集合法性。
- 递推只使用当前 source row 和上一交易日以前的状态。
- full-window production 不允许按年份 reset 后宣称连续状态；如果按 chunk 跑，必须传递上一 chunk final state，或显式 warm-up 并丢弃 warm-up metrics。

### 盘中 terminal correlation state

`intraday_terminal_corr_state_v1` 是 CPV/尾盘形态类因子的通用预处理层。它对每个 `ts_code + trade_date + cutoff_time + window_id`，只使用 `trade_time <= cutoff_time` 的分钟，返回最后一个 rolling window 的价量相关状态。默认特征包括 `close_amount_corr`、`ret_amount_corr`、terminal return、terminal amount/volume、terminal realized volatility。

当前已有 builder/validator、bounded kernel/read-smoke proof；尚未跑 full-window worker plan 和性能 gate，因此还不是 production-ready datamart。

```python
result = client.fetch(
    DataQuery(
        dataset="intraday_terminal_corr_state_v1",
        start_date="20240103",
        end_date="20240103",
        universe="a_share_all",
        fields=[
            "cutoff_time",
            "window_id",
            "close_amount_corr",
            "ret_amount_corr",
            "terminal_ret",
            "terminal_realized_vol",
            "no_future_intraday_minutes",
        ],
        frequency="intraday_cutoff",
    )
)
```

唯一键：`ts_code + trade_date + cutoff_time + window_id`

信息集限制：

- 每行只使用 cutoff 前分钟。
- 使用 terminal-only rolling correlation operator，只返回每组最后状态，不物化全量 per-minute rolling vector。
- full-window 前需要先完成 kernel performance gate 和 worker read-smoke。

### pseudo dollar bar

`intraday_pseudo_dollar_bar_v1` 是从 1 分钟 bar 重建的 pseudo dollar bar，不是真 tick dollar bar。必须显式保留 `bucket_id`。

```python
result = client.fetch(
    DataQuery(
        dataset="intraday_pseudo_dollar_bar_v1",
        start_date="20240110",
        end_date="20240110",
        universe=["000001.SZ"],
        fields=[
            "bucket_id",
            "start_time",
            "end_time",
            "open",
            "high",
            "low",
            "close",
            "amount",
            "vol",
            "signed_amount",
            "return",
            "large_proxy_amount",
            "small_proxy_amount",
            "threshold_source",
            "no_future_intraday_minutes",
            "research_window",
        ],
        frequency="intraday",
    )
)
```

### 盘中分布形态

```python
result = client.fetch(
    DataQuery(
        dataset="intraday_flow_distribution_moments_v1",
        start_date="20240110",
        end_date="20240110",
        universe="a_share_all",
        fields=[
            "cutoff_time",
            "ret_skew",
            "ret_excess_kurtosis",
            "ret_tail_asymmetry",
            "amount_skew",
            "amount_excess_kurtosis",
            "amount_hhi",
            "amount_entropy",
            "signed_amount_skew",
            "signed_amount_excess_kurtosis",
            "signed_flow_hhi",
            "signed_flow_tail_asymmetry",
            "large_proxy_amount",
            "small_proxy_amount",
            "threshold_source",
            "no_future_intraday_minutes",
            "research_window",
        ],
        frequency="intraday",
    )
)
```

## 正式数据集

### `clean_daily_bar`

用途：日度 OHLCV 行情，Factor Forge daily factor 和 Step3 sample validation 的基础表。

唯一键：`ts_code + trade_date`

常用字段：

| 字段 | 含义 | 说明 |
| --- | --- | --- |
| `ts_code` | 股票代码 | Tushare 风格代码 |
| `trade_date` | 交易日 | `YYYYMMDD` |
| `open` | 开盘价 | 未在本文档声明复权口径时，以 catalog metadata 为准 |
| `high` | 最高价 | 同上 |
| `low` | 最低价 | 同上 |
| `close` | 收盘价 | 同上 |
| `vol` | 成交量 | Tushare 原生口径 |
| `amount` | 成交额 | Tushare 原生口径 |
| `pct_chg` | 日收益/涨跌幅 | 若 catalog 有该列，可作为 return alias 来源 |

使用注意：

- 请求 `volume` 会按 Data API alias 解析到 `vol`。
- 请求 `market_cap` 不会从日线行情静默推导，应使用 `daily_basic` 或 `backtest_base`。

### `daily_basic`

用途：日度基础指标、市值、换手率和量比。

唯一键：`ts_code + trade_date`

正式 IS warm-cache 验收口径：2016-01-04 到 2025-07-11。

正式 proof 摘要：

| 项 | 值 |
| --- | --- |
| rows | `9,500,407` |
| dates | `2,313` |
| duplicate keys | `0` |
| required fields | `circ_mv`, `total_mv`, `turnover_rate`, `turnover_rate_f`, `volume_ratio` |

常用字段：

| 字段 | 含义 | 说明 |
| --- | --- | --- |
| `circ_mv` | 流通市值 | fixed small universe 优先使用 |
| `total_mv` | 总市值 | `circ_mv` 缺失时 fallback |
| `turnover_rate` | 换手率 | 日度基础字段 |
| `turnover_rate_f` | 自由流通换手率 | 日度基础字段 |
| `volume_ratio` | 量比 | 日度基础字段 |

### `backtest_base`

用途：回测基础表，复用 `daily_basic` warm-cache，给 Step4/worker 减少重复读取。

唯一键：`ts_code + trade_date`

正式 proof 摘要：

| 项 | 值 |
| --- | --- |
| datamart | `/opt/factorforge/data-api-datamarts/daily_basic_backtest_base_is` |
| coverage | 2016-01-04 到 2025-07-11 |
| rows | `9,500,407` |
| dates | `2,313` |
| duplicate keys | `0` |
| backtest_base_reuse_hit | `true` |

`fixed_small_universe_flag` 口径：

1. 市值优先使用 `circ_mv`，缺失时 fallback 到 `total_mv`。
2. 剔除市值低于 5 亿人民币的股票。
3. 剔除当日市值最小 10%。
4. 在剩余样本中取最小 20%。

### `minute_bar`

用途：1 分钟自然时间 bar，是 intraday flow、pseudo dollar bar 和分布形态数据的上游来源。

唯一键：`ts_code + trade_date + trade_time`

常用字段：

| 字段 | 含义 | 说明 |
| --- | --- | --- |
| `trade_time` | 分钟时间 | A 股交易分钟 |
| `open` | 分钟开盘价 | 1m bar |
| `high` | 分钟最高价 | 1m bar |
| `low` | 分钟最低价 | 1m bar |
| `close` | 分钟收盘价 | 1m bar |
| `vol` | 分钟成交量 | 1m bar |
| `amount` | 分钟成交额 | 1m bar |

使用注意：

- 当前 V7/V9/V10 moneyflow 研究仍以 1 分钟 bar 为上游，不是 true tick dollar bar。
- Mac 或 worker 若没有 warm cache，跨多年读取会被 raw source IO 限制。
- full-window production loop 应优先使用预聚合 intraday datamart，而不是每次重新扫分钟流。

### `standard_full_market_universe`

用途：Factor Forge 默认“标准全市场”回测样本空间。

唯一键：`trade_date + ts_code`

正式 IS coverage：2016-01-04 到 2025-07-11。

本地 proof 摘要：

| 项 | 值 |
| --- | --- |
| datamart | `/Users/humphrey/projects/factor-factory-data-api/factorforge/data/datamart/standard_full_market_universe` |
| rows | `9,500,407` |
| selected rows | `7,865,012` |
| dates | `2,313` |
| duplicate keys | `0` |

筛选规则：

1. 市值优先使用 `circ_mv`，缺失时 fallback 到 `total_mv`。
2. 每个交易日剔除市值最大的 `min(300, ceil(n * 10%))` 只股票。
3. 每个交易日剔除市值最小的 `ceil(n * 10%)` 只股票。
4. 剔除市值小于 5 亿人民币的股票。Tushare `daily_basic` 市值单位为万元，所以阈值为 `50000`。

常用字段：

| 字段 | 含义 | 说明 |
| --- | --- | --- |
| `universe_id` | universe id | `standard_full_market` |
| `universe_name` | 中文名 | `标准全市场` |
| `market_cap` | 用于筛选的市值 | `circ_mv` 优先，`total_mv` fallback |
| `market_cap_source` | 市值来源 | `circ_mv` / `total_mv` / `missing` |
| `excluded_top_market_cap` | 是否被大市值头部剔除 | bool |
| `excluded_bottom_market_cap` | 是否被小市值尾部剔除 | bool |
| `excluded_small_cap` | 是否低于 5 亿 | bool |
| `in_universe` | 是否入样本空间 | 回测应过滤为 true |

### `microcap_universe`

用途：微盘风格回测样本空间，当前包含两个日度时序 universe：

| universe_id | universe_name | 口径 |
| --- | --- | --- |
| `microcap_small10` | `微盘Small10` | 风险和可交易性排除后，剩余股票中市值最小的 10% |
| `microcap_small20` | `微盘Small20` | 风险和可交易性排除后，剩余股票中市值最小的 20% |

唯一键：`universe_id + trade_date + ts_code`

筛选规则：

1. 市值优先使用 `circ_mv`，缺失时 fallback 到 `total_mv`。
2. 剔除市值小于 5 亿人民币的股票。Tushare `daily_basic` 市值单位为万元，所以阈值为 `50000`。
3. 每个交易日先剔除全市场市值最小的 `ceil(n * 10%)` 只股票。
4. 剔除 ST：`stock_st` 区间命中，或股票名称包含 `ST`。
5. 剔除新股：上市交易日龄小于 60 个交易日，或缺少有效 `list_date`。
6. 剔除不可交易股票：当日 `vol <= 0`、`amount <= 0` 或 `close` 缺失。
7. 剔除重大风险股票：`stock_basic.list_status != L`，或股票名称包含 `退`。
8. 在剩余可选池中按市值从小到大排序，分别取最小 10% 和最小 20%。

常用字段：

| 字段 | 含义 | 说明 |
| --- | --- | --- |
| `universe_id` | universe id | `microcap_small10` / `microcap_small20` |
| `universe_name` | 中文名 | `微盘Small10` / `微盘Small20` |
| `market_cap` | 用于筛选的市值 | `circ_mv` 优先，`total_mv` fallback |
| `market_cap_source` | 市值来源 | `circ_mv` / `total_mv` / `missing` |
| `base_market_cap_rank_asc` | 全市场市值升序排名 | 用于底部 10% 剔除 |
| `microcap_rank_asc_after_exclusion` | 排除后的市值升序排名 | 用于 Small10 / Small20 选择 |
| `microcap_rank_pct_after_exclusion` | 排除后的市值排名百分位 | 越小越微盘 |
| `excluded_small_cap` | 是否低于 5 亿 | bool |
| `excluded_bottom_market_cap` | 是否被全市场最小 10% 剔除 | bool |
| `excluded_st` | 是否 ST | bool |
| `excluded_new_stock` | 是否新股 | bool |
| `excluded_untradable` | 是否不可交易 | bool |
| `excluded_major_risk` | 是否重大风险 | bool |
| `is_eligible_after_exclusion` | 是否进入微盘排序候选池 | bool |
| `in_universe` | 是否入当前 universe | 回测应同时过滤 `universe_id` 和 true |

### `tradability_risk_flags_daily`

用途：统一的日度可投资性后过滤表。标准全市场、指数成分、微盘 universe 等 raw universe 均不应被原地覆盖；回测时应按 `trade_date + ts_code` join 本表，再选择 `is_investable_core` 或 `is_investable_500m`。

唯一键：`trade_date + ts_code`

正式 IS coverage：2016-01-04 到 2025-07-11。

本地 proof 摘要：

| 项 | 值 |
| --- | --- |
| datamart | `/Users/humphrey/projects/factor-factory-data-api/factorforge/data/datamart/tradability_risk_flags_daily` |
| rows | `9,238,520` |
| dates | `2,313` |
| duplicate keys | `0` |
| `is_investable_core` rows | `8,075,552` |
| `is_investable_500m` rows | `7,980,415` |

字段：

| 字段 | 含义 | 说明 |
| --- | --- | --- |
| `trade_date` | 交易日 | `YYYYMMDD` |
| `ts_code` | 股票代码 | Tushare 风格代码 |
| `market_cap` | 用于市值过滤的市值 | `circ_mv` 优先，`total_mv` fallback |
| `market_cap_source` | 市值来源 | `circ_mv` / `total_mv` / `missing` |
| `excluded_small_cap` | 是否低于 5 亿 | Tushare 市值单位为万元，阈值 `50000` |
| `excluded_st` | 是否 ST | `stock_st` 区间或名称包含 `ST` |
| `excluded_new_stock` | 是否新股 | 上市交易日龄小于 60 个交易日，或缺少有效 `list_date` |
| `excluded_untradable` | 是否不可交易 | 当日 `vol <= 0`、`amount <= 0` 或 `close` 缺失 |
| `excluded_major_risk` | 是否重大风险 | `list_status != L` 或名称包含 `退` |
| `is_investable_core` | 核心可投资 | 未触发 ST、新股、不可交易、重大风险 |
| `is_investable_500m` | 5亿市值加强可投资 | `is_investable_core` 且未触发 `excluded_small_cap` |

使用注意：

- 指数 raw universe 仍保留真实指数成分和权重；实际回测时 join 本表过滤。
- 若策略不希望剔除小市值，仅使用 `is_investable_core`。
- 若策略需要通用机构可投资性口径，使用 `is_investable_500m`。

### `index_weight_universe`

用途：沪深300、中证A500、中证1000、中证500、中证800、中证全指、中证2000 的历史成分股和权重，展开为 daily 回测 universe。

唯一键：`universe_id + trade_date + ts_code`

上游：Tushare `index_weight`。

当前目标指数：

| universe_id | index_code | index_name |
| --- | --- | --- |
| `csi300` | `000300.SH` | 沪深300 |
| `csi_a500` | `000510.SH` | 中证A500 |
| `csi1000` | `000852.SH` | 中证1000 |
| `csi500` | `000905.SH` | 中证500 |
| `csi800` | `000906.SH` | 中证800 |
| `csi_all_share` | `000985.CSI` | 中证全指 |
| `csi2000` | `932000.CSI` | 中证2000 |

字段：

| 字段 | 含义 | 说明 |
| --- | --- | --- |
| `universe_id` | 回测 universe id | 下游按该字段筛选指数 |
| `index_code` | Tushare 指数代码 | 原始指数代码 |
| `index_name` | 指数名称 | 中文名 |
| `trade_date` | 回测交易日 | 已按交易日历展开 |
| `source_weight_date` | 权重快照日期 | Tushare `index_weight` 原始日期 |
| `ts_code` | 成分股代码 | 股票代码 |
| `weight` | 指数权重 | 原始权重 forward-fill 到交易日 |
| `in_universe` | 是否为成分 | bool |

使用注意：

- Tushare `index_weight` 返回的是权重快照日期，不是每个交易日一份。
- Data API datamart 会把快照权重按交易日历 forward-fill 成 daily universe，并保留 `source_weight_date`。
- 下游 duplicate validation 必须按 `universe_id + trade_date + ts_code`，不能只按 `ts_code + trade_date`。

### `intraday_value_occupation_state_v1`

用途：把 `minute_bar` 的分钟成交额从时间轴投影到价格轴，形成日频 price-axis occupation / volume profile state，供筹码分布、成本分布、支撑、套牢、breakout resistance、repair / defense 类研究复用。

当前状态：P0 builder、schema、catalog sidecar 和本地测试已定义；2016-01-04 到 2025-07-11 full-window parquet、QA json 和 worker read smoke 生成前，不得标记为 production-ready。

唯一键：`ts_code + trade_date + cutoff_time + lookback_days`

研究侧口径确认：2026-06-10 已确认 P0 只保留 state variables；`support_minus_overhang`、`below_cost_guarded_support`、`vp_below_cost_repair_v1` 等组合分数由研究侧在 Factor Forge 下游计算，Data 组不写入 production datamart，也不交付 alpha 有效性结论。

MVP coverage 目标：2016-01-04 到 2025-07-11。

MVP 参数：

| 参数 | 值 |
| --- | --- |
| `cutoff_time` | `14:50:00` |
| `lookback_days` | `20` |
| `bin_width_bps` | `20` |
| `value_area_mass` | `0.70` |
| `near_band_bps` | `300` |
| `source_dataset` | `minute_bar` |

信息集约束：

| metadata | 值 |
| --- | --- |
| `no_future_intraday_minutes` | `true` |
| `source_dataset` | `minute_bar` |
| `missing_date_policy` | `source_ready_trade_dates_only` |
| `oos_holdout_policy` | `post_20250711_not_used_for_fitting` |

P0 字段：

| 字段族 | 字段 | 说明 |
| --- | --- | --- |
| key / metadata | `ts_code`, `trade_date`, `cutoff_time`, `lookback_days` | 唯一键字段 |
| source coverage | `minute_count`, `current_day_minute_count`, `amount_total` | rolling window 和当日 cutoff 前覆盖 |
| contract metadata | `schema_version`, `producer_version`, `source_dataset`, `no_future_intraday_minutes` | 口径和信息集证明 |
| price-axis core | `reference_price`, `vwap_cost`, `poc_price`, `value_area_low`, `value_area_high` | cutoff 前 reference price 与价格轴 profile |
| distances | `distance_to_poc`, `distance_to_val`, `distance_to_vah` | 相对 reference price 距离 |
| profile params | `bin_width_bps`, `near_band_bps`, `profile_bin_count` | profile 构造参数 |
| support / overhang | `lower_support_mass`, `upper_overhang_mass`, `below_price_amount_mass`, `above_price_amount_mass` | reference price 上下方成交额质量 |
| ratios | `lower_support_ratio`, `upper_overhang_ratio`, `below_mass_ratio`, `above_mass_ratio` | amount-normalized ratios |
| below-cost / repair diagnostics | `below_cost_depth`, `below_cost_depth_score`, `downside_lvn_gap`, `upside_lvn_vacuum`, `no_break_gate`, `defended_support_gate` | 状态变量，不是 alpha 结论 |

使用注意：

- Data 组只交付状态变量，不交付 `support_minus_overhang`、`below_cost_guarded_support`、`vp_support_defense_repair_v1` 等研究侧组合分数。
- 研究侧已确认 `reference_price` 使用 cutoff 前最后一分钟 close，occupation mass 使用 `abs(amount)`，价格轴坐标使用 minute close，value area 按 price bin amount mass 从大到小累计到 70%。
- read smoke 必须证明 catalog projection 会自动带出 `cutoff_time` 和 `lookback_days`，duplicate validation 也必须使用这两个键。
- full-window production 运行应在 worker / warm datamart 上完成，不应在 Mac 上冷扫 raw S3 minute partitions。

### `intraday_flow_state_v2`

用途：Moneyflow V7/V9/V10 的正式盘中 flow state datamart。

唯一键：`ts_code + trade_date + cutoff_time`

正式 IS coverage：2016-01-04 到 2025-07-11。

OOS 规则：2025-07-12 之后只允许标记 holdout，不得混入参数或 revision fitting。

支持 cutoff：

```text
10:30, 11:30, 14:00, 14:30, 14:50, 14:55
```

信息集约束：

| metadata | 值 |
| --- | --- |
| `threshold_source` | `prior_dates` |
| `threshold_lookback_days` | `20,60` |
| `no_future_intraday_minutes` | `true` |
| `research_window` | `IS` |

使用注意：

- 每个 `ts_code + trade_date` 会有多个 cutoff 行。
- 调用方应显式请求 `cutoff_time`。
- validator 和下游 join 必须按 `ts_code + trade_date + cutoff_time` 判重。

常用字段族：

| 字段族 | 典型字段 | 说明 |
| --- | --- | --- |
| flow totals | `signed_amount_sum`, `gross_amount_sum`, `buy_amount_sum`, `sell_amount_sum` | cutoff 前分钟 flow 聚合 |
| large/small proxy | `large_net_flow_ratio_abs`, `large_net_flow_ratio_rel`, `small_net_flow_ratio_abs`, `small_net_flow_ratio_rel` | 绝对阈值和历史相对阈值两套口径 |
| concentration | `amount_hhi`, `participant_concentration_proxy`, `flow_hhi` | 资金集中度 proxy |
| volatility/noise | `intraday_ret_std`, `intraday_abs_ret_sum`, `intraday_noise` | cutoff 前分钟收益形态 |
| tail flow | `tail_net_flow_ratio_1400_1450`, `tail_net_flow_ratio_1430_1450`, `tail_net_flow_ratio_1450_1455` | 尾盘 flow 特征 |
| threshold metadata | `large_abs_threshold`, `small_abs_threshold`, `large_rel_threshold`, `small_rel_threshold`, `threshold_source`, `threshold_lookback_days` | prior-date threshold contract |

### `intraday_pseudo_dollar_bar_v1`

用途：从 1 分钟 bar 构造的 pseudo dollar bar datamart，用于 dollar-flow style 因子和稳定 bucket 特征。

唯一键：`ts_code + trade_date + bucket_id`

正式 proof 摘要：

| 项 | 值 |
| --- | --- |
| storage | `s3://yufan-data-lake/factorforge/datamart/intraday_pseudo_dollar_bar_v1/is` |
| coverage | 2016-01-04 到 2025-07-11 |
| rows | `1,860,126,542` |
| dates | `2,313` |
| duplicate keys | `0` |
| `threshold_source` | `prior_dates` |
| `no_future_intraday_minutes` | `true` |
| `true_tick_dollar_bar` | `false` |

常用字段：

| 字段 | 含义 | 说明 |
| --- | --- | --- |
| `bucket_id` | pseudo dollar bucket 编号 | 下游必须保留 |
| `start_time` | bucket 起始分钟 | 从 1m bar 推导 |
| `end_time` | bucket 结束分钟 | 从 1m bar 推导 |
| `open/high/low/close` | bucket OHLC | 从分钟 bar 聚合 |
| `vol` | bucket 成交量 | 从分钟 bar 聚合 |
| `amount` | bucket 成交额 | 从分钟 bar 聚合 |
| `signed_amount` | signed flow proxy | 基于分钟内价格方向的 proxy，不是逐笔主动买卖 |
| `large_proxy_amount` | 大单 proxy 金额 | 使用 prior-date threshold |
| `small_proxy_amount` | 小单 proxy 金额 | 使用 prior-date threshold |

限制：

- 这不是 true tick dollar bar。
- 由于上游是 1 分钟 bar，bucket 内的真实逐笔成交顺序不可恢复。

### `intraday_flow_distribution_moments_v1`

用途：按 cutoff 输出盘中 return、amount、signed-flow 的分布形态和 profit-payer ecology controls。

唯一键：`ts_code + trade_date + cutoff_time`

正式 proof 摘要：

| 项 | 值 |
| --- | --- |
| datamart | `/opt/factorforge/data-api-datamarts/intraday_flow_distribution_moments_v1_is` |
| coverage | 2016-01-04 到 2025-07-11 |
| rows | `55,529,370` |
| dates | `2,313` |
| duplicate keys | `0` |
| `threshold_source` | `prior_dates` |
| `no_future_intraday_minutes` | `true` |

支持 cutoff：

```text
10:30, 11:30, 14:00, 14:30, 14:50, 14:55
```

字段族：

| 字段族 | 典型字段 | 说明 |
| --- | --- | --- |
| return moments | `ret_skew`, `ret_excess_kurtosis`, `ret_tail_asymmetry` | 只使用 `trade_time <= cutoff_time` |
| amount moments | `amount_skew`, `amount_excess_kurtosis`, `amount_hhi`, `amount_entropy` | 成交额分布形态 |
| signed-flow moments | `signed_amount_skew`, `signed_amount_excess_kurtosis`, `signed_flow_hhi`, `signed_flow_tail_asymmetry` | signed flow proxy 分布形态 |
| concentration | `amount_hhi`, `signed_flow_hhi`, `amount_entropy` | flow concentration / dominance controls |
| proxy controls | `large_proxy_amount`, `small_proxy_amount`, `large_proxy_signed_amount`, `small_proxy_signed_amount` | prior-date threshold 口径 |

使用注意：

- 所有 cutoff 特征必须只使用 `trade_time <= cutoff_time`。
- 不得用当日全日 amount 分位作为 14:50/14:55 信号阈值。

## Source / topic 数据集

以下数据集可能存在于 active catalog 中，但是否可用于正式研究取决于该 dataset 的 coverage、QA 和 catalog metadata。没有 full-window proof 时，只能作为 source/exploratory 输入，不能直接宣称 production-ready。

| dataset | 用途 | 备注 |
| --- | --- | --- |
| `moneyflow` | Tushare 个股资金流向 | 历史覆盖曾经不足，正式使用前必须看 catalog coverage |
| `limit_list_d` | 打板/涨跌停相关日表 | Manus 和题材/打板研究常用 |
| `index_basic` | 指数基础信息 | 指数数据目录 |
| `index_daily` | 指数日线 | 指数行情 |
| `dc_index` | 东方财富主题/概念指数 | 题材指数 |
| `dc_member` | 东方财富主题/概念成分 | 题材成分 |

## 关键字段和口径

### 市值字段

| 字段 | 口径 | 使用建议 |
| --- | --- | --- |
| `circ_mv` | 流通市值 | fixed small universe、size control 优先使用 |
| `total_mv` | 总市值 | `circ_mv` 缺失时 fallback |
| `market_cap` | 逻辑字段 | 只有 catalog 显式配置 proxy 时才允许解析 |

### 阈值字段

| 字段 | 允许值/含义 | 要求 |
| --- | --- | --- |
| `threshold_source` | `prior_dates` | 正式 intraday 研究必须使用历史阈值 |
| `threshold_lookback_days` / `lookback_days` | `20`, `60` 等 | 不同 intraday dataset 字段名可能不同，metadata 和字段应能说明 |
| `no_future_intraday_minutes` | `true` | cutoff 特征不得看未来分钟 |

### cutoff 字段

`cutoff_time` 是 intraday dataset 的核心键字段，不是普通属性。支持：

```text
10:30, 11:30, 14:00, 14:30, 14:50, 14:55
```

下游 join、dedupe、coverage validation 必须把 `cutoff_time` 纳入唯一键。

### bucket 字段

`bucket_id` 是 pseudo dollar bar 的核心键字段。下游 join、dedupe、coverage validation 必须把 `bucket_id` 纳入唯一键。

## QA / 验收要求

每个 production dataset 至少需要保留以下证据：

| 证据 | 要求 |
| --- | --- |
| catalog json | dataset 已注册，包含 storage、format、schema、partition、metadata |
| QA json | `verdict=ACCEPT` 或等价字段 |
| coverage summary | dates、tickers、rows、missing dates、duplicate keys、null ratio |
| worker read smoke | true factor research worker 上能 import Data API 并读代表日期 |
| representative dates | 至少覆盖 early IS、mid IS、特殊缺失修复日、recent IS |
| information set proof | cutoff 只使用 cutoff 前分钟和 prior-date thresholds |

通用 DataApiClient read-smoke 命令：

```bash
PYTHONPATH=. python3 scripts/run_data_api_read_smoke.py \
  --catalog /path/to/catalog.json \
  --dataset-id daily_technical_state_v1 \
  --start-date 20240110 \
  --end-date 20240110 \
  --fields ret_1d,volatility_20d,amihud_20d \
  --output-path /tmp/daily_technical_state_v1.read_smoke.json
```

输出必须包含 `verdict`、`status`、`validation_result`、`warm_read_seconds`、`row_count`、`date_count`、`ticker_count`、`duplicate_key_count`、`returned_columns` 和 safety flags。生产 closeout 应消费这个 read-smoke，而不是每个 datamart 自己手写不同格式。

Moneyflow V9/V10 最近一次代表日期 read proof：

```text
20160104
20200102
20210930
20240110
20250711
```

## 新增或修改数据集时如何维护本文档

每次新增 dataset 或改变字段口径时，必须同步更新本文档的对应条目，至少包含：

1. `dataset_id`
2. 用途和 production/exploratory 状态
3. catalog path 或 active catalog 注册说明
4. datamart path 或 S3 URI
5. coverage window
6. 唯一键
7. 常用字段和字段含义
8. 信息集限制
9. QA json / smoke proof 路径
10. 不能做什么，例如不能替代 true tick dollar bar

没有 QA 和 worker read smoke 的数据集，不得写成 production-ready。
