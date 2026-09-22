# Phase O P1C Positive Mechanism Modelling 任务说明书

> **执行对象:** Factor Factory coder thread  
> **审查对象:** reviewer thread  
> **架构依据:** `/Users/humphrey/projects/factor-factory/docs/operations/phase-o-p1c-positive-mechanism-modelling-architecture.zh-CN.md`  
> **目标:** 关闭 Phase O P1B review 的两个 P1 和一个 P2，让 Step1/Step2/Step6 走正向公式理解与经济到数学建模，而不是 Alpha019 特判或旧文本 keyword fallback。

## 0. 当前 BLOCK 证据

Review 已复现：

```python
from factor_factory.mechanism_math.classifier import infer_model_family

spec = {
    "canonical_spec": {
        "formula_text": "rank(delta(close, 20))",
        "required_inputs": ["close"],
        "operators": ["rank", "delta"],
    },
    "research_contract": {
        "economic_mechanism": "published formula may capture behavioral, liquidity, or microstructure effects embedded in ranked price-volume transformations"
    },
}

infer_model_family(spec)
```

当前错误输出：

```text
("price_volume_microstructure", ["price_volume_pressure_terms"], "medium")
```

这说明旧文本仍能把 price-only 公式污染成 price-volume mechanism。

同时，Step12 Alpha019 smoke artifact 里：

```text
factor_intuition = published formula may capture behavioral, liquidity, or microstructure effects embedded in ranked price-volume transformations
return_source_hypothesis = published formula may capture behavioral, liquidity, or microstructure effects embedded in ranked price-volume transformations
```

但 nested `economic_hypothesis` 已经是 slow winner / short threshold。顶层 thesis 和结构化 hypothesis 不一致。

## 1. 修改文件

必须修改：

```text
/Users/humphrey/projects/factor-factory/factor_factory/mechanism_math/formula_specific.py
/Users/humphrey/projects/factor-factory/factor_factory/mechanism_math/classifier.py
/Users/humphrey/projects/factor-factory/scripts/step12_intake_common.py
/Users/humphrey/projects/factor-factory/scripts/run_step12_hypothesis_contract_smoke.py
/Users/humphrey/projects/factor-factory/scripts/run_mechanism_math_contract_smoke.py
```

按需要修改：

```text
/Users/humphrey/projects/factor-factory/skills/factor-forge-step2/scripts/run_step2.py
/Users/humphrey/projects/factor-factory/skills/factor-forge-step6/scripts/run_step6.py
/Users/humphrey/projects/factor-factory/skills/factor-forge-step6/scripts/validate_step6.py
/Users/humphrey/projects/factor-factory/skills/factor-forge-step2/SKILL.md
/Users/humphrey/projects/factor-factory/skills/factor-forge-step6/SKILL.md
/Users/humphrey/projects/factor-factory/skills/factor-forge-ultimate/SKILL.md
```

不要修改：

```text
Step3B / Step4 performance path
data/clean
official library writeback
search worker
promotion gate
```

## 2. Task A: 新增 formula-specific headline builder

**文件:** `/Users/humphrey/projects/factor-factory/factor_factory/mechanism_math/formula_specific.py`

新增函数：

```python
def build_formula_specific_headline(
    economic_hypothesis: dict[str, Any],
    math_selection: dict[str, Any],
    formula_understanding: dict[str, Any],
) -> str:
    second = economic_hypothesis.get("second_layer") if isinstance(economic_hypothesis, dict) else {}
    subtype = str((second or {}).get("subtype") or "").strip()
    payer = str((second or {}).get("expected_counterparty_or_payer") or "").strip()
    why_pay = str((second or {}).get("why_they_may_pay") or "").strip()
    interaction = str((formula_understanding or {}).get("interaction_structure") or "").strip()
    model_family = str((math_selection or {}).get("model_family") or (math_selection or {}).get("selected_baseline_model") or "").strip()

    if interaction == "slow_state_x_short_horizon_threshold":
        return (
            "Formula estimates a slow winner state interacting with short-horizon pullback and sign-threshold migration; "
            f"expected payoff comes from {payer or 'trend extrapolators or delayed updaters'} because "
            f"{why_pay or 'they react late to conditional state migration'}; selected math model is "
            f"{model_family or 'stochastic_process'}."
        )
    if subtype and why_pay:
        return f"Formula-specific thesis: {subtype}; payer: {payer}; why they may pay: {why_pay}; selected math model: {model_family or 'under review'}."
    return "Formula-specific thesis remains under-specified and must be resolved by Step1/Step2 mechanism modelling before promotion."
```

要求：

- 不要返回 generic `ranked price-volume transformations`。
- 不要把此函数写成 Alpha019-only；Alpha019 只是一个特定 branch。
- 如果缺字段，返回 under-specified thesis，让 validator/smoke 能发现，而不是回退到旧 price-volume 文本。

## 3. Task B: Step1 headline thesis 使用 formula-specific modelling

**文件:** `/Users/humphrey/projects/factor-factory/scripts/step12_intake_common.py`

修改 `build_canonical_formula_step1()`：

1. `common_research_discipline(...)` 可以继续接收 legacy fallback text，但不能再直接用于 `factor_intuition` / `return_source_hypothesis`。
2. `hypotheses = canonical_formula_hypotheses(...)` 后，基于 `economic_hypothesis`、`economic_to_math_modelling.selected_baseline_model`、`formula_understanding` 生成 `formula_headline`。
3. 写入：

```python
formula_headline = build_formula_specific_headline(
    research.get("economic_hypothesis") or {},
    (research.get("economic_to_math_modelling") or {}).get("selected_baseline_model") or {},
    research.get("formula_understanding") or {},
)
```

然后替换：

```python
"factor_intuition": formula_headline,
"return_source_hypothesis": formula_headline,
...
"final_factor": {
    ...
    "economic_logic": formula_headline,
}
```

`primary["economic_logic"]` 也应使用 `formula_headline`。

验收：

Alpha019-like Step1 artifact 中以下字段都不得包含 `price-volume`：

```text
factor_intuition
return_source_hypothesis
final_factor.economic_logic
report_map_validation.economic_logic
```

除非公式实际包含 formula-derived volume/amount/turnover 且 model selection 选择 price-volume。

## 4. Task C: 重写 Step2 classifier 的模型选择优先级

**文件:** `/Users/humphrey/projects/factor-factory/factor_factory/mechanism_math/classifier.py`

当前问题位于：

```python
if selected.get("model_family") == "stochastic_process" and interaction == "slow_state_x_short_horizon_threshold":
    return ...
...
has_volume = bool(inputs & VOLUME_INPUT_FIELDS) or _contains_field_token(text, VOLUME_INPUT_FIELDS)
```

修改要求：

1. 新增 normalization helper：

```python
def normalize_selected_model_family(model_family: str, formula_understanding: dict[str, Any]) -> str:
    raw = (model_family or "").strip()
    if raw in {"stochastic_process", "valuation_identity", "linear_factor_projection", "functional_filter", "cross_sectional_statistics", "constraint_model", "price_volume_microstructure"}:
        return raw
    if raw in {"ranked_price_state_process", "canonical_formula_state_process"}:
        return "stochastic_process"
    if raw == "ranked_price_volume_state_process":
        features = (formula_understanding or {}).get("formula_features") or {}
        if features.get("has_volume") is True:
            return "price_volume_microstructure"
        return "stochastic_process"
    return "other"
```

2. 在 `infer_model_family()` 中，`select_math_model_from_economic_hypothesis(...)` 后，先采用明确 selected model：

```python
normalized = normalize_selected_model_family(str(selected.get("model_family") or selected.get("selected_baseline_model") or ""), formula_understanding if isinstance(formula_understanding, dict) else {})
if normalized != "other":
    interaction = (formula_understanding or {}).get("interaction_structure")
    evidence = [f"step1_economic_to_math_modelling:{normalized}"]
    if interaction:
        evidence.append(f"formula_understanding:{interaction}")
    return normalized, evidence, "low"
```

3. fallback 阶段的 `has_price` / `has_volume` 必须只来自 formula-derived fields：

```python
formula_features = (formula_understanding or {}).get("formula_features") if isinstance(formula_understanding, dict) else {}
formula_fields = {str(item).lower() for item in (formula_features or {}).get("fields", [])}
if not formula_fields:
    formula_fields = {item.lower() for item in _observable_inputs(spec_like)}
has_price = bool(formula_fields & PRICE_INPUT_FIELDS)
has_volume = bool(formula_fields & VOLUME_INPUT_FIELDS)
```

4. `_contains_field_token(text, VOLUME_INPUT_FIELDS)` 不能再让 `has_volume=True`。如果仍要保留 text fallback，只能作为 `text_mentions_volume` 进入 evidence，不得作为 observable field。

验收反例：

```python
rank(delta(close, 20)) + stale price-volume text
```

不得返回 `price_volume_microstructure`。

## 5. Task D: Smoke 增加两个必测项

### D1. Step12 headline consistency

**文件:** `/Users/humphrey/projects/factor-factory/scripts/run_step12_hypothesis_contract_smoke.py`

新增 case：

```text
alpha019_headline_formula_specific_no_generic_price_volume
```

检查：

```python
headline_blob = json.dumps({
    "factor_intuition": alpha019_aim.get("factor_intuition"),
    "return_source_hypothesis": alpha019_aim.get("return_source_hypothesis"),
    "final_factor_economic_logic": (alpha019_aim.get("final_factor") or {}).get("economic_logic"),
}, ensure_ascii=False).lower()

case_ok = (
    "slow" in headline_blob
    and ("threshold" in headline_blob or "short-horizon" in headline_blob)
    and "price-volume" not in headline_blob
)
```

### D2. Non-Alpha019 polluted text classifier guard

**文件:** `/Users/humphrey/projects/factor-factory/scripts/run_mechanism_math_contract_smoke.py`

新增 case：

```text
price_only_formula_stale_price_volume_text_not_microstructure
```

构造：

```python
spec = {
    "canonical_spec": {
        "formula_text": "rank(delta(close, 20))",
        "required_inputs": ["close"],
        "operators": ["rank", "delta"],
    },
    "research_contract": {
        "economic_mechanism": "published formula may capture behavioral, liquidity, or microstructure effects embedded in ranked price-volume transformations",
        "economic_hypothesis": {
            "macro_return_source": "mixed",
            "second_layer": {
                "subtype": "short_horizon_price_state_reversal_or_continuation",
                "expected_counterparty_or_payer": "investors extrapolating recent price states",
                "why_they_may_pay": "recent price states may contain temporary impact or behavioral extrapolation"
            }
        },
        "math_hypothesis_candidates": [
            {
                "model_family": "ranked_price_state_process",
                "state_or_object": "cross-sectional security-day price state",
                "process_or_distribution_hypothesis": "conditional drift depends on ranked recent price movement",
                "observable_estimator": "rank(delta(close,20))",
                "target_functional": "E[r_i,t+1 | price_state_i,t]",
                "why_suitable": "formula uses only price-state fields"
            }
        ]
    }
}
```

期望：

```python
contract = build_mechanism_math_contract(spec)
assert contract["model_family"] != "price_volume_microstructure"
assert contract["formula_understanding"]["formula_features"]["has_volume"] is False
```

建议期望 family 为 `stochastic_process`。

## 6. Task E: 复跑 Alpha019 fresh report

完成代码和 smoke 后，使用新的 fresh report id，不复用旧 artifact：

```bash
python3 scripts/run_factorforge_ultimate_loop.py \
  --report-id ALPHA019_CANONICAL_FORMULA_20160101_AGENTIC_AUTO_RETEST_P1C_<YYYYMMDDHHMM> \
  --start-step 2 \
  --max-loops 10 \
  --council-mode auto
```

验收：

```text
status = PAUSED or PASS
final_outcome = awaiting_agent_results
stop_reason = revision_council_awaiting_agent_results
wrapper proof status = PASS
revision_council.effective_mode = agentic_dispatch_manifest
mechanism_formula_consistency.status = PASS
```

并检查：

```text
Step1 factor_intuition 不含旧 generic price-volume thesis
Step1 return_source_hypothesis 不含旧 generic price-volume thesis
Step2 mechanism_math_contract.model_family = stochastic_process
Council packet/taskbook 携带 formula_understanding / economic_to_math modelling
```

## 7. 验证命令

必须跑：

```bash
python3 -m py_compile \
  factor_factory/mechanism_math/formula_specific.py \
  factor_factory/mechanism_math/classifier.py \
  scripts/step12_intake_common.py \
  scripts/run_step12_hypothesis_contract_smoke.py \
  scripts/run_mechanism_math_contract_smoke.py
```

```bash
python3 scripts/run_step12_hypothesis_contract_smoke.py \
  --fresh \
  --root /tmp/factorforge_step12_phase_o_p1c_positive_modelling
```

```bash
python3 scripts/run_mechanism_math_contract_smoke.py \
  --fresh \
  --root /tmp/factorforge_mechanism_math_phase_o_p1c_positive_modelling
```

```bash
python3 scripts/run_step6_intelligence_smoke.py \
  --fresh \
  --root /tmp/factorforge_step6_intelligence_phase_o_p1c_positive_modelling
```

```bash
python3 scripts/run_step6_intelligence_acceptance.py \
  --fresh \
  --root /tmp/factorforge_step6_intelligence_acceptance_phase_o_p1c_positive_modelling
```

如修改 Ultimate/Step6 installed skill：

```bash
diff -qr -x __pycache__ \
  /Users/humphrey/projects/factor-factory/skills/factor-forge-step6 \
  /Users/humphrey/.codex/skills/factor-forge-step6

diff -qr -x __pycache__ \
  /Users/humphrey/projects/factor-factory/skills/factor-forge-ultimate \
  /Users/humphrey/.codex/skills/factor-forge-ultimate
```

## 8. 回报格式

Coder 完成后回报必须包含：

```text
Modified files:
- ...

Static behavior:
- formula fields are formula-derived only
- classifier selected model precedence
- Step1 headline thesis source

Smoke:
- Step12 verdict/path
- mechanism math verdict/path
- Step6 intelligence smoke verdict/path
- acceptance token

Alpha019 fresh retest:
- report id
- loop proof path
- wrapper proof path
- final_outcome
- council status/effective mode
- mechanism_formula_consistency.status
- Step1 headline no generic price-volume

Sync:
- installed skill diffs, if touched

Confirm not done:
- no clean data
- no search worker
- no official promotion
- no Step3B/Step4 performance change
```

