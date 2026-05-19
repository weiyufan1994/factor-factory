# Phase O.2 Main-Agent Formula-Specific Mechanism Memo 架构书

> **状态:** 待实现  
> **范围:** Step6 主 agent 机制推导合同、validator、Council packet/taskbook 输入、Alpha030/Alpha019 回归 smoke。  
> **非范围:** Step3B/Step4 性能优化、clean data、search worker、official promotion、真实 subagent API。

## 1. 背景

Phase O/P1C 已经解决了两个重要问题：

1. Alpha019-like no-volume 公式不会再被错误归为 price-volume mechanism。
2. `--council-mode auto` 在 formal iterate 场景会进入 `agentic_dispatch_manifest`，不会把 deterministic scaffold 当成 formal Council。

但 Alpha030 production-loop 暴露了新的架构缺口：

```text
主 agent 在 Council 前没有硬性产出 formula-specific economic/math mechanism memo。
```

这导致 Step1/2 可以产生初始机制 priors，Step6/Council dispatch 也能通过，但 Council packet 仍可能携带泛化机制语言。例如 Alpha030 公式是短期 signed price state + relative volume participation 的 additive state，却被描述成 rolling rank covariance/correlation/dependence。

这个问题不是 prompt polish。它需要一个 artifact contract 和 validator。

## 2. 目标

在 Council dispatch 前，Step6 主 agent 必须显性写出：

```text
formula component map
-> economic state
-> mathematical object
-> process/distribution assumption
-> target functional
-> expected metric signature
-> observed evidence comparison
-> contradictions / revision implications
-> Council questions
```

Council 的职责是 critique 和拓展这个 memo，不是替主 agent 从零补研究。

## 3. 新 Artifact

新增两个 artifact：

```text
objects/research_iteration_master/main_agent_mechanism_memo__<report_id>.json
objects/research_iteration_master/main_agent_mechanism_memo__<report_id>.md
```

JSON contract version：

```text
factorforge_main_agent_mechanism_memo_v1
```

## 4. 生成时点

生成顺序：

```text
Step4 metrics/charts/evaluation available
-> Step5 case/handoff available
-> Step6 run_step6 builds research judgment
-> Step6 writes main_agent_formula_specific_mechanism_memo
-> validate_step6 validates memo
-> build_revision_council_packet includes memo
-> agentic taskbook asks Council to critique memo
```

如果 Step6 decision 不进入 Council，仍应写 memo。因为 memo 是 Step6 主 agent 的研究责任，不是 Council-only 输入。

## 5. Schema

建议 JSON schema：

```json
{
  "contract_version": "factorforge_main_agent_mechanism_memo_v1",
  "report_id": "...",
  "factor_id": "...",
  "created_at_utc": "...",
  "producer": "step6_main_agent",
  "source_refs": {
    "factor_spec_master": "...",
    "factor_case_master": "...",
    "evaluation_summary": "...",
    "research_iteration": "...",
    "mechanism_math_contract": "..."
  },
  "formula": "...",
  "formula_understanding": {},
  "formula_component_map": [
    {
      "component_id": "short_signed_price_state",
      "formula_subexpression": "sign(delta(close,1)) + sign(delta(delay(close,1),1)) + sign(delta(delay(close,2),1))",
      "operators": ["sign", "delta", "delay"],
      "observable_estimator": "three-day signed price pressure state",
      "economic_state": "short-horizon weakness / reversal / continuation pressure",
      "mathematical_object": "discrete threshold state",
      "expected_role": "state direction and bucket migration",
      "metric_link": "should explain short-horizon payoff direction and turnover"
    }
  ],
  "economic_hypothesis": {
    "return_source_class": "risk_premium | information_advantage | market_structure_arbitrage | mixed",
    "payer_or_counterparty": "...",
    "why_they_pay": "...",
    "necessary_market_structure": "..."
  },
  "math_hypothesis": {
    "selected_model_family": "stochastic_process | state_space | threshold_process | transient_impact | valuation_identity | projection | other",
    "why_this_model": "...",
    "why_not_generic_template": "...",
    "random_object": "...",
    "latent_state": "...",
    "process_or_distribution": "...",
    "target_functional": "...",
    "formula_as_estimator": "...",
    "expected_metric_signature": {
      "rank_ic": "...",
      "long_side": "...",
      "cost_adjusted": "...",
      "monotonicity": "...",
      "turnover": "..."
    }
  },
  "evidence_comparison": {
    "observed_metrics": {
      "rank_ic_mean": null,
      "long_side_annual_return": null,
      "cost_adjusted_annual_return": null,
      "long_side_max_drawdown": null,
      "daily_turnover": null,
      "quantile_nav": {}
    },
    "mechanism_supported": "yes | partial | no",
    "contradictions": [],
    "revision_implications": [],
    "kill_criteria_triggered": []
  },
  "operator_claim_consistency": {
    "claims_correlation_or_covariance": false,
    "formula_has_correlation_or_covariance_operator": false,
    "claims_dependence_without_operator_justification": false,
    "has_sign_or_threshold": true,
    "sign_threshold_discussion_present": true,
    "has_volume_ratio": true,
    "volume_ratio_participation_discussion_present": true
  },
  "council_questions": [
    "Which assumption should Council challenge?",
    "Which alternative model family is plausible?",
    "Which ablation distinguishes reversal from continuation?"
  ],
  "canonical_write_permission": false,
  "execution_allowed_by_default": false
}
```

## 6. Alpha030 Expected Memo Content

Alpha030 formula:

```text
plus(
  plus(
    negate(rank(plus(plus(sign(delta(close,1)), sign(delta(delay(close,1),1))), sign(delta(delay(close,2),1))))),
    1
  ),
  multiply(1, divide(sum(volume,5), sum(volume,20)))
)
```

Formula-specific decomposition:

```text
S_i,t = sign(r_i,t) + sign(r_i,t-1) + sign(r_i,t-2)
V_i,t = Sum(volume_i,t-4:t) / Sum(volume_i,t-19:t)
A_i,t = -Rank(S_i,t) + 1 + V_i,t
```

Required component map:

1. `short_signed_price_state`
   - operators: `sign`, `delta`, `delay`
   - mathematical object: discrete threshold / bucket migration state
   - must discuss discontinuity and turnover

2. `relative_volume_participation`
   - operators: `sum`, `divide`, `volume`
   - mathematical object: positive participation-intensity state
   - must discuss abnormal volume / participation intensity, not generic liquidity

3. `additive_score_combination`
   - operators: `plus`, rank plus raw ratio
   - mathematical object: additive state with scale/commensurability risk
   - must discuss whether ranked signed price state and raw volume ratio are commensurable

Expected mechanism:

```text
P_i,t = F_i,t + I_i,t + epsilon_i,t
I_i,t is transient price pressure / liquidity shock.
S_i,t estimates direction and persistence of recent short-horizon price pressure.
V_i,t estimates participation intensity or crowded attention.
Target: E[r_i,t+1 | S_i,t low, V_i,t high]
```

Must not claim unless justified:

```text
rolling rank covariance
rolling correlation
price-volume dependence estimator
```

because Alpha030 does not contain correlation/covariance operators.

Expected evidence conclusion for current Alpha030:

```text
The proposed reversal/crowding monetization mechanism is not supported for promotion.
High score appears to identify a bad or cost-destroyed state, not a tradable long-side recovery state.
Council may explore smoothing, sign threshold mutation, volume gate, or continuation-vs-reversal ablation.
```

## 7. Validator Requirements

新增 validator，可实现为独立脚本并由 `validate_step6.py` 调用：

```text
skills/factor-forge-step6/scripts/validate_main_agent_mechanism_memo.py
```

BLOCK 条件：

1. memo missing。
2. `contract_version` 不正确。
3. `canonical_write_permission=true`。
4. `execution_allowed_by_default=true`。
5. `formula_component_map` 为空。
6. 组件没有 `formula_subexpression` / `observable_estimator` / `economic_state` / `mathematical_object` / `expected_role`。
7. `math_hypothesis.process_or_distribution` 只是复述公式，没有模型假设。
8. `target_functional` 没有未来收益对象或信息集。
9. `expected_metric_signature` 缺少 long-side / cost-adjusted / monotonicity / turnover。
10. `evidence_comparison` 没有 Step4 metrics 对照。
11. 文本 claims correlation/covariance/dependence，但公式没有对应 operator 且没有 explicit justification。
12. formula 有 `sign` / threshold，但 memo 没讨论 discontinuity、bucket migration、turnover。
13. formula 有 `sum(volume,k1)/sum(volume,k2)`，但 memo 没讨论 relative participation intensity / abnormal volume。
14. formula 混合 rank state 和 raw ratio additive score，但 memo 没讨论 scale / commensurability。
15. memo generic，占位文本过多，例如 `formula estimates the state`、`generic expected payoff`、`counterparty implied`。

## 8. Council Packet Contract

`build_revision_council_packet.py` 必须加入：

```json
{
  "main_agent_mechanism_memo_ref": "objects/research_iteration_master/main_agent_mechanism_memo__<report_id>.json",
  "main_agent_formula_component_map": [],
  "main_agent_math_hypothesis": {},
  "main_agent_evidence_comparison": {},
  "council_required_critiques": []
}
```

如果 Council packet 正在构建，而 memo 缺失或 validator 不通过，应 BLOCK，不能让 Council 接收 generic summary。

## 9. Agentic Taskbook Contract

`build_agentic_council_taskbook.py` 必须把 memo 作为 required input。

每个 subagent task 应明确：

```text
Critique the main agent mechanism memo.
Do not reconstruct from a generic family label.
Challenge formula component mapping, mathematical model, payer derivation, expected metric signature, and contradictions.
```

至少要求输出：

- `main_agent_memo_agreement`
- `model_selection_critique`
- `component_mapping_critique`
- `payer_derivation_critique`
- `evidence_contradiction_review`
- `revision_or_kill_recommendation`

## 10. Acceptance Tests

### 10.1 /tmp smoke

新增 smoke：

```text
scripts/run_main_agent_mechanism_memo_smoke.py
```

或集成进 `run_step6_intelligence_smoke.py`，但建议单独 smoke，避免 Step6 smoke 继续膨胀。

Cases:

1. `alpha030_main_agent_memo_pass`
2. `memo_missing_blocks_before_council_packet`
3. `generic_memo_blocks`
4. `correlation_claim_without_operator_blocks`
5. `sign_without_threshold_turnover_discussion_blocks`
6. `volume_ratio_without_participation_discussion_blocks`
7. `additive_rank_raw_ratio_without_commensurability_discussion_blocks`
8. `canonical_write_permission_blocks`
9. `execution_allowed_by_default_blocks`
10. `council_packet_requires_memo_ref`
11. `taskbook_requires_memo_critique`

### 10.2 Alpha030 production regression

Fresh report id：

```bash
python3 scripts/run_factorforge_ultimate_loop.py \
  --report-id ALPHA030_CANONICAL_FORMULA_20160101_MAIN_AGENT_MECH_TEST_<timestamp> \
  --start-step 2 \
  --max-loops 10 \
  --council-mode auto
```

Expected:

```text
wrapper status = PASS
final_outcome = awaiting_agent_results, unless promoted/rejected earlier
Council effective_mode = agentic_dispatch_manifest when iterate
main_agent_mechanism_memo exists
Council packet references main_agent_mechanism_memo
memo discusses short signed price state
memo discusses relative volume participation
memo discusses sign discontinuity / threshold migration / turnover
memo discusses additive rank/raw-ratio scale commensurability
memo does not claim rolling rank covariance/correlation unless explicitly justified
memo compares Step4 evidence and states current Alpha030 is not promotion-supported
```

### 10.3 Regression

Must still pass:

```bash
python3 scripts/run_step12_hypothesis_contract_smoke.py --fresh --root /tmp/factorforge_step12_phase_o2_memo_regression
python3 scripts/run_mechanism_math_contract_smoke.py --fresh --root /tmp/factorforge_mechanism_math_phase_o2_memo_regression
python3 scripts/run_step6_intelligence_acceptance.py --fresh --root /tmp/factorforge_step6_intelligence_acceptance_phase_o2_memo
```

## 11. Final Acceptance Boundary

Accept only if:

- Step6 writes main-agent memo for formal runs.
- `validate_step6.py` blocks missing/generic/inconsistent memo.
- Council packet and taskbook carry memo and require critique.
- Alpha030 fresh run proves memo exists and is formula-specific.
- Alpha019 regression still passes.
- No clean data processing.
- No search worker.
- No official promotion unless an existing gate independently permits it.
- No Step3B/Step4 performance path changes.

