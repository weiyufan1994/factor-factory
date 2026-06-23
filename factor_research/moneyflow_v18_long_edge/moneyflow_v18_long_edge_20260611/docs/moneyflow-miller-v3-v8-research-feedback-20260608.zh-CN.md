# Moneyflow / Miller V3-V8 研究反馈与版本说明

日期：2026-06-08

对象：用户 / 架构师 / coder / reviewer / 后续 Factor Forge researcher

研究主题：

```text
intraday moneyflow / Miller disagreement / participant concentration / expected-cost boundary
```

默认研究窗口：

```text
in-sample <= 2025-07-11
2025-07-11 之后仅作为 out-of-sample holdout
```

## 一句话结论

这轮研究不是简单地证明“资金流因子有效”或“资金流因子无效”。更准确的结论是：

1. 原始 moneyflow detector 有信息，但换手太高、成本不可承受。
2. V3/V5 证明 posterior / residualized state 可以保留较强横截面排序信息。
3. V6 证明 Fisher-style innovation 能进一步提取信息，但会把因子推向高频抖动，交易成本爆炸。
4. V7 是当前最好的可继续研究版本：信号、换手、回撤之间最平衡，但成本调整后仍未过关。
5. V8 的数学动机更干净，但实际过度惩罚 stale/noisy state，导致 IC 和 long-side return 明显坍塌，应判定为 falsified branch，不应继续作为 exploit parent。

当前应保留：

```text
incumbent_for_next_exploit = V7
V8_status = falsified / do_not_continue_as_exploit
promotion_status = not_promotable
```

## 本轮遇到的问题

### 1. Step4 CSV policy 缺口

V8 跑完后发现 Step4 diagnostics 中出现：

```text
csv_output_policy = legacy_missing
factor_csv_written_by_step4 = true
```

并且写出了约 117MB 的 full factor CSV。问题不在 V8 因子本身，而在 Step4 policy 继承逻辑：

1. Step4 原先只读取 Step3B `run_metadata.performance_profile.csv_output_profile.csv_output_policy`。
2. direct-code child / recompute 路径可能没有这个字段。
3. 即使 SSM 环境变量设置了 `FACTORFORGE_CSV_OUTPUT_POLICY=sample_csv`，Step4 仍会 fallback 到 `legacy_missing`。
4. fallback 后就允许写 full CSV。

已做窄修：

```text
skills/factor-forge-step4/scripts/run_step4.py
```

修复逻辑：

1. 优先使用 Step3B metadata 中的 policy。
2. 如果 Step3B 没有 policy，则读取环境变量 `FACTORFORGE_CSV_OUTPUT_POLICY`。
3. 两者都没有时才保留 `legacy_missing`。

验证：

```text
SSM command: bc3ef1d8-e744-49c1-ad05-a1c6d5f9f509
token: FACTOR_RESEARCH_WORKER_STEP4_CSV_POLICY_ENV_FIX_ACCEPT
```

注意：V8 已经写出的 117MB CSV 没有删除，因为那是本轮 run evidence 的一部分。修复只影响后续 run。

### 2. `--max-loops 1` 只消费 approval，未 materialize child

V7 到 V8 时，第一次用 `--max-loops 1` 跑 ultimate loop，结果只完成了 Council synthesis approval，没有进入 child materialization / child Step3B/4/5/6。

这不是 validator 失败，而是 loop budget 语义问题：

```text
max_loops=1
  -> consumes completed council synthesis
  -> activates approved handoff
  -> reaches max loop boundary before child execution
```

之后用 `--max-loops 2` 才正常生成并执行 V8 child。

证据：

```text
approval-only command: 360365c4-afd3-4f46-9fb9-9aed69885d0c
V8 child command:      ebd29364-e0b9-4fe8-adf8-3f07201e50ed
```

建议：后续从 completed Council synthesis 继续 materialize child 时，至少给 `--max-loops 2`，或者让 wrapper 把 approval bridge 和 child execution 分成不同预算单位。

### 3. SSM 引号与远端只读检查成本较高

这轮多次需要从 true research worker 读取 artifact。直接在 SSM JSON 里塞多层 Python/quote 容易出错，曾出现只因引号剥离导致的 verifier false failure。

建议后续统一使用：

```text
base64(script) -> echo | base64 -d | bash
```

或沉淀一个只读 artifact probe helper，避免每次临时拼 SSM 命令。

### 4. V8 理论过强但实证变差

V8 的理论目标是把 raw moneyflow state 变成净边际收益：

$$
\begin{aligned}
R^{net}_{i,t+1}
&=
\beta m_{i,t}q_{i,t}
- C_{i,t}
- S^{stale}_{i,t}
+ \varepsilon_{i,t+1}
\end{aligned}
$$

其中：

- $m_{i,t}$：资金流方向状态。
- $q_{i,t}$：状态质量。
- $C_{i,t}$：预期交易成本。
- $S^{stale}_{i,t}$：状态陈旧惩罚。

这个推导方向合理，但实现后把很多有用的持久状态也当作 stale/noisy state 扣掉了。结果：

```text
turnover_mean: 0.255 -> 0.223
rank_ic_mean: 0.0305 -> 0.0122
long_side_annual_return: 0.1179 -> 0.0477
long_side_max_drawdown: -0.2329 -> -0.3227
```

结论：V8 不是框架 bug，而是一个被实证证伪的 revision branch。

### 5. 当前 artifact inspection 仍偏碎片化

一些关键 evidence 分散在：

```text
objects/validation/factor_evaluation__<report_id>.json
objects/validation/factor_run_diagnostics__<report_id>.json
runs/<report_id>/run_metadata__<report_id>.json
objects/runtime_context/ultimate_run_report__<report_id>.json
```

建议后续补一个只读 summary tool，一次性输出：

```text
report_id
parent_report_id
selected_law_id
formula/code hash
Step3B backend
Step4 backend
derived state hit
daily_basic parquet/cache proof
csv policy proof
core metrics
side effects
```

这样研究员不需要每次手动追多个 JSON。

## V3 到 V8 的版本解释

### 指标总览

| Version | Report suffix | rank IC | IC IR | Turnover | Long annual | Long Sharpe | Long MDD | Recovery | Cost adj annual | Cost adj Sharpe |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| V3 | posterior hold gate | 0.0404 | 0.4948 | 0.3862 | 0.1186 | 0.5291 | -0.2070 | 272 | -0.1729 | -0.7712 |
| V4 | sparse posterior cost boundary | -0.0062 | -0.0972 | 0.3601 | 0.1285 | 0.5687 | -0.2131 | 272 | -0.1433 | -0.6341 |
| V5 | residualized posterior hold gate | 0.0407 | 0.4882 | 0.3314 | 0.0999 | 0.4435 | -0.2379 | 272 | -0.1502 | -0.6664 |
| V6 | Fisher innovation ratio | 0.0452 | 0.4589 | 0.7520 | 0.1394 | 0.4942 | -0.3261 | 272 | -0.4281 | -1.5183 |
| V7 | Fisher hysteretic expected-cost boundary | 0.0305 | 0.3202 | 0.2552 | 0.1179 | 0.5213 | -0.2329 | 272 | -0.0747 | -0.3304 |
| V8 | Fisher net-edge state decay | 0.0122 | 0.1459 | 0.2231 | 0.0477 | 0.1738 | -0.3227 | 552 | -0.1207 | -0.4403 |

### V3：Posterior Hold Gate

直觉：

V3 第一次把 moneyflow 从“当天资金流冲击”改成“可持续的 latent state”。它的核心不是每天都重新下注，而是只有当 posterior state 足够可信时才保留仓位。

机制可以写成：

$$
\begin{aligned}
m_{i,t}
&=
\rho m_{i,t-1}
+ (1-\rho)z_{i,t}
\end{aligned}
$$

$$
\kappa_{i,t}
=
\frac{|m_{i,t}|}{\sigma_{\eta,i,t}+C_{i,t}+\epsilon}
$$

$$
\Phi_{i,t}
=
m_{i,t}\mathbf{1}\{\kappa_{i,t}>B\}
$$

其中：

- $z_{i,t}$：当日标准化资金流冲击。
- $m_{i,t}$：平滑后的 latent moneyflow state。
- $\rho$：状态持续性。
- $\sigma_{\eta,i,t}$：观测噪声。
- $C_{i,t}$：交易成本或拥挤成本。
- $B$：hold gate 阈值。
- $\Phi_{i,t}$：最终因子值。

结果：

V3 明显改善了原始 detector。`rank_ic_mean=0.0404`，`turnover=0.3862`，说明 posterior state 是有效方向。但成本调整后仍为负，说明仍交易太频繁，edge 还没有超过交易成本。

### V4：Sparse Posterior Cost Boundary

直觉：

V4 的目标是更激进地减少交易：只有 posterior state 扣掉成本边界后仍足够大，才输出信号。它像一个更硬的 no-trade band。

机制可以写成：

$$
G_{i,t}
=
|m_{i,t}| - C_{i,t} - B^{sparse}_{i,t}
$$

$$
\Phi_{i,t}
=
\operatorname{sign}(m_{i,t})\max(G_{i,t},0)
$$

其中：

- $G_{i,t}$：扣除成本和稀疏边界后的 gross edge。
- $B^{sparse}_{i,t}$：更高的稀疏触发阈值。

结果：

V4 的 long-side return 和 Sharpe 看起来更好，但 `rank_ic_mean=-0.0062`，说明横截面排序关系被破坏。也就是说，它可能只保留了一些偶然高收益片段，却没有保住稳定的排序信息。

结论：V4 不能作为主线继续。

### V5：Residualized Posterior Hold Gate

直觉：

用户担心 moneyflow 信号其实只是 small-size / illiquidity 暴露。V5 的目标是把 known controls 剥离出去，保留“不是市值/流动性解释的资金流状态”。

机制可以写成：

$$
\begin{aligned}
m_{i,t}
&=
\gamma^\top X_{i,t}
+ u_{i,t}
\end{aligned}
$$

$$
\tilde{m}_{i,t}
=
u_{i,t}
$$

$$
\Phi_{i,t}
=
\tilde{m}_{i,t}\mathbf{1}\{|\tilde{m}_{i,t}|>B\}
$$

其中：

- $X_{i,t}$：市值、换手、成交活跃度、流动性等控制变量。
- $\gamma^\top X_{i,t}$：可被常见风格/流动性解释的部分。
- $\tilde{m}_{i,t}$：残差化后的 moneyflow state。

结果：

V5 把 IC 基本保住了：`rank_ic_mean=0.0407`，并把 turnover 降到 `0.3314`。但 long-side annual 从 V3 的 `0.1186` 降到 `0.0999`，成本调整后仍为负。

解释：

残差化是正确的诊断方向，但也剥离掉了部分真正有收益的 liquidity/size-related component。它证明“资金流信号不全是 size”，但还没有成为可交易版本。

### V6：Fisher Innovation Ratio

直觉：

V6 试图回答：当资金流出现新信息时，这个 innovation 的信息含量有多高？如果观测噪声低、状态变化大，就放大信号。

机制可以写成：

$$
\Delta m_{i,t}
=
m_{i,t}-m_{i,t-1}
$$

$$
\mathcal{I}_{i,t}
=
\frac{1}{\sigma_{\eta,i,t}^{2}+\epsilon}
$$

$$
\Phi_{i,t}
=
\frac{\Delta m_{i,t}\sqrt{\mathcal{I}_{i,t}}}{C_{i,t}+\epsilon}
$$

其中：

- $\Delta m_{i,t}$：资金流状态的新变化。
- $\mathcal{I}_{i,t}$：Fisher-style 信息精度。
- $C_{i,t}$：成本或交易摩擦。

结果：

V6 的 `rank_ic_mean=0.0452` 是 V3-V8 中最高，但 `turnover=0.7520`，成本调整年化 `-0.4281`，最大回撤也显著恶化。

结论：

V6 证明 innovation 里有信息，但它更像高频信息检测器，不是可交易长仓因子。下一步不能继续单纯放大 innovation，必须加 hysteresis / expected-cost boundary。

### V7：Fisher Hysteretic Expected-Cost Boundary

直觉：

V7 是从 V6 回到可交易性的关键版本。它保留 Fisher 信息，但增加滞后阈值和预期成本边界，避免每天因为微小 innovation 翻仓。

机制可以写成：

$$
\begin{aligned}
H_{i,t}
&=
\lambda H_{i,t-1}
+ (1-\lambda)\Delta m_{i,t}\sqrt{\mathcal{I}_{i,t}}
\end{aligned}
$$

$$
B^{enter}_{i,t}
>
B^{exit}_{i,t}
$$

$$
\Phi_{i,t}
=
H_{i,t}
\mathbf{1}
\{
|H_{i,t}|>B^{enter}_{i,t}
\ \text{or}\
(position_{i,t-1}\neq 0 \land |H_{i,t}|>B^{exit}_{i,t})
\}
$$

其中：

- $H_{i,t}$：带记忆的 Fisher state。
- $B^{enter}$：开仓阈值。
- $B^{exit}$：退出阈值。
- $B^{enter}>B^{exit}$：形成 hysteresis，降低反复换手。

结果：

V7 的 `rank_ic_mean=0.0305` 低于 V6，但 turnover 降到 `0.2552`，cost-adjusted annual 改善到 `-0.0747`，是 V3-V8 中最接近可交易的版本。

结论：

V7 是当前 incumbent。它还不能 promote，因为成本调整后仍为负，且 cost-adjusted recovery days 仍为 `871`。但它是下一轮 exploit 或 OOS / small-cap 分桶验证的合理 parent。

### V8：Fisher Net-Edge State Decay

直觉：

V8 试图把 V7 的经验规则进一步写成净边际收益模型：只有当状态质量扣除成本、陈旧、no-trade band 后仍有净 edge，才输出信号。

机制可以写成：

$$
\begin{aligned}
R^{net}_{i,t+1}
&=
\beta m_{i,t}q_{i,t}
- C_{i,t}
- S^{stale}_{i,t}
+ \varepsilon_{i,t+1}
\end{aligned}
$$

$$
\begin{aligned}
G_{i,t}
&=
|m_{i,t}|q_{i,t}
- C_{i,t}
- S^{stale}_{i,t}
\end{aligned}
$$

$$
\Phi_{i,t}
=
\operatorname{sign}(m_{i,t})
\max(G_{i,t}-B^{no\ trade}_{i,t},0)
(1+0.1\log(1+\mathcal{I}_{i,t}))
$$

其中：

- $q_{i,t}$：状态质量。
- $S^{stale}_{i,t}$：状态陈旧惩罚。
- $B^{no\ trade}$：不交易边界。
- $\mathcal{I}_{i,t}$：Fisher-style 信息精度。

结果：

V8 确实进一步降低 turnover：`0.2231`。但 IC 降到 `0.0122`，long-side annual 降到 `0.0477`，long-side Sharpe 降到 `0.1738`，max drawdown 恶化到 `-0.3227`。

解释：

V8 把“持久有效状态”和“陈旧无效状态”混在一起惩罚了。对于 moneyflow，这可能是错误的：真正的 informed accumulation 本来就可能表现为缓慢、持久、低噪声的状态，不应被简单 stale penalty 杀掉。

结论：

V8 是一个有价值的 falsification。它告诉我们：下一轮不要继续加重状态衰减和 no-trade 惩罚，而应回到 V7，做更温和的质量分层、分桶验证或 OOS 验证。

## 当前推荐路线

### 不建议

不要继续以 V8 作为 exploit parent。

原因：

```text
V8 turnover improved
but rank IC / long-side return / drawdown all worsened
```

也不要直接 promotion：

```text
best branch V7 cost_adjusted_annual_return < 0
best branch V7 cost_adjusted_recovery_days = 871
```

### 建议

下一步以 V7 为 incumbent，做三件事：

1. V7 全样本 / 小市值 / 高流动性分桶对比。
2. V7 在 2025-07-11 之后的 OOS holdout 检验。
3. V7 的温和质量分层，而不是 V8 式强 stale decay。

一个更保守的下一版方向可以写成：

$$
\Phi^{next}_{i,t}
=
H^{V7}_{i,t}
\cdot
w(q_{i,t})
\cdot
\mathbf{1}\{C_{i,t}<C^{max}_{bucket,t}\}
$$

其中：

- $H^{V7}_{i,t}$：保留 V7 的 hysteretic Fisher state。
- $w(q_{i,t})$：温和质量权重，而不是硬过滤。
- $C^{max}_{bucket,t}$：按市值/流动性分桶设定的成本上限。

这样做的目的不是“再加一个复杂惩罚项”，而是保住 V7 的可持续信息，同时只在明显不可交易的样本上减仓。

## 证据索引

V7 Council finalize：

```text
SSM command: 696b841c-9f62-4813-9231-4eb05ac5fa01
```

V8 adapter sync：

```text
SSM command: 870ba225-edb5-4c60-ab9d-38f3fae33525
```

V8 synthesis approval：

```text
SSM command: fa00d9fd-e581-4c18-a266-019a48930613
```

V8 loop execution：

```text
approval-only: 360365c4-afd3-4f46-9fb9-9aed69885d0c
child run:     ebd29364-e0b9-4fe8-adf8-3f07201e50ed
```

Step4 CSV policy env fallback fix：

```text
SSM command: bc3ef1d8-e744-49c1-ad05-a1c6d5f9f509
token: FACTOR_RESEARCH_WORKER_STEP4_CSV_POLICY_ENV_FIX_ACCEPT
```

Remote read-only metric probes：

```text
V4/V5/V7/V8 metrics: 05ee5d6b-bd80-469c-9f67-0a07e0cc6c8a
V6 metrics:          302e67f0-9db9-48b5-968f-ad9f91d7a4ce
```

## Side Effects

本轮没有做：

```text
official promotion
clean data processing
search_worker
new production data mutation
```

本轮确实发生：

```text
V8 run wrote a full factor CSV before Step4 policy gap was fixed.
The file was not deleted, because it is run evidence.
```

本地状态提醒：

```text
This report is a local research note.
No commit / push is implied by this document.
```
