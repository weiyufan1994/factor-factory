# RTA-07D Ts-Rank Experimental Kernel Hardening Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Harden and formally cover the existing opt-in `ts_rank` Formula-IR experimental kernel path so it can be trusted as an experimental research accelerator without changing production defaults.

**Architecture:** Do not rewrite `ts_rank` from scratch. The current `numpy_rolling_experimental` formula-kernel path already dispatches `ts_rank` through `ts_rank_fast_numpy()`, which is per-ticker and parity-tested in candidate benchmarks. RTA-07D should add explicit smoke coverage, metadata proof, and small code hardening only where needed: default path unchanged, opt-in gate required, ties/NaN/multi-ticker/unsorted input parity, Step3B metadata, parity-failure BLOCK, runtime-guard BLOCK, and `safe_to_make_default=false`.

**Tech Stack:** Python 3, pandas, numpy, existing Formula-IR evaluator, existing `factor_factory.formula.fast_rolling`, existing Step3B formula-kernel profile contract, existing performance smoke.

---

## Scope

Allowed:
- Modify `factor_factory/formula/kernels.py` only if required for clearer metadata or explicit failure handling.
- Modify `factor_factory/formula/evaluator.py` only if required to preserve or clarify the existing opt-in gate.
- Modify `scripts/run_factorforge_performance_smoke.py`.
- Optionally update `docs/operations/factorforge-production-vs-experimental-performance.zh-CN.md` with one short note after smoke passes.

Not allowed:
- Do not modify `factor_factory/formula/operators.py`.
- Do not change default `ts_rank` behavior.
- Do not remove or weaken the separate `FACTORFORGE_TS_RANK_ENGINE` path.
- Do not wire `rolling_corr` or `rolling_cov`.
- Do not install dependencies.
- Do not run `scripts/run_factorforge_ultimate.py` or loop wrappers.
- Do not process clean data.
- Do not run search worker.
- Do not write official promotion.

## Current State To Preserve

Current intended routing:

```python
elif op == 'ts_rank':
    if formula_kernel_config and (formula_kernel_config.get('selected_engine') or 'pandas_optimized') != 'pandas_optimized':
        result = apply_kernel_operator(op, args, _window(args[1]), frame, stats=stats, config=formula_kernel_config)
    else:
        result = ts_rank(args[0], _window(args[1]), frame, stats=stats, engine_config=ts_rank_engine_config)
```

This means:
- default formula kernel path uses the existing `ts_rank()` resolver, which defaults to pandas reference;
- formula-kernel experimental path uses `apply_kernel_operator(..., op='ts_rank')`;
- `numpy_rolling_experimental` currently calls `ts_rank_fast_numpy()`;
- `safe_to_make_default` must stay false.

## Contract

Default behavior:
- `resolve_formula_kernel_engine()` defaults to `pandas_optimized`.
- `FACTORFORGE_ENABLE_EXPERIMENTAL_FORMULA_KERNEL` absent means formula kernel experimental path is not enabled.
- `ts_rank` default path still uses pandas reference unless the separate `FACTORFORGE_TS_RANK_ENGINE` gate is explicitly enabled.

Experimental behavior:
- With `FACTORFORGE_ENABLE_EXPERIMENTAL_FORMULA_KERNEL=1` and `FACTORFORGE_FORMULA_KERNEL_ENGINE=numpy_rolling_experimental`, `ts_rank` uses the numpy per-ticker implementation via `ts_rank_fast_numpy()`.
- `kernel_profile.by_operator.ts_rank.optimized_call_count >= 1`.
- Step3B sample parity runs before full execution and blocks on mismatch.
- runtime guard uses the existing `BLOCK_EXPERIMENTAL_FORMULA_KERNEL_RUNTIME_GUARD`.
- `safe_to_make_default=false`.

## Task 1: Inspect And Minimally Harden Kernel Code

**Files:**
- Modify only if needed: `factor_factory/formula/kernels.py`
- Modify only if needed: `factor_factory/formula/evaluator.py`

- [ ] **Step 1: Confirm ts_rank is supported**

Verify `NUMPY_ROLLING_SUPPORTED_OPERATORS` contains `ts_rank`.

If it does not, add:

```python
'ts_rank',
```

- [ ] **Step 2: Confirm experimental dispatch**

Verify `apply_kernel_operator()` has:

```python
elif op == 'ts_rank':
    result = ts_rank_fast_numpy(args[0], window, frame, stats=None)
    optimized = True
```

If present, do not rewrite it.

- [ ] **Step 3: Preserve evaluator gate**

Verify `evaluator._eval_cached()` only dispatches `ts_rank` to `apply_kernel_operator()` when formula kernel engine is not `pandas_optimized`.

Do not route default `pandas_optimized` through `apply_kernel_operator()` for `ts_rank`.

- [ ] **Step 4: Add metadata detail only if helpful**

If smoke cannot distinguish the formula-kernel `ts_rank` path from the separate `FACTORFORGE_TS_RANK_ENGINE` path, add a non-breaking detail field under `kernel_profile.by_operator.ts_rank`, for example:

```json
"implementation": "ts_rank_fast_numpy"
```

This is optional. Do not change the profile version unless absolutely necessary.

## Task 2: Add Smoke Coverage

**Files:**
- Modify: `scripts/run_factorforge_performance_smoke.py`

- [ ] **Step 1: Add robust fixture**

Add helper:

```python
def build_ts_rank_edge_frame() -> pd.DataFrame:
```

Requirements:
- columns: `ts_code`, `trade_date`, `close`, `volume`
- at least 4 tickers
- includes ties inside rolling windows
- includes NaNs inside rolling windows
- includes incomplete windows
- includes unsorted row order
- preserves all rows after reordering

Example shape:

```python
rows = []
for code in ['A', 'B', 'C', 'D']:
    for idx, dt in enumerate(pd.bdate_range('2020-01-01', periods=16)):
        close = float((idx * 3) % 7)
        volume = float(100 + idx)
        if code == 'B' and idx in {4, 5, 6}:
            close = 3.0
        if code == 'C' and idx == 8:
            close = np.nan
        rows.append({'ts_code': code, 'trade_date': dt.strftime('%Y%m%d'), 'close': close, 'volume': volume})
frame = pd.DataFrame(rows)
return frame.iloc[[*range(2, len(frame), 4), *range(0, len(frame), 4), *range(3, len(frame), 4), *range(1, len(frame), 4)]].reset_index(drop=True)
```

- [ ] **Step 2: Add formula-level parity smoke**

Add case:

```text
formula_kernel_ts_rank_edge_parity
```

Formula:

```text
ts_rank(close, 5)
```

Run reference:

```python
reference = evaluate_formula_frame(formula_ir, frame, engine='reference')
```

Run candidate:

```python
with temporary_envs({
    'FACTORFORGE_ENABLE_EXPERIMENTAL_FORMULA_KERNEL': '1',
    'FACTORFORGE_FORMULA_KERNEL_ENGINE': 'numpy_rolling_experimental',
    'FACTORFORGE_FORMULA_KERNEL_FAULT_INJECTION': None,
    'FACTORFORGE_TS_RANK_ENGINE': None,
    'FACTORFORGE_ENABLE_EXPERIMENTAL_TS_RANK_ENGINE': None,
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
- row count equal
- key order equal
- NaN mask equal
- max abs diff <= `1e-12`
- `kernel_profile.selected_engine == numpy_rolling_experimental`
- `kernel_profile.experimental_enabled is True`
- `kernel_profile.by_operator.ts_rank.optimized_call_count >= 1`
- `kernel_profile.safe_to_make_default is False`

- [ ] **Step 3: Add default path smoke**

Add case:

```text
formula_kernel_ts_rank_default_path_unchanged
```

Run optimized evaluator without formula-kernel experimental env:

```python
with temporary_envs({
    'FACTORFORGE_ENABLE_EXPERIMENTAL_FORMULA_KERNEL': None,
    'FACTORFORGE_FORMULA_KERNEL_ENGINE': None,
    'FACTORFORGE_TS_RANK_ENGINE': None,
    'FACTORFORGE_ENABLE_EXPERIMENTAL_TS_RANK_ENGINE': None,
}):
    kernel_config = resolve_formula_kernel_engine()
    candidate, profile = evaluate_formula_frame(...)
```

Assert:
- output equals reference
- `kernel_profile.selected_engine == pandas_optimized`
- `kernel_profile.experimental_enabled is False`
- no `kernel_profile.by_operator.ts_rank.optimized_call_count`
- `ts_rank_engine_profile.selected_engine == pandas_reference` if present

- [ ] **Step 4: Add separate ts_rank engine coexistence smoke**

Add case:

```text
formula_kernel_ts_rank_engine_gate_coexists
```

Purpose: prove the separate `FACTORFORGE_TS_RANK_ENGINE` gate still works and is not silently replaced by formula kernel changes.

Run with:

```python
with temporary_envs({
    'FACTORFORGE_ENABLE_EXPERIMENTAL_FORMULA_KERNEL': None,
    'FACTORFORGE_FORMULA_KERNEL_ENGINE': None,
    'FACTORFORGE_TS_RANK_ENGINE': 'numpy_sliding_window_experimental',
    'FACTORFORGE_ENABLE_EXPERIMENTAL_TS_RANK_ENGINE': '1',
}):
```

Assert:
- output equals reference
- `kernel_profile.selected_engine == pandas_optimized`
- `kernel_profile.by_operator.ts_rank` absent or optimized count == 0
- `ts_rank_engine_profile.selected_engine == numpy_sliding_window_experimental`
- `ts_rank_engine_profile.experimental_enabled is True`

- [ ] **Step 5: Add Step3B metadata smoke**

Add case:

```text
step3b_formula_kernel_ts_rank_metadata
```

Use existing `run_step3b_formula_kernel_case()` helper with formula:

```text
ts_rank(close, 5)
```

Env:

```python
{
    'FACTORFORGE_ENABLE_EXPERIMENTAL_FORMULA_KERNEL': '1',
    'FACTORFORGE_FORMULA_KERNEL_ENGINE': 'numpy_rolling_experimental',
    'FACTORFORGE_FORMULA_KERNEL_FAULT_INJECTION': None,
    'FACTORFORGE_TS_RANK_ENGINE': None,
    'FACTORFORGE_ENABLE_EXPERIMENTAL_TS_RANK_ENGINE': None,
}
```

Assert metadata `performance_profile.formula_engine_profile.kernel_profile` has:
- `version == factorforge_formula_kernel_profile_v1`
- `selected_engine == numpy_rolling_experimental`
- `experimental_enabled is True`
- `parity_checked is True`
- `parity_nan_mask_equal is True`
- `parity_key_order_equal is True`
- `safe_to_make_default is False`
- `by_operator.ts_rank.optimized_call_count >= 1`

- [ ] **Step 6: Add ts_rank parity-failure smoke**

Add case:

```text
formula_kernel_ts_rank_parity_failure_blocks
```

Use Step3B helper with formula:

```text
ts_rank(close, 5)
```

Env:

```python
{
    'FACTORFORGE_ENABLE_EXPERIMENTAL_FORMULA_KERNEL': '1',
    'FACTORFORGE_FORMULA_KERNEL_ENGINE': 'numpy_rolling_experimental',
    'FACTORFORGE_FORMULA_KERNEL_FAULT_INJECTION': '1',
}
```

Expected:
- rc == 1
- error contains `BLOCK_EXPERIMENTAL_FORMULA_KERNEL_PARITY_FAILED`

- [ ] **Step 7: Add ts_rank runtime guard smoke**

Add case:

```text
formula_kernel_ts_rank_runtime_guard_blocks
```

Use Step3B helper with formula:

```text
ts_rank(close, 5)
```

Env:

```python
{
    'FACTORFORGE_ENABLE_EXPERIMENTAL_FORMULA_KERNEL': '1',
    'FACTORFORGE_FORMULA_KERNEL_ENGINE': 'numpy_rolling_experimental',
    'FACTORFORGE_EXPERIMENTAL_FORMULA_KERNEL_MAX_SECONDS': '0.000001',
}
```

Expected:
- rc == 1
- error contains `BLOCK_EXPERIMENTAL_FORMULA_KERNEL_RUNTIME_GUARD`

## Task 3: Verification

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
python3 scripts/run_factorforge_performance_smoke.py --fresh --root /tmp/factorforge_rta07d_ts_rank_kernel_smoke
```

Expected:
- `verdict=ACCEPT`
- `canonical_pollution=false`
- all new RTA-07D cases pass

- [ ] **Step 3: Report scope**

Confirm:
- default path unchanged
- `operators.py` unchanged
- separate `FACTORFORGE_TS_RANK_ENGINE` path still works
- no `rolling_corr/rolling_cov` changes
- no dependency installed
- no ultimate/loop run
- no clean data/search worker/official promotion

## Reviewer Checklist

Reviewer should verify:
- `ts_rank` optimized output exactly matches pandas reference on ties, NaNs, incomplete windows, multiple tickers, and unsorted row order.
- default path does not route through formula-kernel `ts_rank`.
- separate `FACTORFORGE_TS_RANK_ENGINE` remains functional and gated.
- Step3B metadata records formula-kernel `ts_rank` optimized calls and parity fields.
- fault injection blocks with `BLOCK_EXPERIMENTAL_FORMULA_KERNEL_PARITY_FAILED`.
- runtime guard blocks with `BLOCK_EXPERIMENTAL_FORMULA_KERNEL_RUNTIME_GUARD`.
- `safe_to_make_default` remains false.
- `rolling_corr/rolling_cov` are not touched.

## Expected Handoff Summary

Coder should report:
- Changed files.
- Smoke summary path.
- `py_compile` result.
- Smoke verdict and canonical pollution.
- New RTA-07D case results.
- Confirmation that default path and production semantics are unchanged.
