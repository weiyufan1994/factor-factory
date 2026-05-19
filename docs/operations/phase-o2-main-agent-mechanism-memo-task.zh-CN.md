# Phase O.2 Main-Agent Mechanism Memo Contract 任务说明书

> **执行对象:** Factor Factory coder thread  
> **审查对象:** reviewer thread  
> **架构依据:** `/Users/humphrey/projects/factor-factory/docs/operations/phase-o2-main-agent-mechanism-memo-architecture.zh-CN.md`  
> **目标:** 在 Council dispatch 前强制 Step6 主 agent 写出 formula-specific mechanism memo，并由 validator / Council packet / taskbook 硬执行。

## 0. 当前问题

Alpha030 production-loop 证明：

- Council dispatch 工作正常。
- 但 Step6 主 agent 没有硬性产出公式特异机制 memo。
- Council packet 仍可能携带 generic mechanism language。

Alpha030 公式：

```text
plus(
  plus(
    negate(rank(plus(plus(sign(delta(close,1)), sign(delta(delay(close,1),1))), sign(delta(delay(close,2),1))))),
    1
  ),
  multiply(1, divide(sum(volume,5), sum(volume,20)))
)
```

正确机制应围绕：

```text
short signed price state
relative volume participation
additive rank/raw-ratio combination
transient pressure / threshold migration / turnover / commensurability
```

而不是泛化为：

```text
rolling rank covariance / rolling correlation / price-volume dependence estimator
```

## 1. 修改文件

新增：

```text
/Users/humphrey/projects/factor-factory/factor_factory/mechanism_math/main_agent_memo.py
/Users/humphrey/projects/factor-factory/skills/factor-forge-step6/scripts/validate_main_agent_mechanism_memo.py
/Users/humphrey/projects/factor-factory/scripts/run_main_agent_mechanism_memo_smoke.py
```

修改：

```text
/Users/humphrey/projects/factor-factory/skills/factor-forge-step6/scripts/run_step6.py
/Users/humphrey/projects/factor-factory/skills/factor-forge-step6/scripts/validate_step6.py
/Users/humphrey/projects/factor-factory/skills/factor-forge-step6/scripts/build_revision_council_packet.py
/Users/humphrey/projects/factor-factory/skills/factor-forge-step6/scripts/build_agentic_council_taskbook.py
/Users/humphrey/projects/factor-factory/scripts/run_step6_intelligence_smoke.py
/Users/humphrey/projects/factor-factory/scripts/run_agentic_council_dispatch_smoke.py
/Users/humphrey/projects/factor-factory/skills/factor-forge-step6/SKILL.md
/Users/humphrey/projects/factor-factory/skills/factor-forge-ultimate/SKILL.md
```

不要修改：

```text
Step3B / Step4 performance path
clean data builders
search worker
official promotion gate
real subagent API
```

## 2. Task A: 新增 main agent memo builder

**文件:** `/Users/humphrey/projects/factor-factory/factor_factory/mechanism_math/main_agent_memo.py`

实现函数：

```python
def build_main_agent_mechanism_memo(
    *,
    report_id: str,
    factor_spec: dict[str, Any],
    factor_case: dict[str, Any],
    evaluation_summary: dict[str, Any],
    step6_iteration: dict[str, Any] | None = None,
) -> dict[str, Any]:
    ...
```

输出必须符合：

```json
{
  "contract_version": "factorforge_main_agent_mechanism_memo_v1",
  "report_id": "...",
  "factor_id": "...",
  "producer": "step6_main_agent",
  "formula": "...",
  "formula_understanding": {},
  "formula_component_map": [],
  "economic_hypothesis": {},
  "math_hypothesis": {},
  "evidence_comparison": {},
  "operator_claim_consistency": {},
  "council_questions": [],
  "canonical_write_permission": false,
  "execution_allowed_by_default": false
}
```

### Alpha030-specific builder requirements

如果 formula contains:

```text
sign(delta(close,1))
sign(delta(delay(close,1),1))
sign(delta(delay(close,2),1))
sum(volume,5) / sum(volume,20)
```

memo 必须生成以下 components：

```json
[
  {
    "component_id": "short_signed_price_state",
    "formula_subexpression": "sign(delta(close,1)) + sign(delta(delay(close,1),1)) + sign(delta(delay(close,2),1))",
    "operators": ["sign", "delta", "delay"],
    "observable_estimator": "three-day signed price pressure state",
    "economic_state": "short-horizon weakness / reversal / continuation pressure",
    "mathematical_object": "discrete threshold state",
    "expected_role": "state direction and bucket migration",
    "metric_link": "short sign changes imply turnover and possible bucket churn"
  },
  {
    "component_id": "relative_volume_participation",
    "formula_subexpression": "sum(volume,5) / sum(volume,20)",
    "operators": ["sum", "divide", "volume"],
    "observable_estimator": "5-day volume over 20-day volume ratio",
    "economic_state": "relative participation intensity / crowded attention / liquidity demand",
    "mathematical_object": "positive scale state",
    "expected_role": "shock or crowding intensity",
    "metric_link": "high participation should strengthen or identify transient pressure if mechanism is valid"
  },
  {
    "component_id": "additive_score_combination",
    "formula_subexpression": "-rank(short_signed_price_state) + 1 + relative_volume_participation",
    "operators": ["rank", "plus", "negate"],
    "observable_estimator": "additive score combining ranked signed-price weakness and raw relative volume ratio",
    "economic_state": "high-participation short-horizon weakness state",
    "mathematical_object": "additive latent-state proxy with scale commensurability risk",
    "expected_role": "tests whether weak recent signed price state plus high participation predicts next return",
    "metric_link": "G10 should outperform if high-score state is monetizable; G9 > G10 challenges monotonicity"
  }
]
```

Memo `math_hypothesis` for Alpha030 must include:

```json
{
  "selected_model_family": "transient_impact_or_threshold_process",
  "why_this_model": "formula estimates short-horizon signed price pressure and relative participation intensity",
  "why_not_generic_template": "formula has no correlation/covariance operator; additive sign-state plus volume-ratio is not rolling rank covariance",
  "random_object": "security-day forward return conditional on formula state and information set F_t",
  "latent_state": "transient price pressure / liquidity demand state",
  "process_or_distribution": "P_i,t = F_i,t + I_i,t + epsilon_i,t, where I_i,t decays if temporary pressure reverts",
  "target_functional": "E[r_i,t+1 | F_t, S_i,t low, V_i,t high]",
  "formula_as_estimator": "S_i,t estimates signed short-horizon price pressure; V_i,t estimates relative participation intensity"
}
```

`evidence_comparison` must include observed metrics from Step4/Step5 when present:

```text
rank_ic_mean
long_side_annual_return
cost_adjusted_annual_return
long_side_max_drawdown
daily_turnover
quantile_nav / G9 / G10 if available
```

For current Alpha030 evidence, conclusion must be not promotion-supported:

```text
mechanism_supported = "no" or "partial"
contradictions include long-side negative / cost adjusted negative / G9 > G10 or non-monotone high score
revision_implications include smoothing, sign threshold mutation, volume gate, reversal-vs-continuation ablation
```

## 3. Task B: 写 JSON 和 MD artifact

**文件:** `/Users/humphrey/projects/factor-factory/skills/factor-forge-step6/scripts/run_step6.py`

在 Step6 research iteration 写入前后均可，但必须在 Council packet 构建前存在：

```text
objects/research_iteration_master/main_agent_mechanism_memo__<report_id>.json
objects/research_iteration_master/main_agent_mechanism_memo__<report_id>.md
```

MD 至少包含：

```markdown
# Main Agent Formula-Specific Mechanism Memo

## Formula Component Map
## Economic Hypothesis
## Math Hypothesis
## Evidence Comparison
## Operator-Claim Consistency
## Council Questions
```

Step6 iteration/research memo 中加引用：

```json
"main_agent_mechanism_memo_ref": "objects/research_iteration_master/main_agent_mechanism_memo__<report_id>.json"
```

## 4. Task C: 新增 validator

**文件:** `/Users/humphrey/projects/factor-factory/skills/factor-forge-step6/scripts/validate_main_agent_mechanism_memo.py`

CLI：

```bash
python3 skills/factor-forge-step6/scripts/validate_main_agent_mechanism_memo.py --report-id <report_id>
```

BLOCK tokens:

```text
BLOCK_MAIN_AGENT_MECHANISM_MEMO_MISSING
BLOCK_MAIN_AGENT_MECHANISM_MEMO_CONTRACT_VERSION
BLOCK_MAIN_AGENT_MECHANISM_MEMO_CANONICAL_WRITE_PERMISSION
BLOCK_MAIN_AGENT_MECHANISM_MEMO_EXECUTION_ALLOWED
BLOCK_MAIN_AGENT_MECHANISM_MEMO_COMPONENT_MAP_MISSING
BLOCK_MAIN_AGENT_MECHANISM_MEMO_COMPONENT_INCOMPLETE
BLOCK_MAIN_AGENT_MECHANISM_MEMO_GENERIC
BLOCK_MAIN_AGENT_MECHANISM_MEMO_TARGET_FUNCTIONAL_INVALID
BLOCK_MAIN_AGENT_MECHANISM_MEMO_EXPECTED_METRIC_SIGNATURE_MISSING
BLOCK_MAIN_AGENT_MECHANISM_MEMO_EVIDENCE_COMPARISON_MISSING
BLOCK_MAIN_AGENT_MECHANISM_MEMO_OPERATOR_CLAIM_CONTRADICTION
BLOCK_MAIN_AGENT_MECHANISM_MEMO_SIGN_DISCUSSION_MISSING
BLOCK_MAIN_AGENT_MECHANISM_MEMO_VOLUME_RATIO_DISCUSSION_MISSING
BLOCK_MAIN_AGENT_MECHANISM_MEMO_ADDITIVE_SCALE_DISCUSSION_MISSING
```

Required checks:

1. JSON exists and version matches.
2. `canonical_write_permission` is false.
3. `execution_allowed_by_default` is false.
4. `formula_component_map` nonempty.
5. Every component has:
   - `component_id`
   - `formula_subexpression`
   - `observable_estimator`
   - `economic_state`
   - `mathematical_object`
   - `expected_role`
6. `math_hypothesis.process_or_distribution` must include a model object/process and not just formula tokens.
7. `target_functional` must mention future return and information set or conditioning state.
8. `expected_metric_signature` includes:
   - `long_side`
   - `cost_adjusted`
   - `monotonicity`
   - `turnover`
9. `evidence_comparison.observed_metrics` is nonempty after Step4/5 evidence exists.
10. If memo claims `correlation`, `covariance`, or `dependence`, formula must include matching operator or `operator_claim_consistency.explicit_dependence_justification` must be nonempty.
11. If formula has `sign`, memo must discuss discontinuity / threshold / bucket migration / turnover.
12. If formula has `sum(volume,...)/sum(volume,...)`, memo must discuss relative participation intensity / abnormal volume.
13. If formula mixes rank state and raw volume ratio additively, memo must discuss scale / commensurability.

Then call this validator from `validate_step6.py`.

## 5. Task D: Council packet requires memo

**文件:** `/Users/humphrey/projects/factor-factory/skills/factor-forge-step6/scripts/build_revision_council_packet.py`

Before writing packet:

1. Check memo JSON exists.
2. Run/inline validate memo.
3. If missing/invalid: BLOCK before packet write.

Add packet fields:

```json
{
  "main_agent_mechanism_memo_ref": "objects/research_iteration_master/main_agent_mechanism_memo__<report_id>.json",
  "main_agent_formula_component_map": [],
  "main_agent_math_hypothesis": {},
  "main_agent_evidence_comparison": {},
  "council_required_critiques": [
    "critique formula component mapping",
    "critique selected mathematical model",
    "critique payer derivation",
    "critique evidence contradictions",
    "propose revision or kill recommendation"
  ]
}
```

## 6. Task E: Agentic taskbook requires memo critique

**文件:** `/Users/humphrey/projects/factor-factory/skills/factor-forge-step6/scripts/build_agentic_council_taskbook.py`

For each agent task, add required input:

```json
"main_agent_mechanism_memo_ref": "objects/research_iteration_master/main_agent_mechanism_memo__<report_id>.json"
```

Required outputs include:

```json
{
  "main_agent_memo_agreement": "...",
  "model_selection_critique": "...",
  "component_mapping_critique": "...",
  "payer_derivation_critique": "...",
  "evidence_contradiction_review": "...",
  "revision_or_kill_recommendation": "..."
}
```

Task prompt text must say:

```text
Critique the main agent mechanism memo. Do not reconstruct from a generic family label.
```

## 7. Task F: Smoke

新增：

```text
/Users/humphrey/projects/factor-factory/scripts/run_main_agent_mechanism_memo_smoke.py
```

Cases:

```text
alpha030_main_agent_memo_pass
memo_missing_blocks_before_council_packet
generic_memo_blocks
correlation_claim_without_operator_blocks
sign_without_threshold_turnover_discussion_blocks
volume_ratio_without_participation_discussion_blocks
additive_rank_raw_ratio_without_commensurability_discussion_blocks
canonical_write_permission_blocks
execution_allowed_by_default_blocks
council_packet_requires_memo_ref
taskbook_requires_memo_critique
non_tmp_root_blocks
canonical_pollution_false
```

Smoke root must be `/tmp` only. Non-`/tmp` root must emit:

```text
BLOCK_NON_TMP_FACTORFORGE_ROOT
```

## 8. Task G: Alpha030 fresh regression

Run:

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
loop final_outcome = awaiting_agent_results, unless independently rejected/promoted earlier
Council effective_mode = agentic_dispatch_manifest when iterate
main_agent_mechanism_memo exists
Council packet references main_agent_mechanism_memo
taskbook requires memo critique
```

Content checks:

```text
memo has short_signed_price_state
memo has relative_volume_participation
memo has additive_score_combination
memo discusses sign discontinuity / threshold / turnover
memo discusses relative participation intensity
memo discusses scale / commensurability
memo does not claim rolling rank covariance/correlation unless explicitly justified
memo compares Step4 metrics and says current Alpha030 is not promotion-supported
```

## 9. Regression commands

Required:

```bash
python3 -m py_compile \
  factor_factory/mechanism_math/main_agent_memo.py \
  skills/factor-forge-step6/scripts/validate_main_agent_mechanism_memo.py \
  skills/factor-forge-step6/scripts/run_step6.py \
  skills/factor-forge-step6/scripts/validate_step6.py \
  skills/factor-forge-step6/scripts/build_revision_council_packet.py \
  skills/factor-forge-step6/scripts/build_agentic_council_taskbook.py \
  scripts/run_main_agent_mechanism_memo_smoke.py
```

```bash
python3 scripts/run_main_agent_mechanism_memo_smoke.py \
  --fresh \
  --root /tmp/factorforge_main_agent_mechanism_memo_phase_o2
```

```bash
python3 scripts/run_step12_hypothesis_contract_smoke.py \
  --fresh \
  --root /tmp/factorforge_step12_phase_o2_memo_regression
```

```bash
python3 scripts/run_mechanism_math_contract_smoke.py \
  --fresh \
  --root /tmp/factorforge_mechanism_math_phase_o2_memo_regression
```

```bash
python3 scripts/run_step6_intelligence_acceptance.py \
  --fresh \
  --root /tmp/factorforge_step6_intelligence_acceptance_phase_o2_memo
```

If Step6/Ultimate skills changed, sync installed copies and prove diff clean:

```bash
diff -qr -x __pycache__ \
  /Users/humphrey/projects/factor-factory/skills/factor-forge-step6 \
  /Users/humphrey/.codex/skills/factor-forge-step6

diff -qr -x __pycache__ \
  /Users/humphrey/projects/factor-factory/skills/factor-forge-ultimate \
  /Users/humphrey/.codex/skills/factor-forge-ultimate
```

## 10. Coder 回报格式

Return:

```text
Modified files:
- ...

New artifact:
- main_agent_mechanism_memo__<report_id>.json/md

Static behavior:
- Step6 writes memo before Council packet
- validate_step6 requires memo
- Council packet includes memo ref/content
- taskbook requires critique of memo

Smoke:
- main-agent memo smoke verdict/path
- key negative cases
- canonical pollution

Alpha030 fresh regression:
- report id
- loop proof path
- wrapper proof path
- final_outcome
- council effective_mode
- memo path
- packet/taskbook memo refs
- content checks

Regressions:
- Step12
- mechanism math
- Step6 intelligence acceptance
- installed diffs

Confirm not done:
- no clean data
- no search worker
- no official promotion
- no Step3B/Step4 performance change
- no real subagent API
```

