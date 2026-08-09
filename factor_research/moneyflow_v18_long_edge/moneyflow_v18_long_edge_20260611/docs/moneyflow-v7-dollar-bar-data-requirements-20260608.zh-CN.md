# Moneyflow V7 / Dollar-Bar 数据需求书

日期：2026-06-08

对象：Data 组 / Factor Forge 架构师 / 研究员

用途：

```text
支持 intraday moneyflow / Miller disagreement / Fisher hysteresis 因子的后续研究。
当前 V7 使用 1 分钟 bar 构造资金流 proxy；下一步希望补充 dollar bar / tick 级数据，以降低自然分钟切分带来的行为识别误差。
```

边界：

```text
不要启动 clean data processing。
不要写 official promotion。
不要启动 search_worker。
数据组只需准备和注册数据，不需要判断因子是否 promote。
```

## 一句话需求

请为 Factor Forge 提供一个可被 Data API 正式读取、可 warm-cache、可追溯版本的数据层，用于从分钟或逐笔成交中构造：

```text
signed flow
order imbalance proxy
large/small order proxy
HHI / participation concentration
dollar-bar signed flow
intraday noise / volatility
tail-window pressure before close
```

最终目标不是把每个因子都重新扫全量分钟数据，而是形成可复用的 derived datamart。

## 当前 V7 数据路径

当前 V7 使用：

```text
minute_bar
-> trade_time <= 14:50
-> sign(close - open) * amount
-> daily aggregation
-> merge lagged daily_basic controls
-> Fisher-style information precision
-> hysteretic expected-cost boundary
```

当前不是 dollar bar，也不是真逐笔主动买卖。

当前 proxy：

$$
signed\_amount_{i,\tau}
=
\operatorname{sign}(close_{i,\tau}-open_{i,\tau})
\cdot amount_{i,\tau}
$$

其中：

- $i$：股票。
- $\tau$：日内 1 分钟 bar。
- $amount_{i,\tau}$：该分钟成交额。
- $\operatorname{sign}(close-open)$：用分钟收开盘方向近似主动买卖方向。

问题：

1. 1 分钟是自然时间切分，不是资金行为切分。
2. 第 59 秒和下一分钟第 1 秒会被硬切开。
3. 一个分钟内可能先卖后买，也可能先买后卖，OHLCV 无法恢复内部路径。
4. 大单拆单、小单噪声、尾盘集合竞价会被混在一起。
5. 因此当前 V7 是可用 detector，但不是最理想的 microstructure estimator。

## P0 数据需求：正式 minute_bar 可用性

### 覆盖范围

```text
market: A-share
start_date: 2016-01-01
end_date: latest available
minimum required for current retest: 2024-01-02 through latest
preferred full research window: 2016-01-01 through latest
in_sample_cutoff: 2025-07-11
oos_holdout: after 2025-07-11
```

### 必需字段

```text
ts_code
trade_date
trade_time
open
high
low
close
vol
amount
```

字段说明：

- `trade_time` 必须能区分至少分钟级时间，例如 `09:31:00`。
- `amount` 必须是成交额，单位需固定并写入 schema，例如 CNY 或 thousand CNY。
- `vol` 单位需固定，例如 shares / lots，并写入 schema。
- 价格字段应说明是否复权。分钟资金流构造通常应使用原始成交价格；日频收益评价可另行使用复权价格。

### 质量检查

请输出 QA summary：

```text
date_count
ticker_count
row_count
missing_date_count
missing_ticker_count
duplicate_key_count(ts_code, trade_date, trade_time)
zero_amount_count
negative_amount_count
invalid_ohlc_count
trade_time_coverage_by_date
limit_up_down_or_suspension_flags_available
```

最低要求：

1. `(ts_code, trade_date, trade_time)` 唯一。
2. `amount >= 0`。
3. 正常交易分钟的 `high >= max(open, close)`，`low <= min(open, close)`。
4. 交易日历和 Data API catalog 一致。
5. 停牌、临停、涨跌停、ST、新股上市初期最好有 flags；如果没有，也要明确缺失。

## P1 数据需求：Dollar Bar / Pseudo Dollar Bar

### 为什么需要 dollar bar

moneyflow 因子的核心不是“每一分钟发生了什么”，而是“每一单位资金冲击如何改变价格和后续收益预期”。

自然分钟 bar 会把资金行为切碎；dollar bar 按成交额切分，更接近真实交易行为单位。

目标是构造：

$$
\mathcal{B}_{i,t,k}
=
\left\{
\tau:
\sum_{\tau \in \mathcal{B}_{i,t,k}} amount_{i,\tau}
\approx A_{i,t}^{bucket}
\right\}
$$

其中：

- $\mathcal{B}_{i,t,k}$：股票 $i$ 在日期 $t$ 的第 $k$ 个 dollar bucket。
- $A_{i,t}^{bucket}$：该股票当日或历史自适应的目标 bucket 成交额。

### 如果只有 minute_bar

可以先做 pseudo dollar bar：

```text
minute_bar
-> 按 trade_time 排序
-> 累积 amount
-> 每达到 threshold 形成一个 pseudo dollar bucket
```

需要承认：

```text
pseudo dollar bar cannot recover within-minute order sequence
```

但它仍然比自然分钟切分更接近资金尺度。

### 如果能提供 tick / transaction 数据

优先提供真 dollar bar。所需字段：

```text
ts_code
trade_date
trade_time
trade_id or sequence_id
price
volume
amount
buy_sell_flag if available
trade_side if available
order_id / bid_order_id / ask_order_id if available
```

如果有逐笔成交方向，Data 组应明确：

```text
side_source = exchange / vendor / inferred
side_definition = buyer_initiated / seller_initiated / unknown
```

如果没有成交方向，则研究侧会用 tick rule / Lee-Ready-like proxy。

### Dollar-bar 输出字段

建议新增 Data API dataset：

```text
intraday_dollar_bar_v1
```

推荐 schema：

```text
ts_code
trade_date
bucket_id
start_time
end_time
open
high
low
close
vol
amount
trade_count
signed_amount
buy_amount
sell_amount
unknown_side_amount
large_order_amount
small_order_amount
amount_hhi
price_impact
bar_return
source_dataset
source_version
bucket_policy
bucket_target_amount
producer_version
created_at
```

如果 `buy_amount/sell_amount` 无法可靠提供，可以先置空，但必须写明：

```text
side_available=false
side_proxy_required=true
```

## P1 数据需求：Large / Small Order Proxy

用户关心：

1. 大单可能更接近聪明钱或机构约束资金。
2. 小单可能更接近散户追随或博傻。
3. 绝对金额和相对金额都要看。
4. 市场活跃度变化很大，不能用固定金额阈值一刀切。

因此需要同时提供三类分组。

### 1. 绝对金额阈值

例如：

```text
small_order_abs
medium_order_abs
large_order_abs
extra_large_order_abs
```

阈值由 Data 组按 Tushare/vendor 定义记录，不要求研究员先定死。

### 2. 股票自身滚动分位阈值

建议按股票历史成交金额分布定义：

$$
Q^{amount}_{i,t}(p)
=
\operatorname{Quantile}_{s<t}
\left(amount_{i,s,\tau}, p\right)
$$

然后定义：

```text
large_relative = amount >= Q_i,t(0.90)
extra_large_relative = amount >= Q_i,t(0.99)
```

### 3. 当日市场状态调整阈值

为了处理 924 之后市场活跃度变化、2024-01 流动性冲击等 regime，应提供滚动基准：

$$
\tilde{A}_{i,t}
=
\operatorname{EWMA}_{s<t}
\left(
median_{\tau}(amount_{i,s,\tau})
\right)
$$

并输出：

```text
amount_to_own_history
amount_to_market_history
amount_zscore_ewma
```

如果 Data 组能提供 Ledoit-Wolf shrinkage 风格的稳定化估计更好，但不是 P0：

$$
\begin{aligned}
\hat{\mu}^{shrunk}_{i,t}
&=
\omega \mu^{market}_{t}
+ (1-\omega)\mu^{own}_{i,t}
\end{aligned}
$$

## P1 数据需求：Derived Moneyflow State Datamart

为避免 Step4 每次全量扫描 minute/tick，建议 Data API 正式维护：

```text
minute_derived_flow_state_v1
```

或扩展为：

```text
intraday_flow_state_v2
```

推荐按日期分区：

```text
s3://.../datamart/intraday_flow_state/v2/trade_date=YYYYMMDD/*.parquet
```

推荐字段：

```text
ts_code
trade_date
cutoff_time
net_flow_ratio
signed_amount_sum
gross_amount_sum
buy_amount_sum
sell_amount_sum
unknown_side_amount_sum
large_net_flow_ratio_abs
large_net_flow_ratio_rel
small_net_flow_ratio_abs
small_net_flow_ratio_rel
amount_hhi
participant_concentration_proxy
flow_hhi
intraday_ret_std
intraday_abs_ret_sum
intraday_noise
tail_net_flow_ratio_1400_1450
tail_net_flow_ratio_1430_1450
tail_net_flow_ratio_1450_1455
impact_proxy
elasticity_proxy
bucket_count
minute_count
source_dataset
source_version
producer_version
data_quality_flags
```

重要：需要同时支持多个 cutoff：

```text
10:30
11:30
14:00
14:30
14:50
14:55
```

原因：研究员要比较不同信息集下的合法性和收益：

```text
14:50 signal -> close execution
14:55 signal -> close execution
close-after-market signal -> next-day execution
```

## P2 数据需求：Market Player / HHI 增强

当前 HHI 只能表示成交额集中度，不能直接表示“谁在交易”。若有更细数据，希望提供：

```text
broker / seat / branch id if legally available
order_id-level concentration
account_type if legally available
institution / retail classification if legally available
northbound flow
margin financing / securities lending
mutual fund pressure proxy
ETF creation redemption pressure
```

如果不能提供真实 participant identity，也可以提供 proxy：

```text
order_size_distribution
trade_count_distribution
large_order_arrival_clustering
same-direction run length
signed flow autocorrelation
tail-window concentration
```

核心是区分：

```text
informed concentration
crowded chasing
retail small-order inflow
forced institutional demand
liquidity drought
```

## Data API / Catalog 要求

所有正式数据集都需要注册进 Data API catalog：

```text
minute_bar
moneyflow
daily_basic
intraday_dollar_bar_v1
intraday_flow_state_v2
```

每个 dataset 需要提供：

```text
dataset_name
version
source_uri
local_cache_policy
partition_keys
schema
coverage_start
coverage_end
trade_calendar
data_quality_summary_path
producer
updated_at
```

性能要求：

```text
cold read can be slower but bounded and resumable
warm cache must be fast
local persistent cache must be supported
negative cache for missing non-trading dates
parquet-first for derived states
```

建议环境变量：

```bash
FACTORFORGE_DATA_CACHE=/persistent/path/factorforge_data_api_cache
FACTORFORGE_S3_REGION=ap-southeast-1
```

## 验收标准

Data 组完成后，请给研究员以下 proof：

```text
catalog path local
catalog path s3
dataset names
schema json
coverage_start / coverage_end
row_count by dataset
date_count by dataset
ticker_count by dataset
sample read command
sample read output row count
cold read time
warm read time
cache path
QA summary path
known limitations
```

最低 smoke：

```text
read minute_bar 2024-01-02 to 2024-01-05
read daily_basic 2024-01-02 to 2024-01-05
read intraday_flow_state_v2 2024-01-02 to 2024-01-05 cutoff=14:50
optional: read intraday_dollar_bar_v1 2024-01-02 to 2024-01-05
```

期望结果：

```text
status=ready
warm_cache_hit=true on second read
source_format=parquet
same trade calendar as Step4 evaluation
no unexpected CSV fallback
```

## 给 Data 组的优先级

P0：

```text
minute_bar 2016-latest formal catalog coverage
daily_basic parquet warm cache
existing minute_derived_flow_state_v1 coverage and QA
```

P1：

```text
intraday_flow_state_v2 with multiple cutoff_time
pseudo dollar bar from minute_bar
large/small order proxy by absolute and relative thresholds
```

P2：

```text
true tick-derived dollar bar
order-level / participant-level concentration if legally available
market-player proxy enhancements
```

## 研究员下一步如何使用

拿到 P0/P1 后，研究员会先验证 V7：

```text
V7 all universe
V7 small-size bucket
V7 high-liquidity bucket
V7 OOS after 2025-07-11
V7 minute-bar vs pseudo-dollar-bar
```

如果 dollar bar 明显降低噪声并改善 cost-adjusted return，再设计下一版 V9；否则 V7 仍只是一个 moneyflow state detector，不应 promotion。
