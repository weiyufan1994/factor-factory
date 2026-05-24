# RTA-09 Direct Code High-Speed Policy Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make non-Formula-IR `direct_code` and `hybrid` implementations prefer vectorized NumPy/Polars and reject unapproved slow Python row loops.

**Architecture:** Extend the existing Step3B validator instead of creating a new enforcement path. The validator will build a deterministic `factorforge_high_speed_code_profile_v1` from generated Python/custom-block source, classify vectorized backends, detect slow row-wise patterns, and require explicit justification for risky patterns. Performance smoke owns the red/green proof.

**Tech Stack:** Python AST, Step3B validator, performance smoke, generated-code contract metadata.

---

### Task 1: Add RED Smoke For Direct Code Slow-Pattern Detection

**Files:**
- Modify: `scripts/run_factorforge_performance_smoke.py`

- [x] **Step 1: Add smoke case importing `build_high_speed_code_profile`**

The new smoke must call the validator helper on two snippets:
- A vectorized NumPy/Polars-friendly implementation with no row loop risk.
- A slow implementation using `iterrows()` or equivalent row-wise patterns.

- [x] **Step 2: Run the targeted case and verify RED**

Run:
```bash
python3 - <<'PY'
from scripts.run_factorforge_performance_smoke import run_direct_code_high_speed_profile_case
print(run_direct_code_high_speed_profile_case())
PY
```

Expected before implementation: failure because `build_high_speed_code_profile` does not exist.

### Task 2: Implement High-Speed Code Profile In Step3B Validator

**Files:**
- Modify: `skills/factor-forge-step3/scripts/validate_step3b.py`

- [x] **Step 1: Add `HIGH_SPEED_CODE_PROFILE_VERSION`**

Use `factorforge_high_speed_code_profile_v1`.

- [x] **Step 2: Implement `build_high_speed_code_profile(text)`**

The profile must record:
- `uses_numpy`
- `uses_polars`
- `uses_pandas`
- `vectorized_backend_present`
- `slow_patterns`
- `requires_justification`
- `preferred_backends`
- `avoid_by_default`

- [x] **Step 3: Implement `assert_high_speed_code_policy(text, contract)`**

If slow patterns are present, require a non-empty `performance_justification` or `allow_slow_patterns=true` in the relevant contract/block. Otherwise raise `BLOCK_DIRECT_CODE_PERFORMANCE_RISK`.

### Task 3: Enforce Direct Code And Hybrid Custom Blocks

**Files:**
- Modify: `skills/factor-forge-step3/scripts/validate_step3b.py`
- Modify: `scripts/run_factorforge_performance_smoke.py`

- [x] **Step 1: Call the policy from `validate_direct_code_mode()`**

Direct code must be scanned after leakage checks and before fixture smoke.

- [x] **Step 2: Call the policy from `assert_hybrid_custom_source_safe()`**

Hybrid custom blocks must use the same slow-pattern logic, with the custom block as its contract source.

- [x] **Step 3: Add smoke cases**

Add cases proving:
- Vectorized direct code profile passes.
- Direct code with `iterrows()` blocks without justification.
- Direct code with a justification passes profile-level policy.
- Hybrid custom block with `groupby.apply` blocks without justification.

### Task 4: Update Documentation

**Files:**
- Modify: `skills/factor-forge-step3/SKILL.md`
- Modify: `docs/contracts/step3-contract.md`
- Modify: `docs/contracts/step3-contract.zh-CN.md`

- [x] **Step 1: Document the policy**

Generated `direct_code` and `hybrid` custom blocks should prefer NumPy/Polars, may use pandas vectorized APIs, and must justify Python row loops or pandas `groupby.apply`.

### Task 5: Verification

Run:
```bash
python3 -m py_compile skills/factor-forge-step3/scripts/validate_step3b.py scripts/run_factorforge_performance_smoke.py
python3 scripts/run_factorforge_performance_smoke.py --fresh --root /tmp/factorforge_rta09_direct_code_high_speed_smoke
```

Expected:
- `verdict=ACCEPT`
- `canonical_pollution=false`
- New RTA-09 cases pass
- Existing RTA-07 default kernel cases still pass
