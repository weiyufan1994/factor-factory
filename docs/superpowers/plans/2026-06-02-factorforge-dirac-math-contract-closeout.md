# Factor Forge Dirac Math Contract Closeout Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Upgrade Factor Forge mechanism research so every Step1/2/6 factor judgment is anchored to a classified research equation, a formula-implied latent state, a T+0/T+1 stochastic benchmark projection, model-linked metrics, and drawdown-geometry financial diagnostics.

**Architecture:** Preserve the existing `mechanism_math_contract_v2` and extend it rather than replacing it. The main model is selected from the economic hypothesis, while stochastic price-process projection is a required benchmark layer for T+0/T+1 or short-horizon market-price implications. Step6 must interpret metrics against model layers and factor financial economics, not just IC/backtest output.

**Tech Stack:** Python 3, Factor Forge mechanism math package under `factor_factory/mechanism_math`, Step1/Step2/Step6 skills, Step4/Step6 diagnostics, JSON artifacts, smoke scripts under `scripts/`.

---

## Required Branch Discipline

Use a clean worktree. Do not implement in a dirty local branch.

Recommended setup:

```bash
cd /Users/humphrey/projects/factor-factory
git fetch origin
git worktree add /tmp/factorforge-dirac-math-closeout origin/main
cd /tmp/factorforge-dirac-math-closeout
git switch -c codex/factorforge-dirac-math-contract-closeout
```

## Hard Boundaries

Do not modify:

- Step3/Step4 high-performance compute paths, except where Step4 metrics output needs drawdown geometry fields.
- Data API package boundaries or clean-data generation.
- Raw market data, S3 data, research artifacts from prior formal runs, or generated raw LLM JSON.
- Portfolio construction rules, long-only mandate, or Step5/6 promotion thresholds unless explicitly required by this plan.
- EC2/OpenClaw control-plane scripts.

Do not claim completion unless:

- validators reject bad contracts;
- smoke tests include both positive and negative cases;
- existing mechanism math v2 smoke still passes;
- Step6 outputs include model-layer linkage and drawdown-geometry fields when inputs are available.

---

## Files Map

Likely modified files:

- `factor_factory/mechanism_math/schema.py`
  - Add research equation statuses, T+0/T+1 stochastic benchmark schema constants, anomaly classification constants, and drawdown geometry field names.
- `factor_factory/mechanism_math/classifier.py`
  - Extend `build_mechanism_math_contract_v2()` with `research_equation`, `t0_t1_stochastic_benchmark`, and richer formula-implied review defaults.
- `factor_factory/mechanism_math/validator.py`
  - Validate research equation classification, assumptions, validity scope, stochastic benchmark, formula-implied anomaly review, and non-generic field content.
- `factor_factory/mechanism_math/formula_specific.py`
  - Extend formula/operator consistency checks so absent-input mechanism claims and generic equations are blocked.
- `factor_factory/mechanism_math/equation_quality.py`
  - Score and validate proposed strict identities, constraint equations, behavioral feedback equations, empirical invariances, and research conjectures before they can be used as factor foundations.
- `factor_factory/mechanism_math/factor_discovery_queue.py`
  - Materialize a reviewed queue from research equations to observable detector candidates and branch seeds without running Step3/4 automatically.
- `skills/factor-forge-step1/SKILL.md`
- `skills/factor-forge-step1/references/prompts.md`
- `skills/factor-forge-step2/SKILL.md`
- `skills/factor-forge-step2/references/prompts.md`
  - Update prompts to require research equation level and T+0/T+1 stochastic benchmark as distinct from primary model.
- `skills/factor-forge-step6/references/prompts.md`
  - Add Step6 reviewer/Council prompts for equation quality, stochastic benchmark, metric linkage, anomaly review, and discovery queue output.
- `skills/factor-forge-step6/SKILL.md`
  - Update Step6 requirements for research equation reviewer, T+0/T+1 stochastic benchmark, Dirac-style anomaly review, and drawdown geometry.
- `skills/factor-forge-step6/scripts/run_step6.py`
  - Add research equation fields to mechanism analysis and add drawdown geometry to factor business review.
- `skills/factor-forge-step6/scripts/validate_step6.py`
  - Enforce model-linked metrics plus research equation linkage.
- `factor_factory/revision_council/validator.py`
  - Enforce Council anomaly branch-law and research equation fields for revision proposals.
- `scripts/run_factorforge_mechanism_math_v2_smoke.py`
  - Add negative and positive contract cases for new rules.
- `scripts/run_factorforge_dirac_discovery_smoke.py`
  - Add smoke tests for equation quality scoring and equation-to-detector candidate generation.
- `scripts/run_factorforge_prompt_contract_smoke.py`
  - Verify Step1/Step2/Step6 prompt references contain required Dirac-style prompt blocks, required field names, and anti-pattern bans.
- `scripts/run_main_agent_mechanism_memo_smoke.py`
  - Add main-agent memo cases for research equation and stochastic benchmark.
- `scripts/run_step6_intelligence_acceptance.py`
  - Add acceptance cases for drawdown geometry and model-layer metric linkage.
- `docs/operations/factorforge-dirac-style-research-contract.zh-CN.md`
  - Keep architecture reference updated with the implemented field names.

Avoid changing unless tests prove necessary:

- `skills/factor-forge-step3/`
- `factor_factory/data_api/`
- `factor_factory/data_access/`
- `scripts/run_factorforge_performance_smoke.py`

---

### Task 1: Research Equation Contract

**Objective:** Add a classified `research_equation` object to `mechanism_math_contract_v2` so every factor states whether its structure is a strict identity, institutional constraint, behavioral feedback equation, empirical invariance, or research conjecture.

**Boundary:** This task defines the research contract. It does not change Step3/4 execution, Data API behavior, or promotion gates.

**Files:**
- Modify: `factor_factory/mechanism_math/schema.py`
- Modify: `factor_factory/mechanism_math/classifier.py`
- Modify: `factor_factory/mechanism_math/validator.py`
- Modify: `scripts/run_factorforge_mechanism_math_v2_smoke.py`
- Modify: `docs/operations/factorforge-dirac-style-research-contract.zh-CN.md`

- [ ] **Step 1: Add schema constants**

In `factor_factory/mechanism_math/schema.py`, add:

```python
VALID_RESEARCH_EQUATION_STATUSES = {
    "strict_identity",
    "institutional_constraint",
    "behavioral_feedback",
    "empirical_invariance",
    "research_conjecture",
}

VALID_SYMMETRY_BREAKING_TYPES = {
    "none",
    "institutional_constraint",
    "liquidity_constraint",
    "behavioral_bias",
    "information_delay",
    "funding_pressure",
    "inventory_pressure",
    "market_microstructure_friction",
    "capacity_or_crowding",
    "regime_shift",
    "other",
}

REQUIRED_RESEARCH_EQUATION_FIELDS = [
    "equation_text",
    "equation_status",
    "assumptions",
    "validity_scope",
    "symmetry_or_constraint",
    "symmetry_breaking_mechanism",
    "latent_state",
    "observable_estimator",
    "expected_metric_signature",
    "falsification_tests",
    "kill_criteria",
]
```

- [ ] **Step 2: Add RED smoke cases**

In `scripts/run_factorforge_mechanism_math_v2_smoke.py`, add cases:

```text
missing_research_equation_blocks
research_equation_unknown_status_blocks
research_equation_missing_validity_scope_blocks
research_equation_generic_text_blocks
strict_identity_without_identity_language_blocks
behavioral_feedback_without_assumptions_blocks
valid_research_equation_passes
```

Expected failure tokens:

```text
BLOCK_MECHANISM_MATH_V2_RESEARCH_EQUATION_MISSING
BLOCK_MECHANISM_MATH_V2_RESEARCH_EQUATION_INVALID
```

- [ ] **Step 3: Extend classifier defaults**

In `factor_factory/mechanism_math/classifier.py`, add a helper:

```python
def _research_equation(v1: dict[str, Any], research_contract: dict[str, Any], formula_estimator: str) -> dict[str, Any]:
    family = str(v1.get("model_family") or "")
    if family in {"valuation_identity"}:
        status = "strict_identity"
        symmetry = "cash-flow or valuation identity"
    elif family in {"price_volume_microstructure"}:
        status = "empirical_invariance"
        symmetry = "market-impact or liquidity response relation"
    elif family in {"constraint_model"}:
        status = "institutional_constraint"
        symmetry = "participant or institutional constraint"
    else:
        status = "research_conjecture"
        symmetry = "report-specific conditional return relation"
    return {
        "equation_text": str(v1.get("process_hypothesis") or "observable_factor_t = estimator(latent_state_t, F_t) + measurement_noise_t"),
        "equation_status": status,
        "assumptions": research_contract.get("assumptions") or [
            "The estimated latent state changes the conditional distribution of next-horizon returns."
        ],
        "validity_scope": {
            "market": str(research_contract.get("market") or "report_scope"),
            "frequency": str(research_contract.get("frequency") or "report_horizon"),
            "regime": str(research_contract.get("regime") or "under_specified"),
            "participant_structure": str(research_contract.get("participant_structure") or "under_specified"),
        },
        "symmetry_or_constraint": symmetry,
        "symmetry_breaking_mechanism": str(v1.get("economic_mechanism") or "report-specific mechanism"),
        "latent_state": str(v1.get("latent_state") or v1.get("state_or_object") or "latent return-process state"),
        "observable_estimator": formula_estimator,
        "expected_metric_signature": v1.get("expected_metric_signature") or ["rank IC and long-side return should match the declared sign"],
        "falsification_tests": v1.get("falsification_tests") or ["Falsify if metrics do not support the estimated latent state."],
        "kill_criteria": v1.get("kill_criteria") or ["Kill if no formula-mappable latent state remains."],
    }
```

Call it from `build_mechanism_math_contract_v2()` and write the returned object at top-level key `research_equation`.

- [ ] **Step 4: Implement validator**

In `factor_factory/mechanism_math/validator.py`, add `_validate_research_equation(contract)` and call it from `validate_mechanism_math_contract_v2()`.

Rules:

```text
research_equation must be a nonempty dict
all REQUIRED_RESEARCH_EQUATION_FIELDS must exist
equation_status must be in VALID_RESEARCH_EQUATION_STATUSES
assumptions, expected_metric_signature, falsification_tests, kill_criteria must be nonempty lists
validity_scope must include market, frequency, regime, participant_structure
equation_text must not be generic placeholder text only
strict_identity must mention identity, accounting, clearing, SDF, Euler, cash-flow, balance-sheet, or no-arbitrage
behavioral_feedback must include at least one explicit assumption and one falsification test
empirical_invariance must include validity_scope and falsification_tests
research_conjecture must not be eligible for promotion unless Step6 evidence later supports it
```

- [ ] **Step 5: Run verification**

```bash
python3 -m py_compile \
  factor_factory/mechanism_math/schema.py \
  factor_factory/mechanism_math/classifier.py \
  factor_factory/mechanism_math/validator.py \
  scripts/run_factorforge_mechanism_math_v2_smoke.py
python3 scripts/run_factorforge_mechanism_math_v2_smoke.py
```

Expected:

```text
"verdict": "ACCEPT"
"case": "missing_research_equation_blocks"
"ok": true
"case": "valid_research_equation_passes"
"ok": true
```

- [ ] **Step 6: Commit**

```bash
git add \
  factor_factory/mechanism_math/schema.py \
  factor_factory/mechanism_math/classifier.py \
  factor_factory/mechanism_math/validator.py \
  scripts/run_factorforge_mechanism_math_v2_smoke.py \
  docs/operations/factorforge-dirac-style-research-contract.zh-CN.md
git commit -m "Add Factor Forge research equation contract"
```

---

### Task 2: T+0/T+1 Stochastic Benchmark Projection

**Objective:** Keep primary model selection flexible while making stochastic price-process projection a required benchmark layer for T+0/T+1 and short-horizon factors.

**Boundary:** Do not force all factors to use stochastic process as the primary model. The stochastic layer is a diagnostic/projection layer, especially useful when the primary economic model cannot derive return-distribution implications directly.

**Files:**
- Modify: `factor_factory/mechanism_math/schema.py`
- Modify: `factor_factory/mechanism_math/classifier.py`
- Modify: `factor_factory/mechanism_math/validator.py`
- Modify: `skills/factor-forge-step1/SKILL.md`
- Modify: `skills/factor-forge-step1/references/prompts.md`
- Modify: `skills/factor-forge-step2/SKILL.md`
- Modify: `skills/factor-forge-step2/references/prompts.md`
- Modify: `skills/factor-forge-step6/SKILL.md`
- Modify: `scripts/run_factorforge_mechanism_math_v2_smoke.py`

- [ ] **Step 1: Add benchmark schema**

In `schema.py`, add:

```python
VALID_T0_T1_PRICE_PROCESS_TERMS = {
    "drift",
    "diffusion",
    "jump",
    "friction",
    "regime_transition",
    "observation_equation",
}

REQUIRED_T0_T1_BENCHMARK_FIELDS = [
    "benchmark_required",
    "horizon",
    "affected_terms",
    "conditional_distribution_claim",
    "benchmark_implication",
    "when_primary_model_cannot_infer",
    "falsification_tests",
]
```

- [ ] **Step 2: Add RED smoke cases**

Add to `scripts/run_factorforge_mechanism_math_v2_smoke.py`:

```text
missing_t0_t1_stochastic_benchmark_blocks
t0_t1_benchmark_without_affected_terms_blocks
t0_t1_generic_benchmark_blocks
primary_non_stochastic_with_valid_benchmark_passes
```

Expected tokens:

```text
BLOCK_MECHANISM_MATH_V2_T0_T1_BENCHMARK_MISSING
BLOCK_MECHANISM_MATH_V2_T0_T1_BENCHMARK_INVALID
```

- [ ] **Step 3: Extend classifier output**

In `build_mechanism_math_contract_v2()`, add top-level:

```json
"t0_t1_stochastic_benchmark": {
  "benchmark_required": true,
  "horizon": "T+0/T+1 or report horizon",
  "affected_terms": ["drift", "diffusion", "friction"],
  "conditional_distribution_claim": "r_{t+h} | F_t, estimated_state_t changes in the declared direction",
  "benchmark_implication": "The estimated state must shift next-horizon return distribution enough to survive turnover and risk drag.",
  "when_primary_model_cannot_infer": "Use this stochastic projection as a benchmark diagnostic, not as the primary model.",
  "falsification_tests": ["Falsify if the conditional return distribution does not change after controlling for implementation and turnover."]
}
```

Choose `affected_terms` from the existing family:

```text
behavioral/constraint model -> drift, friction, regime_transition
microstructure/inventory model -> friction, observation_equation, jump
valuation model -> drift
tail/jump model -> jump, diffusion
```

- [ ] **Step 4: Implement validator**

Rules:

```text
t0_t1_stochastic_benchmark must exist
benchmark_required must be true unless the contract explicitly marks the factor non-price-producing with proof
horizon must mention T+0, T+1, short_horizon, or report_horizon
affected_terms must be nonempty and within VALID_T0_T1_PRICE_PROCESS_TERMS
conditional_distribution_claim, benchmark_implication, and when_primary_model_cannot_infer must be meaningful
falsification_tests must be nonempty
Generic dS = mu S dt + sigma S dW text alone is invalid
```

- [ ] **Step 5: Update prompts and skills**

Update Step1/Step2/Step6 skills and prompt references with this rule:

```text
Do not default every factor to a stochastic process as the primary model. However, because the traded object is a stock price, every price-predictive factor must include a T+0/T+1 stochastic benchmark projection explaining whether the observable estimator affects drift, diffusion, jump, friction, regime transition, or observation equation.
```

- [ ] **Step 6: Run verification**

```bash
python3 -m py_compile \
  factor_factory/mechanism_math/schema.py \
  factor_factory/mechanism_math/classifier.py \
  factor_factory/mechanism_math/validator.py \
  scripts/run_factorforge_mechanism_math_v2_smoke.py
python3 scripts/run_factorforge_mechanism_math_v2_smoke.py
```

Expected:

```text
"verdict": "ACCEPT"
"case": "primary_non_stochastic_with_valid_benchmark_passes"
"ok": true
```

- [ ] **Step 7: Commit**

```bash
git add \
  factor_factory/mechanism_math/schema.py \
  factor_factory/mechanism_math/classifier.py \
  factor_factory/mechanism_math/validator.py \
  skills/factor-forge-step1/SKILL.md \
  skills/factor-forge-step1/references/prompts.md \
  skills/factor-forge-step2/SKILL.md \
  skills/factor-forge-step2/references/prompts.md \
  skills/factor-forge-step6/SKILL.md \
  scripts/run_factorforge_mechanism_math_v2_smoke.py
git commit -m "Add T0 T1 stochastic benchmark projection"
```

---

### Task 3: Step6 Research Equation Reviewer And Metric Linkage

**Objective:** Make Step6 and Council explicitly review whether metrics support the research equation, not only the existing model-layer chain.

**Boundary:** This task changes Step6 analysis and validation, not Step4 computation or portfolio rules.

**Files:**
- Modify: `skills/factor-forge-step6/SKILL.md`
- Modify: `skills/factor-forge-step6/scripts/run_step6.py`
- Modify: `skills/factor-forge-step6/scripts/validate_step6.py`
- Modify: `factor_factory/revision_council/validator.py`
- Modify: `scripts/run_factorforge_mechanism_math_v2_smoke.py`
- Modify: `scripts/run_main_agent_mechanism_memo_smoke.py`
- Modify: `scripts/run_step6_intelligence_acceptance.py`

- [ ] **Step 1: Add research equation reviewer to Step6 outputs**

In `run_step6.py`, add to `mechanism_analysis`:

```json
{
  "research_equation_review": {
    "reviewer_task": "research_equation_reviewer",
    "equation_status": "",
    "equation_supported_by_metrics": "supported|challenged|under_specified",
    "metric_links": {
      "rank_ic": "",
      "long_side_return": "",
      "cost_adjusted_return": "",
      "turnover": "",
      "volatility_drag": "",
      "max_drawdown": "",
      "recovery_days": ""
    },
    "failed_equation_component": "none|assumptions|latent_state|observable_estimator|price_process_projection|implementation_contract|trading_cost|drawdown_geometry",
    "revision_implication": ""
  }
}
```

- [ ] **Step 2: Add RED validation cases**

Add to `scripts/run_factorforge_mechanism_math_v2_smoke.py` or `scripts/run_step6_intelligence_acceptance.py`:

```text
step6_missing_research_equation_review_blocks
step6_research_equation_metrics_generic_blocks
step6_research_equation_valid_linkage_passes
```

Expected token:

```text
BLOCK_STEP6_RESEARCH_EQUATION_NOT_LINKED_TO_METRICS
```

- [ ] **Step 3: Extend validate_step6.py**

Add validation:

```text
mechanism_analysis.research_equation_review must exist
reviewer_task must equal research_equation_reviewer
equation_status must match mechanism_math_contract_v2.research_equation.equation_status
equation_supported_by_metrics must be supported/challenged/under_specified
metric_links must include rank_ic, long_side_return, cost_adjusted_return, turnover, volatility_drag, max_drawdown, recovery_days
failed_equation_component must be from the allowed set
generic text such as "metrics support the model" is not enough
```

- [ ] **Step 4: Extend Council proposal validator**

In `factor_factory/revision_council/validator.py`, require Council proposals to include:

```json
"research_equation_revision": {
  "equation_component_target": "assumptions|latent_state|observable_estimator|price_process_projection|implementation_contract|trading_cost|drawdown_geometry",
  "equation_change": "",
  "expected_metric_signature_change": [],
  "falsification_tests": []
}
```

If a Council proposal has anomaly branch law but no research equation revision target, block:

```text
BLOCK_COUNCIL_RESEARCH_EQUATION_REVISION_MISSING
```

- [ ] **Step 5: Run verification**

```bash
python3 -m py_compile \
  skills/factor-forge-step6/scripts/run_step6.py \
  skills/factor-forge-step6/scripts/validate_step6.py \
  factor_factory/revision_council/validator.py \
  scripts/run_factorforge_mechanism_math_v2_smoke.py \
  scripts/run_main_agent_mechanism_memo_smoke.py \
  scripts/run_step6_intelligence_acceptance.py
python3 scripts/run_factorforge_mechanism_math_v2_smoke.py
python3 scripts/run_main_agent_mechanism_memo_smoke.py
python3 scripts/run_step6_intelligence_acceptance.py
```

Expected:

```text
mechanism math v2 smoke: verdict=ACCEPT
main agent mechanism memo smoke: ACCEPT or zero failed cases
step6 intelligence acceptance: PASS or zero failed cases
```

- [ ] **Step 6: Commit**

```bash
git add \
  skills/factor-forge-step6/SKILL.md \
  skills/factor-forge-step6/scripts/run_step6.py \
  skills/factor-forge-step6/scripts/validate_step6.py \
  factor_factory/revision_council/validator.py \
  scripts/run_factorforge_mechanism_math_v2_smoke.py \
  scripts/run_main_agent_mechanism_memo_smoke.py \
  scripts/run_step6_intelligence_acceptance.py
git commit -m "Link Step6 metrics to research equations"
```

---

### Task 4: Drawdown Geometry Metrics

**Objective:** Add drawdown area and recovery pain area to Factor Forge financial evaluation so max drawdown is not treated as a single-point statistic.

**Boundary:** Do not change portfolio construction or backtest engine behavior. This task only computes and consumes metrics from NAV/return series already produced by Step4/self-quant/qlib.

**Files:**
- Modify: `skills/factor-forge-step4/scripts/self_quant_adapter.py`
- Modify: `skills/factor-forge-step4/scripts/run_step4.py`
- Modify: `skills/factor-forge-step6/scripts/run_step6.py`
- Modify: `scripts/run_step6_intelligence_acceptance.py`
- Create if useful: `factor_factory/risk/drawdown_geometry.py`

- [ ] **Step 1: Create drawdown utility**

Create `factor_factory/risk/drawdown_geometry.py`:

```python
from __future__ import annotations

from typing import Iterable, Any

import math


def _to_float_list(values: Iterable[Any]) -> list[float]:
    out: list[float] = []
    for value in values:
        try:
            x = float(value)
        except Exception:
            continue
        if math.isfinite(x):
            out.append(x)
    return out


def drawdown_geometry(nav_values: Iterable[Any]) -> dict[str, float | int | None]:
    nav = _to_float_list(nav_values)
    if not nav:
        return {
            "drawdown_area": None,
            "normalized_drawdown_area": None,
            "max_drawdown_episode_area": None,
            "recovery_pain_area": None,
            "max_drawdown": None,
            "recovery_days": None,
            "episode_count": 0,
        }

    high = nav[0]
    underwater: list[float] = []
    max_dd = 0.0
    trough_idx = 0
    high_idx_at_trough = 0
    current_episode_area = 0.0
    max_episode_area = 0.0
    episode_count = 0
    in_episode = False
    episode_start = 0
    trough_in_episode = 0
    recovery_days = None
    recovery_pain_area = None

    for idx, value in enumerate(nav):
        if value >= high:
            if in_episode:
                max_episode_area = max(max_episode_area, current_episode_area)
                if trough_in_episode == trough_idx and recovery_days is None:
                    recovery_days = idx - trough_idx
                    recovery_pain_area = sum(underwater[trough_idx:idx + 1])
                current_episode_area = 0.0
                in_episode = False
            high = value
            depth = 0.0
        else:
            depth = (high - value) / high if high else 0.0
            if not in_episode:
                in_episode = True
                episode_count += 1
                episode_start = idx
                trough_in_episode = idx
            current_episode_area += depth
            if depth > abs(max_dd):
                max_dd = -depth
                trough_idx = idx
                high_idx_at_trough = episode_start
                trough_in_episode = idx
        underwater.append(depth)

    if in_episode:
        max_episode_area = max(max_episode_area, current_episode_area)
        if trough_idx >= high_idx_at_trough and recovery_days is None:
            recovery_days = None
            recovery_pain_area = sum(underwater[trough_idx:])

    area = float(sum(underwater))
    return {
        "drawdown_area": area,
        "normalized_drawdown_area": area / len(underwater) if underwater else None,
        "max_drawdown_episode_area": float(max_episode_area),
        "recovery_pain_area": float(recovery_pain_area) if recovery_pain_area is not None else None,
        "max_drawdown": float(max_dd),
        "recovery_days": recovery_days,
        "episode_count": episode_count,
    }
```

- [ ] **Step 2: Add RED unit/smoke case**

Add a case in `scripts/run_step6_intelligence_acceptance.py`:

```text
drawdown_geometry_area_computes_expected_values
```

Use NAV:

```python
[1.0, 1.1, 1.0, 0.9, 1.1, 1.2]
```

Expected:

```text
drawdown_area > 0
normalized_drawdown_area > 0
max_drawdown_episode_area > 0
recovery_pain_area > 0
episode_count == 1
```

- [ ] **Step 3: Wire Step4/self-quant output**

Where long-side NAV is available in `self_quant_adapter.py` or `run_step4.py`, compute:

```python
from factor_factory.risk.drawdown_geometry import drawdown_geometry

geometry = drawdown_geometry(long_side_nav_values)
long_side_performance.update({
    "long_side_drawdown_area": geometry["drawdown_area"],
    "long_side_normalized_drawdown_area": geometry["normalized_drawdown_area"],
    "long_side_max_drawdown_episode_area": geometry["max_drawdown_episode_area"],
    "long_side_recovery_pain_area": geometry["recovery_pain_area"],
})
```

If only cost-adjusted NAV is available, write the cost-adjusted names:

```text
cost_adjusted_long_side_drawdown_area
cost_adjusted_long_side_normalized_drawdown_area
cost_adjusted_long_side_max_drawdown_episode_area
cost_adjusted_long_side_recovery_pain_area
```

- [ ] **Step 4: Wire Step6 extraction and business review**

In `run_step6.py`, update `extract_headline_metrics()` to include:

```text
long_side_drawdown_area
long_side_normalized_drawdown_area
long_side_max_drawdown_episode_area
long_side_recovery_pain_area
cost_adjusted_long_side_drawdown_area
cost_adjusted_long_side_normalized_drawdown_area
cost_adjusted_long_side_max_drawdown_episode_area
cost_adjusted_long_side_recovery_pain_area
```

In `build_factor_business_review()`, add:

```json
"drawdown_geometry": {
  "drawdown_area": null,
  "normalized_drawdown_area": null,
  "max_drawdown_episode_area": null,
  "recovery_pain_area": null,
  "interpretation": "area measures total underwater investor pain; smaller is better"
}
```

Use drawdown geometry as a secondary risk-budget driver, not as a replacement for max drawdown or recovery days.

- [ ] **Step 5: Add metric interpretation**

In Step6 long-side review, add:

```text
If normalized_drawdown_area is available and high, add negative evidence:
"drawdown area is large; holder experience remains poor even if max drawdown alone is acceptable."
```

Do not create a hard threshold yet unless the code already has a threshold convention. Mark status as:

```text
missing | acceptable | elevated | high
```

Use conservative defaults:

```text
normalized_drawdown_area < 0.03 -> acceptable
0.03 to 0.08 -> elevated
> 0.08 -> high
```

- [ ] **Step 6: Run verification**

```bash
python3 -m py_compile \
  factor_factory/risk/drawdown_geometry.py \
  skills/factor-forge-step4/scripts/self_quant_adapter.py \
  skills/factor-forge-step4/scripts/run_step4.py \
  skills/factor-forge-step6/scripts/run_step6.py \
  scripts/run_step6_intelligence_acceptance.py
python3 scripts/run_step6_intelligence_acceptance.py
```

Expected:

```text
"case": "drawdown_geometry_area_computes_expected_values"
"ok": true
```

- [ ] **Step 7: Commit**

```bash
git add \
  factor_factory/risk/drawdown_geometry.py \
  skills/factor-forge-step4/scripts/self_quant_adapter.py \
  skills/factor-forge-step4/scripts/run_step4.py \
  skills/factor-forge-step6/scripts/run_step6.py \
  scripts/run_step6_intelligence_acceptance.py
git commit -m "Add drawdown geometry diagnostics"
```

---

### Task 5: Prompt, Skill, And Installed Skill Sync

**Objective:** Make researchers, Humphrey, Bernard, and Codex read the same Dirac-style contract rules after code changes.

**Boundary:** Sync skills only after tests pass. Do not sync partial work to installed skills.

**Files:**
- Modify: `skills/factor-forge-step1/SKILL.md`
- Modify: `skills/factor-forge-step1/references/prompts.md`
- Modify: `skills/factor-forge-step2/SKILL.md`
- Modify: `skills/factor-forge-step2/references/prompts.md`
- Modify: `skills/factor-forge-step6/SKILL.md`
- Modify: `docs/operations/factorforge-dirac-style-research-contract.zh-CN.md`

- [ ] **Step 1: Update skill language**

Add this exact conceptual rule to Step1, Step2, and Step6 skill docs:

```text
Factor Forge uses a Dirac-style research discipline: a factor must be tied to a classified research equation, a primary mathematical model selected from the economic hypothesis, a T+0/T+1 stochastic benchmark projection for traded price implications, formula-implied latent information, expected metric signature, anomaly classification, and falsification tests. Stochastic process is not always the primary model, but it remains a benchmark/projection tool for price-process implications.
```

- [ ] **Step 2: Update prompt references**

Prompt references must ask LLM/research agents to output:

```text
research_equation
t0_t1_stochastic_benchmark
formula_implied_information
formula_implied_information_review
metric_signature_match by model layer
drawdown geometry interpretation when Step4 metrics exist
```

- [ ] **Step 3: Run prompt/contract smoke**

```bash
python3 scripts/run_factorforge_mechanism_math_v2_smoke.py
python3 scripts/run_main_agent_mechanism_memo_smoke.py
```

Expected:

```text
verdict=ACCEPT or zero failed cases
```

- [ ] **Step 4: Sync installed skills after merge approval**

After branch is merged and verified, sync:

```bash
rsync -a --delete --exclude='__pycache__' skills/factor-forge-step1/ /Users/humphrey/.codex/skills/factor-forge-step1/
rsync -a --delete --exclude='__pycache__' skills/factor-forge-step2/ /Users/humphrey/.codex/skills/factor-forge-step2/
rsync -a --delete --exclude='__pycache__' skills/factor-forge-step6/ /Users/humphrey/.codex/skills/factor-forge-step6/
rsync -a --delete --exclude='__pycache__' skills/factor-forge-step1/ /Users/humphrey/.openclaw/workspace/skills/factor-forge-step1/
rsync -a --delete --exclude='__pycache__' skills/factor-forge-step2/ /Users/humphrey/.openclaw/workspace/skills/factor-forge-step2/
rsync -a --delete --exclude='__pycache__' skills/factor-forge-step6/ /Users/humphrey/.openclaw/workspace/skills/factor-forge-step6/
```

Then verify:

```bash
diff -qr --exclude='__pycache__' skills/factor-forge-step1 /Users/humphrey/.codex/skills/factor-forge-step1
diff -qr --exclude='__pycache__' skills/factor-forge-step2 /Users/humphrey/.codex/skills/factor-forge-step2
diff -qr --exclude='__pycache__' skills/factor-forge-step6 /Users/humphrey/.codex/skills/factor-forge-step6
diff -qr --exclude='__pycache__' skills/factor-forge-step1 /Users/humphrey/.openclaw/workspace/skills/factor-forge-step1
diff -qr --exclude='__pycache__' skills/factor-forge-step2 /Users/humphrey/.openclaw/workspace/skills/factor-forge-step2
diff -qr --exclude='__pycache__' skills/factor-forge-step6 /Users/humphrey/.openclaw/workspace/skills/factor-forge-step6
```

Expected: no output.

- [ ] **Step 5: Commit**

```bash
git add \
  skills/factor-forge-step1/SKILL.md \
  skills/factor-forge-step1/references/prompts.md \
  skills/factor-forge-step2/SKILL.md \
  skills/factor-forge-step2/references/prompts.md \
  skills/factor-forge-step6/SKILL.md \
  docs/operations/factorforge-dirac-style-research-contract.zh-CN.md
git commit -m "Document Dirac-style factor research contract"
```

---

### Task 6: Equation Search Registry

**Objective:** Make Factor Forge search over market-structure equations before searching over formula strings. A factor candidate should first identify the equation, constraint, symmetry, or invariance it is trying to exploit.

**Boundary:** This task adds a research registry and Step1/Step6 use of that registry. It does not run formula mining, mutate formulas, or alter Step3/4 execution.

**Files:**
- Create: `factor_factory/mechanism_math/equation_registry.py`
- Modify: `factor_factory/mechanism_math/classifier.py`
- Modify: `factor_factory/mechanism_math/validator.py`
- Modify: `scripts/run_factorforge_mechanism_math_v2_smoke.py`
- Modify: `docs/operations/factorforge-dirac-style-research-contract.zh-CN.md`

- [ ] **Step 1: Create equation registry**

Create `factor_factory/mechanism_math/equation_registry.py` with a small curated registry:

```python
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ResearchEquationTemplate:
    template_id: str
    equation_status: str
    family: str
    equation_text: str
    symmetry_or_constraint: str
    symmetry_breaking_mechanism: str
    typical_latent_states: tuple[str, ...]
    typical_observables: tuple[str, ...]
    expected_metric_signature: tuple[str, ...]
    falsification_tests: tuple[str, ...]


EQUATION_REGISTRY: dict[str, ResearchEquationTemplate] = {
    "sdf_euler_pricing_identity": ResearchEquationTemplate(
        template_id="sdf_euler_pricing_identity",
        equation_status="strict_identity",
        family="valuation_or_pricing",
        equation_text="P_t = E_t[m_{t+1}(P_{t+1}+CF_{t+1})]",
        symmetry_or_constraint="no-arbitrage/SDF Euler pricing identity",
        symmetry_breaking_mechanism="cash-flow news, discount-rate news, risk-premium repricing, or mispricing unwind",
        typical_latent_states=("cash_flow_news", "discount_rate_news", "risk_premium_state", "mispricing_gap"),
        typical_observables=("valuation_ratio", "earnings_revision", "quality_spread", "price_reversal"),
        expected_metric_signature=("long-side return comes from the declared repricing component", "signal survives cost and drawdown checks"),
        falsification_tests=("cannot map payoff to cash-flow, discount-rate, risk-premium, or mispricing component",),
    ),
    "clearing_impact_asymmetry": ResearchEquationTemplate(
        template_id="clearing_impact_asymmetry",
        equation_status="institutional_constraint",
        family="microstructure",
        equation_text="matched_trade_quantity_buy = matched_trade_quantity_sell, but impact_buy(q,state) may differ from impact_sell(q,state)",
        symmetry_or_constraint="market clearing quantity symmetry",
        symmetry_breaking_mechanism="asymmetric liquidity, inventory pressure, informed-flow imbalance, or order-book resilience",
        typical_latent_states=("impact_asymmetry", "hidden_liquidity", "inventory_pressure", "informed_flow_state"),
        typical_observables=("signed_impact_efficiency", "volume_absorption", "post_trade_reversal", "order_flow_imbalance"),
        expected_metric_signature=("same-volume buy/sell pressure has asymmetric forward return or reversal", "effect weakens after liquidity controls if it is only size noise"),
        falsification_tests=("buyer/seller initiated impact is symmetric after controls", "signal vanishes after spread/liquidity controls"),
    ),
    "holding_period_turnover_identity": ResearchEquationTemplate(
        template_id="holding_period_turnover_identity",
        equation_status="institutional_constraint",
        family="participant_horizon",
        equation_text="average_holding_period ≈ 1 / turnover",
        symmetry_or_constraint="capital holding-period/turnover accounting relation",
        symmetry_breaking_mechanism="short-horizon capital dominance, redemption pressure, mandate pressure, or rebalance constraints",
        typical_latent_states=("participant_horizon", "short_termism_pressure", "forced_rebalance_pressure"),
        typical_observables=("market_turnover", "fund_flow_turnover", "holding_period_shift", "factor_half_life"),
        expected_metric_signature=("short-horizon factors strengthen when holding period contracts", "value/quality strengthen when holding period lengthens"),
        falsification_tests=("factor efficacy does not vary with participant horizon proxy",),
    ),
    "disposition_feedback_pressure": ResearchEquationTemplate(
        template_id="disposition_feedback_pressure",
        equation_status="behavioral_feedback",
        family="behavioral_feedback",
        equation_text="sell_pressure_t = f(price_vs_cost_basis_t, trapped_position_density_t, liquidity_t) - absorption_capacity_t - time_decay_t",
        symmetry_or_constraint="path dependence and time-reversal asymmetry from investor cost basis",
        symmetry_breaking_mechanism="anchoring, disposition effect, regret, and delayed selling pressure",
        typical_latent_states=("trapped_position_density", "absorption_capacity", "breakout_quality"),
        typical_observables=("cost_basis_density", "breakout_volume", "post_break_pullback_depth", "resistance_penetration_strength"),
        expected_metric_signature=("breakouts with high absorption and shallow pullback outperform", "signal weakens when trapped-position density is low"),
        falsification_tests=("post-break shallow pullback does not predict forward return", "signal disappears after controlling for volume and volatility"),
    ),
    "square_root_impact_invariance": ResearchEquationTemplate(
        template_id="square_root_impact_invariance",
        equation_status="empirical_invariance",
        family="microstructure_invariance",
        equation_text="impact ≈ sigma * sqrt(Q / V)",
        symmetry_or_constraint="empirical market-impact scaling relation",
        symmetry_breaking_mechanism="hidden liquidity, informed meta-orders, inventory imbalance, or temporary liquidity withdrawal",
        typical_latent_states=("impact_residual", "hidden_liquidity", "meta_order_pressure"),
        typical_observables=("impact_residual", "volume_volatility_coupling", "liquidity_absorption"),
        expected_metric_signature=("impact residual predicts short-horizon continuation or reversal depending on absorption state",),
        falsification_tests=("residual impact has no forward-return or volatility signature", "effect vanishes out of sample across liquidity buckets"),
    ),
    "cross_scale_signal_invariance": ResearchEquationTemplate(
        template_id="cross_scale_signal_invariance",
        equation_status="empirical_invariance",
        family="multi_scale_signal",
        equation_text="signal_ic(frequency) should preserve sign or converge to a nonzero fixed point under scale transformation",
        symmetry_or_constraint="renormalization-like cross-frequency invariance",
        symmetry_breaking_mechanism="noise dominates at one scale or structural information persists across scales",
        typical_latent_states=("persistent_information_state", "scale_specific_noise", "signal_half_life"),
        typical_observables=("multi_frequency_rank_ic", "scale_decay", "cross_frequency_sign_agreement"),
        expected_metric_signature=("valid signal keeps sign across selected frequencies", "frequency collapse warns of factor decay"),
        falsification_tests=("IC sign flips unpredictably across neighboring frequencies", "no stable horizon exists"),
    ),
}
```

- [ ] **Step 2: Add registry lookup helper**

Add:

```python
def equation_template(template_id: str) -> ResearchEquationTemplate | None:
    return EQUATION_REGISTRY.get(template_id)


def templates_for_family(family: str) -> list[ResearchEquationTemplate]:
    return [item for item in EQUATION_REGISTRY.values() if item.family == family]
```

- [ ] **Step 3: Add RED smoke cases**

In `scripts/run_factorforge_mechanism_math_v2_smoke.py`, add:

```text
equation_registry_contains_core_templates
research_equation_template_id_unknown_blocks
valid_registry_template_contract_passes
```

Expected token:

```text
BLOCK_MECHANISM_MATH_V2_RESEARCH_EQUATION_TEMPLATE_UNKNOWN
```

- [ ] **Step 4: Wire template id into contract**

Extend `research_equation` with:

```json
{
  "template_id": "disposition_feedback_pressure",
  "template_source": "equation_registry|report_specific|human_supplied",
  "template_fit_reason": "",
  "template_limitations": []
}
```

Validator rules:

```text
If template_source=equation_registry, template_id must exist.
If template_source=report_specific or human_supplied, equation_text, assumptions, validity_scope, and falsification_tests must be stronger and non-generic.
```

- [ ] **Step 5: Verify**

```bash
python3 -m py_compile \
  factor_factory/mechanism_math/equation_registry.py \
  factor_factory/mechanism_math/classifier.py \
  factor_factory/mechanism_math/validator.py \
  scripts/run_factorforge_mechanism_math_v2_smoke.py
python3 scripts/run_factorforge_mechanism_math_v2_smoke.py
```

Expected:

```text
"verdict": "ACCEPT"
"case": "equation_registry_contains_core_templates"
"ok": true
```

- [ ] **Step 6: Commit**

```bash
git add \
  factor_factory/mechanism_math/equation_registry.py \
  factor_factory/mechanism_math/classifier.py \
  factor_factory/mechanism_math/validator.py \
  scripts/run_factorforge_mechanism_math_v2_smoke.py \
  docs/operations/factorforge-dirac-style-research-contract.zh-CN.md
git commit -m "Add Factor Forge research equation registry"
```

---

### Task 7: Observable Detector / Estimator Contract

**Objective:** Treat a factor formula as a detector of a latent market state, not as the research object itself.

**Boundary:** This task adds validation that formulas map to detectors/estimators. It does not create new formula mining algorithms.

**Files:**
- Modify: `factor_factory/mechanism_math/schema.py`
- Modify: `factor_factory/mechanism_math/classifier.py`
- Modify: `factor_factory/mechanism_math/validator.py`
- Modify: `factor_factory/mechanism_math/formula_specific.py`
- Modify: `scripts/run_factorforge_mechanism_math_v2_smoke.py`
- Modify: `scripts/run_main_agent_mechanism_memo_smoke.py`

- [ ] **Step 1: Add detector contract fields**

Extend `mechanism_math_contract_v2` with:

```json
"observable_detector_contract": {
  "detector_name": "",
  "detected_latent_state": "",
  "null_state_behavior": "",
  "symmetry_breaking_detected": "",
  "measurement_noise_sources": [],
  "required_controls": [],
  "detector_failure_modes": [],
  "estimator_family": "threshold|rank|projection|residual|response_function|state_space|distribution_tail|cross_scale|other"
}
```

- [ ] **Step 2: Add RED smoke cases**

Add:

```text
missing_observable_detector_contract_blocks
detector_restates_formula_blocks
detector_missing_null_state_blocks
detector_valid_latent_state_passes
```

Expected token:

```text
BLOCK_MECHANISM_MATH_V2_OBSERVABLE_DETECTOR_MISSING
BLOCK_MECHANISM_MATH_V2_OBSERVABLE_DETECTOR_RESTATEMENT
```

- [ ] **Step 3: Implement validator rules**

Rules:

```text
detected_latent_state must not be raw field or formula call
null_state_behavior is required and must state what happens if the symmetry/constraint is absent
symmetry_breaking_detected must match research_equation.symmetry_breaking_mechanism or explain divergence
measurement_noise_sources must be nonempty
required_controls must be nonempty for microstructure/behavioral/empirical invariance equations
detector_failure_modes must be nonempty
```

- [ ] **Step 4: Add formula-specific consistency checks**

In `formula_specific.py`, enforce examples:

```text
Formula without volume/amount/turnover cannot claim detector of volume-liquidity state unless required_controls justify external context.
Threshold/sign formulas must discuss null-state behavior and threshold instability.
Rank/correlation formulas must say whether they detect monotone dependence, copula structure, or relative state ordering.
Cross-scale claims require at least two frequency/horizon observables.
```

- [ ] **Step 5: Verify**

```bash
python3 -m py_compile \
  factor_factory/mechanism_math/schema.py \
  factor_factory/mechanism_math/classifier.py \
  factor_factory/mechanism_math/validator.py \
  factor_factory/mechanism_math/formula_specific.py \
  scripts/run_factorforge_mechanism_math_v2_smoke.py \
  scripts/run_main_agent_mechanism_memo_smoke.py
python3 scripts/run_factorforge_mechanism_math_v2_smoke.py
python3 scripts/run_main_agent_mechanism_memo_smoke.py
```

Expected:

```text
"detector_valid_latent_state_passes": true
```

- [ ] **Step 6: Commit**

```bash
git add \
  factor_factory/mechanism_math/schema.py \
  factor_factory/mechanism_math/classifier.py \
  factor_factory/mechanism_math/validator.py \
  factor_factory/mechanism_math/formula_specific.py \
  scripts/run_factorforge_mechanism_math_v2_smoke.py \
  scripts/run_main_agent_mechanism_memo_smoke.py
git commit -m "Require formula observable detector contract"
```

---

### Task 8: Anomaly-Driven Revision Workflow

**Objective:** Make unexpected implications and negative solutions create structured review output and possible branch seeds rather than being discarded as failed backtests.

**Boundary:** This task changes Step6/Council reasoning and validation only. It does not automatically launch child runs or modify Step3B handoffs without existing human approval gates.

**Files:**
- Modify: `factor_factory/revision_council/validator.py`
- Modify: `skills/factor-forge-step6/scripts/run_step6.py`
- Modify: `skills/factor-forge-step6/scripts/merge_revision_council.py`
- Modify: `skills/factor-forge-step6/scripts/build_council_derivation_appendix.py`
- Modify: `scripts/run_factorforge_mechanism_math_v2_smoke.py`
- Modify: `scripts/run_agentic_council_operating_protocol_smoke.py`

- [ ] **Step 1: Add anomaly review artifact contract**

Step6 should write, when unexpected implications exist:

```text
objects/research_iteration_master/revision_council/<report_id>/anomaly_review__<report_id>.json
objects/research_iteration_master/revision_council/<report_id>/anomaly_review__<report_id>.md
```

JSON shape:

```json
{
  "version": "factorforge_dirac_anomaly_review_v1",
  "report_id": "",
  "source_contract_hash": "",
  "unexpected_implications": [
    {
      "implication": "",
      "classification": "bug|data_artifact|implementation_artifact|benign_model_implication|tradable_anomaly|new_factor_seed|theory_rejected",
      "reasoning": "",
      "evidence_required": [],
      "branch_seed_if_any": {
        "child_formula_or_law": "",
        "expected_metric_signature": [],
        "kill_criteria": []
      }
    }
  ],
  "approved_for_branch_generation": false
}
```

- [ ] **Step 2: Add RED smoke cases**

Add:

```text
anomaly_review_artifact_required_for_unexpected_implications
anomaly_theory_rejected_requires_falsification_evidence
anomaly_new_factor_seed_requires_branch_seed
anomaly_artifact_does_not_authorize_child_without_approval
```

Expected tokens:

```text
BLOCK_DIRAC_ANOMALY_REVIEW_MISSING
BLOCK_DIRAC_ANOMALY_BRANCH_SEED_MISSING
BLOCK_DIRAC_ANOMALY_APPROVAL_MISSING
```

- [ ] **Step 3: Implement Council validator rules**

Rules:

```text
bug/data_artifact/implementation_artifact require evidence_required
theory_rejected requires falsification evidence and cannot be used as silent terminal rejection before loop cap
tradable_anomaly/new_factor_seed require branch_seed_if_any
anomaly branch seed remains advisory until existing Step6 approval bridge approves it
```

- [ ] **Step 4: Include anomaly review in derivation appendix**

Update `build_council_derivation_appendix.py` to include:

```text
unexpected implications
classification
reasoning
branch seed
falsification tests
approval status
```

- [ ] **Step 5: Verify**

```bash
python3 -m py_compile \
  factor_factory/revision_council/validator.py \
  skills/factor-forge-step6/scripts/run_step6.py \
  skills/factor-forge-step6/scripts/merge_revision_council.py \
  skills/factor-forge-step6/scripts/build_council_derivation_appendix.py \
  scripts/run_factorforge_mechanism_math_v2_smoke.py \
  scripts/run_agentic_council_operating_protocol_smoke.py
python3 scripts/run_factorforge_mechanism_math_v2_smoke.py
python3 scripts/run_agentic_council_operating_protocol_smoke.py
```

Expected:

```text
"anomaly_new_factor_seed_requires_branch_seed": true
"anomaly_artifact_does_not_authorize_child_without_approval": true
```

- [ ] **Step 6: Commit**

```bash
git add \
  factor_factory/revision_council/validator.py \
  skills/factor-forge-step6/scripts/run_step6.py \
  skills/factor-forge-step6/scripts/merge_revision_council.py \
  skills/factor-forge-step6/scripts/build_council_derivation_appendix.py \
  scripts/run_factorforge_mechanism_math_v2_smoke.py \
  scripts/run_agentic_council_operating_protocol_smoke.py
git commit -m "Add Dirac-style anomaly revision workflow"
```

---

### Task 9: Equation Quality Rubric And Assumption Boundary

**Objective:** Prevent weak market observations from being treated as hard laws. Every strict identity, institutional constraint, behavioral feedback equation, empirical invariance, or research conjecture must carry a quality score, assumption boundary, evidence tier, and demotion rule.

**Boundary:** This task scores research equations and quasi-equations. It does not decide whether a factor is promotable, does not run backtests, and does not turn conjectures into official laws.

**Files:**
- Create: `factor_factory/mechanism_math/equation_quality.py`
- Modify: `factor_factory/mechanism_math/equation_registry.py`
- Modify: `factor_factory/mechanism_math/schema.py`
- Modify: `factor_factory/mechanism_math/validator.py`
- Modify: `scripts/run_factorforge_dirac_discovery_smoke.py`
- Modify: `docs/operations/factorforge-dirac-style-research-contract.zh-CN.md`

- [ ] **Step 1: Write RED smoke cases**

Create `scripts/run_factorforge_dirac_discovery_smoke.py` with these cases:

```python
CASES = [
    "strict_identity_without_audit_basis_blocks",
    "behavioral_feedback_without_participant_loop_blocks",
    "empirical_invariance_without_scope_blocks",
    "research_conjecture_auto_promotion_blocks",
    "valid_behavioral_feedback_quality_passes",
]
```

Expected block tokens:

```text
BLOCK_DIRAC_EQUATION_AUDIT_BASIS_MISSING
BLOCK_DIRAC_EQUATION_PARTICIPANT_LOOP_MISSING
BLOCK_DIRAC_EQUATION_SCOPE_MISSING
BLOCK_DIRAC_EQUATION_CONJECTURE_PROMOTION_FORBIDDEN
```

- [ ] **Step 2: Create quality rubric module**

Create `factor_factory/mechanism_math/equation_quality.py`:

```python
from __future__ import annotations

from dataclasses import dataclass
from typing import Any


VALID_EVIDENCE_TIERS = {
    "logical_identity",
    "institutional_rule",
    "documented_microstructure_law",
    "cross_asset_empirical_invariance",
    "single_market_empirical_regular",
    "report_specific_hypothesis",
}

VALID_DEMOTION_TRIGGERS = {
    "identity_violation",
    "rule_change",
    "participant_structure_change",
    "liquidity_regime_change",
    "cost_or_capacity_break",
    "cross_sample_failure",
    "metric_signature_mismatch",
}


@dataclass(frozen=True)
class EquationQualityResult:
    ok: bool
    block_codes: tuple[str, ...]
    quality_score: int
    evidence_tier: str


def score_research_equation(equation: dict[str, Any]) -> EquationQualityResult:
    status = str(equation.get("equation_status") or "")
    evidence_tier = str(equation.get("evidence_tier") or "")
    assumptions = equation.get("assumptions") or []
    validity_scope = equation.get("validity_scope") or {}
    participant_loop = equation.get("participant_constraint_loop") or {}
    demotion_triggers = equation.get("demotion_triggers") or []
    audit_basis = equation.get("audit_basis") or []
    block_codes: list[str] = []
    score = 0

    if evidence_tier not in VALID_EVIDENCE_TIERS:
        block_codes.append("BLOCK_DIRAC_EQUATION_EVIDENCE_TIER_INVALID")
    else:
        score += {
            "logical_identity": 30,
            "institutional_rule": 24,
            "documented_microstructure_law": 20,
            "cross_asset_empirical_invariance": 18,
            "single_market_empirical_regular": 12,
            "report_specific_hypothesis": 8,
        }[evidence_tier]

    if status == "strict_identity" and not audit_basis:
        block_codes.append("BLOCK_DIRAC_EQUATION_AUDIT_BASIS_MISSING")
    if status == "behavioral_feedback" and not participant_loop:
        block_codes.append("BLOCK_DIRAC_EQUATION_PARTICIPANT_LOOP_MISSING")
    if status in {"empirical_invariance", "research_conjecture"} and not validity_scope:
        block_codes.append("BLOCK_DIRAC_EQUATION_SCOPE_MISSING")
    if status == "research_conjecture" and equation.get("promotion_allowed") is True:
        block_codes.append("BLOCK_DIRAC_EQUATION_CONJECTURE_PROMOTION_FORBIDDEN")
    if not assumptions:
        block_codes.append("BLOCK_DIRAC_EQUATION_ASSUMPTIONS_MISSING")
    if not demotion_triggers:
        block_codes.append("BLOCK_DIRAC_EQUATION_DEMOTION_TRIGGERS_MISSING")
    if any(str(item) not in VALID_DEMOTION_TRIGGERS for item in demotion_triggers):
        block_codes.append("BLOCK_DIRAC_EQUATION_DEMOTION_TRIGGER_INVALID")

    score += min(len(assumptions), 4) * 4
    score += min(len(demotion_triggers), 4) * 3
    score += 8 if validity_scope else 0
    score += 8 if participant_loop else 0
    score += 8 if audit_basis else 0
    return EquationQualityResult(
        ok=not block_codes,
        block_codes=tuple(block_codes),
        quality_score=min(score, 100),
        evidence_tier=evidence_tier,
    )
```

- [ ] **Step 3: Extend research equation schema**

In `schema.py`, add required fields:

```python
REQUIRED_EQUATION_QUALITY_FIELDS = [
    "evidence_tier",
    "audit_basis",
    "participant_constraint_loop",
    "demotion_triggers",
    "quality_score",
]
```

Add rule comments in the same file:

```text
strict_identity requires audit_basis
institutional_constraint requires cited rule/mandate/constraint
behavioral_feedback requires participant_constraint_loop
empirical_invariance requires validity_scope and cross-sample test
research_conjecture cannot authorize promotion before Step6 evidence
```

- [ ] **Step 4: Attach quality to registry templates**

Extend every `ResearchEquationTemplate` in `equation_registry.py` with:

```python
evidence_tier: str
audit_basis: tuple[str, ...]
participant_constraint_loop: dict[str, str]
demotion_triggers: tuple[str, ...]
```

Example for `disposition_feedback_pressure`:

```python
evidence_tier="report_specific_hypothesis",
audit_basis=("Report text or cited behavioral finance evidence must support the cost-basis pressure claim.",),
participant_constraint_loop={
    "payer": "anchored holders or short-horizon traders",
    "constraint": "cannot or will not immediately abandon cost-basis anchored behavior",
    "repeat_mechanism": "new trapped positions are created by prior trading waves",
    "failure_condition": "participant structure changes or trapped-position density no longer maps to selling pressure",
},
demotion_triggers=("participant_structure_change", "metric_signature_mismatch", "cross_sample_failure"),
```

- [ ] **Step 5: Wire validator**

In `validator.py`, call:

```python
from factor_factory.mechanism_math.equation_quality import score_research_equation
```

Validation rules:

```text
score_research_equation(research_equation).ok must be true
quality_score must be written back or recomputed by validator
research_conjecture quality_score below 40 blocks official promotion but may remain a branch seed
strict_identity with quality_score below 60 blocks the contract
behavioral_feedback with no repeat_mechanism blocks the contract
```

- [ ] **Step 6: Verify**

```bash
python3 -m py_compile \
  factor_factory/mechanism_math/equation_quality.py \
  factor_factory/mechanism_math/equation_registry.py \
  factor_factory/mechanism_math/schema.py \
  factor_factory/mechanism_math/validator.py \
  scripts/run_factorforge_dirac_discovery_smoke.py
python3 scripts/run_factorforge_dirac_discovery_smoke.py
python3 scripts/run_factorforge_mechanism_math_v2_smoke.py
```

Expected:

```text
"strict_identity_without_audit_basis_blocks": true
"behavioral_feedback_without_participant_loop_blocks": true
"research_conjecture_auto_promotion_blocks": true
"valid_behavioral_feedback_quality_passes": true
```

- [ ] **Step 7: Commit**

```bash
git add \
  factor_factory/mechanism_math/equation_quality.py \
  factor_factory/mechanism_math/equation_registry.py \
  factor_factory/mechanism_math/schema.py \
  factor_factory/mechanism_math/validator.py \
  scripts/run_factorforge_dirac_discovery_smoke.py \
  docs/operations/factorforge-dirac-style-research-contract.zh-CN.md
git commit -m "Add research equation quality rubric"
```

---

### Task 10: Equation-To-Factor Discovery Queue

**Objective:** Make the Dirac-style method useful for factor discovery, not only factor review. Step1/Step6 should be able to produce a reviewed queue of equation-derived detector candidates, each with observable inputs, expected metric signature, cost/risk expectation, and branch boundary.

**Boundary:** This task creates candidate research packets only. It must not start Step2/Step3/Step4, must not mutate formal artifacts, and must not promote generated candidates without the existing human-approved Factor Forge loop.

**Files:**
- Create: `factor_factory/mechanism_math/factor_discovery_queue.py`
- Modify: `factor_factory/mechanism_math/equation_registry.py`
- Modify: `skills/factor-forge-step1/SKILL.md`
- Modify: `skills/factor-forge-step6/SKILL.md`
- Modify: `skills/factor-forge-step6/scripts/run_step6.py`
- Modify: `scripts/run_factorforge_dirac_discovery_smoke.py`
- Modify: `docs/operations/factorforge-dirac-style-research-contract.zh-CN.md`

- [ ] **Step 1: Write RED discovery smoke cases**

In `scripts/run_factorforge_dirac_discovery_smoke.py`, add:

```text
equation_to_detector_queue_contains_no_auto_run
queue_candidate_missing_observables_blocks
queue_candidate_missing_expected_signature_blocks
queue_candidate_missing_cost_risk_hypothesis_blocks
valid_square_root_impact_candidate_passes
valid_disposition_feedback_candidate_passes
```

Expected tokens:

```text
BLOCK_DIRAC_DISCOVERY_OBSERVABLES_MISSING
BLOCK_DIRAC_DISCOVERY_METRIC_SIGNATURE_MISSING
BLOCK_DIRAC_DISCOVERY_COST_RISK_MISSING
BLOCK_DIRAC_DISCOVERY_AUTORUN_FORBIDDEN
```

- [ ] **Step 2: Create discovery queue module**

Create `factor_factory/mechanism_math/factor_discovery_queue.py`:

```python
from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Any

from factor_factory.mechanism_math.equation_registry import equation_template


@dataclass(frozen=True)
class DiscoveryCandidate:
    candidate_id: str
    source_equation_id: str
    detector_hypothesis: str
    observable_inputs: tuple[str, ...]
    measurement_equation: str
    expected_metric_signature: tuple[str, ...]
    expected_cost_risk_profile: tuple[str, ...]
    stochastic_benchmark_terms: tuple[str, ...]
    falsification_tests: tuple[str, ...]
    branch_action: str
    auto_run_allowed: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def validate_discovery_candidate(candidate: DiscoveryCandidate) -> tuple[str, ...]:
    block_codes: list[str] = []
    if not candidate.observable_inputs:
        block_codes.append("BLOCK_DIRAC_DISCOVERY_OBSERVABLES_MISSING")
    if not candidate.expected_metric_signature:
        block_codes.append("BLOCK_DIRAC_DISCOVERY_METRIC_SIGNATURE_MISSING")
    if not candidate.expected_cost_risk_profile:
        block_codes.append("BLOCK_DIRAC_DISCOVERY_COST_RISK_MISSING")
    if candidate.auto_run_allowed:
        block_codes.append("BLOCK_DIRAC_DISCOVERY_AUTORUN_FORBIDDEN")
    if candidate.branch_action not in {"review_only", "human_approval_required"}:
        block_codes.append("BLOCK_DIRAC_DISCOVERY_BRANCH_ACTION_INVALID")
    if equation_template(candidate.source_equation_id) is None:
        block_codes.append("BLOCK_DIRAC_DISCOVERY_SOURCE_EQUATION_UNKNOWN")
    return tuple(block_codes)
```

- [ ] **Step 3: Add seed candidate builders**

In the same file, add:

```python
def square_root_impact_candidates() -> list[DiscoveryCandidate]:
    return [
        DiscoveryCandidate(
            candidate_id="sqrt_impact_residual_absorption_v1",
            source_equation_id="square_root_impact_invariance",
            detector_hypothesis="Actual short-horizon impact below sigma*sqrt(Q/V) detects hidden liquidity or absorption capacity.",
            observable_inputs=("minute_price", "minute_volume", "daily_volatility", "adv", "spread_or_proxy"),
            measurement_equation="impact_residual_t = realized_impact_t - sigma_t * sqrt(Q_t / V_t)",
            expected_metric_signature=(
                "negative residual with high absorption predicts continuation if informed demand is being absorbed",
                "positive residual predicts reversal when liquidity withdrawal dominates",
            ),
            expected_cost_risk_profile=(
                "turnover cost is COGS and must be netted before promotion",
                "short-horizon volatility drag and jump risk must be measured",
            ),
            stochastic_benchmark_terms=("friction", "observation_equation", "jump"),
            falsification_tests=("Residual has no conditional return or volatility signature after liquidity controls.",),
            branch_action="review_only",
        )
    ]


def disposition_feedback_candidates() -> list[DiscoveryCandidate]:
    return [
        DiscoveryCandidate(
            candidate_id="trapped_position_absorption_v1",
            source_equation_id="disposition_feedback_pressure",
            detector_hypothesis="Breakout through high trapped-position density with shallow pullback detects absorption of delayed selling pressure.",
            observable_inputs=("close", "volume", "turnover", "cost_basis_density_proxy", "post_break_pullback"),
            measurement_equation="absorption_strength_t = breakout_volume_t / max(post_break_pullback_depth_t, epsilon)",
            expected_metric_signature=(
                "high absorption strength predicts positive forward return",
                "signal weakens when trapped-position density is low",
            ),
            expected_cost_risk_profile=(
                "high turnover raises COGS and can erase gross edge",
                "drawdown recovery area should be small if absorption thesis is correct",
            ),
            stochastic_benchmark_terms=("drift", "friction", "regime_transition"),
            falsification_tests=("Breakout absorption does not improve return after controlling for momentum and liquidity.",),
            branch_action="review_only",
        )
    ]
```

- [ ] **Step 4: Add queue materializer**

Add:

```python
def build_default_discovery_queue() -> dict[str, Any]:
    candidates = [*square_root_impact_candidates(), *disposition_feedback_candidates()]
    candidate_dicts = []
    all_blocks: dict[str, tuple[str, ...]] = {}
    for candidate in candidates:
        blocks = validate_discovery_candidate(candidate)
        all_blocks[candidate.candidate_id] = blocks
        candidate_dicts.append(candidate.to_dict())
    return {
        "version": "factorforge_dirac_discovery_queue_v1",
        "auto_run_allowed": False,
        "candidates": candidate_dicts,
        "validation_blocks": all_blocks,
    }
```

- [ ] **Step 5: Wire Step1/Step6 prompts**

Update Step1 and Step6 skill text with:

```text
When a report suggests a market structure relation, first identify the research equation or quasi-equation, then derive one or more observable detector candidates. A detector candidate is not an approved factor. It must state source_equation_id, observable_inputs, measurement_equation, expected_metric_signature, expected_cost_risk_profile, stochastic_benchmark_terms, falsification_tests, and branch_action=review_only or human_approval_required.
```

Add a hard rule:

```text
No equation-derived candidate may launch Step2/Step3/Step4 automatically. Candidate packets are advisory until the existing run loop or a human-approved branch request starts a formal factor run.
```

- [ ] **Step 6: Add Step6 artifact output**

In `run_step6.py`, when anomaly review produces `new_factor_seed` or when Step6 is explicitly asked for discovery ideas, write:

```text
objects/research_iteration_master/revision_council/<report_id>/dirac_discovery_queue__<report_id>.json
objects/research_iteration_master/revision_council/<report_id>/dirac_discovery_queue__<report_id>.md
```

The JSON top-level fields must be:

```json
{
  "version": "factorforge_dirac_discovery_queue_v1",
  "report_id": "",
  "source": "step6_anomaly_review|explicit_discovery_request",
  "auto_run_allowed": false,
  "candidates": [],
  "validation_blocks": {}
}
```

- [ ] **Step 7: Verify**

```bash
python3 -m py_compile \
  factor_factory/mechanism_math/factor_discovery_queue.py \
  factor_factory/mechanism_math/equation_registry.py \
  skills/factor-forge-step6/scripts/run_step6.py \
  scripts/run_factorforge_dirac_discovery_smoke.py
python3 scripts/run_factorforge_dirac_discovery_smoke.py
python3 scripts/run_factorforge_mechanism_math_v2_smoke.py
```

Expected:

```text
"equation_to_detector_queue_contains_no_auto_run": true
"valid_square_root_impact_candidate_passes": true
"valid_disposition_feedback_candidate_passes": true
```

- [ ] **Step 8: Commit**

```bash
git add \
  factor_factory/mechanism_math/factor_discovery_queue.py \
  factor_factory/mechanism_math/equation_registry.py \
  skills/factor-forge-step1/SKILL.md \
  skills/factor-forge-step6/SKILL.md \
  skills/factor-forge-step6/scripts/run_step6.py \
  scripts/run_factorforge_dirac_discovery_smoke.py \
  docs/operations/factorforge-dirac-style-research-contract.zh-CN.md
git commit -m "Add Dirac-style equation-to-factor discovery queue"
```

---

### Task 11: LLM Prompt Pack And Prompt Compliance Smoke

**Objective:** Make the LLMs actually produce the new research structure. Step1, Step2, Step6, and Council prompts must explicitly force the chain `market relation -> classified equation -> assumptions -> primary model -> stochastic benchmark -> observable detector -> expected metric signature -> falsification -> anomaly/revision`, instead of asking only for an economic story or formula summary.

**Boundary:** This task changes prompt text and prompt compliance tests only. It does not run formal Factor Forge research, does not rewrite raw artifacts, and does not change Step3/4 compute behavior.

**Files:**
- Modify: `skills/factor-forge-step1/references/prompts.md`
- Modify: `skills/factor-forge-step1/SKILL.md`
- Modify: `skills/factor-forge-step2/references/prompts.md`
- Modify: `skills/factor-forge-step2/SKILL.md`
- Create or modify: `skills/factor-forge-step6/references/prompts.md`
- Modify: `skills/factor-forge-step6/SKILL.md`
- Create: `scripts/run_factorforge_prompt_contract_smoke.py`
- Modify: `docs/operations/factorforge-dirac-style-research-contract.zh-CN.md`

- [ ] **Step 1: Write prompt compliance smoke first**

Create `scripts/run_factorforge_prompt_contract_smoke.py`:

```python
from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

PROMPT_FILES = {
    "step1": ROOT / "skills/factor-forge-step1/references/prompts.md",
    "step2": ROOT / "skills/factor-forge-step2/references/prompts.md",
    "step6": ROOT / "skills/factor-forge-step6/references/prompts.md",
}

REQUIRED_TERMS = {
    "all": [
        "classified research equation",
        "equation_status",
        "assumptions",
        "validity_scope",
        "primary_mathematical_model",
        "t0_t1_stochastic_benchmark",
        "observable_detector_contract",
        "formula_implied_information",
        "expected_metric_signature",
        "falsification_tests",
        "kill_criteria",
    ],
    "step1": [
        "payer_or_forced_counterparty",
        "why_the_payer_cannot_stop",
        "participant_constraint_loop",
        "equation_quality",
        "do not select stochastic process as the primary model by default",
    ],
    "step2": [
        "formula is an observable estimator",
        "measurement_equation",
        "null_state_behavior",
        "direct_code must implement the estimator only after the mechanism contract is coherent",
        "raw-field restatement is invalid",
    ],
    "step6": [
        "research_equation_reviewer",
        "metric_links",
        "turnover cost is COGS",
        "volatility_drag",
        "drawdown_recovery_area",
        "Dirac-style anomaly review",
        "equation-to-factor discovery queue",
    ],
}

FORBIDDEN_PATTERNS = [
    "just explain the formula",
    "stochastic process is always the primary model",
    "IC alone proves the factor",
    "formula_text is the mechanism",
]


def _read(path: Path) -> str:
    if not path.exists():
        raise AssertionError(f"missing prompt file: {path}")
    return path.read_text(encoding="utf-8")


def main() -> None:
    results: dict[str, bool] = {}
    for key, path in PROMPT_FILES.items():
        text = _read(path)
        lower = text.lower()
        for term in REQUIRED_TERMS["all"] + REQUIRED_TERMS[key]:
            results[f"{key}_contains_{term}"] = term.lower() in lower
        for pattern in FORBIDDEN_PATTERNS:
            results[f"{key}_forbids_{pattern}"] = pattern.lower() not in lower
    failed = [name for name, ok in results.items() if not ok]
    print({"verdict": "ACCEPT" if not failed else "BLOCK", "failed": failed})
    if failed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
```

Run it before prompt edits and confirm it fails:

```bash
python3 scripts/run_factorforge_prompt_contract_smoke.py
```

Expected: `verdict=BLOCK` with missing required terms.

- [ ] **Step 2: Add exact Step1 prompt block**

In `skills/factor-forge-step1/references/prompts.md`, add a section named `Dirac-Style Step1 Mechanism Extraction Prompt` with this exact prompt skeleton:

```text
You are the Step1 mechanism extractor for Factor Forge.

Your job is not to summarize the formula. Your job is to extract the market relation that would make the formula worth testing.

Required reasoning chain:
1. Identify the market behavior or structural relation claimed by the report.
2. Classify the research equation:
   - strict_identity
   - institutional_constraint
   - behavioral_feedback
   - empirical_invariance
   - research_conjecture
3. State the equation_text. It may be a strict identity or a quasi-equation based on market assumptions, but it must be explicit enough to be falsified.
4. State assumptions, validity_scope, payer_or_forced_counterparty, why_the_payer_cannot_stop, participant_constraint_loop, and demotion_triggers.
5. Select the primary_mathematical_model from the economic hypothesis. Do not select stochastic process as the primary model by default.
6. Add t0_t1_stochastic_benchmark as a benchmark/projection layer for traded-price implications. Explain whether the factor affects drift, diffusion, jump, friction, regime_transition, or observation_equation.
7. Explain formula_implied_information: what latent state the formula is trying to recover. Raw-field restatement is invalid.
8. State expected_metric_signature, falsification_tests, and kill_criteria.
9. If the formula implies an unexpected or negative solution, do not discard it. Classify it as bug, data_artifact, implementation_artifact, benign_model_implication, tradable_anomaly, new_factor_seed, or theory_rejected.

Output JSON keys:
{
  "market_process_thesis": "",
  "economic_hypothesis": {
    "return_source_type": "risk_premium|information_rent|liquidity_rent|institutional_constraint_rent|behavioral_rent|time_option_rent|mixed|unknown",
    "payer_or_forced_counterparty": "",
    "why_the_payer_cannot_stop": "",
    "risk_borne_by_strategy": [],
    "capacity_boundary": ""
  },
  "research_equation": {
    "equation_status": "",
    "equation_text": "",
    "assumptions": [],
    "validity_scope": {"market": "", "frequency": "", "regime": "", "participant_structure": ""},
    "symmetry_or_constraint": "",
    "symmetry_breaking_mechanism": "",
    "participant_constraint_loop": {
      "payer": "",
      "constraint": "",
      "repeat_mechanism": "",
      "failure_condition": ""
    },
    "evidence_tier": "",
    "audit_basis": [],
    "demotion_triggers": [],
    "latent_state": "",
    "observable_estimator": "",
    "expected_metric_signature": [],
    "falsification_tests": [],
    "kill_criteria": []
  },
  "primary_mathematical_model": {
    "model_family": "",
    "why_this_model_matches_the_hypothesis": "",
    "why_not_alternative_models": []
  },
  "t0_t1_stochastic_benchmark": {
    "benchmark_required": true,
    "affected_terms": [],
    "conditional_distribution_claim": "",
    "benchmark_implication": "",
    "when_primary_model_cannot_infer": "",
    "falsification_tests": []
  },
  "formula_implied_information": {
    "latent_state_recovered": "",
    "not_raw_field_restatement_reason": "",
    "observable_detector_contract": {
      "detector_name": "",
      "detected_latent_state": "",
      "measurement_equation": "",
      "null_state_behavior": "",
      "measurement_noise_sources": [],
      "required_controls": [],
      "detector_failure_modes": []
    }
  }
}
```

Add this hard instruction immediately after the prompt:

```text
Reject answers that only say "the factor predicts returns because the report says it works." Reject answers that only restate close, volume, rank, correlation, or the formula. The output must explain the market relation, who pays, why the payment repeats, and what observable detector recovers the latent state.
```

- [ ] **Step 3: Add exact Step2 prompt block**

In `skills/factor-forge-step2/references/prompts.md`, add `Dirac-Style Step2 Factor Spec Prompt`:

```text
You are the Step2 factor specification builder.

Your task is to convert Step1's alpha_idea_master into a factor_spec_master. Do not let direct_code become a shortcut around the mechanism contract.

Mandatory order:
1. Validate Step1 research_equation. If equation_status, assumptions, validity_scope, participant_constraint_loop, expected_metric_signature, or falsification_tests are missing, mark the spec blocked.
2. Validate primary_mathematical_model. It must be chosen from the economic hypothesis. Stochastic process is not automatically the primary model.
3. Validate t0_t1_stochastic_benchmark. For price-predictive factors, it must explain affected_terms among drift, diffusion, jump, friction, regime_transition, observation_equation.
4. Build observable_detector_contract. The formula is an observable estimator of a latent state, not the mechanism itself.
5. Build canonical_spec.formula_text only after the detector contract is coherent.
6. Generate direct_code only after the formula and data requirements are unambiguous.
7. If direct_code cannot implement the detector without unstated assumptions, set implementation_contract.code_contract.status = "blocked".

Required output additions:
{
  "mechanism_math_contract_v2": {
    "research_equation": {},
    "equation_quality": {},
    "primary_mathematical_model": {},
    "t0_t1_stochastic_benchmark": {},
    "formula_implied_information": {},
    "formula_implied_information_review": {},
    "observable_detector_contract": {},
    "expected_metric_signature": [],
    "falsification_tests": [],
    "kill_criteria": []
  },
  "canonical_spec": {
    "formula_text": "",
    "formula_text_must_reference_detector_contract": true
  },
  "implementation_contract": {
    "code_contract": {
      "status": "ready|blocked",
      "blocked_reason": "",
      "source_code": ""
    }
  }
}

Invalid outputs:
- formula_text that is only a formula paraphrase
- formula_implied_information that repeats raw fields
- stochastic process used as primary model without economic justification
- direct_code that ignores rolling windows, valid-day filters, cost basis, liquidity state, or other detector requirements stated in the contract
- direct_code that computes a proxy different from the declared measurement_equation
```

- [ ] **Step 4: Add exact Step6 prompt block**

Create or update `skills/factor-forge-step6/references/prompts.md` with `Dirac-Style Step6 Council Prompt`:

```text
You are the Step6 research equation reviewer and Council analyst.

Your task is to decide which layer failed or succeeded:
1. research_equation
2. assumptions and validity_scope
3. primary_mathematical_model
4. t0_t1_stochastic_benchmark
5. observable_detector_contract
6. implementation_contract
7. cost/risk economics
8. drawdown geometry

Do not judge by IC alone. Every metric must be linked back to a model layer.

Required metric interpretation:
- rank_ic: whether the observable estimator orders the latent state correctly
- long_side_return: whether the sign of the economic hypothesis is correct
- turnover: trading cost COGS and participant-horizon implication
- cost_adjusted_return: whether gross edge survives implementation economics
- volatility_drag: second-order P&L loss from variance/convexity and unstable NAV compounding
- max_drawdown: realized stress against the declared price-process risk terms
- drawdown_recovery_days: time-option cost borne by capital provider
- drawdown_recovery_area: NAV pain area; smaller area means better holder experience for equal return

Required output:
{
  "research_equation_review": {
    "reviewer_task": "research_equation_reviewer",
    "equation_supported_by_metrics": "supported|challenged|under_specified",
    "metric_links": {
      "rank_ic": "",
      "long_side_return": "",
      "cost_adjusted_return": "",
      "turnover": "",
      "volatility_drag": "",
      "max_drawdown": "",
      "drawdown_recovery_days": "",
      "drawdown_recovery_area": ""
    },
    "failed_equation_component": "none|assumptions|latent_state|observable_estimator|price_process_projection|implementation_contract|trading_cost|drawdown_geometry",
    "revision_implication": ""
  },
  "dirac_anomaly_review": {
    "unexpected_implications": [
      {
        "implication": "",
        "classification": "bug|data_artifact|implementation_artifact|benign_model_implication|tradable_anomaly|new_factor_seed|theory_rejected",
        "equation_component_implicated": "",
        "branch_seed_if_any": {
          "child_formula_or_law": "",
          "expected_metric_signature": [],
          "kill_criteria": []
        }
      }
    ],
    "approved_for_branch_generation": false
  }
}

Rules:
- If metrics fail, identify the failed layer instead of saying "factor bad".
- If a negative or unexpected implication appears, classify it. Do not discard it silently.
- new_factor_seed and tradable_anomaly require branch_seed_if_any, but approved_for_branch_generation remains false unless the existing human approval gate approves it.
```

- [ ] **Step 5: Add exact discovery prompt block**

In Step1 and Step6 prompt references, add `Equation-To-Factor Discovery Prompt`:

```text
When asked to brainstorm or discover factor ideas, do not start from feature search. Start from equation search.

Procedure:
1. List candidate research equations or quasi-equations.
2. For each equation, state equation_status and evidence_tier.
3. Identify the symmetry, constraint, or invariance.
4. Identify the likely symmetry-breaking or constraint term.
5. Design an observable detector for that term.
6. State measurement_equation.
7. State observable_inputs and required_controls.
8. State expected_metric_signature.
9. State expected_cost_risk_profile, including turnover COGS, volatility drag, max drawdown, and drawdown recovery area.
10. State falsification_tests and kill_criteria.
11. Output candidates as review_only unless human approval explicitly asks to open a formal branch.

Output candidate shape:
{
  "candidate_id": "",
  "source_equation_id": "",
  "equation_status": "",
  "evidence_tier": "",
  "detector_hypothesis": "",
  "observable_inputs": [],
  "measurement_equation": "",
  "required_controls": [],
  "expected_metric_signature": [],
  "expected_cost_risk_profile": [],
  "stochastic_benchmark_terms": [],
  "falsification_tests": [],
  "kill_criteria": [],
  "branch_action": "review_only|human_approval_required",
  "auto_run_allowed": false
}
```

- [ ] **Step 6: Update skill docs to invoke prompt blocks**

In Step1/Step2/Step6 `SKILL.md`, add exact references:

```text
Before generating alpha_idea_master, use the Dirac-Style Step1 Mechanism Extraction Prompt in references/prompts.md.
```

```text
Before generating factor_spec_master or direct_code, use the Dirac-Style Step2 Factor Spec Prompt in references/prompts.md.
```

```text
Before writing Step6 final recommendations, use the Dirac-Style Step6 Council Prompt in references/prompts.md. When asked for new ideas, use the Equation-To-Factor Discovery Prompt.
```

- [ ] **Step 7: Verify prompt compliance**

```bash
python3 -m py_compile scripts/run_factorforge_prompt_contract_smoke.py
python3 scripts/run_factorforge_prompt_contract_smoke.py
python3 scripts/run_factorforge_mechanism_math_v2_smoke.py
python3 scripts/run_factorforge_dirac_discovery_smoke.py
```

Expected:

```text
"verdict": "ACCEPT"
"failed": []
```

- [ ] **Step 8: Commit**

```bash
git add \
  skills/factor-forge-step1/references/prompts.md \
  skills/factor-forge-step1/SKILL.md \
  skills/factor-forge-step2/references/prompts.md \
  skills/factor-forge-step2/SKILL.md \
  skills/factor-forge-step6/references/prompts.md \
  skills/factor-forge-step6/SKILL.md \
  scripts/run_factorforge_prompt_contract_smoke.py \
  docs/operations/factorforge-dirac-style-research-contract.zh-CN.md
git commit -m "Add Dirac-style LLM prompt pack"
```

---

## Final Verification

Run all commands before claiming completion:

```bash
python3 -m py_compile \
  factor_factory/mechanism_math/schema.py \
  factor_factory/mechanism_math/equation_registry.py \
  factor_factory/mechanism_math/equation_quality.py \
  factor_factory/mechanism_math/factor_discovery_queue.py \
  factor_factory/mechanism_math/classifier.py \
  factor_factory/mechanism_math/validator.py \
  factor_factory/mechanism_math/formula_specific.py \
  factor_factory/revision_council/validator.py \
  factor_factory/risk/drawdown_geometry.py \
  skills/factor-forge-step4/scripts/self_quant_adapter.py \
  skills/factor-forge-step4/scripts/run_step4.py \
  skills/factor-forge-step6/scripts/run_step6.py \
  skills/factor-forge-step6/scripts/validate_step6.py \
  scripts/run_factorforge_mechanism_math_v2_smoke.py \
  scripts/run_factorforge_dirac_discovery_smoke.py \
  scripts/run_factorforge_prompt_contract_smoke.py \
  scripts/run_main_agent_mechanism_memo_smoke.py \
  scripts/run_step6_intelligence_acceptance.py
python3 scripts/run_factorforge_mechanism_math_v2_smoke.py
python3 scripts/run_factorforge_dirac_discovery_smoke.py
python3 scripts/run_factorforge_prompt_contract_smoke.py
python3 scripts/run_main_agent_mechanism_memo_smoke.py
python3 scripts/run_agentic_council_operating_protocol_smoke.py
python3 scripts/run_step6_intelligence_acceptance.py
python3 scripts/run_factorforge_unit_tests.py
```

Expected:

```text
mechanism math v2 smoke: verdict=ACCEPT
dirac discovery smoke: verdict=ACCEPT
prompt contract smoke: verdict=ACCEPT
main agent mechanism memo smoke: ACCEPT or zero failed cases
step6 intelligence acceptance: PASS or zero failed cases
unit tests: failed=[]
```

If any environment lacks optional packages, report the exact missing dependency and command:

```text
BLOCK_ENV_DEPENDENCY_MISSING: <package>
```

Do not silently skip.

---

## Final Deliverables

The coder must report:

```text
branch
commits
changed files
research_equation schema fields
research equation registry templates
research equation quality rubric fields and block tokens
observable detector contract fields
equation-to-factor discovery queue fields and artifact paths
Step1/Step2/Step6 prompt block names and installed prompt paths
prompt contract smoke required terms and output
t0_t1_stochastic_benchmark schema fields
formula_implied_information validator status
Dirac anomaly review artifact paths and validator status
Step6 research_equation_review fields
drawdown geometry fields
negative smoke cases added
positive smoke cases added
verification commands and outputs
installed skill sync status
remaining risks
```

Completion means the rules are enforced by validators and smoke tests, not merely documented.
