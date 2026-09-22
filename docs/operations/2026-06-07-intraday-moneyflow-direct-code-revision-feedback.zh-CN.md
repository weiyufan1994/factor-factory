# Factor Forge Intraday Moneyflow 研究反馈与框架修复建议

日期：2026-06-07

对象：架构师 / coder / reviewer

Report id：
`ORIG_INTRADAY_FLOW_SP3_DRIFT_MINUS_NOISE_20240102_20260525_FULL_LOOP_20260606172221`

## 一句话结论

本次分钟资金流方向不是“没有信号”，而是“当前 raw detector 有弱信号，但信号太噪、换手太高、成本不可承受”。更重要的是，Factor Forge 当前 Step6 -> child revision bridge 对 `direct_code/native minute` 因子支持不完整，导致 Council 已完成真实推导后无法安全 materialize 下一轮 child revision。

因此当前应判定为：

- 研究结论：`iterate / revision required`
- 因子状态：弱信号、不可推广、不可 promotion
- 框架状态：`BLOCK_DIRECT_CODE_CHILD_REVISION_BRIDGE`
- 不应伪造 Formula-IR child formula，也不应用 `rank(close)` 等无关公式绕过

## 当前实证结果

Step4 / self_quant 已修复并成功跑过全量窗口，核心指标如下：

```text
rank_ic_mean                = 0.0089229067
rank_ic_ir                  = 0.0812455354
pearson_ic_mean             = 0.0120536907
pearson_ic_ir               = 0.1679377066
long_side_annual_return     = 0.0073743037
long_side_sharpe            = 0.0284604293
long_side_max_drawdown      = -0.2768799458
long_side_recovery_days     = 588
long_side_turnover_mean     = 0.8826173655
trading_cogs_annual         = 0.6672587283
cost_adjusted_annual_return = -0.6587239747
```

覆盖：

```text
merged_rows       = 2,600,628
ticker_count      = 5,522
date_count        = 576
rank_ic_count     = 575
avg_cross_section = 4,522.83
```

解释：

1. `rank_ic_mean` 和 `pearson_ic_mean` 为正，说明当前资金流 state 不是纯噪声。
2. `long_side_annual_return` 只有约 0.74%，说明高分组正向收益很弱。
3. `turnover_mean_daily` 高达 88.26%，成本项直接吞噬收益。
4. 因子更像一个 raw detector：它能看到部分资金流/市场结构状态，但不是最终可交易 alpha。

## 用户提出的关键问题

### 1. 即使是分钟数据也没有信号吗？

不能这么说。

更准确的判断是：

- 当前实现下，分钟资金流有弱预测信息。
- 但当前 Step4 标准评估用的是日频 `factor_value_t_vs_return_t_plus_1`：
  - `signal_timestamp_policy = close_after_market`
  - `label_policy = next_trading_day_return`
  - `forward_return_source = pct_chg.shift(-1)`
  - `same_day_return_used_as_label = false`
- 它不是专门测试 “14:55 计算因子值，在 close 买入，持有 close -> next open / close -> next close” 的 intraday execution label。

所以现有结果不能证明“14:55 资金流没有信号”。它只能证明：

> 在当前 daily close-to-next-day 标准标签、当前 raw moneyflow/HHI 实现、当前成本模型下，信号太弱且换手过高。

如果用户的真实交易假设是：

```text
14:50 或 14:55 生成信号
14:57-15:00 或收盘价附近成交
目标收益 = close_t -> open_{t+1}
或 close_t -> close_{t+1}
```

则 Step4 需要新增 intraday signal timing evaluator，而不是复用普通日频 evaluator 后直接下结论。

建议新增标签/评估模式：

```text
label.close_to_next_open
label.close_to_next_close
label.close_to_next_vwap_0935_1000
label.close_to_next_vwap_0930_1030
label.open_to_close_next_day
```

并在 artifact 中明确：

```text
signal_cutoff_time = 14:50 or 14:55
execution_price_policy = close / closing_auction / next_open / next_vwap
information_set = minute_bar <= cutoff_time
same_day_close_used_as_execution_price = true/false
same_day_close_used_as label = false
```

### 2. 当前数学机制是什么？

当前经济假设是：

> 午后前资金流方向、集中度和异常参与度可能是 informed flow 或 forced flow 的观测值。慢资金、被动/约束型资金、等待信息发酵的参与者、噪声追随者可能在之后付钱。

当前数学机制可以写成：

```text
dP_i,t / P_i,t = mu_i,t dt + lambda_i,t I_i,t dt
                 + sigma_i,t(volume, turnover, crowding) dW_i,t

Y_i,t = I_i,t + eta_i,t
I_i,t = rho I_i,t-1 + xi_i,t
```

其中：

- `I_i,t`：隐藏的真实资金流状态，代表 informed / forced demand pressure
- `Y_i,t`：分钟数据观测到的资金流 proxy
- `eta_i,t`：观测噪声，包括小单噪声、撮合噪声、价格跳动造成的符号误判
- `rho`：资金流状态持续性
- `lambda_i,t`：资金流状态对未来条件漂移的影响
- `sigma_i,t`：随交易拥挤、换手、流动性变化的噪声/冲击项

当前 raw 实现基本是在估计 `Y_i,t`，而不是估计 `E[I_i,t | Y_i,t, controls]`。这也是 Council 认为需要 revision 的核心。

### 3. 当前代码大概怎么实现？

当前 Step4 对分钟资金流做了一个 report-specific fast path：

1. 从本地/缓存的 `minute_bar` parquet partitions 读取分钟数据。
2. 只取 `trade_time <= 14:50:00`。
3. 对每个分钟 bar 计算：

```text
bar_ret = close / open - 1
signed_amt = sign(bar_ret) * abs(amount)
gross_amt = sum(abs(amount))
amt_sq_sum = sum(abs(amount)^2)
abs_ret_sum = sum(abs(bar_ret))
ret_std = std(bar_ret)
minute_count = count(minutes)
```

4. 按 `ts_code, trade_date` 聚合成日频 flow features。
5. 与 `daily_basic` 合并，使用：

```text
total_mv
turnover_rate
turnover_rate_f
volume_ratio
```

6. 构造类似状态：

```text
net_flow_ratio      = signed_amt_sum / gross_amt
flow_hhi            = amt_sq_sum / gross_amt^2
hhi_impact          = net_flow_ratio * flow_hhi
volume_ratio_lag1
turnover_rate_f_lag1
crowding_penalty
```

7. 形成 drift-minus-noise 类型 score。
8. Step4 再用 `close_t -> close_{t+1}` 风格的日频 forward return 评估。

性能上已做的临时/研究路径修复：

- Polars lazy scan parquet partitions
- 按日期 batch 聚合
- 生成 persistent derived feature cache
- 后续读取 cache 后，flow daily aggregation 从约 324 秒降到约 9 秒内

## 数据质量还是方法问题？

目前不能把失败主要归因于数据质量。

更合理的拆分是：

### 数据质量可能有问题，但不是第一嫌疑

当前主买主卖 proxy 来自 1min OHLCV：

```text
if close > open: 视为主动买入
if close < open: 视为主动卖出
```

这只是 Lee-Ready / tick rule 的粗代理，不是真正的逐笔主动买卖。它会有明显误差：

- 一个 1min bar 内可能先卖后买，也可能先买后卖。
- `close > open` 不代表所有成交都是主买。
- 大单切分、小单噪声、集合竞价、尾盘冲击都会污染 proxy。
- amount 的单位、复权、异常分钟、停牌/临停/涨跌停附近都需要更严格 QA。

但现有结果已经显示正 IC，不像是完全无效数据。

### 当前方法更可能是主要问题

当前方法的问题更直接：

1. 用 raw signed amount imbalance 估计 `Y_t`，没有充分估计隐藏状态 `I_t`。
2. HHI 当前作为集中度 confidence，但没有区分：
   - informed concentration
   - crowded chasing
   - liquidity drought
   - small-size illiquidity
3. size / turnover / volume_ratio 的剥离还不够。
4. 没有专门测试 14:55 execution label。
5. 没有对 close-to-open 的 overnight 信息扩散过程建模。
6. 没有做 Bayesian / state-space smoothing，导致换手极高。
7. U 型 NAV 风险说明 raw score 可能同时混入：
   - 正向 informed flow
   - 负向 crowding/toxic flow
   - small-size liquidity premium
   - high-turnover reversal

所以当前更像是：

```text
数据 proxy 有噪声 + 数学状态估计太粗 + evaluation timing 不完全匹配交易假设
```

而不是简单的“数据差”或“思路无效”。

## Council 已形成的 revision 方向

Council 5 个角色结果均已通过 validator，结论不是 reject，而是建议继续 revision。

### 方向 1：persistent flow state

把 raw one-day impulse 改成 latent demand state：

```text
I_t = rho I_t-1 + innovation_t
score_t = E[I_t | Y_t, Y_t-1, ...] - noise_penalty
```

实现建议：

```text
rolling_mean(net_flow_ratio, 3/5/10)
rolling_mean(hhi_impact, 3/5/10)
rolling_std(raw_state, 5)
abs(raw_state - delay(raw_state, 1))
```

### 方向 2：dimensionless residualized flow

先把资金流状态无量纲化，再剥离规模/换手：

```text
P_t = net_amount / gross_amount
C_t = sqrt(sum(amount^2)) / sum(amount)
score = residualize(z(P_t) * z(C_t), [log_total_mv, turnover_rate_f, volume_ratio])
```

### 方向 3：Bayesian / state-space filter

把 HHI 看作 observation precision：

```text
Y_t = I_t + eta_t
precision_t = f(flow_hhi, gross_amount, minute_count)
posterior_state_t = precision_weight * Y_t + (1 - precision_weight) * prior_state_t
```

### 方向 4：cost-aware state

公式层面降低 churn：

```text
score_t = persistent_state_t
          - k * abs(persistent_state_t - persistent_state_t-1)
          - n * activity_noise_t
```

### 方向 5：falsification gate

每个 revision 必须测试：

```text
neutralized rank IC
size-slice rank IC
turnover-slice rank IC
2024/2025/2026 time split
close_t -> open_t+1
close_t -> close_t+1
cost delta versus raw branch
```

## 当前框架 BLOCK

### Blocker A：Ultimate loop 误走 terminal bridge

现象：

Council 已 completed，5/5 real-agent result valid，但没有 `main_agent_council_synthesis` 时：

```text
run_factorforge_ultimate_loop.py
```

会尝试：

```text
close_terminal_council_rejection.py
```

而不是等待/要求主 agent synthesis。

当 terminal bridge 发现 Council 不是 unanimous terminal 时，返回 non-terminal failure；ultimate loop 将其当成：

```text
BLOCK_FACTORFORGE_LOOP_TERMINAL_COUNCIL_REJECTION_FAILED
```

这不对。正确行为应该是：

```text
awaiting_main_agent_council_synthesis
```

或让当前主 agent继续写 synthesis。

### Blocker B：direct-code child revision bridge 不完整

当前 parent formula 是：

```text
Compute pre-14:50 signed amount imbalance from minute_bar.
```

这是 direct-code/native 因子的自然语言实现合同，不是 Formula-IR。

但当前：

- `approve_main_agent_council_synthesis.py`
- `materialize_step6_child_revision.py`
- `run_step3b.py`

仍强制：

```text
parse_formula(child_formula).parse_status == success
implementation_mode = operator
```

这会迫使主 agent 选择可解析但经济机制错误的公式，例如：

```text
rank(close)
rank(mean(close, 5))
```

这类绕过应被禁止。

## 需要 coder 修复的合同

### 1. Ultimate loop state fix

当存在：

```text
revision_council_summary exists
agentic_result_collection exists
main_agent_council_synthesis absent
terminal bridge returns NOT_UNANIMOUS
```

应返回：

```text
status = PAUSED
final_outcome = awaiting_main_agent_council_synthesis
stop_reason = completed_council_requires_main_agent_synthesis
```

不得标记为 BLOCK。

### 2. direct-code executable revision spec

新增 direct-code child revision contract：

```json
{
  "contract_version": "factorforge_executable_revision_spec_v1",
  "implementation_mode": "direct_code",
  "revision_type": "direct_code_mutation",
  "parent_formula_text": "...",
  "parent_formula_hash": "stable_hash(parent implementation contract)",
  "child_formula": "human-readable law statement",
  "child_formula_hash": "stable_hash(child direct-code law + synthesis + code mutation contract)",
  "child_formula_ir": null,
  "direct_code_revision_contract": {
    "target_function": "compute_factor_intraday_flow_daily_preagg_contract",
    "state_features": [...],
    "formula_law": "...",
    "required_fields": [...],
    "code_mutation_scope": [...]
  }
}
```

### 3. Step3B child direct-code application

`apply_executable_revision_spec()` 不应总是：

```python
parsed = parse_formula(child_formula)
implementation_contract["mode"] = "operator"
```

应分支：

```text
if implementation_mode == operator:
    require Formula-IR parse
elif implementation_mode in {direct_code, hybrid}:
    require direct_code_revision_contract
    require child code hash / law hash changed
    preserve implementation_mode
    block if no executable mutation is provided
```

### 4. Materializer must preserve direct-code paths

child materializer 应复制/继承：

- generated_code scaffold
- custom direct-code implementation contract
- daily/minute data contract
- report-local snapshots
- direct-code revision spec

并在 child factor_spec 中写：

```text
implementation_mode = direct_code
formula_ir = null
formula_hash = child direct-code law hash
executable_revision_spec_ref = ...
```

### 5. Step4 intraday timing evaluator

新增 evaluation label modes：

```text
close_to_next_open
close_to_next_close
close_to_next_vwap_0935_1000
close_to_next_vwap_0930_1030
```

并写入：

```text
signal_cutoff_time
execution_price_policy
label_price_policy
information_set
same_day_return_used_as_label=false
```

否则不能回答“14:55 算完、close 买入是否有效”。

## 建议的下一轮研究设计

在框架修复后，对同一 report 做 3-5 个 child branch：

1. `persistent_flow_state_5d`
   - 5 日 smooth raw flow / hhi impact
   - penalty raw state volatility

2. `dimensionless_residual_flow`
   - net/gross flow
   - HHI confidence
   - residualize total_mv / turnover_rate_f / volume_ratio

3. `bayesian_precision_flow`
   - HHI/gross amount/minute_count 作为 observation precision
   - posterior state 替代 raw observation

4. `cost_aware_flow_state`
   - persistent state
   - state change penalty
   - high-turnover/high-volume-ratio penalty

5. `intraday_label_timing_branch`
   - 不改公式，只改 evaluator
   - 测 close->next_open 与 close->next_close

每个 branch 必须汇报：

```text
rank_ic_mean
rank_ic_ir
long_side_annual_return
cost_adjusted_annual_return
turnover
max_drawdown
recovery_days
size-neutral IC
turnover-neutral IC
size-slice IC
label timing result
```

## 风险边界

不得做：

- 不得用无关 Formula-IR 公式绕过 direct-code bridge。
- 不得污染 clean data。
- 不得把 execution-layer 修复伪装成 factor formula revision。
- 不得用 bottom bucket 或 diagnostic spread 替代 long-side evidence。
- 不得 promotion。

可以做：

- 修复 direct-code child revision bridge。
- 新增 intraday timing evaluator。
- 对资金流状态做 formula/code-level estimator revision。
- 用 persistent derived feature cache 加速 minute aggregation。

## 当前研究员判断

这个方向仍值得继续，但要降级预期：

- 它不是已经找到强 alpha。
- 它是一个有弱信息含量的资金流 detector。
- 真正的研究价值在于：能不能从 noisy order-flow proxy 中提取 persistent informed/forced demand state。
- 如果 smoothing、residualization、Bayesian filtering、cost-aware penalty 后仍然无法让 cost-adjusted evidence 接近非负，则应结束这个 moneyflow proxy 分支，转向更高质量逐笔/Level2 主买主卖数据。

