# RTA-07B Operator Candidate Benchmark Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a read-only benchmark/parity harness for the highest-risk Formula-IR operators (`rolling_corr`, `rolling_cov`, `ts_argmin`, `ts_argmax`, and existing `ts_rank` candidates) without changing production operator semantics or defaults.

**Architecture:** Add isolated candidate implementations under `factor_factory/formula/` and a standalone benchmark CLI under `scripts/`. The CLI compares each candidate against the current pandas reference implementation on deterministic fixtures, records speed/memory/parity, and emits a JSON recommendation matrix. No candidate is wired into `operators.py`, `kernels.py`, Step3B, or production runtime in this phase.

**Tech Stack:** Python 3, pandas, numpy, stdlib `tracemalloc`, existing Formula-IR reference operators, existing performance smoke framework.

---

## Scope

Allowed:
- Create `factor_factory/formula/operator_candidate_benchmarks.py`
- Create `scripts/run_factorforge_operator_candidate_benchmark.py`
- Modify `scripts/run_factorforge_performance_smoke.py`
- Optionally update `docs/operations/factorforge-production-vs-experimental-performance.zh-CN.md` with a short pointer after smoke passes

Not allowed:
- Do not modify `factor_factory/formula/operators.py`.
- Do not modify `factor_factory/formula/kernels.py`.
- Do not change Step3B/Step4 production defaults.
- Do not install TA-Lib, numba, bottleneck, numbagg, window-ops, or any dependency.
- Do not run `scripts/run_factorforge_ultimate.py` or loop wrappers.
- Do not process clean data.
- Do not run search worker.
- Do not write official promotion.
- Do not benchmark full Alpha runs unless the user separately authorizes it.

## Output Contract

The benchmark CLI must write JSON:

```json
{
  "version": "factorforge_operator_candidate_benchmark_v1",
  "generated_at": "2026-05-23T00:00:00Z",
  "repo_root": "/Users/humphrey/projects/factor-factory",
  "read_only": true,
  "production_semantics_changed": false,
  "operators": [],
  "cases": [],
  "recommendations": [],
  "diagnostics": [],
  "canonical_pollution": false
}
```

Required diagnostics:
- `OPERATOR_CANDIDATE_BENCHMARK_READ_ONLY`
- `PRODUCTION_OPERATOR_PATH_UNCHANGED`
- `ARGMIN_ARGMAX_CANDIDATES_BENCHMARKED`
- `CORR_COV_CANDIDATES_BENCHMARKED`
- `TS_RANK_EXISTING_CANDIDATES_INCLUDED`

The output must never mark a candidate as production-ready. Use:

```json
"safe_to_wire_into_step3b": false
```

for every candidate and every recommendation.

## Task 1: Add Candidate Benchmark Module

**Files:**
- Create: `factor_factory/formula/operator_candidate_benchmarks.py`

- [ ] **Step 1: Define candidate result model**

Create:

```python
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

import numpy as np
import pandas as pd

from factor_factory.formula import operators
from factor_factory.formula.ts_rank_candidates import (
    CandidateResult,
    available_candidates as available_ts_rank_candidates,
    compare_candidate_to_reference,
    prepare_ts_rank_frame,
)


@dataclass(frozen=True)
class OperatorCandidateResult:
    operator: str
    candidate: str
    status: str
    values: pd.Series | None
    skip_reason: str | None = None
    failure_reason: str | None = None
    experimental: bool = True
    safe_to_wire_into_step3b: bool = False
```

- [ ] **Step 2: Implement reference operators**

Implement:

```python
def reference_argmin(frame: pd.DataFrame, value_col: str, window: int) -> OperatorCandidateResult:
    values = pd.to_numeric(frame[value_col], errors="coerce")
    return OperatorCandidateResult("ts_argmin", "pandas_reference", "PASS", operators.ts_argmin(values, window, frame), experimental=False)


def reference_argmax(frame: pd.DataFrame, value_col: str, window: int) -> OperatorCandidateResult:
    values = pd.to_numeric(frame[value_col], errors="coerce")
    return OperatorCandidateResult("ts_argmax", "pandas_reference", "PASS", operators.ts_argmax(values, window, frame), experimental=False)


def reference_corr(frame: pd.DataFrame, left_col: str, right_col: str, window: int) -> OperatorCandidateResult:
    left = pd.to_numeric(frame[left_col], errors="coerce")
    right = pd.to_numeric(frame[right_col], errors="coerce")
    return OperatorCandidateResult("rolling_corr", "pandas_reference", "PASS", operators.rolling_corr(left, right, window, frame), experimental=False)


def reference_cov(frame: pd.DataFrame, left_col: str, right_col: str, window: int) -> OperatorCandidateResult:
    left = pd.to_numeric(frame[left_col], errors="coerce")
    right = pd.to_numeric(frame[right_col], errors="coerce")
    return OperatorCandidateResult("rolling_cov", "pandas_reference", "PASS", operators.rolling_cov(left, right, window, frame), experimental=False)
```

- [ ] **Step 3: Implement numpy argmin/argmax candidate**

Implement a per-ticker numpy candidate. It may use `np.lib.stride_tricks.sliding_window_view`; this is benchmark-only and must not be wired into production.

Rules:
- group only by `ts_code`
- preserve input row index
- return NaN when `window <= 0`, not enough rows, or any NaN exists in the window
- tie behavior must match `np.argmin` / `np.argmax`: first occurrence, 1-based index

Required helper:

```python
def _rolling_arg_one(values: np.ndarray, window: int, mode: str) -> np.ndarray:
    out = np.full(len(values), np.nan, dtype="float64")
    if window <= 0 or len(values) < window:
        return out
    windows = np.lib.stride_tricks.sliding_window_view(values, window_shape=window)
    valid = ~np.isnan(windows).any(axis=1)
    if not valid.any():
        return out
    if mode == "argmin":
        raw = np.argmin(windows[valid], axis=1)
    elif mode == "argmax":
        raw = np.argmax(windows[valid], axis=1)
    else:
        raise ValueError(f"unsupported arg mode: {mode}")
    out[np.flatnonzero(valid) + window - 1] = raw.astype("float64") + 1.0
    return out
```

Expose:

```python
def numpy_argmin_per_ticker(frame: pd.DataFrame, value_col: str, window: int) -> OperatorCandidateResult
def numpy_argmax_per_ticker(frame: pd.DataFrame, value_col: str, window: int) -> OperatorCandidateResult
```

- [ ] **Step 4: Implement rolling corr/cov formula candidate**

Implement a per-ticker numpy formula candidate using complete-window semantics.

Rules:
- group only by `ts_code`
- preserve input row index
- return NaN when `window <= 1`, not enough rows, any NaN exists in either input window, or corr denominator is zero
- `cov` must match pandas sample covariance `ddof=1`
- `corr` must equal `cov / sqrt(var_x * var_y)` using sample variance terms
- use tolerance in comparison; do not assume exact equality

Required helper:

```python
def _rolling_pairwise_one(left: np.ndarray, right: np.ndarray, window: int, mode: str) -> np.ndarray:
    out = np.full(len(left), np.nan, dtype="float64")
    if window <= 1 or len(left) < window:
        return out
    lw = np.lib.stride_tricks.sliding_window_view(left, window_shape=window)
    rw = np.lib.stride_tricks.sliding_window_view(right, window_shape=window)
    valid = (~np.isnan(lw).any(axis=1)) & (~np.isnan(rw).any(axis=1))
    if not valid.any():
        return out
    lx = lw[valid]
    ry = rw[valid]
    lx_mean = lx.mean(axis=1)
    ry_mean = ry.mean(axis=1)
    lx_centered = lx - lx_mean[:, None]
    ry_centered = ry - ry_mean[:, None]
    cov = (lx_centered * ry_centered).sum(axis=1) / float(window - 1)
    if mode == "cov":
        values = cov
    elif mode == "corr":
        var_l = (lx_centered * lx_centered).sum(axis=1) / float(window - 1)
        var_r = (ry_centered * ry_centered).sum(axis=1) / float(window - 1)
        denom = np.sqrt(var_l * var_r)
        values = np.full(len(cov), np.nan, dtype="float64")
        nonzero = denom != 0.0
        values[nonzero] = cov[nonzero] / denom[nonzero]
    else:
        raise ValueError(f"unsupported pairwise mode: {mode}")
    out[np.flatnonzero(valid) + window - 1] = values
    return out
```

Expose:

```python
def numpy_corr_formula_per_ticker(frame: pd.DataFrame, left_col: str, right_col: str, window: int) -> OperatorCandidateResult
def numpy_cov_formula_per_ticker(frame: pd.DataFrame, left_col: str, right_col: str, window: int) -> OperatorCandidateResult
```

- [ ] **Step 5: Add parity helper**

Implement:

```python
def compare_series_to_reference(
    frame: pd.DataFrame,
    reference: pd.Series,
    candidate: pd.Series,
    *,
    tolerance: float,
) -> dict:
```

Return:

```json
{
  "row_count_equal": true,
  "key_order_equal": true,
  "nan_mask_equal": true,
  "max_abs_diff": 0.0,
  "rank_corr": 1.0,
  "parity_pass": true
}
```

`key_order_equal` should verify that candidate and reference align to the same frame row order, not that the frame is globally sorted. This benchmark must include unsorted fixtures, because production operators currently use input order within each `ts_code` group.

- [ ] **Step 6: Add candidate registries**

Expose:

```python
def available_operator_candidates() -> dict[str, dict[str, Callable]]:
    return {
        "ts_argmin": {
            "pandas_reference": reference_argmin,
            "numpy_argmin_per_ticker": numpy_argmin_per_ticker,
        },
        "ts_argmax": {
            "pandas_reference": reference_argmax,
            "numpy_argmax_per_ticker": numpy_argmax_per_ticker,
        },
        "rolling_corr": {
            "pandas_reference": reference_corr,
            "numpy_corr_formula_per_ticker": numpy_corr_formula_per_ticker,
        },
        "rolling_cov": {
            "pandas_reference": reference_cov,
            "numpy_cov_formula_per_ticker": numpy_cov_formula_per_ticker,
        },
    }
```

Also expose a wrapper to include existing `ts_rank` candidates from `factor_factory.formula.ts_rank_candidates.available_candidates()`.

## Task 2: Add Benchmark CLI

**Files:**
- Create: `scripts/run_factorforge_operator_candidate_benchmark.py`

- [ ] **Step 1: Add CLI skeleton**

Create a CLI with:

```python
#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
import time
import tracemalloc
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

VERSION = "factorforge_operator_candidate_benchmark_v1"
CANONICAL_DIRS = ["objects", "runs", "evaluations", "generated_code", "archive", "factorforge", "data/clean"]
```

Arguments:

```text
--output PATH
--allow-non-tmp-output
--windows 5,10,20
--ticker-count 120
--days 180
--seed 707
--include-ts-rank
```

Default behavior must include `ts_argmin`, `ts_argmax`, `rolling_corr`, and `rolling_cov`. `ts_rank` is included when `--include-ts-rank` is set.

If output is not under `/tmp/` or `/private/tmp/` and `--allow-non-tmp-output` is absent, exit non-zero with:

```text
BLOCK_OPERATOR_CANDIDATE_BENCHMARK_NON_TMP_OUTPUT
```

- [ ] **Step 2: Add deterministic fixtures**

Implement:

```python
def panel_fixture(*, ticker_count: int, days: int, seed: int, unsorted: bool) -> pd.DataFrame:
```

Columns:
- `ts_code`
- `trade_date`
- `value`
- `left`
- `right`

Fixture requirements:
- at least three tickers with NaN windows
- at least two tickers with ties
- at least one constant segment for corr denominator zero
- if `unsorted=True`, reorder rows without dropping rows; do not globally sort before running candidates

Run cases:
- `small_ties_nan_unsorted`
- `medium_panel_sorted`
- `medium_panel_unsorted`

- [ ] **Step 3: Run candidates**

Implement:

```python
def run_candidate(operator: str, candidate_name: str, func, frame: pd.DataFrame, window: int, reference_values: pd.Series | None) -> dict[str, Any]:
```

The result must include:

```json
{
  "operator": "ts_argmin",
  "candidate": "numpy_argmin_per_ticker",
  "status": "PASS",
  "seconds": 0.001,
  "rows_per_second": 1000000.0,
  "peak_memory_mb": 1.0,
  "parity_pass": true,
  "row_count_equal": true,
  "key_order_equal": true,
  "nan_mask_equal": true,
  "max_abs_diff": 0.0,
  "rank_corr": 1.0,
  "speedup_vs_reference": 2.0,
  "safe_to_wire_into_step3b": false,
  "skip_reason": null,
  "failure_reason": null
}
```

Reference candidates must always report `safe_to_wire_into_step3b=false` too; this phase is observational.

- [ ] **Step 4: Include existing ts_rank candidates**

When `--include-ts-rank` is provided, call existing `factor_factory.formula.ts_rank_candidates.available_candidates()`.

Rules:
- Use existing `prepare_ts_rank_frame()` for `ts_rank` because that benchmark already sorts by `ts_code, trade_date`.
- Mark in output:

```json
"ts_rank_fixture_sorted_by_benchmark": true
```

This distinction matters because `argmin/argmax/corr/cov` cases must also test unsorted input-order parity.

- [ ] **Step 5: Add recommendations**

For each operator, select the fastest candidate with:
- `status == "PASS"`
- `parity_pass == true`
- `candidate != "pandas_reference"`
- `speedup_vs_reference > 1.0`

Emit recommendation:

```json
{
  "operator": "ts_argmin",
  "recommended_candidate": "numpy_argmin_per_ticker",
  "speedup_vs_reference": 2.0,
  "reason": "fastest parity-passing candidate in benchmark fixtures",
  "safe_to_wire_into_step3b": false,
  "next_phase_required": "RTA-07C opt-in experimental kernel implementation with smoke and reviewer approval"
}
```

If no candidate qualifies:

```json
{
  "operator": "rolling_corr",
  "recommended_candidate": null,
  "reason": "no parity-passing candidate exceeded pandas reference speed",
  "safe_to_wire_into_step3b": false,
  "next_phase_required": "keep pandas reference until better candidate exists"
}
```

- [ ] **Step 6: Add canonical pollution guard**

Snapshot canonical dirs before and after benchmark. Only the explicit output path may be written.

`canonical_pollution` must be `false` unless the CLI itself wrote into canonical dirs, which should be blocked by the non-`/tmp` guard.

## Task 3: Add Performance Smoke Coverage

**Files:**
- Modify: `scripts/run_factorforge_performance_smoke.py`

- [ ] **Step 1: Add compile target**

Add:

```text
factor_factory/formula/operator_candidate_benchmarks.py
scripts/run_factorforge_operator_candidate_benchmark.py
```

to the existing py_compile case.

- [ ] **Step 2: Add CLI contract smoke**

Add case:

```text
operator_candidate_benchmark_contract
```

Run:

```bash
python3 scripts/run_factorforge_operator_candidate_benchmark.py \
  --output /tmp/<fresh_root>/operator_candidate_benchmark.json \
  --windows 5,10 \
  --ticker-count 24 \
  --days 60 \
  --seed 707 \
  --include-ts-rank
```

Assert:
- `version == "factorforge_operator_candidate_benchmark_v1"`
- `production_semantics_changed is False`
- diagnostics contain `PRODUCTION_OPERATOR_PATH_UNCHANGED`
- `canonical_pollution is False`
- operators include `ts_argmin`, `ts_argmax`, `rolling_corr`, `rolling_cov`, `ts_rank`

- [ ] **Step 3: Add argmin/argmax parity smoke**

Add case:

```text
operator_candidate_benchmark_argmin_argmax_parity
```

Assert for every non-reference `ts_argmin` and `ts_argmax` result:
- `row_count_equal is True`
- `key_order_equal is True`
- `nan_mask_equal is True`
- `max_abs_diff <= 1e-12`
- `parity_pass is True`
- `safe_to_wire_into_step3b is False`

- [ ] **Step 4: Add corr/cov parity smoke**

Add case:

```text
operator_candidate_benchmark_corr_cov_parity
```

Assert for every non-reference `rolling_corr` and `rolling_cov` result with `status == "PASS"`:
- `row_count_equal is True`
- `key_order_equal is True`
- `nan_mask_equal is True`
- `max_abs_diff <= 1e-10`
- `parity_pass is True`
- `safe_to_wire_into_step3b is False`

If a candidate fails parity, the smoke must fail. Do not convert parity failure into a recommendation.

- [ ] **Step 5: Add non-/tmp block smoke**

Add case:

```text
operator_candidate_benchmark_blocks_non_tmp_output_unless_explicit
```

Run without `--allow-non-tmp-output` against repo-local output:

```text
docs/.tmp_operator_candidate_benchmark_should_block_<pid>.json
```

Expected:
- non-zero return code
- output contains `BLOCK_OPERATOR_CANDIDATE_BENCHMARK_NON_TMP_OUTPUT`
- file does not exist

- [ ] **Step 6: Add no production path mutation smoke**

Add case:

```text
operator_candidate_benchmark_does_not_modify_formula_runtime
```

Before and after the CLI run, compute SHA256 for:

```text
factor_factory/formula/operators.py
factor_factory/formula/kernels.py
skills/factor-forge-step3/scripts/run_step3b.py
skills/factor-forge-step4/scripts/run_step4.py
```

Assert hashes unchanged.

## Task 4: Verification

**Files:**
- Compile and smoke only. Do not run full ultimate.

- [ ] **Step 1: Compile**

Run:

```bash
python3 -m py_compile \
  factor_factory/formula/operator_candidate_benchmarks.py \
  scripts/run_factorforge_operator_candidate_benchmark.py \
  scripts/run_factorforge_performance_smoke.py
```

Expected: exit code 0.

- [ ] **Step 2: Run standalone benchmark**

Run:

```bash
python3 scripts/run_factorforge_operator_candidate_benchmark.py \
  --output /tmp/factorforge_rta07b_operator_candidate_benchmark.json \
  --windows 5,10,20 \
  --ticker-count 120 \
  --days 180 \
  --seed 707 \
  --include-ts-rank
```

Expected:
- exit code 0
- output JSON exists
- `version=factorforge_operator_candidate_benchmark_v1`
- `production_semantics_changed=false`
- `canonical_pollution=false`
- recommendations all have `safe_to_wire_into_step3b=false`

- [ ] **Step 3: Run performance smoke**

Run:

```bash
python3 scripts/run_factorforge_performance_smoke.py --fresh --root /tmp/factorforge_rta07b_operator_candidate_smoke
```

Expected:
- `verdict=ACCEPT`
- `canonical_pollution=false`
- all new RTA-07B cases pass

## Reviewer Checklist

Reviewer should verify:
- No production Formula-IR operator path changed.
- Candidate implementations preserve pandas reference semantics on ties, NaNs, incomplete windows, zero-variance corr, and unsorted input order.
- `rolling_corr/cov` parity uses a suitable tolerance and does not silently accept NaN-mask mismatch.
- `ts_rank` benchmark inclusion is clearly labeled as sorted-by-benchmark and does not imply unsorted parity.
- No dependency was installed or imported unnecessarily.
- Every recommendation has `safe_to_wire_into_step3b=false`.
- Non-`/tmp` output is blocked.
- No canonical artifact pollution occurred.

## Expected Handoff Summary

Coder should report:
- Changed files.
- Benchmark JSON path.
- Performance smoke summary path.
- `py_compile` result.
- Smoke verdict and canonical pollution.
- Fastest parity-passing candidate per operator, if any.
- Confirmation that `operators.py`, `kernels.py`, Step3B, and Step4 production paths were not modified.
