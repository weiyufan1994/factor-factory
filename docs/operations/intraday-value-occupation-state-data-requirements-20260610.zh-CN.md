# Intraday Value Occupation State 数据需求书

日期：2026-06-10

对象：Data 组 / Factor Forge 架构师 / 研究员

用途：

```text
建设一个可复用的价格轴 occupation / volume profile 日频 datamart，
支持后续所有“筹码分布、成本分布、下方支撑、上方套牢、低成本修复、
breakout resistance、support break risk、3-5D repair/defense”类因子研究。
```

边界：

```text
Data 组只负责 production datamart、Data API catalog、QA、read smoke、coverage proof。
不要替研究侧判断因子是否有效。
不要把 support_minus_overhang 或 below_cost_guarded_support 写成官方因子结论。
不要启动 Factor Forge production loop。
不要写 official promotion。
```

## 1. 背景和当前阻塞

研究侧已经用本地脚本验证了价格轴 occupation state 的可计算性：

```text
prototype script: scripts/research_vp_occupation_state.py
prototype dataset id: intraday_value_occupation_state_v1
source: minute_bar
information set: trade_time <= cutoff_time
```

但当前 full-window 研究被数据覆盖阻塞：

```text
IS daily dates: 2,313
cached minute IS partitions: 384
missing minute IS partitions: 1,929
coverage ratio: 16.6%
```

因此不能继续把 Mac / worker 上的临时 minute cache 当成正式 full-window 数据源。需要 Data API / datamart 层先生成稳定的日频预聚合表，然后 Factor Forge Step3/Step4 再消费该表做正式检验。

当前 2024-01 smoke 只说明方向值得 full-window 测试，不构成候选因子结论。

## 2. 为什么值得做成可复用 datamart

这不是只服务一个公式的中间表。

价格轴 occupation state 的数学对象是：

```text
mu_{i,t,c}(dp) = sum amount_{i,s,tau} * delta(P_{i,s,tau} - p)
where s is in the lookback window and trade_time <= cutoff_time
```

它把分钟成交额从时间轴投影到价格轴。下游可以从同一张表派生多类因子：

- 成本分布：`vwap_cost`、`below_cost_depth`；
- 成交密集区：`poc_price`、`value_area_low`、`value_area_high`；
- 支撑/套牢结构：`lower_support_ratio`、`upper_overhang_ratio`；
- repair / defense：低于成本后是否有下方支撑、成交吸收、不再破位；
- breakout / resistance：上方 overhang、上方 LVN vacuum、突破阻力；
- downside risk：下方空洞、尾部下跌、流动性陷阱；
- 大中小市值分层里的量价结构选股。

结论：如果只做某个单因子公式，研究侧可以自己算；但这个 state 是多个后续 intraday 量价因子的共享基础层，值得进入 Data API production datamart。

## 3. P0 数据产品

建议 dataset id：

```text
intraday_value_occupation_state_v1
```

唯一键：

```text
ts_code + trade_date + cutoff_time + lookback_days
```

source dataset：

```text
minute_bar
```

覆盖范围：

```text
market: A-share
IS start: 2016-01-04
IS cutoff: 2025-07-11
missing-date policy: source_ready_trade_dates_only
OOS: 2025-07-12 onward, if available, must be marked as holdout / not used for fitting
```

推荐分区：

```text
partition: trade_date=YYYYMMDD
format: parquet
catalog entry: Data API production dataset
```

## 4. 信息集约束

每一行只能使用当日 cutoff 之前的分钟数据：

```text
trade_time <= cutoff_time
```

滚动窗口只能使用：

```text
current trade_date up to cutoff_time
prior trade_dates full minute history up to the same cutoff policy
```

不能使用：

```text
trade_time > cutoff_time
future trade_date
future daily return
future daily high/low/close
当日 cutoff 之后的成交额、价格、波动、尾盘信息
```

每行必须显式记录：

```text
cutoff_time
lookback_days
no_future_intraday_minutes = true
source_dataset = minute_bar
schema_version
producer_version
```

推荐先支持：

```text
cutoff_time: 14:50:00
lookback_days: 20
```

如果算力允许，可扩展：

```text
cutoff_time: 10:30:00 / 11:30:00 / 14:00:00 / 14:30:00 / 14:50:00
lookback_days: 5 / 20 / 60
```

## 5. P0 必需字段

### Key / metadata

```text
ts_code
trade_date
cutoff_time
lookback_days
minute_count
current_day_minute_count
amount_total
schema_version
producer_version
source_dataset
no_future_intraday_minutes
```

### Price-axis core

```text
reference_price
vwap_cost
poc_price
value_area_low
value_area_high
distance_to_poc
distance_to_val
distance_to_vah
bin_width_bps
near_band_bps
profile_bin_count
```

口径：

```text
reference_price = last minute close at or before cutoff_time
vwap_cost = amount-weighted average price over the rolling occupation window
poc_price = price bin with maximum amount mass
value_area_low/high = price area covering target mass, default 70%
```

### Support / overhang

```text
lower_support_mass
upper_overhang_mass
below_price_amount_mass
above_price_amount_mass
lower_support_ratio
upper_overhang_ratio
below_mass_ratio
above_mass_ratio
```

口径：

```text
lower_support_mass = amount mass below reference_price and within near_band_bps
upper_overhang_mass = amount mass above reference_price and within near_band_bps
lower_support_ratio = lower_support_mass / amount_total
upper_overhang_ratio = upper_overhang_mass / amount_total
below_mass_ratio = below_price_amount_mass / amount_total
above_mass_ratio = above_price_amount_mass / amount_total
```

### Below-cost / repair diagnostics

```text
below_cost_depth
below_cost_depth_score
downside_lvn_gap
upside_lvn_vacuum
no_break_gate
defended_support_gate
```

口径：

```text
below_cost_depth = max(0, (vwap_cost - reference_price) / reference_price)
below_cost_depth_score = below_cost_depth * 100
no_break_gate = 1 if reference_price >= value_area_low else 0
```

## 6. P1 增强字段

P1 字段不是第一版交付的硬阻塞，但建议尽量同表产出，因为它们复用同一批分钟读数。

```text
absorption_confirmation
signed_flow_ratio
tail_signed_flow_ratio
one_sided_downside_tail_risk
illiquidity_trap_penalty
reward_risk_proxy
reward_risk_score
```

当前研究原型中 `signed_flow_ratio` 使用分钟 proxy：

```text
signed_amount = sign(close - open) * amount
```

如果 Data 组沿用这个 proxy，catalog 里必须明确：

```text
side_source = minute_close_minus_open_proxy
true_trade_side_available = false
```

如果未来有更真实的主动买卖方向，可以新增 version，不要静默替换 `v1` 口径。

## 7. 不建议由 Data 组交付的字段

以下字段可以作为 sample / reference output，但不建议写入 production datamart 的核心口径。它们属于研究侧因子组合律，应由 Factor Forge 下游计算：

```text
support_minus_overhang
support_absorption_minus_overhang
vp_support_defense_repair_v1
below_cost_guarded_support
support_with_below_cost_cap
vp_below_cost_repair_v1
```

如果为了方便 smoke 暂时产出，也必须在 catalog 标记：

```text
field_type = research_derived_score
not_official_factor = true
```

原因：

```text
Data 组负责稳定状态变量，不负责 alpha 方向判断。
below_cost_depth 在 2024-01 smoke 中单独表现为反向信号，不能把它固化成正向结论。
support-overhang 主体仍需要 full-window、成本、换手和 universe 过滤验证。
```

## 8. 建议算法口径

对每个 `ts_code, trade_date, cutoff_time, lookback_days`：

1. 读取该股票 rolling window 内的分钟数据，只保留 `trade_time <= cutoff_time`。
2. 使用分钟 `close` 作为价格轴坐标，`abs(amount)` 作为 occupation mass。
3. 用 `reference_price * bin_width_bps / 10000` 作为价格 bin 宽度。
4. 按价格 bin 聚合 amount mass，得到 profile。
5. 最大 mass bin 为 `poc_price`。
6. 按 bin mass 从大到小累计到 `value_area_mass`，得到 `value_area_low/high`。
7. 用 `near_band_bps` 计算 reference price 上下方近邻支撑和套牢 mass。
8. 输出 P0/P1 字段和 QA metadata。

建议默认参数：

```text
bin_width_bps = 20
value_area_mass = 0.70
near_band_bps = 300
tail_start = 14:30:00
min_minutes = 20
```

`min_minutes` 可由 Data 组根据历史分钟覆盖质量调整，但必须写入 metadata。

## 9. QA / 验收要求

每次 backfill 必须产出 QA json 或等价 proof：

```text
dataset_id
schema_version
producer_version
source_dataset
source_min_trade_date
source_max_trade_date
output_min_trade_date
output_max_trade_date
row_count
date_count
ticker_count
duplicate_key_count
missing_dates
cutoff_times
lookback_days
null_ratio_by_field
finite_ratio_by_numeric_field
non_negative_checks
coverage_by_date
runtime_seconds
input_minute_row_count
output_path
catalog_path
```

硬性校验：

```text
duplicate_key_count = 0 for ts_code + trade_date + cutoff_time + lookback_days
lower_support_ratio >= 0
upper_overhang_ratio >= 0
below_cost_depth >= 0
amount_total > 0
minute_count >= min_minutes
no_future_intraday_minutes = true
```

比例字段建议校验：

```text
0 <= lower_support_ratio <= 1
0 <= upper_overhang_ratio <= 1
0 <= below_mass_ratio <= 1
0 <= above_mass_ratio <= 1
```

Data API read smoke：

```text
describe intraday_value_occupation_state_v1
sample intraday_value_occupation_state_v1 --start 20160104 --end 20160108
sample intraday_value_occupation_state_v1 --start 20200102 --end 20200110
sample intraday_value_occupation_state_v1 --start 20240102 --end 20240110
sample intraday_value_occupation_state_v1 --start 20250707 --end 20250711
```

read smoke 必须证明：

```text
status = ready
projection can include helper keys automatically
duplicate-key validator uses cutoff_time and lookback_days
warm read path is partitioned parquet / datamart, not raw S3 minute scan
```

## 10. 下游研究如何消费

Factor Forge 研究侧会从 datamart 读取 P0/P1 状态变量，再自行计算候选因子，例如：

```text
support_minus_overhang =
  lower_support_ratio - upper_overhang_ratio

support_absorption_minus_overhang =
  lower_support_ratio * (1 + absorption_confirmation) - upper_overhang_ratio

below_cost_guarded_support =
  below_cost_depth_score
  * lower_support_ratio
  * (1 + absorption_confirmation)
  * no_break_gate
  - upper_overhang_ratio
```

正式评估会至少覆盖：

```text
universe:
  full universe reference
  middle universe: 20% < total_mv rank pct < 90%
  largest 10% diagnostic
  smallest 20% diagnostic

horizons:
  1D / 3D / 5D

diagnostics:
  rank IC / ICIR
  top decile excess
  top-bottom diagnostic
  long-only cost-adjusted return
  turnover
  drawdown
  size / industry residual checks if metadata is available
```

## 11. 交付物清单

请 Data 组交付：

```text
1. production parquet datamart path
2. Data API catalog entry
3. data dictionary entry
4. schema / field definition
5. QA json
6. worker read smoke output
7. performance proof
8. known limitations
```

建议路径形态：

```text
s3://.../factorforge/datamart/intraday_value_occupation_state/v1/trade_date=YYYYMMDD/*.parquet
```

建议 catalog id：

```text
intraday_value_occupation_state_v1
```

## 12. 最小可交付版本

如果先做 MVP，最小版本只需要：

```text
cutoff_time = 14:50:00
lookback_days = 20
coverage = 2016-01-04 through 2025-07-11
P0 fields only
QA + Data API read smoke
```

这已经足够让研究侧恢复 full-window 检验。

P1 字段、多个 cutoff、多个 lookback 可以在 v1 ready 后追加，或者发布 `v1_1` / `v2`，但不要阻塞 P0。
