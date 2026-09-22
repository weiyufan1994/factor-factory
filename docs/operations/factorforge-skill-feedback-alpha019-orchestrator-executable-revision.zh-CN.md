# Factor Forge Skill Feedback: Alpha019 Council Orchestration 到 Executable Revision 断裂

日期：2026-05-19  
Repo：`/Users/humphrey/projects/factor-factory`  
相关 report：

- Parent: `ALPHA019_CANONICAL_FORMULA_20160101_FULL_RESEARCH_20260519_141504`
- Child: `ALPHA019_CANONICAL_FORMULA_20160101_FULL_RESEARCH_20260519_141504__LOOP01__MAIN_ITER_004`

## 一句话结论

这次 Alpha019 暴露的问题不是 Council agents 没有提出合理研究方向，而是主 agent 没有被合同要求作为 `orchestrator` 汇总 Council 意见并产出唯一、明确、可执行的 Step3 revision。

因此系统在 `Council results -> Step3B child revision` 之间出现断裂：Council 推荐的是短期状态去噪 / 平滑 / persistence confirmation，但 materializer 最终因为没有 explicit `child_formula`，走了兜底 `generic_sign_challenge = negate(parent)`，导致 child revision 与 Council 研究意见不一致。

严格说，这种情况应该 BLOCK，而不是自动取反继续跑。

## 本轮实际流程

### 1. Parent 完整运行并进入 Council

Parent report:

```text
ALPHA019_CANONICAL_FORMULA_20160101_FULL_RESEARCH_20260519_141504
```

Parent formula:

```text
multiply(
  negate(sign(plus(minus(close, delay(close, 7)), delta(close, 7)))),
  plus(1, rank(plus(1, sum(returns, 250))))
)
```

Parent 机制 memo 已由当前主 agent 写入并通过 validator：

```text
objects/research_iteration_master/main_agent_mechanism_memo__ALPHA019_CANONICAL_FORMULA_20160101_FULL_RESEARCH_20260519_141504.json
```

机制判断：

- 公式只使用 `close` / `returns`，不是 price-volume mechanism。
- 经济机制是 `250d slow winner state x 7d short-horizon pullback / threshold state`。
- 数学模型是 `stochastic_process`：

```text
log P_i,t = X_i,t + M_i,t + U_i,t + epsilon_i,t
S_i,t = rank(sum_250 returns) * -sign(close_t - close_t-7)
target = E[r_i,t+1 | F_t, rank(M_i,t), -sign(U_i,t)]
```

Parent metrics:

```text
rank_ic_mean = 0.02864184519558975
rank_ic_ir = 0.28056395974027354
long_side_annual_return = 0.08814636385869713
long_side_sharpe = 0.38408984124349227
long_side_max_drawdown = -0.4882542593817618
long_side_recovery_days = 1852
turnover_mean = 0.3089171316044917
cost_adjusted_annual_return = -0.14529132968867364
```

研究解释：有弱 IC 和 gross long-side revenue，但成本后失败、回撤过深、恢复期过长，因此不能 promote，需要 Council 判断是否值得做公式层 revision。

### 2. Council agents 正常完成

5 个真实 Council result 均写入并通过 validator：

```text
objects/research_iteration_master/revision_council/ALPHA019_CANONICAL_FORMULA_20160101_FULL_RESEARCH_20260519_141504/agent_results/
```

已验证：

```text
python3 skills/factor-forge-step6/scripts/validate_agentic_council_result.py \
  --report-id ALPHA019_CANONICAL_FORMULA_20160101_FULL_RESEARCH_20260519_141504

result = PASS
```

collection / finalize 也通过：

```text
objects/research_iteration_master/revision_council/ALPHA019_CANONICAL_FORMULA_20160101_FULL_RESEARCH_20260519_141504/agentic_result_collection__ALPHA019_CANONICAL_FORMULA_20160101_FULL_RESEARCH_20260519_141504.json

valid_result_count = 5
missing_result_count = 0
ready_for_finalize = true
```

### 3. Council 推荐方向是平滑 / 去噪 / persistence confirmation

Council summary:

```text
objects/research_iteration_master/revision_council/ALPHA019_CANONICAL_FORMULA_20160101_FULL_RESEARCH_20260519_141504/revision_council_summary__ALPHA019_CANONICAL_FORMULA_20160101_FULL_RESEARCH_20260519_141504.json
```

其 `recommended_branch_templates` 中的方向包括：

1. `alpha019_dimensional_scaling_law_001_continuous_pullback_rank`
   - Replace hard seven-day sign label with ranked nonnegative pullback magnitude.

2. `ALPHA019_COST_LAW_001_PERSISTENT_PULLBACK_CONFIRMATION`
   - Replace instantaneous 7d sign boundary with persistence-confirmed pullback label.

3. `alpha019_smooth_7d_boundary_one_trial`
   - Replace discontinuous one-day 7d boundary with 3-observation summed boundary.

4. `agent_stochastic_process_modeler_law_001_persistent_u_gate`
   - Require local persistence of negative `U_t` before multiplying by slow winner state.

5. `LAW_ALPHA019_DEDUP_NORMALIZED_SMOOTHED_GATE`
   - Replace duplicated 7d close displacement with normalized 7d returns state and one-lag confirmation.

这些意见方向是一致的：Alpha019 的问题不是 sign 整体反了，而是 7 日 hard sign gate 太噪、太容易边界翻转，导致 turnover / drawdown / cost-adjusted evidence 失败。

### 4. 但 Council 没有输出可执行 child formula

虽然 `recommended_branch_templates` 有 5 条，但 summary 中没有真正的 executable selection：

```text
candidate_proposals = []
selected_proposals = []
```

Parent `handoff_to_step3b` 也没有携带：

```text
child_formula
selected_revision.child_formula
executable_revision_spec.child_formula
selected_revision_law_ids
expected_metric_signature
falsification_tests
kill_criteria
```

Parent handoff path:

```text
objects/handoff/handoff_to_step3b__ALPHA019_CANONICAL_FORMULA_20160101_FULL_RESEARCH_20260519_141504.json
```

Handoff 只有泛化的 modification targets，例如：

```text
revise factor expression/code to improve long-side Sharpe by reducing volatility drag and drawdown
```

这不是可执行 Step3B revision。

### 5. Materializer 走了兜底 `generic_sign_challenge`

Materializer 代码路径：

```text
skills/factor-forge-step6/scripts/materialize_step6_child_revision.py
```

关键逻辑：

```python
explicit = (
    parent_handoff.get("child_formula")
    or (parent_handoff.get("executable_revision_spec") or {}).get("child_formula")
    or (parent_handoff.get("selected_revision") or {}).get("child_formula")
)
if isinstance(explicit, str) and explicit.strip():
    return explicit.strip(), "explicit_handoff_child_formula"

...
return f"negate({parent_formula})", "generic_sign_challenge"
```

因为 handoff 没有 explicit child formula，最终 executable spec 变成：

```text
derivation_rule = generic_sign_challenge
selected_revision_law_ids = []
child_formula = negate(parent_formula)
expected_metric_signature = {}
falsification_tests = []
kill_criteria = []
```

Executable spec path:

```text
objects/research_iteration_master/executable_revision_spec__ALPHA019_CANONICAL_FORMULA_20160101_FULL_RESEARCH_20260519_141504__LOOP01__MAIN_ITER_004.json
```

Child formula:

```text
negate(
  multiply(
    negate(sign(plus(minus(close, delay(close, 7)), delta(close, 7)))),
    plus(1, rank(plus(1, sum(returns, 250))))
  )
)
```

这与 Council 的核心建议不一致。

### 6. Child sign challenge 被证伪

Child metrics:

```text
rank_ic_mean = -0.02864184519558975
rank_ic_ir = -0.28056395974027354
long_side_annual_return = -0.19851239443202462
long_side_sharpe = -0.9556436465120902
long_side_max_drawdown = -0.8810391224581016
long_side_recovery_days = 3318
turnover_mean = 0.2679774242158988
cost_adjusted_annual_return = -0.4010134066187349
```

Child 最终 Step6 决策为 reject：

```text
objects/runtime_context/ultimate_loop_report__ALPHA019_CANONICAL_FORMULA_20160101_FULL_RESEARCH_20260519_141504__LOOP01__MAIN_ITER_004.json

status = PASS
final_outcome = rejected
stop_reason = step6_decision_reject
```

这个 reject 对 `generic_sign_challenge` 是正确的，但它没有验证 Council 的主建议。

## Root Cause

当前系统缺少一个关键合同层：

```text
Council results
  -> main-agent orchestration synthesis
  -> selected executable revision
  -> child_formula / metric signature / falsification / kill criteria
  -> materializer
  -> Step3B
```

现在真实发生的是：

```text
Council results
  -> recommended_branch_templates only
  -> Step3B handoff with generic modification text
  -> materializer fallback
  -> negate(parent)
```

也就是说，主 agent 作为 orchestra 只完成了：

- dispatch Council
- collect results
- finalize Council

但没有完成最关键的研究职责：

- 综合多个 Council 结果；
- 判断哪些方向一致、哪些互斥；
- 选择一个最符合 economic / math mechanism 的 revision law；
- 把它写成唯一、明确、可执行的 child formula；
- 配套 expected metric signature / falsification tests / kill criteria；
- 明确哪些 Council proposal 被拒绝，以及为什么。

## 为什么这不是小问题

Factor Forge Ultimate 的目标不是“有 child formula 就跑”，而是让 Step3 revision 继承研究逻辑。

在 Alpha019 中，Council 的经济和数学判断是：

- Parent 有弱 signal；
- hard sign gate 太噪；
- 应该测试 smoothing / persistence confirmation / continuous pullback magnitude；
- 成功标准是 turnover 降低、cost-adjusted return 转正、rank IC 不崩、drawdown 改善。

但 child 实际测试的是：

- parent sign 是否整体取反。

这两个研究问题不同。即使 child reject，也不能说明 Council 主建议被证伪。

## 期望行为

### A. 新增 Main-Agent Orchestration Synthesis Artifact

在 Council finalize 后、materialize child 前，必须要求当前主 agent 写：

```text
objects/research_iteration_master/revision_council/<report_id>/main_agent_council_synthesis__<report_id>.json
objects/research_iteration_master/revision_council/<report_id>/main_agent_council_synthesis__<report_id>.md
```

建议 contract version：

```text
factorforge_main_agent_council_synthesis_v1
```

核心字段：

```json
{
  "contract_version": "factorforge_main_agent_council_synthesis_v1",
  "report_id": "<parent>",
  "producer": "current_main_agent_orchestrator",
  "agent_authorship": {
    "authoring_mode": "current_agent_freeform",
    "answered_without_deterministic_template": true
  },
  "council_result_refs": [...],
  "consensus_summary": "...",
  "disagreement_summary": "...",
  "rejected_revision_laws": [
    {
      "law_id": "...",
      "reason": "..."
    }
  ],
  "selected_revision": {
    "law_id": "...",
    "source_agent_roles": [...],
    "why_selected": "...",
    "economic_mechanism_link": "...",
    "math_model_link": "...",
    "child_formula": "...",
    "formula_mutation_description": "...",
    "expected_metric_signature": {
      "rank_ic_mean": "...",
      "turnover_mean": "...",
      "long_side_annual_return": "...",
      "cost_adjusted_annual_return": "...",
      "drawdown": "..."
    },
    "falsification_tests": [...],
    "kill_criteria": [...]
  },
  "no_revision_reason": null,
  "canonical_write_permission": false,
  "execution_allowed_by_default": false,
  "human_approval_required": true
}
```

### B. 如果无法选出 executable revision，必须 BLOCK / exhausted

以下情况不能 materialize child：

- `selected_revision.child_formula` 缺失；
- `selected_revision.law_id` 缺失；
- `expected_metric_signature` 为空；
- `falsification_tests` 为空；
- `kill_criteria` 为空；
- selected law 与 Council proposal 不一致；
- child formula 只是 materializer 自行兜底生成；
- child formula hash 与 parent 相同，且不是显式 audit rerun；
- child formula 不能从 selected law 推导。

建议 BLOCK token：

```text
BLOCK_FACTORFORGE_MAIN_AGENT_COUNCIL_SYNTHESIS_MISSING
BLOCK_FACTORFORGE_EXECUTABLE_REVISION_CHILD_FORMULA_MISSING
BLOCK_FACTORFORGE_EXECUTABLE_REVISION_SELECTED_LAW_MISSING
BLOCK_FACTORFORGE_EXECUTABLE_REVISION_METRIC_SIGNATURE_MISSING
BLOCK_FACTORFORGE_EXECUTABLE_REVISION_FALSIFICATION_MISSING
BLOCK_FACTORFORGE_EXECUTABLE_REVISION_KILL_CRITERIA_MISSING
BLOCK_FACTORFORGE_EXECUTABLE_REVISION_ORCHESTRATOR_MISMATCH
```

### C. `generic_sign_challenge` 不能作为默认 fallback

`generic_sign_challenge` 只能在以下条件全部满足时使用：

1. Council 或主 agent synthesis 明确选择 sign/orientation challenge；
2. selected law id 明确说明是 sign/orientation challenge；
3. expected metric signature 说明为什么取反应该改善；
4. falsification tests / kill criteria 完整；
5. child formula 由 synthesis 明确写入。

否则 materializer 必须 BLOCK。

当前这段默认逻辑应删除或降级为仅 debug：

```python
return f"negate({parent_formula})", "generic_sign_challenge"
```

更合适的行为：

```python
raise ValueError(
    "BLOCK_FACTORFORGE_EXECUTABLE_REVISION_CHILD_FORMULA_MISSING: "
    "Council produced advisory templates but no main-agent selected child_formula"
)
```

### D. Step3B handoff 必须消费 orchestrator synthesis

`handoff_to_step3b__<report_id>.json` 不应只包含泛化 modification text。正式 loop handoff 应包含或引用：

```json
{
  "orchestrator_synthesis_path": "...",
  "selected_revision": {
    "law_id": "...",
    "child_formula": "...",
    "formula_hash_expected_to_change": true,
    "expected_metric_signature": {...},
    "falsification_tests": [...],
    "kill_criteria": [...]
  }
}
```

如果 handoff 只有：

```text
revise factor expression/code to improve long-side Sharpe
```

这只能算 advisory，不足以 materialize child Step3B。

### E. Materializer 应校验 Council / synthesis 一致性

`materialize_step6_child_revision.py` 应校验：

- selected law id 存在于 Council result / synthesis；
- child formula 来自 synthesis，不来自 materializer fallback；
- executable spec 的 `selected_revision_law_ids` 非空；
- `expected_metric_signature` 非空；
- `falsification_tests` 非空；
- `kill_criteria` 非空；
- child formula hash different from parent unless audit rerun；
- if prior revision memory says a law was falsified, synthesis cannot repeat it。

## Alpha019 应有的正确 orchestrator decision 示例

这不是要求硬编码该公式，只是说明主 agent synthesis 应该达到的具体程度。

可能选择的 Council consensus law：

```text
alpha019_smooth_7d_boundary_one_trial
```

可能 child formula：

```text
multiply(
  rank(plus(1, sum(returns, 250))),
  rank(negate(sum(returns, 7)))
)
```

或 persistence-confirmed version：

```text
multiply(
  rank(plus(1, sum(returns, 250))),
  negate(sign(plus(sum(returns, 7), delay(sum(returns, 7), 1))))
)
```

这些公式表达的研究问题是：

- 保留 250d slow winner state；
- 不再使用重复的 `close-delay(close,7)` + `delta(close,7)`；
- 降低 hard sign boundary 的噪声；
- 测试 pullback magnitude / persistence 是否比单日阈值翻转更可交易。

成功标准：

```text
rank_ic_mean >= 0.015
turnover_mean < 0.3089
long_side_annual_return > 0
cost_adjusted_annual_return > 0
long_side_max_drawdown materially better than -0.4883
recovery_days materially below 1852
```

失败标准：

```text
cost_adjusted_annual_return <= 0
rank_ic_mean collapses or flips negative
long_side_annual_return <= 0
drawdown not improved
250d state ablation does not weaken evidence
```

## 验收标准

建议新增 smoke / regression：

### 1. Alpha019 Council-Orchestrator Regression

Fixture：Council summary 只有 advisory branch templates，没有 selected child formula。

期望：

```text
materialize_step6_child_revision.py -> BLOCK_FACTORFORGE_MAIN_AGENT_COUNCIL_SYNTHESIS_MISSING
```

不允许：

```text
derivation_rule = generic_sign_challenge
child_formula = negate(parent)
```

### 2. Explicit Synthesis Pass Case

Fixture：主 agent synthesis 明确选择 `alpha019_smooth_7d_boundary_one_trial`，写入 child formula / metric signature / falsification / kill criteria。

期望：

```text
executable_revision_spec.child_formula == synthesis.selected_revision.child_formula
selected_revision_law_ids non-empty
expected_metric_signature non-empty
falsification_tests non-empty
kill_criteria non-empty
child_formula_hash != parent_formula_hash
```

### 3. Generic Sign Challenge Guard

Fixture：没有显式 sign/orientation selected law，但 handoff 文本出现 generic “sign / monotonic / orientation” 字样。

期望：

```text
BLOCK
```

不允许 materializer 自动生成：

```text
negate(parent_formula)
```

### 4. Prior Revision Memory Guard

如果某个 child 已证伪 `generic_sign_challenge`：

```text
prior_revision_outcome = falsified
forbidden_repeat_revision_rules = ["generic_sign_challenge"]
```

下一轮 synthesis / materializer 必须阻止重复同一 law。

## 对当前 Alpha019 结论的影响

当前 formal child outcome 是：

```text
final_outcome = rejected
```

但需要解释清楚：

- 这个 reject 严格证伪的是 `generic_sign_challenge = negate(parent)`；
- 它没有充分测试 Council 的核心平滑 / 去噪 / persistence confirmation 建议；
- 因此不能把“child reject”解释成“Council 最佳建议被证伪”。

如果修复 orchestration contract 后继续 Alpha019，应该从 parent Council results 重新做 synthesis，选择一个明确平滑/确认 child formula，再跑一次正式 child；如果那一轮仍成本后失败，则 Alpha019 的 reject 才更完整。

## 建议优先级

P0：

- 删除 materializer 默认 `negate(parent)` fallback，或要求显式 synthesis 才允许。
- 新增 main-agent council synthesis artifact。
- materializer 必须消费 synthesis / selected child formula。

P1：

- `attach_revision_council_to_step6.py` 不应把 advisory templates 自动转成可 materialize handoff。
- `handoff_to_step3b` 缺 executable selected revision 时只能 advisory，不得进入 child materialization。

P2：

- 在 ultimate loop report 中区分：
  - `council_completed_advisory_only`
  - `orchestrator_synthesis_missing`
  - `executable_revision_ready`
  - `child_materialized`

这样主 agent / reviewer / user 能一眼看出是否真的进入了可执行 revision，而不是误以为 Council 已经驱动了 Step3B。
