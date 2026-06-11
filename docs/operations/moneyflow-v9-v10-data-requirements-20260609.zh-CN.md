# Moneyflow V9/V10 数据需求书

日期：2026-06-09

对象：Data 组 / Factor Forge 架构师 / 研究员

用途：

```text
支持 moneyflow / Miller disagreement / profit-payer ecology 方向的 V9/V10 后续研究。
当前 V9A 是最强基线；V10 条件过滤显示 hot-money / concentration 变量能提高排序诊断，
但没有改善 long-only 经济性。下一步需要更干净的数据层来区分：
1. 真实资金行为尺度，而不是自然分钟尺度；
2. intraday return/volume/flow distribution moments；
3. profit payer ecology 条件，而不是粗糙 size/liquidity gate。
```

边界：

```text
不要启动 clean data processing。
不要启动 search_worker。
不要写 official promotion。
不要启动 Factor Forge production loop。
Data 组只负责数据层构建、catalog、QA、read smoke 和性能证明。
研究结论由研究员在 Factor Forge workflow 中给出。
```

## 当前状态

### 已 production-ready

`intraday_flow_state_v2` 已完成 true factor-research-worker production contract：

```text
dataset: intraday_flow_state_v2
IS coverage: 2016-01-04 through 2025-07-11
row_count: 55,529,370
date_count: 2,313
duplicate_key_count: 0
threshold_source: prior_dates
lookback_days: 20 / 60
no_future_intraday_minutes: true
supported_cutoffs: 10:30 / 11:30 / 14:00 / 14:30 / 14:50 / 14:55
```

### 已有 bounded proof，但还不是 production state

`intraday_pseudo_dollar_bar_v1` 已有算法和单日全市场 proof：

```text
source: minute_bar
date: 2024-01-05
rows: 737,660
tickers: 5,245
file size: about 43 MB
compute: about 262.55s
warm read: about 0.29s
duplicate keys: 0
```

但它当前不是 full-window production datamart：

```text
2016-01-04 through 2025-07-11 IS backfill 未完成。
Factor Forge Step3/Step4 还没有正式消费该 state。
它是基于 1 分钟 bar 的 pseudo dollar bar，不是真 tick / transaction dollar bar。
```

### 尚未 production-ready

`distribution moments` 目前没有正式 datamart。研究侧之前用的是 proxy：

```text
amount_hhi
flow_hhi
large/small flow spread
concentration_z
relative_participation_z
```

这些不是完整的 intraday distribution moments。后续 V10/V11 需要真实的 return / volume / flow 分布矩。

## P0 需求：production pseudo dollar bar

请将现有 pseudo dollar bar 从 bounded proof 升级为正式 Data API dataset。

建议 dataset id：

```text
intraday_pseudo_dollar_bar_v1
```

### 覆盖范围

```text
market: A-share
IS start: 2016-01-04
IS cutoff: 2025-07-11
OOS holdout: 2025-07-12 onward
source dataset: minute_bar
```

如果 OOS 暂时不 backfill，也必须在 catalog 中明确：

```text
research_window = IS only
oos_holdout_excluded = true
```

### 构造逻辑

对每只股票 $i$、日期 $t$，按分钟成交额累积形成 pseudo dollar buckets：

$$
\mathcal B_{i,t,k}
=
\left\{
\tau:
\sum_{\tau \in \mathcal B_{i,t,k}} amount_{i,\tau}
\approx A^{bucket}_{i,t}
\right\}
$$

其中：

- $\mathcal B_{i,t,k}$：股票 $i$ 在日期 $t$ 的第 $k$ 个 pseudo dollar bucket。
- $A^{bucket}_{i,t}$：目标 bucket 成交额。
- $\tau$：1 分钟 bar。

目标 bucket 阈值必须只来自 prior dates，不能用当日全日信息：

$$
A^{bucket}_{i,t}
=
\frac{
\operatorname{median}_{s<t,\ s \in \mathcal W}
\left(amount^{day}_{i,s}\right)
}{K}
$$

建议：

```text
lookback_days: 20 and 60
bucket_count candidates: 60 / 120 / 240
threshold_source: prior_dates
no_future_intraday_minutes: true
```

如果使用固定 bucket_count，请在 catalog 中写明：

```text
bucket_policy = fixed_count
bucket_count = 240
threshold_lookback_days = 20 or 60
```

### 必需字段

```text
ts_code
trade_date
bucket_id
start_time
end_time
minute_count
open
high
low
close
vol
amount
signed_amount
abs_signed_amount
buy_proxy_amount
sell_proxy_amount
unknown_side_amount
return
realized_vol
price_impact
amount_hhi
source_minute_count
threshold_source
threshold_lookback_days
bucket_policy
bucket_count
research_window
no_future_intraday_minutes
```

如果方向仍用分钟 proxy，请明确：

$$
signed\_amount_{i,\tau}
=
\operatorname{sign}(close_{i,\tau}-open_{i,\tau})
\cdot amount_{i,\tau}
$$

并在 catalog 中写：

```text
side_source = minute_close_minus_open_proxy
true_trade_side_available = false
```

### 唯一键

```text
ts_code + trade_date + bucket_id
```

Data API projection 即使用户没有显式请求 `bucket_id`，也必须自动带出 validator 需要的 helper key，避免 duplicate key 误判。

## P1 需求：intraday distribution moments

请新增一个可直接被 Factor Forge 读取的 distribution moments datamart。

建议 dataset id：

```text
intraday_flow_distribution_moments_v1
```

### 覆盖范围

```text
source: minute_bar and/or intraday_flow_state_v2
IS start: 2016-01-04
IS cutoff: 2025-07-11
cutoffs: 10:30 / 11:30 / 14:00 / 14:30 / 14:50 / 14:55
```

### 信息集合约束

所有 cutoff 行只能使用：

$$
trade\_time \le cutoff\_time
$$

不得使用当日 cutoff 之后的任何 minute。

rolling threshold、winsor 参数、large/small proxy 分位数必须来自 prior dates：

$$
\theta_{i,t}
=
Q_{q}
\left(
\{amount_{i,s,\tau}: s<t,\ s \in \mathcal W\}
\right)
$$

推荐：

```text
lookback_days: 20 / 60
threshold_source: prior_dates
no_future_intraday_minutes: true
```

### 必需字段

基础 key：

```text
ts_code
trade_date
cutoff_time
research_window
threshold_source
lookback_days
no_future_intraday_minutes
```

return distribution：

```text
ret_mean
ret_std
ret_skew
ret_excess_kurtosis
ret_downside_semivol
ret_upside_semivol
ret_tail_95
ret_tail_05
ret_tail_asymmetry
realized_vol
realized_vol_of_vol
```

volume / amount distribution：

```text
amount_mean
amount_std
amount_skew
amount_excess_kurtosis
amount_hhi
amount_top5_share
amount_top10_share
amount_entropy
```

signed flow distribution：

```text
signed_amount_sum
signed_amount_mean
signed_amount_std
signed_amount_skew
signed_amount_excess_kurtosis
signed_flow_imbalance
signed_flow_hhi
signed_flow_top5_share
signed_flow_tail_asymmetry
positive_signed_amount_share
negative_signed_amount_share
```

large/small proxy：

```text
large_proxy_threshold
large_proxy_amount
small_proxy_amount
large_proxy_signed_amount
small_proxy_signed_amount
large_small_signed_spread
large_proxy_hhi
small_proxy_hhi
```

如果 pseudo dollar bar 已 production-ready，可补充 dollar bucket moments：

```text
pseudo_dollar_ret_skew
pseudo_dollar_ret_excess_kurtosis
pseudo_dollar_signed_flow_skew
pseudo_dollar_signed_flow_excess_kurtosis
pseudo_dollar_amount_hhi
pseudo_dollar_tail_asymmetry
```

### 唯一键

```text
ts_code + trade_date + cutoff_time
```

Data API projection 即使用户没有显式请求 `cutoff_time`，也必须自动带出 validator 需要的 helper key。

## P1 需求：profit-payer ecology controls

当前 V9/V10 的核心问题不是 rank IC，而是 long-only 经济性和成本。研究侧需要把可能的 profit payer ecology 从粗糙 gate 变成正式控制变量。

请确认或补齐以下字段的 Data API 可用性。

### 固定小市值研究口径

后续 moneyflow 小市值空间统一使用以下规则，不再临时改口径：

```text
market_cap_field_preference: circ_mv first, total_mv fallback
unit: Tushare daily_basic 万元
hard_floor: market_cap >= 50,000 万元，即 5 亿元
extreme_microcap_exclusion: exclude bottom 10% by market cap within each trade_date
fixed_small_universe: after the two exclusions, select the smallest 20% by market cap within each trade_date
```

数学上，对日期 $t$ 的股票集合 $\Omega_t$，令 $M_{i,t}$ 为 `circ_mv`，若缺失则使用 `total_mv`：

$$
\Omega^{eligible}_t
=
\left\{
i \in \Omega_t:
M_{i,t} \ge 50{,}000
\right\}
\cap
\left\{
i \in \Omega_t:
\operatorname{rankpct}_t(M_{i,t}) > 0.10
\right\}
$$

固定小市值空间定义为：

$$
\Omega^{small,fixed}_t
=
\left\{
i \in \Omega^{eligible}_t:
\operatorname{rankpct}_{\Omega^{eligible}_t}(M_{i,t}) \le 0.20
\right\}
$$

该口径的目的：

1. 保留小市值 profit-payer ecology。
2. 剔除极端微盘、壳股、流动性/退市风险过高样本。
3. 避免把无法承载真实资金容量的最小市值段误判成可交易 alpha。

### Size / liquidity

```text
ts_code
trade_date
total_mv
circ_mv
float_mv
turnover_rate
turnover_rate_f
amount
vol
free_float_share if available
```

要求：

```text
daily_basic parquet-first warm cache
same contract second run backtest_base_reuse_hit = true
no fallback to cold CSV when parquet is required
```

### Trading constraints / tradability

```text
is_st
is_suspended
is_limit_up
is_limit_down
list_days
delist_flag
special_treatment_flag
```

### Optional market-player proxies

如果 Data 组已有以下数据，请进入 catalog；如果没有，请明确 `not_available`：

```text
top_holder_concentration
state_owned_or_central_state_owned_flag
industry_owner_or_strategic_holder_flag
margin_balance
short_balance
northbound_holding
fund_holding_ratio
institutional_holding_ratio
retail_proxy_if_any
```

这些字段用于区分：

```text
smart money prepositioning
hot-money crowding
retail chase
strategic / state / industrial player disturbance
```

不是本轮 P0，但需要知道是否可得。

## P2 需求：true tick / transaction dollar bar

当前 pseudo dollar bar 不能恢复分钟内部交易顺序。若 tick / transaction 数据可以正式 catalog 化，请准备 true dollar bar。

建议 dataset id：

```text
intraday_true_dollar_bar_v1
```

必需字段：

```text
ts_code
trade_date
trade_time
sequence_id or trade_id
price
volume
amount
trade_side if available
buy_order_id if available
sell_order_id if available
```

如果有成交方向，必须说明：

```text
side_source = exchange / vendor / inferred
side_definition = buyer_initiated / seller_initiated / unknown
```

如果没有成交方向，研究侧可以用 tick rule / Lee-Ready-like proxy，但 Data 组需在 catalog 中明确：

```text
true_side_available = false
side_inference_required = true
```

## QA / proof 要求

每个 dataset 都需要提供：

```text
catalog json path
QA json path
datamart path
row_count
date_count
ticker_count
missing_dates
duplicate_key_count
source-ready coverage
warm read seconds
cold build/backfill runtime
cache path
file size summary
```

代表日期 read smoke：

```text
2016-01-04
2020-01-02
2021-09-30
2024-01-10
2025-07-11
```

每个日期至少输出：

```text
status = ready
rows
tickers
warm_read_s
duplicate_key_count = 0
research_window = IS
threshold_source = prior_dates
no_future_intraday_minutes = true
```

## 交付格式

请给研究员返回：

```text
dataset id
datamart path
catalog path
QA path
worker read smoke command id
worker read smoke output
local test result
pytest result
py_compile result
known limitations
```

如果某项不能完成，请明确 BLOCK：

```text
BLOCK_INTRADAY_PSEUDO_DOLLAR_BAR_FULL_IS_BACKFILL_MISSING
BLOCK_INTRADAY_DISTRIBUTION_MOMENTS_MISSING
BLOCK_TRUE_DOLLAR_BAR_TICK_DATA_NOT_CATALOGED
BLOCK_PROFIT_PAYER_ECOLOGY_CONTROLS_MISSING
```

## 研究员下一步依赖

研究员在 Data 组准备期间会继续：

1. 以 V9A 为基线，不把 V10 condition filter 当成新 incumbent。
2. 分析 hot-money branch 为什么提高 rank IC / long-short，但损害 long-only economics。
3. 设计下一版 cost-aware / holding-period-aware revision，重点降低 turnover 和成本拖累。
4. 等 `intraday_flow_distribution_moments_v1` 或 `intraday_pseudo_dollar_bar_v1` production-ready 后，再做正式 multibranch child。

当前不应继续把没有 production datamart 的 pseudo dollar bar 或 true moments 硬塞进 Factor Forge production loop。
