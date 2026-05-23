# RTA-07F Default Safe NumPy TS Kernels Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Promote correctness-proven low-risk NumPy time-series kernels from opt-in experimental to the default `pandas_optimized` Formula-IR path, with explicit metadata and a hard rollback switch.

**Architecture:** Keep `pandas_reference` as the correctness oracle, but make `pandas_optimized` actually use NumPy kernels for operators whose semantics are already covered by smoke/review: `sum`, `mean`, `min`, `max`, `delta`, `delay`, `argmin`, `argmax`, and `ts_rank`. Keep `std`, `rolling_corr`, and `rolling_cov` out of default promotion for now. Add `FACTORFORGE_DISABLE_DEFAULT_NUMPY_TS_KERNEL=1` to force the old pandas optimized path when needed.

**Tech Stack:** Python 3, pandas, numpy, existing `factor_factory.formula.kernels`, existing Formula-IR evaluator, existing Step3B parity/profile contract, existing performance smoke.

---

## Scope

Allowed:
- Modify `factor_factory/formula/kernels.py`
- Modify `scripts/run_factorforge_performance_smoke.py`
- Optionally modify `factor_factory/formula/evaluator.py` only if needed to keep metadata clear
- Optionally update `docs/operations/factorforge-production-vs-experimental-performance.zh-CN.md`

Not allowed:
- Do not modify `factor_factory/formula/operators.py`.
- Do not default-promote `std` / `stddev`.
- Do not default-promote `rolling_corr` / `rolling_cov`.
- Do not install dependencies.
- Do not run `scripts/run_factorforge_ultimate.py` or loop wrappers unless the user separately authorizes selected Alpha benchmark.
- Do not process clean data.
- Do not run search worker.
- Do not write official promotion.

## Default Promotion Policy

Default-promote:

```python
DEFAULT_NUMPY_TS_OPERATORS = {
    'sum',
    'mean',
    'min',
    'max',
    'delta',
    'delay',
    'argmin',
    'argmax',
    'ts_rank',
}
```

Do not default-promote:

```python
{'std', 'stddev', 'correlation', 'corr', 'covariance', 'rolling_corr', 'rolling_cov'}
```

Rationale:
- `sum/mean/min/max/delta/delay`: simple TS semantics and existing parity coverage.
- `argmin/argmax`: RTA-07C reviewed and accepted.
- `ts_rank`: existing fast path plus RTA-07D proof.
- `std`: ddof/NaN/floating details deserve separate default-promotion review.
- `corr/cov`: RTA-07E semantic gate failed; must be fixed before wiring.

## Runtime Contract

Default behavior after RTA-07F:

```text
FACTORFORGE_FORMULA_KERNEL_ENGINE unset
FACTORFORGE_ENABLE_EXPERIMENTAL_FORMULA_KERNEL unset
```

means:

```text
selected_engine=pandas_optimized
default_numpy_ts_enabled=true
```

and safe TS operators use NumPy kernels.

Rollback:

```text
FACTORFORGE_DISABLE_DEFAULT_NUMPY_TS_KERNEL=1
```

must force old pandas optimized behavior for the default-promoted operators.

Experimental behavior:

```text
FACTORFORGE_ENABLE_EXPERIMENTAL_FORMULA_KERNEL=1
FACTORFORGE_FORMULA_KERNEL_ENGINE=numpy_rolling_experimental
```

still works as before.

`safe_to_make_default` should no longer be a single global false for these default-promoted operators. Preserve backward compatibility by keeping:

```json
"safe_to_make_default": false
```

but add operator-level metadata:

```json
"default_numpy_ts_profile": {
  "enabled": true,
  "rollback_env": "FACTORFORGE_DISABLE_DEFAULT_NUMPY_TS_KERNEL",
  "operators": ["sum", "mean", "min", "max", "delta", "delay", "argmin", "argmax", "ts_rank"],
  "excluded_operators": ["std", "stddev", "corr", "cov", "rolling_corr", "rolling_cov"]
}
```

## Task 1: Add Default NumPy TS Policy

**Files:**
- Modify: `factor_factory/formula/kernels.py`

- [ ] **Step 1: Add policy constants**

Add near existing engine constants:

```python
DEFAULT_NUMPY_TS_OPERATORS = {
    'sum',
    'mean',
    'min',
    'max',
    'delta',
    'delay',
    'argmin',
    'argmax',
    'ts_rank',
}

DEFAULT_NUMPY_TS_EXCLUDED_OPERATORS = {
    'std',
    'stddev',
    'correlation',
    'corr',
    'covariance',
    'rolling_corr',
    'rolling_cov',
}

DEFAULT_NUMPY_TS_ROLLBACK_ENV = 'FACTORFORGE_DISABLE_DEFAULT_NUMPY_TS_KERNEL'
```

- [ ] **Step 2: Add resolver helper**

Add:

```python
def default_numpy_ts_enabled() -> bool:
    return os.getenv(DEFAULT_NUMPY_TS_ROLLBACK_ENV) != '1'
```

Add:

```python
def default_numpy_ts_profile() -> dict[str, Any]:
    enabled = default_numpy_ts_enabled()
    return {
        'version': 'factorforge_default_numpy_ts_profile_v1',
        'enabled': bool(enabled),
        'rollback_env': DEFAULT_NUMPY_TS_ROLLBACK_ENV,
        'operators': sorted(DEFAULT_NUMPY_TS_OPERATORS),
        'excluded_operators': sorted(DEFAULT_NUMPY_TS_EXCLUDED_OPERATORS),
    }
```

- [ ] **Step 3: Add profile to default kernel profile**

Extend `default_kernel_profile()`:

```python
'default_numpy_ts_profile': default_numpy_ts_profile(),
```

Also make `_profile()` refresh this field each time:

```python
profile['default_numpy_ts_profile'] = default_numpy_ts_profile()
```

## Task 2: Promote Safe Operators In pandas_optimized

**Files:**
- Modify: `factor_factory/formula/kernels.py`

- [ ] **Step 1: Add default dispatch branch**

Inside `apply_kernel_operator()`, before the existing `if selected == 'numpy_rolling_experimental':` branch, implement:

```python
if selected == 'pandas_optimized' and default_numpy_ts_enabled() and op in DEFAULT_NUMPY_TS_OPERATORS:
    if op in {'sum', 'mean', 'min', 'max'}:
        result = _numpy_rolling(args[0], window, frame, op)
        optimized = True
    elif op == 'delta':
        result = _numpy_delta(args[0], window, frame)
        optimized = True
    elif op == 'delay':
        result = _numpy_delay(args[0], window, frame)
        optimized = True
    elif op == 'ts_rank':
        result = ts_rank_fast_numpy(args[0], window, frame, stats=None)
        optimized = True
    elif op in {'argmin', 'argmax'}:
        result = _numpy_arg(args[0], window, frame, op)
        optimized = True
    else:
        result = _pandas_operator(op, args, window, frame)
        fallback_reason = f'default_numpy_unsupported:{op}'
```

Then keep existing `elif selected == 'numpy_rolling_experimental':` branch for explicitly experimental mode.

- [ ] **Step 2: Preserve rollback behavior**

When `FACTORFORGE_DISABLE_DEFAULT_NUMPY_TS_KERNEL=1`, `pandas_optimized` must call `_pandas_operator()` for these operators.

Record fallback reason:

```text
default_numpy_ts_disabled
```

only once in `kernel_profile.fallback_reasons`.

- [ ] **Step 3: Do not promote std/corr/cov**

Add smoke-enforced behavior:
- `std/stddev` under default `pandas_optimized` must still have `optimized_call_count == 0`.
- `rolling_corr/rolling_cov` are not handled by `apply_kernel_operator()` in the evaluator and must remain direct pandas path.

Do not add corr/cov to `NUMPY_ROLLING_SUPPORTED_OPERATORS`.

## Task 3: Add Smoke Coverage

**Files:**
- Modify: `scripts/run_factorforge_performance_smoke.py`

- [ ] **Step 1: Add default promotion parity smoke**

Add case:

```text
formula_kernel_default_numpy_ts_promoted_parity
```

Use a formula that touches all promoted operators:

```text
sum(close, 4) + mean(volume, 4) + min(close, 4) + max(volume, 4) + delta(close, 3) + delay(volume, 2) + argmin(close, 4) + argmax(volume, 4) + ts_rank(close, 5)
```

Run reference:

```python
reference = evaluate_formula_frame(formula_ir, frame, engine='reference')
```

Run default optimized with no experimental env:

```python
with temporary_envs({
    'FACTORFORGE_ENABLE_EXPERIMENTAL_FORMULA_KERNEL': None,
    'FACTORFORGE_FORMULA_KERNEL_ENGINE': None,
    'FACTORFORGE_DISABLE_DEFAULT_NUMPY_TS_KERNEL': None,
    'FACTORFORGE_TS_RANK_ENGINE': None,
    'FACTORFORGE_ENABLE_EXPERIMENTAL_TS_RANK_ENGINE': None,
}):
    kernel_config = resolve_formula_kernel_engine()
    candidate, profile = evaluate_formula_frame(..., engine='optimized', return_profile=True, formula_kernel_config=kernel_config)
```

Assert:
- output equals reference, tolerance `1e-12`
- `kernel_profile.selected_engine == pandas_optimized`
- `kernel_profile.experimental_enabled is False`
- `default_numpy_ts_profile.enabled is True`
- each promoted operator has `optimized_call_count >= 1`
- `safe_to_make_default` remains backward-compatible false

- [ ] **Step 2: Add rollback smoke**

Add case:

```text
formula_kernel_default_numpy_ts_rollback_env_restores_pandas
```

Use same formula and frame, with:

```python
'FACTORFORGE_DISABLE_DEFAULT_NUMPY_TS_KERNEL': '1'
```

Assert:
- output equals reference
- `default_numpy_ts_profile.enabled is False`
- promoted operators have `optimized_call_count == 0`
- fallback reasons include `default_numpy_ts_disabled` or by-operator fallback counts reflect pandas path

- [ ] **Step 3: Add std exclusion smoke**

Add case:

```text
formula_kernel_default_numpy_ts_std_excluded
```

Formula:

```text
std(close, 4)
```

Assert under default env:
- output equals reference
- `by_operator.stddev.optimized_call_count == 0`
- fallback count for `stddev >= 1`
- `std` or `stddev` is listed in `default_numpy_ts_profile.excluded_operators`

- [ ] **Step 4: Add corr/cov exclusion smoke**

Add case:

```text
formula_kernel_default_numpy_ts_corr_cov_excluded
```

Formula:

```text
corr(close, volume, 4) + covariance(close, volume, 4)
```

Assert:
- output equals reference with tolerance `1e-10`
- `kernel_profile.by_operator` does not contain optimized `corr/cov`
- `corr/cov/rolling_corr/rolling_cov` are listed in `default_numpy_ts_profile.excluded_operators`

- [ ] **Step 5: Add Step3B metadata smoke**

Add case:

```text
step3b_default_numpy_ts_metadata
```

Use `run_step3b_formula_kernel_case()` with the all-promoted-operator formula and default env:

```python
env={
    'FACTORFORGE_ENABLE_EXPERIMENTAL_FORMULA_KERNEL': None,
    'FACTORFORGE_FORMULA_KERNEL_ENGINE': None,
    'FACTORFORGE_DISABLE_DEFAULT_NUMPY_TS_KERNEL': None,
}
```

Assert Step3B succeeds and metadata has:
- `kernel_profile.selected_engine == pandas_optimized`
- `kernel_profile.experimental_enabled is False`
- `kernel_profile.default_numpy_ts_profile.enabled is True`
- each promoted operator has optimized call count
- `parity_checked is True`
- `parity_nan_mask_equal is True`
- `parity_key_order_equal is True`

- [ ] **Step 6: Add Step3B rollback metadata smoke**

Add case:

```text
step3b_default_numpy_ts_rollback_metadata
```

Use same formula with:

```python
'FACTORFORGE_DISABLE_DEFAULT_NUMPY_TS_KERNEL': '1'
```

Assert:
- `default_numpy_ts_profile.enabled is False`
- promoted operator optimized counts are zero
- output succeeds through pandas path

## Task 4: Verification

**Files:**
- Compile:
  - `factor_factory/formula/kernels.py`
  - `factor_factory/formula/evaluator.py`
  - `scripts/run_factorforge_performance_smoke.py`

- [ ] **Step 1: Compile**

Run:

```bash
python3 -m py_compile \
  factor_factory/formula/kernels.py \
  factor_factory/formula/evaluator.py \
  scripts/run_factorforge_performance_smoke.py
```

Expected: exit code 0.

- [ ] **Step 2: Run performance smoke**

Run:

```bash
python3 scripts/run_factorforge_performance_smoke.py --fresh --root /tmp/factorforge_rta07f_default_numpy_ts_smoke
```

Expected:
- `verdict=ACCEPT`
- `canonical_pollution=false`
- all new RTA-07F cases pass

- [ ] **Step 3: Optional selected Alpha benchmark only with user approval**

Do not run full Alpha benchmark unless user explicitly authorizes it.

If authorized later, use wrapper and report:
- Step3B compute_factor time
- Step3B normalize_sort time
- Step4 time
- kernel_profile optimized operator counts
- any parity BLOCK

## Reviewer Checklist

Reviewer should verify:
- Default `pandas_optimized` now uses NumPy only for the approved operator allowlist.
- Rollback env restores old pandas path.
- `std/stddev` is excluded from default promotion.
- `rolling_corr/rolling_cov` are excluded and not wired.
- Step3B metadata clearly records default NumPy TS usage.
- Reference-vs-default parity covers ties, NaNs, incomplete windows, multiple tickers, and unsorted input order.
- No clean data/search worker/official promotion path touched.

## Expected Handoff Summary

Coder should report:
- Changed files.
- Smoke summary path.
- `py_compile` result.
- Smoke verdict and canonical pollution.
- New RTA-07F case results.
- Default-promoted operator list.
- Rollback env proof.
- Confirmation that `std` and `corr/cov` remain excluded.
