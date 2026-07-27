# Factor Forge Factor Proof Certificate v2

## 1. 定位

`factorforge_factor_proof_certificate_v2` 是 Factor Forge 的可机检研究证书。
它借鉴 Lean 的思路，把结论拆成明确前提、可重算等式、已冻结阈值和确定性
verifier；但它不是金融市场的定理证明器。

对应关系是：

- theorem statement：`claim_class + data_contract + decision_rules`；
- hypotheses：同一数据快照、窗口、信息时点、成本和执行合同；
- proof terms：每个 required metric 的受信 verifier report；
- kernel：`validate_factorforge_factor_proof.py` 的确定性检查；
- theorem result：由 kernel 推导的 `ACCEPT|REJECT|INCONCLUSIVE|BLOCK`。

研究员、Council 或大模型不能自行宣布 theorem result。它们只能提交候选证书和
证据；小型确定性 kernel 负责复算等式、检查类型、身份、哈希和规则。

它能证明的是：

> 在指定 factor、样本、信息时点、成本模型、阈值注册和证据文件下，
> 声明的研究 verdict 是否由这些输入一致地推出。

它不能证明：

- 市场规律永远成立；
- 经济机制叙述是真的；
- 未来分布与历史分布相同；
- 未观测的 payer 身份；
- 一个高 IC 结果没有选择偏差。

这些问题由猜想协议、反例、sealed OOS、Council、独立 reviewer 和最终
production proof 共同约束。

## 2. Claim Class 决定证明义务

`claim_class` 在初始 `research_conjecture` 中冻结，最终证书必须完全一致。

通用类型包括：

- `information_rent`
- `liquidity_rent`
- `institutional_constraint_rent`
- `behavioral_rent`
- `time_option_rent`
- `mixed`
- `unknown`
- `risk_premium`

所有 claim class 都要求：

1. IC；
2. ICIR；
3. volatility cost；
4. transaction cost；
5. max drawdown；
6. long-end return。

只有 `risk_premium` 额外要求：

1. Fama-MacBeth cross-sectional risk-premium regression；
2. quintile 或 decile monotonicity。

`mixed` 与 `unknown` 可用于搜索、重定向、拒绝或不确定结论，但不能直接得到
`ACCEPT`。正式 promotion 前必须冻结一个可判定的主 claim class，防止用模糊标签
绕过 risk-premium 专属义务。

对于非 `risk_premium`，分组图仍可作为诊断，但不得标成
`promotion_gate_evidence`，也不得设置 `required_for_acceptance=true`。
事件、阈值、可选性和局部状态因子可能天然非单调；强制单调会错误拒绝它们。

## 3. 证书结构

证书位于：

```text
<factor_workspace>/objects/research_protocol/
  factor_proof_certificate__<report_id>.json
```

顶层至少包含：

```json
{
  "certificate_version": "factorforge_factor_proof_certificate_v2",
  "report_id": "REPORT_ID",
  "factor_id": "FACTOR_ID",
  "claim_class": "information_rent",
  "data_contract": {},
  "metrics": {},
  "evidence_bindings": {},
  "threshold_registration": {},
  "decision_rules": [],
  "declared_verdict": "ACCEPT"
}
```

`declared_verdict` 只能是 `ACCEPT`、`REJECT`、`INCONCLUSIVE` 或 `BLOCK`。
verifier 会重新计算规则结果；声明与推导不一致时直接 BLOCK。

## 4. Data Contract

`data_contract` 必须冻结：

- `is_window`
- `universe`
- `sample_frequency`
- `forward_return_horizon`
- `forward_return_horizon_days`
- `label_start_timestamp`
- `label_end_timestamp`
- `forward_return_formula=label_end_price/label_start_price-1`
- `path_is_disjoint=true`
- `label_contract_version=factorforge_daily_return_label_contract_v1`
- `signal_date_column`
- `label_start_date_column`
- `label_end_date_column`
- `label_start_price_column`
- `label_end_price_column`
- `forward_return_column`
- `return_tolerance`
- `trading_calendar_ref`
- `trading_calendar_id`
- `trading_calendar_sha256`
- `trading_calendar_file_sha256`
- `trading_calendar_registry_sha256`
- `trading_calendar_registry_git_commit`
- `trading_calendar_registry_git_blob`
- `trading_calendar_snapshot_id`
- `trading_calendar_source_snapshot_hash`
- `verification_scope=production`
- `return_path_mode`
- `holding_period_days`
- `rebalance_frequency`
- `signal_timestamp`
- `execution_timestamp`
- `cost_policy_id`
- `label_definition`
- `dataset_snapshot_hash`
- `window_hash`
- `evaluation_contract_hash`
- `label_contract_hash`
- `observed_start_date`
- `observed_end_date`
- `label_observed_start_date`
- `label_observed_end_date`
- `signal_period_count`
- `independent_path_period_count`
- `calendar_period_count`
- `signal_coverage_ratio=1`
- `return_reconciliation_max_abs_error`
- `minimum_periods>=60`
- `search_trial_ledger_ref`
- `oos_release_manifest_ref`
- `oos_status=sealed|released_once_for_final_evaluation`
- `same_sample_for_all_required_metrics=true`

IC、ICIR、成本、回撤和多头收益必须来自同一受控样本合同。不同 mask、
不同日期或不同 execution convention 的结果不能拼成一张证书。每个
`evidence_bindings.<metric>` 必须同时绑定该 metric 名称、相同
`dataset_snapshot_hash`、`window_hash` 和 `evaluation_contract_hash`；不能用另一个 verifier 的 PASS
文件替代当前 metric，也不能跨窗口拼接证据。evidence JSON 内的
`metric_payload` 还必须与证书 `metrics.<metric>` 逐字段完全一致，禁止在
保留 PASS 文件的同时替换证书数值。

日历 registry 不能只信任当前工作树文件。verifier 必须从已批准的独立 Git
anchor commit 读取 registry blob，要求工作树 registry 与该 blob 完全一致，并把
commit、blob、registry SHA 和显式 snapshot id 一起绑定到 label、release、evidence
和 certificate。正式 verifier 只接受 `verification_scope=production`；任务名或目录名
包含 `SMOKE` 不得改变信任范围。

搜索期间必须保持 `oos_status=sealed`。要推导 `ACCEPT`，还必须记录：

- `oos_status=released_once_for_final_evaluation`
- `evaluation_window_role=OOS_FINAL`
- `oos_window`
- `observed_start_date` 与 panel 实际最早日期完全一致
- `observed_end_date` 与 panel 实际最晚日期完全一致
- 实际交易期数不少于 `minimum_periods`；v2 日频正式证据最低为 60 期
- `search_frozen_before_oos_release=true`
- `oos_evidence_included=true`
- `oos_release_token_hash`
- hash-bound `search_trial_ledger -> threshold_registration ->
  oos_release_manifest`，且 `freeze_sequence < registration_sequence <
  release_sequence`

因此 IS-only 证书即使算术完全一致，也不能得到最终 ACCEPT。

### 4.1 Return-Path v2 边界

正式 v2 组合路径只支持：

```text
forward_return_horizon_days = 1
holding_period_days = 1
return_path_mode = daily_one_period_forward_return
rebalance_frequency = daily
path_is_disjoint = true
execution_timestamp = label_start_timestamp
```

`label_start_timestamp`、`label_end_timestamp` 和
`forward_return_formula` 必须显式声明。若执行发生在 `t+1 close`，标签不能从
`t close` 开始。正式面板还必须包含 label start/end date 与 price 列；kernel
根据 Data API/data-access 独立解析完整 authoritative trading calendar，并同时
绑定原始文件 SHA、规范化 open-date snapshot SHA、repo-tracked trusted snapshot
registry SHA 与 snapshot id，再验证
`signal -> label start -> label end` 恰好各前进一个交易日，并按
`label_end_price/label_start_price-1` 重算 forward return。不能从 panel
自身稀疏日期推导交易日序列，也不能把 workspace 内文件配置为 trusted
calendar。workspace 外的任意自报 calendar 也不自动可信，其规范化 snapshot 必须
已进入受代码审查的
`docs/contracts/factorforge-trusted-trading-calendar-snapshots-v1.json`。
正式逻辑引用固定 authority
`factorforge_data_access.trade_cal_csv`；实际路径由 operator/Data API 环境解析。
缺少这些列、日历路径落在 workspace、文件/快照/registry SHA 或身份不匹配、
snapshot 未登记、收益无法重算、
日期不是相邻交易日、signal 日期不逐交易日连续，或 `signal_period_count !=
independent_path_period_count` 时一律 BLOCK。

多日滚动 forward label 可以用于 IC、Fama-MacBeth 或机制诊断，但不能被当成
逐日 portfolio return 重复复利。v2 对 `t+5`、重叠 cohort 或
`holding_period_days>1` 直接
`BLOCK_FACTORFORGE_METRIC_VERIFIER_MULTI_PERIOD_PORTFOLIO_PATH_REQUIRED`。
只有独立的逐日持仓/NAV 引擎，或未来明确实现的非重叠 stride 合同，才能为
多日 horizon 生成正式 long-end、成本、波动和回撤证据。

`evaluation_contract_hash` 同时冻结 return/window、panel column mapping、
label contract、portfolio path、annualization、cost policy、Fama-MacBeth 和
bucket 合同。
OOS release 后修改成本、持有期或路径模式会导致 replay BLOCK。
threshold registration 是不可覆盖的：同路径同内容允许幂等读取，任何不同内容
必须命中
`BLOCK_FACTORFORGE_RESEARCH_RELEASE_THRESHOLD_REGISTRATION_IMMUTABLE`。

## 5. 通用 Metric Obligations

### 5.1 IC

`metrics.ic` 必须给出：

- `method=rank_ic|pearson_ic|both`
- `mean`
- `std`
- `period_count`
- `horizon`
- `evidence_role=promotion_gate_evidence`

协议不内置“所有因子统一 IC 门槛”。门槛必须按因子类型、频率、持有期和
业务目标预注册。

### 5.2 ICIR

verifier 复算：

```text
ICIR = mean(IC_t) / std(IC_t)
```

若 `annualized=true`，再乘 `sqrt(annualization_factor)`。证书值、IC 均值、
标准差和年化约定不一致时 BLOCK。

### 5.3 Volatility Cost

证书同时记录：

```text
realized_volatility_drag
  = arithmetic_return_annual - geometric_return_annual

half_variance_benchmark
  = 0.5 * realized_volatility_annual^2
```

第一项是实际复利损耗核对，第二项是连续时间近似 benchmark。二者不能混称，
也不能仅凭 `-1/2 sigma^2` 叙述认定机制成立。

### 5.4 Transaction Cost

verifier 复算：

```text
modeled_cost_annual
  = annual_turnover * cost_bps_per_turnover / 10000
  + other_annual_costs

net_return_annual
  = gross_return_annual - modeled_cost_annual
```

同时要求明确 turnover definition、cost scope 和 execution assumption。

### 5.5 Max Drawdown

`max_drawdown` 必须小于等于零，并绑定明确的 `nav_definition`。证书还记录
`recovery_days` 与 `recovery_area`，防止只看一个最低点而忽略资本占用时间。

### 5.6 Long-End Return

`long_end` 必须是可执行的多头端：

- `gross_return_annual`
- `net_return_annual`
- `net_geometric_return_annual`
- `terminal_wealth`
- `minimum_wealth`
- `sharpe_net`
- `coverage`
- `selection_rule`
- `weighting`
- `rebalance_frequency`
- `return_path_mode`
- `holding_period_days`
- `observation_frequency=daily`
- `short_leg_used_for_acceptance=false`
- `evidence_role=promotion_gate_evidence`

正式 admission 使用 `net_geometric_return_annual`。`net_return_annual` 是
gross-to-cost 的算术核对字段，不能在高波动路径上替代复利结果。若任一日
simple return 小于等于 `-1`，或 terminal/minimum wealth 非正，必须 BLOCK。
空头端和 long-short spread 只能做诊断，不能替代多头端 admission。

## 6. Risk-Premium 专属 Obligations

### 6.1 Fama-MacBeth

`risk_premium` 必须提供：

- `lambda_mean`
- `lambda_tstat`
- `period_count`
- `newey_west_lags`
- `cross_sectional_regression`
- `controls`
- `exposure_timing`
- `return_horizon`
- `return_horizon_days`
- `required_for_acceptance=true`
- `evidence_role=promotion_gate_evidence`

该检验回答的是横截面暴露是否获得价格，而不是一个交易信号是否可盈利。
当多日标签只作为诊断时，`newey_west_lags` 至少为
`forward_return_horizon_days-1`。
非 risk-premium claim 可附加 Fama-MacBeth 诊断，但必须使用
`required_for_acceptance=false` 与 `evidence_role=diagnostic_evidence`，不得参与
promotion verdict。

### 6.2 Quintile/Decile Monotonicity

`bucket_count` 只能为 5 或 10，并要求：

- `expected_direction`
- `bucket_returns`
- `monotonicity_score`
- `adjacent_pairs_total`
- `adjacent_pairs_violated`
- `required_for_acceptance=true`
- `evidence_role=promotion_gate_evidence`

具体允许多少 violation 由预注册 `decision_rules` 决定。
verifier 会从 `bucket_returns` 重新计算相邻组总数、违反次数和
`monotonicity_score`，不能由研究员自行填一个分数。

分桶使用 value-based quantile，不得用资产行顺序打破相同 signal 的 ties。若 ties
使某日无法形成完整 5/10 桶，正式 risk-premium 单调性证据直接 BLOCK；不得用
`rank(method="first")` 制造伪单调。

## 7. Evidence Binding

每个 required metric 都必须有同名 `evidence_bindings`：

```json
{
  "ic": {
    "path": "objects/evidence/ic.json",
    "metric": "ic",
    "sha256": "<64 hex>",
    "dataset_snapshot_hash": "<64 hex>",
    "window_hash": "<64 hex>",
    "threshold_registration_sha256": "<64 hex>",
    "threshold_rule_set_sha256": "<64 hex>",
    "verifier_id": "factorforge_step4_metric_verifier_v2",
    "verifier_status": "PASS"
  }
}
```

verifier 会检查：

1. 文件存在；
2. 文件位于当前 factor workspace；
3. SHA256 完全一致；
4. `verifier_status=PASS`；
5. `verifier_id` 属于 factor-proof kernel 的受信列表，而不是研究员自定义字符串；
6. evidence JSON 内嵌的 verifier、dataset snapshot、window 和 status 与
   reference 完全一致；
7. evidence JSON 声明
   `verifier_contract_version=factorforge_metric_verifier_report_v2`；
8. evidence reference 与 evidence JSON 同时绑定评估时使用的 threshold
   registration hash 和 rule-set hash；
9. evidence JSON 的 `metric_payload` 与证书中同名 metric 完全一致；
10. evidence JSON 必须带 workspace 内的 `source_panel_ref` 和完整
    `verifier_spec`；kernel 使用当前受信 verifier 源码重新读取原子面板、阈值文件并
    重算 metric，结果必须逐字段等于 evidence report。

引用一个路径字符串、截图、Council 意见或不存在的文件都不能升级为 passed。
只复制受信 `verifier_id`/源码 hash 并手写 `PASS` 也不能升级为 passed。指标
evidence 生成后再修改原子面板、spec 或阈值会在 replay 时 BLOCK。

## 8. Preregistration 与 Verdict

`threshold_registration` 必须包含：

```json
{
  "registered_before_evaluation": true,
  "registration_ref": "objects/research_protocol/thresholds__REPORT_ID.json",
  "registration_sha256": "<64 hex>",
  "rule_set_sha256": "<64 hex>"
}
```

每条 `decision_rules` 指向证书内一个数值路径，定义 operator、threshold 和
`on_fail=REJECT|INCONCLUSIVE|BLOCK`。注册文件必须为 `LOCKED`，内含完整
规则集，并与两个 SHA256 一致。注册文件还必须绑定 `report_id`、`factor_id`、
`claim_class`、冻结的 `window_hash` 和 `search_trial_ledger`。OOS panel 的
`dataset_snapshot_hash` 只能在阈值锁定后的 release 阶段加入 spec 和 release
manifest，不能为了预注册阈值先读取 OOS panel。

每个通用 required metric 都必须至少有一条指向其核心决策字段的规则；例如 IC
必须作用于 `metrics.ic.mean`，不能用永远成立的
`metrics.ic.period_count >= 0` 冒充 IC 门槛。`risk_premium` 还必须覆盖
Fama-MacBeth 的 `lambda_tstat` 和 monotonicity 的
`monotonicity_score`。非
`risk_premium` 不得把这两项写成 verdict 规则。verifier 自动推导：

Kernel 还执行最低方向性 guardrail：IC、ICIR、after-cost net return、long-end
net return 和 risk-premium lambda t-stat 的 acceptance threshold 不得小于
零；volatility drag 必须使用上限规则；max drawdown 阈值必须在 `[-0.8,0]`；
monotonicity threshold 必须在 `[0.5,1]`。不同频率/资产/目标可预注册更严格阈值，
但不能用负收益、反向 IC 或随机以下单调性作为 `ACCEPT` 门槛。

```text
任一 BLOCK -> BLOCK
否则任一 REJECT -> REJECT
否则任一 INCONCLUSIVE -> INCONCLUSIVE
否则 -> ACCEPT
```

结果出来后改阈值、删规则或改 claim class 都属于 post-hoc，必须 BLOCK。

## 9. 执行

正式执行必须使用三段式 release chain。先冻结搜索轨迹；`trials.json` 必须包含
所有已测试候选，而不是只保留 winner：

```bash
python3 scripts/write_factorforge_evaluation_release_chain.py freeze-search \
  --workspace-root <factor_workspace> \
  --report-id <report_id> \
  --factor-id <factor_id> \
  --trials <all_trials.json> \
  --candidate-space <candidate_space.json> \
  --selected-hypothesis <selected_hypothesis.json> \
  --output <factor_workspace>/objects/research_protocol/search_trial_ledger__<report_id>.json
```

然后在不读取 OOS panel 的情况下锁定规则：

```bash
python3 scripts/write_factorforge_evaluation_release_chain.py register-threshold \
  --workspace-root <factor_workspace> \
  --spec <metric_verifier_spec.json> \
  --decision-rules <decision_rules.json>
```

`register-threshold` 会拒绝已经带有 `dataset_snapshot_hash` 的 spec，并在
OOS 解封前检查规则 schema、允许的 metric path、方向/阈值 guardrail 及全部
required-family coverage；不完整规则不会生成 threshold registration。最后只
释放一次 OOS；该命令核对实际起止日期和最少 60 个日频观测，绑定 panel hash，
并回写同一个 spec：

```bash
python3 scripts/write_factorforge_evaluation_release_chain.py release-oos \
  --workspace-root <factor_workspace> \
  --panel <factor_workspace>/<frozen_oos_panel.parquet> \
  --spec <metric_verifier_spec.json>
```

release 完成后执行确定性 verifier：

```bash
python3 scripts/build_factorforge_metric_verifier_reports.py \
  --workspace-root <factor_workspace> \
  --panel <factor_workspace>/<frozen_oos_panel.parquet> \
  --spec <metric_verifier_spec.json>
```

`--identity-only` 仅允许开发 smoke 或诊断，不能作为正式阈值预注册流程。
本链条提供 workspace 内可重放、tamper-evident 的结构顺序；它不是外部可信时间戳，
也不能阻止拥有文件系统权限的恶意操作者提前查看 OOS。需要更强隔离时，必须由独立
数据服务/执行者持有 OOS 并在注册凭据确认后才释放。

`factorforge_metric_verifier_spec_v2` 必须指定 report/factor/claim/cost policy、
日期/证券/signal/forward-return 列、risk-premium controls、OOS
release/window contract、universe、investability mask、simple-return convention、
long-only quantile、年化、成本、执行假设和可重算
`factorforge_daily_return_label_contract_v1`。verifier 从原子面板重算：

v2 verifier 的原子面板频率是 `daily`；分钟状态可以生成日频 legal-time signal，
但不能把分钟行直接冒充独立横截面观测。

- daily rank IC 与未年化 ICIR；
- long-only target 与上一期收益漂移后 pretrade weights 的 one-way turnover、
  gross/net arithmetic annual return 与 transaction cost；
- arithmetic/geometric return、realized volatility drag 与 half-variance；
- 从初始 NAV=1.0 开始的 net NAV max drawdown、recovery days 和 recovery area；
- long-end geometric net return、terminal/minimum wealth、Sharpe 和 coverage；
- 仅 risk-premium：逐期 Fama-MacBeth + Newey-West t-stat，以及逐日
  quintile/decile return monotonicity。

risk-premium 的 controls 缺失行会在所有 required metrics 之前统一删除；任一日期
横截面不足或回归秩亏会整体 BLOCK，不能让 IC、Fama-MacBeth 和 buckets 使用不同
日期集合。证书中的 window/cost/universe 字段还必须与 replay spec 完全一致。

它输出 `metric_verifier_bundle__<report_id>.json` 和每个 required metric 的
独立 evidence report。证书必须逐字段使用该 bundle 的 `metrics` 和
`evidence_bindings`，不得人工重填。证书 validator 会重放 evidence 中冻结的
panel/spec；因此 bundle 不是仅凭哈希受信的静态声明。

最后验证证书：

```bash
python3 scripts/validate_factorforge_factor_proof.py \
  --workspace-root <factor_workspace> \
  --report-id <report_id>
```

最终 Ultimate/Council approval 还会运行：

```bash
python3 scripts/validate_factorforge_research_protocol.py \
  --workspace-root <factor_workspace> \
  --report-id <report_id> \
  --stage final
```

只有证书结构、等式、证据绑定、claim class、预注册规则、Council synthesis 和
terminal semantics 同时一致时，研究结论才可进入相应的下一状态。

开发验收：

```bash
python3 scripts/run_factorforge_metric_verifier_smoke.py
python3 scripts/run_factorforge_factor_proof_smoke.py
python3 scripts/run_factorforge_component_obligation_smoke.py
python3 scripts/run_factorforge_promotion_proof_gate_smoke.py
```
