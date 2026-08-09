# Alpha036 生产验收研究报告

Date: 2026-06-02

Report id:

```text
ALPHA036_CANONICAL_FORMULA_20160101_PROD_ACCEPTANCE
```

Source:

```text
https://arxiv.org/pdf/1601.00991
```

## 1. 结论

Alpha036 的原始 canonical formula 已完成 Factor Forge Ultimate 生产验收 run。Wrapper proof 为 `PASS`，Step3/3B/4/5/6 validators 全部通过。研究结论是：

```text
iterate，不可 promote
```

原因很清楚：

- 原始信号有一点横截面排序信息：`rank_ic_mean=0.0099998`，`rank_ic_ir=0.146865`。
- 但 long side 完全不合格：`long_side_annual_return=-9.60%`，`long_side_sharpe=-0.432`。
- 交易成本后更差：`cost_adjusted_annual_return=-54.64%`，`cost_adjusted_long_side_sharpe=-2.460`。
- 回撤和恢复期不可接受：`long_side_max_drawdown=-75.58%`，`long_side_recovery_days=3440`。

所以 Alpha036 目前不是一个可上线因子。它更像一个“有弱排序信息、但高分组 long side 无法变现”的混合量价状态估计器。下一步应该交给 agentic Council 做 expression-level revision，而不是通过换组合构造或依赖 short leg 来救。

## 2. 验收信息

| Item | Value |
|---|---|
| repo sha | `eb72d1f1adfb3742fc85d824b7bacb7890f44b8b` |
| artifact root | `/Users/humphrey/projects/factorforge` |
| run id | `run_001` |
| wrapper proof | `/Users/humphrey/projects/factorforge/objects/runtime_context/ultimate_run_report__ALPHA036_CANONICAL_FORMULA_20160101_PROD_ACCEPTANCE.json` |
| performance profile | `/Users/humphrey/projects/factorforge/objects/validation/performance_profile__ALPHA036_CANONICAL_FORMULA_20160101_PROD_ACCEPTANCE.json` |
| factor evaluation | `/Users/humphrey/projects/factorforge/objects/validation/factor_evaluation__ALPHA036_CANONICAL_FORMULA_20160101_PROD_ACCEPTANCE.json` |
| factor run master | `/Users/humphrey/projects/factorforge/objects/factor_run_master/factor_run_master__ALPHA036_CANONICAL_FORMULA_20160101_PROD_ACCEPTANCE.json` |
| research iteration | `/Users/humphrey/projects/factorforge/objects/research_iteration_master/research_iteration_master__ALPHA036_CANONICAL_FORMULA_20160101_PROD_ACCEPTANCE.json` |
| main agent memo | `/Users/humphrey/projects/factorforge/objects/research_iteration_master/main_agent_mechanism_memo__ALPHA036_CANONICAL_FORMULA_20160101_PROD_ACCEPTANCE.json` |

Wrapper commands:

```text
build_runtime_manifest: PASS
run_step3: PASS
validate_step3: PASS
run_step3b: PASS
validate_step3b: PASS
run_step4: PASS
validate_step4: PASS
run_step5: PASS
validate_step5: PASS
build_researcher_dossier: PASS
build_step6_researcher_packet: PASS
run_step6: PASS
validate_step6: PASS
```

Council status:

```text
status=awaiting_agent_results
effective_mode=agentic_dispatch_manifest
deterministic_scaffold_used=false
agent_task_count=5
```

## 3. Formula

Canonical formula:

```text
(((((2.21 * rank(correlation((close - open), delay(volume, 1), 15)))
  + (0.7 * rank((open - close))))
  + (0.73 * rank(Ts_Rank(delay((-1 * returns), 6), 5))))
  + rank(abs(correlation(vwap, adv20, 6))))
  + (0.6 * rank((((sum(close, 200) / 200) - open) * (close - open)))))
```

它由五个状态分量加权相加：

1. `corr(close-open, delay(volume,1), 15)`：当前日内实体方向与滞后一日成交参与的相关性。
2. `rank(open-close)`：弱收盘压力。
3. `ts_rank(delay(-returns,6),5)`：延迟后的负收益记忆。
4. `abs(corr(vwap, adv20,6))`：VWAP 与 20 日平均成交量的无符号依赖。
5. `(mean200(close)-open)*(close-open)`：长期位置与当前实体方向的交互。

## 4. Economic Hypothesis

主 agent memo 将 Alpha036 解释为：

```text
mixed transient-impact and behavioral microstructure
```

更具体地说，它假设 A 股日线中存在以下可重复状态：

- 弱收盘、延迟负收益、滞后成交参与、VWAP-成交量依赖和长期位置偏离，共同刻画一种短期冲击压力或行为反应状态。
- 这些状态如果是 temporary pressure，而不是 permanent information，就可能在未来出现衰减或反转。
- 高分组应当代表“可获得补偿的临时压力状态”，从而 long side 应该赚钱。

潜在付款方：

```text
forced de-riskers,
late trend extrapolators,
benchmark-liquidity demanders,
stop-loss sellers
```

他们为什么付钱：

- 他们需要即时成交或被风控、基准、赎回、止损约束推动。
- 他们对弱收盘或近期负收益做滞后反应。
- 如果这种反应只是短期压力，耐心资本可以获得补偿。

这套经济解释有一定合理性，但当前 metric 不支持“高分 long side 可以收钱”。IC 说明排序里有弱信息，long side 和成本后指标说明这个信息无法直接变现。

## 5. Math Mechanism

本次 main-agent memo 选择的数学模型是：

```text
volume-conditioned stochastic transient-impact model
```

可以写成一个简化状态过程：

```text
dX_i,t = mu_i,t dt + sigma_i,t(V_i,t, A_i,t) dB_i,t + kappa_i,t(V_i,t, A_i,t) dt
```

其中：

- `X_i,t` 是股票价格或 log price；
- `V_i,t` 是成交参与压力；
- `A_i,t` 是弱收盘、负收益记忆、VWAP-ADV 依赖、长期位置等 observable states；
- `sigma(V,A)` 表示成交参与条件下的波动项；
- `kappa(V,A)` 表示 transient impact drift；
- Alpha036 的公式是在用五个 observable coordinates 估计一个 composite transient-pressure state `S_i,t`。

数学上最可疑的部分是：

1. `abs(corr(vwap, adv20,6))` 去掉了方向信息。正相关和负相关可能代表完全不同的市场结构，却被压成同一个强度项。
2. 五个分量直接线性加权，缺少“哪个状态先发生、哪个状态是条件”的结构。它更像固定投影，不像由明确 process 推导出的充分统计量。
3. `open-close` 和 `close-open` 同时出现，方向上可能互相抵消或造成高分组解释不稳定。
4. 短窗口相关和 rank 容易产生高 turnover，交易成本会吞掉弱 IC。

因此数学层面的下一步不应盲目调权重，而应让 Council 做：

- 分量 ablation；
- `abs(corr(vwap, adv20))` 的 sign split；
- 状态 persistence / smoothing gate；
- 将 transient impact process 里的 `kappa(V,A)` 和 `sigma(V,A)` 分开估计；
- 明确高分组是“压力衰减可做多”，还是“拥挤冲击应回避”。

## 6. Metrics

Self-quant key metrics:

| Metric | Value |
|---|---:|
| `rank_ic_mean` | `0.0099998071` |
| `rank_ic_ir` | `0.1468647095` |
| `pearson_ic_mean` | `0.0045854645` |
| `pearson_ic_ir` | `0.0748451478` |
| `turnover_mean` | `0.5959680513` |
| `long_side_annual_return` | `-0.0960212590` |
| `long_side_sharpe` | `-0.4323198155` |
| `long_side_max_drawdown` | `-0.7557885340` |
| `long_side_recovery_days` | `3440` |
| `cost_adjusted_annual_return` | `-0.5463774689` |
| `cost_adjusted_long_side_sharpe` | `-2.4596033914` |
| `cost_adjusted_long_side_max_drawdown` | `-0.9948642558` |
| `cost_adjusted_long_side_recovery_days` | `3451` |
| `top_decile_mean_return` | `-0.0003810367` |
| `bottom_decile_mean_return` | `-0.0006778503` |
| `long_short_spread_mean` | `0.0002968135` |
| `long_short_spread_ir` | `0.0560953014` |

Interpretation:

- `rank_ic_mean` 为正，但强度很弱。
- long-short spread 有一点正，但 current mandate 不能用 short leg 或 long-short 来 justify promotion。
- top decile 本身为负，说明高分组不是可投资组合。
- turnover 接近 `0.596/day`，以当前成本模型会产生极大的 annual COGS。
- 最大回撤和恢复天数说明它长期没有抓住可持续市场结构。

## 7. Performance Profile

Step3B:

| Phase | Seconds |
|---|---:|
| total | `21.530324` |
| read_inputs | `0.552036` |
| compute_factor | `0.372388` |
| normalize_sort | `0.115259` |
| write_parquet | `0.039018` |
| write_csv | `0.028526` |
| rows_per_second_compute | `144207.1173` |

Formula engine:

| Field | Value |
|---|---:|
| engine | `pandas_formula_ir_optimized` |
| selected kernel | `pandas_optimized` |
| cache_hits | `8` |
| cache_misses | `42` |
| max_abs_diff | `0.0` |
| parity_checked | `true` |
| polars_used | `false` |

Step4 self-quant:

| Phase | Seconds |
|---|---:|
| total | `20.295581` |
| load_daily_snapshot | `5.912014` |
| load_factor_values | `5.088539` |
| merge_forward_returns | `2.365407` |
| ic_calculation | `2.711971` |
| quantile_assignment | `2.568564` |
| quantile_nav | `0.507059` |
| long_side_evidence | `0.533991` |
| rows_per_second_total | `389124.4109` |

Step4 backend timing:

| Backend | Status | Seconds |
|---|---|---:|
| self_quant_analyzer | `success` | `21.617439` |
| qlib_native | `partial` | `34.177349` |

## 8. Backend / Reuse / Side Effects

Step3A:

- `clean_daily_bar` 通过 Data API catalog 读取。
- 生成 report-local daily snapshot。
- `preferred_daily_format=parquet`。
- `daily_filter_policy` 显示已剔除 ST、停牌、涨跌停、异常涨跌幅等不可交易/异常日。

Step3B:

- `implementation_mode=operator`。
- `input_io_profile.daily_selected_format=parquet`。
- Step3B 只写 sample factor values，formal factor values owner 是 Step4。

Step4:

- 从 report-local parquet snapshot 读取。
- self-quant 成功。
- qlib native provider 已 report-local 构建并被尝试使用，但结果为 `partial`。

Side effects:

- `generated_code` digest unchanged。
- `data/clean` digest unchanged。
- `official_record` absent。
- `handoff_to_step3b` absent。
- 无 search worker。
- 无 clean data processing。

## 9. 下一步 Revision Proposal

建议把 Alpha036 交给 Council，不要手写 child formula。Council 应重点研究：

1. `abs(corr(vwap, adv20, 6))` 拆成 signed branches，判断正/负 VWAP-ADV 依赖是否代表不同对手盘。
2. 做五个分量 ablation，确认收益或亏损主要来自哪一项。
3. 对 composite score 加 persistence / smoothing，目标是降低 turnover，同时保留正 Rank IC。
4. 检查 `open-close` 与 `close-open` 的方向冲突，避免同一实体方向被双重计入。
5. 将 stochastic transient-impact model 拆成 drift repair 和 volatility conditioning repair 两条分支。

Kill criteria:

- 如果 revision 后 cost-adjusted long-side return 仍显著为负；
- 或 high-score top decile 仍不能赚钱；
- 或 drawdown / recovery 没有改善；
- 或收益主要来自 short leg；

则应 reject，而不是继续消耗 loop。

## 10. 研究员判断

Alpha036 不是完全没有信息。它的弱正 Rank IC 说明公式中某些状态确实在排序未来收益。但当前原始表达式把多个方向、多个经济机制和多个时间尺度硬加到一起，导致高分 long side 没有可投资性。

我的判断是：

```text
Alpha036 canonical formula = 有弱信息的未成型状态估计器，不是可上线因子。
```

值得做一轮 Council revision，但边际收益不应高估。若第一轮 expression-level revision 不能显著改善 long side 和成本后表现，应尽快沉淀经验并 reject。
