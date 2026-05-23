# RTA-07C Argmin/Argmax Experimental Kernel Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add opt-in experimental Formula-IR kernels for `argmin` and `argmax`, using the RTA-07B parity-passing numpy per-ticker candidates, without changing the default production path.

**Architecture:** Extend the existing `factor_factory.formula.kernels` framework to support `argmin` and `argmax` under `numpy_rolling_experimental` only. Wire `factor_factory.formula.evaluator._eval_cached()` to call `apply_kernel_operator()` for `argmin/argmax` only when the formula kernel engine is experimental; otherwise keep the current direct pandas operator path. Reuse Step3B's existing experimental parity and runtime-guard machinery.

**Tech Stack:** Python 3, pandas, numpy, existing Formula-IR evaluator, existing Step3B formula-kernel profile contract, existing performance smoke.

---

## Scope

Allowed:
- Modify `factor_factory/formula/kernels.py`
- Modify `factor_factory/formula/evaluator.py`
- Modify `scripts/run_factorforge_performance_smoke.py`
- Optionally read `factor_factory/formula/operator_candidate_benchmarks.py` for implementation reference

Not allowed:
- Do not modify `factor_factory/formula/operators.py`.
- Do not wire `rolling_corr` or `rolling_cov` in this phase.
- Do not make experimental kernels default.
- Do not install dependencies.
- Do not run `scripts/run_factorforge_ultimate.py` or loop wrappers.
- Do not process clean data.
- Do not run search worker.
- Do not write official promotion.

## Contract

Default behavior:
- `argmin/argmax` continue using `operators.ts_argmin()` and `operators.ts_argmax()`.
- `resolve_formula_kernel_engine()` still defaults to `pandas_optimized`.
- `FACTORFORGE_ENABLE_EXPERIMENTAL_FORMULA_KERNEL=1` remains required for `numpy_rolling_experimental`.

Experimental behavior:
- With `FACTORFORGE_ENABLE_EXPERIMENTAL_FORMULA_KERNEL=1` and `FACTORFORGE_FORMULA_KERNEL_ENGINE=numpy_rolling_experimental`, `argmin/argmax` may use optimized numpy per-ticker kernels.
- Profile must record optimized calls under `kernel_profile.by_operator.argmin` and `kernel_profile.by_operator.argmax`.
- `safe_to_make_default` must remain `false`.
- Step3B parity failure must still BLOCK with `BLOCK_EXPERIMENTAL_FORMULA_KERNEL_PARITY_FAILED`.
- Runtime guard must still BLOCK with `BLOCK_EXPERIMENTAL_FORMULA_KERNEL_RUNTIME_GUARD`.

## Task 1: Extend Kernel Implementation

**Files:**
- Modify: `factor_factory/formula/kernels.py`

- [ ] **Step 1: Add supported operators**

Add `argmin` and `argmax` to `NUMPY_ROLLING_SUPPORTED_OPERATORS`.

Expected:

```python
NUMPY_ROLLING_SUPPORTED_OPERATORS = {
    'sum',
    'mean',
    'std',
    'stddev',
    'min',
    'max',
    'delta',
    'delay',
    'ts_rank',
    'argmin',
    'argmax',
}
```

- [ ] **Step 2: Add pandas reference fallback**

Extend `_pandas_operator()`:

```python
if op == 'argmin':
    return series.groupby(frame['ts_code'], sort=False).transform(
        lambda s: s.rolling(window, min_periods=window).apply(lambda values: float(np.argmin(values)) + 1.0, raw=True)
    )
if op == 'argmax':
    return series.groupby(frame['ts_code'], sort=False).transform(
        lambda s: s.rolling(window, min_periods=window).apply(lambda values: float(np.argmax(values)) + 1.0, raw=True)
    )
```

This fallback must match current `operators.py` semantics exactly.

- [ ] **Step 3: Add numpy rolling arg helper**

Add:

```python
def _rolling_arg_numpy_one(values: np.ndarray, window: int, op: str) -> np.ndarray:
    out = np.full(len(values), np.nan, dtype='float64')
    if window <= 0 or len(values) < window:
        return out
    windows = np.lib.stride_tricks.sliding_window_view(values, window_shape=window)
    valid = ~np.isnan(windows).any(axis=1)
    if not valid.any():
        return out
    valid_windows = windows[valid]
    if op == 'argmin':
        raw = np.argmin(valid_windows, axis=1)
    elif op == 'argmax':
        raw = np.argmax(valid_windows, axis=1)
    else:
        raise ValueError(f'unsupported numpy arg op: {op}')
    out[np.flatnonzero(valid) + window - 1] = raw.astype('float64', copy=False) + 1.0
    return out
```

Then add:

```python
def _numpy_arg(series: pd.Series, window: int, frame: pd.DataFrame, op: str) -> pd.Series:
    values = pd.to_numeric(series, errors='coerce').to_numpy(dtype='float64', copy=False)
    result = np.full(len(values), np.nan, dtype='float64')
    for positions in _group_positions(frame):
        if len(positions) == 0:
            continue
        result[positions] = _rolling_arg_numpy_one(values[positions], window, op)
    return pd.Series(result, index=series.index, name=series.name)
```

Semantics:
- group by `ts_code`, `sort=False`
- no cross-ticker windows
- incomplete windows output NaN
- any NaN inside the window outputs NaN
- ties use first occurrence, 1-based index, matching `np.argmin/np.argmax`

- [ ] **Step 4: Dispatch experimental operators**

Inside `apply_kernel_operator()`, under `selected == 'numpy_rolling_experimental'`, add:

```python
elif op in {'argmin', 'argmax'}:
    result = _numpy_arg(args[0], window, frame, op)
    optimized = True
```

Do not add `rolling_corr` or `rolling_cov`.

- [ ] **Step 5: Preserve fault injection**

The existing `FACTORFORGE_FORMULA_KERNEL_FAULT_INJECTION=1` mutation block must also mutate argmin/argmax optimized outputs. Do not special-case it away.

## Task 2: Wire Evaluator Under Experimental Gate

**Files:**
- Modify: `factor_factory/formula/evaluator.py`

- [ ] **Step 1: Route argmin/argmax only when experimental**

In `_eval_cached()`, replace the current direct calls:

```python
elif op == 'argmin':
    result = ts_argmin(args[0], _window(args[1]), frame)
elif op == 'argmax':
    result = ts_argmax(args[0], _window(args[1]), frame)
```

with:

```python
elif op == 'argmin':
    if (formula_kernel_config or {}).get('experimental_enabled'):
        result = apply_kernel_operator(op, args, _window(args[1]), frame, stats=stats, config=formula_kernel_config)
    else:
        result = ts_argmin(args[0], _window(args[1]), frame)
elif op == 'argmax':
    if (formula_kernel_config or {}).get('experimental_enabled'):
        result = apply_kernel_operator(op, args, _window(args[1]), frame, stats=stats, config=formula_kernel_config)
    else:
        result = ts_argmax(args[0], _window(args[1]), frame)
```

This preserves default behavior and avoids changing non-experimental profile counts for argmin/argmax.

- [ ] **Step 2: Do not touch reference evaluator**

Do not change `_eval()`. The reference path must keep using `operators.ts_argmin/ts_argmax`.

## Task 3: Add Smoke Coverage

**Files:**
- Modify: `scripts/run_factorforge_performance_smoke.py`

- [ ] **Step 1: Add formula-level parity smoke**

Add case:

```text
formula_kernel_argmin_argmax_parity
```

Use `build_kernel_formula_frame()` and formula:

```text
argmin(close, 4) + argmax(volume, 4)
```

Run reference via `evaluate_formula_frame(..., engine='reference')`.

Run candidate with:

```python
with temporary_envs({
    'FACTORFORGE_ENABLE_EXPERIMENTAL_FORMULA_KERNEL': '1',
    'FACTORFORGE_FORMULA_KERNEL_ENGINE': 'numpy_rolling_experimental',
}):
    kernel_config = resolve_formula_kernel_engine()
    candidate, profile = evaluate_formula_frame(
        formula_ir,
        frame,
        engine='optimized',
        return_profile=True,
        formula_kernel_config=kernel_config,
    )
```

Assert:
- NaN mask equal
- max abs diff <= `1e-12`
- `kernel_profile.by_operator.argmin.optimized_call_count >= 1`
- `kernel_profile.by_operator.argmax.optimized_call_count >= 1`
- `kernel_profile.safe_to_make_default is False`

- [ ] **Step 2: Add default path smoke**

Add case:

```text
formula_kernel_argmin_argmax_default_path_unchanged
```

Run optimized evaluator without experimental env using formula:

```text
argmin(close, 4) + argmax(volume, 4)
```

Assert:
- output equals reference
- no `kernel_profile.by_operator.argmin.optimized_call_count`
- no `kernel_profile.by_operator.argmax.optimized_call_count`
- selected engine is still `pandas_optimized`

- [ ] **Step 3: Add Step3B opt-in metadata smoke**

Add case:

```text
step3b_formula_kernel_argmin_argmax_metadata
```

Use existing `run_step3b_formula_kernel_case()` helper with formula:

```text
argmin(close, 4) + argmax(volume, 4)
```

Environment:

```python
{
    'FACTORFORGE_ENABLE_EXPERIMENTAL_FORMULA_KERNEL': '1',
    'FACTORFORGE_FORMULA_KERNEL_ENGINE': 'numpy_rolling_experimental',
}
```

Assert Step3B succeeds and metadata `performance_profile.formula_engine_profile.kernel_profile` has:
- `version == factorforge_formula_kernel_profile_v1`
- `selected_engine == numpy_rolling_experimental`
- `experimental_enabled is True`
- `parity_checked is True`
- `parity_nan_mask_equal is True`
- `parity_key_order_equal is True`
- `safe_to_make_default is False`
- `by_operator.argmin.optimized_call_count >= 1`
- `by_operator.argmax.optimized_call_count >= 1`

- [ ] **Step 4: Extend parity-failure smoke**

Add case:

```text
formula_kernel_argmin_argmax_parity_failure_blocks
```

Use Step3B helper with:

```python
env={
    'FACTORFORGE_ENABLE_EXPERIMENTAL_FORMULA_KERNEL': '1',
    'FACTORFORGE_FORMULA_KERNEL_ENGINE': 'numpy_rolling_experimental',
    'FACTORFORGE_FORMULA_KERNEL_FAULT_INJECTION': '1',
}
```

Formula:

```text
argmin(close, 4) + argmax(volume, 4)
```

Expected:
- rc == 1
- error contains `BLOCK_EXPERIMENTAL_FORMULA_KERNEL_PARITY_FAILED`

- [ ] **Step 5: Keep runtime guard coverage**

The existing `formula_kernel_runtime_guard_blocks` may already cover runtime guard with mean/sum. Add argmin/argmax-specific coverage only if implementation bypasses `_record_call()` accidentally.

If added, case name:

```text
formula_kernel_argmin_argmax_runtime_guard_blocks
```

Expected token:

```text
BLOCK_EXPERIMENTAL_FORMULA_KERNEL_RUNTIME_GUARD
```

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
python3 scripts/run_factorforge_performance_smoke.py --fresh --root /tmp/factorforge_rta07c_argmin_argmax_kernel_smoke
```

Expected:
- `verdict=ACCEPT`
- `canonical_pollution=false`
- all new RTA-07C cases pass

- [ ] **Step 3: Report scope**

Confirm:
- `operators.py` unchanged
- `rolling_corr/rolling_cov` not wired
- default path unchanged
- no dependency installed
- no ultimate/loop run
- no clean data/search worker/official promotion

## Reviewer Checklist

Reviewer should verify:
- `argmin/argmax` optimized outputs exactly match current pandas reference on ties, NaNs, incomplete windows, and multiple tickers.
- Default path does not route argmin/argmax through experimental kernels.
- Step3B opt-in path records kernel profile and parity checks.
- Fault injection for argmin/argmax blocks, proving parity guard covers the new operators.
- `safe_to_make_default` remains false.
- `rolling_corr/rolling_cov` are not accidentally wired.

## Expected Handoff Summary

Coder should report:
- Changed files.
- Smoke summary path.
- `py_compile` result.
- Smoke verdict and canonical pollution.
- New case results.
- Confirmation that default production path is unchanged and only opt-in experimental argmin/argmax is added.
