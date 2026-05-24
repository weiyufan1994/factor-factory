# RTA-07G Corr/Cov Default Kernel Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix `rolling_corr` and `rolling_cov` high-speed semantics, then default-enable them only after edge parity passes.

**Architecture:** Keep pandas as the reference semantics. Use NumPy vectorized rolling windows for normal windows, with pandas fallback for near-degenerate windows where pandas' current floating-point behavior is itself the compatibility contract. Preserve one rollback env for all default NumPy TS kernels.

**Tech Stack:** Python, pandas reference operators, NumPy rolling/sliding-window kernels, Formula-IR evaluator, performance smoke.

---

### Task 1: Fix Benchmark Candidate Semantics

**Files:**
- Modify: `factor_factory/formula/operator_candidate_benchmarks.py`
- Modify: `scripts/run_factorforge_operator_candidate_benchmark.py`
- Modify: `scripts/run_factorforge_performance_smoke.py`

- [x] **Step 1: Verify RED**

Run:
```bash
python3 scripts/run_factorforge_operator_candidate_benchmark.py --output /tmp/rta07g_red.json --windows 3,5,10 --ticker-count 24 --days 60 --seed 907
```

Expected: `corr_safe_for_opt_in_kernel=false` and `cov_safe_for_opt_in_kernel=false`.

- [x] **Step 2: Implement hybrid pairwise candidate**

Use NumPy for normal windows and pandas fallback when the rolling covariance/correlation window is near-degenerate.

- [x] **Step 3: Verify GREEN**

Run:
```bash
python3 scripts/run_factorforge_operator_candidate_benchmark.py --output /tmp/rta07g_green.json --windows 3,5,10 --ticker-count 24 --days 60 --seed 907
```

Expected: `corr_safe_for_opt_in_kernel=true`, `cov_safe_for_opt_in_kernel=true`, edge failures `0`.

### Task 2: Wire Corr/Cov Into Default Formula Kernel

**Files:**
- Modify: `factor_factory/formula/kernels.py`
- Modify: `factor_factory/formula/evaluator.py`
- Modify: `scripts/run_factorforge_performance_smoke.py`

- [x] **Step 1: Route Formula-IR corr/cov through `apply_kernel_operator()`**

Default `pandas_optimized` should optimize `corr`, `correlation`, and `covariance` after semantic gate passes.

- [x] **Step 2: Preserve rollback**

With `FACTORFORGE_DISABLE_DEFAULT_NUMPY_TS_KERNEL=1`, `corr/cov` must fall back to pandas.

- [x] **Step 3: Keep std excluded**

Do not default-enable `std/stddev` in this task.

### Task 3: High-Speed Code Policy

**Files:**
- Modify: this plan document only for now.

- [x] **Step 1: Record policy**

Formula-IR operators should prefer proven NumPy/Polars kernels over pandas `groupby.apply`. Non-formula factor implementations should prefer vectorized NumPy/Polars designs and avoid Python row loops unless unavoidable and explicitly justified.

Follow-up policy from architecture review: when Step3B must generate custom
`direct_code` or `hybrid` code instead of Formula-IR, the first implementation
choice should be vectorized NumPy and/or Polars. Pandas is still acceptable as a
correctness reference or compatibility layer, but Python row loops and
`groupby.apply` should require an explicit justification in the implementation
plan and metadata.

### Task 4: Verification

Run:
```bash
python3 -m py_compile factor_factory/formula/kernels.py factor_factory/formula/evaluator.py factor_factory/formula/operator_candidate_benchmarks.py scripts/run_factorforge_operator_candidate_benchmark.py scripts/run_factorforge_performance_smoke.py
python3 scripts/run_factorforge_performance_smoke.py --fresh --root /tmp/factorforge_rta07g_corr_cov_default_kernel_smoke
```

- [x] **Step 1: Run compile and full performance smoke**

Expected:
- `verdict=ACCEPT`
- `canonical_pollution=false`
- corr/cov candidate semantic gate passes
- corr/cov default kernel parity passes
- rollback restores pandas fallback
- std remains excluded
