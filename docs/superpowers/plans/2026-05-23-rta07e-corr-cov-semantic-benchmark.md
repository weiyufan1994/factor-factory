# RTA-07E Rolling Corr/Cov Semantic Benchmark Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Strengthen `rolling_corr` / `rolling_cov` semantic evidence before any opt-in production wiring, with edge-case fixtures that cover zero variance, near-constant series, NaNs, unsorted input order, and pandas reference output-order behavior.

**Architecture:** Do not wire `rolling_corr` or `rolling_cov` into `factor_factory.formula.kernels` in this phase. Extend the existing RTA-07B read-only candidate benchmark and performance smoke so reviewer can decide whether `numpy_corr_formula_per_ticker` and `numpy_cov_formula_per_ticker` are safe enough for a later RTA-07F opt-in experimental kernel. The output should explicitly separate `cov` readiness from `corr` readiness.

**Tech Stack:** Python 3, pandas, numpy, existing `factor_factory.formula.operator_candidate_benchmarks`, existing `scripts/run_factorforge_operator_candidate_benchmark.py`, existing performance smoke.

---

## Scope

Allowed:
- Modify `factor_factory/formula/operator_candidate_benchmarks.py`
- Modify `scripts/run_factorforge_operator_candidate_benchmark.py`
- Modify `scripts/run_factorforge_performance_smoke.py`
- Optionally update `docs/operations/factorforge-production-vs-experimental-performance.zh-CN.md` with one short note after smoke passes

Not allowed:
- Do not modify `factor_factory/formula/operators.py`.
- Do not modify `factor_factory/formula/kernels.py`.
- Do not modify `factor_factory/formula/evaluator.py`.
- Do not wire `rolling_corr` / `rolling_cov` into Step3B or Formula-IR runtime.
- Do not install dependencies.
- Do not run `scripts/run_factorforge_ultimate.py` or loop wrappers.
- Do not process clean data.
- Do not run search worker.
- Do not write official promotion.

## Background

RTA-07B found parity-passing speedups on synthetic benchmark:
- `rolling_corr`: `numpy_corr_formula_per_ticker`, about `2.15x`
- `rolling_cov`: `numpy_cov_formula_per_ticker`, about `2.24x`

However, during review probing, `rolling_corr` showed cases where absolute numeric diff was tiny but rank correlation was low in near-constant/near-zero-variance windows. That is not automatically a parity failure, but it is enough to require stronger evidence before wiring.

## Contract

The benchmark JSON remains:

```json
{
  "version": "factorforge_operator_candidate_benchmark_v1",
  "read_only": true,
  "production_semantics_changed": false,
  "cases": [],
  "recommendations": [],
  "canonical_pollution": false
}
```

Add a new optional section:

```json
"corr_cov_semantic_profile": {
  "version": "factorforge_corr_cov_semantic_profile_v1",
  "edge_cases_included": true,
  "corr_safe_for_opt_in_kernel": false,
  "cov_safe_for_opt_in_kernel": false,
  "reasons": []
}
```

Rules:
- This phase must keep both `corr_safe_for_opt_in_kernel` and `cov_safe_for_opt_in_kernel` conservative unless every new edge case passes.
- Even if every edge case passes, do not mark anything production-ready. The strongest allowed next step is `RTA-07F opt-in experimental kernel candidate`.
- Every recommendation must continue to include `safe_to_wire_into_step3b=false`.

## Task 1: Add Edge-Case Fixtures

**Files:**
- Modify: `scripts/run_factorforge_operator_candidate_benchmark.py`

- [ ] **Step 1: Add fixture builder**

Add:

```python
def corr_cov_edge_fixture(*, unsorted: bool) -> pd.DataFrame:
```

Required columns:
- `ts_code`
- `trade_date`
- `value`
- `left`
- `right`

Required ticker patterns:
- `POS`: perfect positive correlation, non-constant.
- `NEG`: perfect negative correlation, non-constant.
- `ZERO_LEFT`: left constant, right non-constant; corr should be NaN where denominator is zero, cov should be 0 where complete windows exist.
- `ZERO_RIGHT`: right constant, left non-constant.
- `NEAR_CONST`: one side nearly constant with tiny variation; this should test numerical stability.
- `NAN_MIX`: NaNs inside left and right windows.
- `TIE_VALUES`: repeated values to exercise stable output and NaN-mask behavior.

Use 18 business dates and windows later tested at `3,5,10`.

If `unsorted=True`, reorder rows with a deterministic non-random permutation that preserves all rows.

- [ ] **Step 2: Include edge cases in benchmark**

Extend the default cases in `build_payload()` to include:

```text
corr_cov_edge_sorted
corr_cov_edge_unsorted
```

These cases must run for all requested windows.

- [ ] **Step 3: Label output-order expectations**

For each case, add:

```json
"input_globally_sorted": true,
"candidate_matches_reference_index_order": true
```

`input_globally_sorted` should inspect `frame[['ts_code', 'trade_date']]`.

`candidate_matches_reference_index_order` should be derived from parity output for non-reference corr/cov candidates.

This is important because current pandas `groupby.apply` output order can differ from raw input row order; benchmark must document the actual contract being matched.

## Task 2: Strengthen Parity Metrics

**Files:**
- Modify: `factor_factory/formula/operator_candidate_benchmarks.py`

- [ ] **Step 1: Add finite-count metrics**

Extend `compare_series_to_reference()` to return:

```json
{
  "finite_count": 0,
  "reference_finite_count": 0,
  "candidate_finite_count": 0,
  "max_abs_diff": 0.0,
  "max_rel_diff": 0.0,
  "rank_corr": 1.0,
  "allclose_pass": true
}
```

Definitions:
- `reference_finite_count`: finite values in reference.
- `candidate_finite_count`: finite values in candidate.
- `finite_count`: positions where both are finite.
- `max_rel_diff`: max `abs(ref-cand) / max(abs(ref), 1e-12)` across finite positions.
- `allclose_pass`: `np.allclose(ref[valid], cand[valid], rtol=1e-10, atol=tolerance, equal_nan=True)`.

Keep existing fields backward compatible:
- `row_count_equal`
- `key_order_equal`
- `nan_mask_equal`
- `max_abs_diff`
- `rank_corr`
- `parity_pass`

- [ ] **Step 2: Make corr/cov parity stricter**

For `rolling_corr` and `rolling_cov`, `parity_pass` must require:
- row count equal
- key order equal
- NaN mask equal
- `allclose_pass is True`
- `max_abs_diff <= 1e-10`
- `max_rel_diff <= 1e-8` unless `finite_count == 0`

Do not require rank correlation for parity pass when finite count is small or values are near-constant. Still record it.

- [ ] **Step 3: Add edge-case failure reasons**

When a candidate fails parity, include a compact `failure_reason`, such as:

```text
parity_failed:nan_mask_mismatch
parity_failed:max_abs_diff
parity_failed:max_rel_diff
parity_failed:key_order_mismatch
```

This can be computed in the benchmark runner after parity is returned.

## Task 3: Add Semantic Profile And Recommendations

**Files:**
- Modify: `scripts/run_factorforge_operator_candidate_benchmark.py`

- [ ] **Step 1: Build semantic profile**

Add:

```python
def build_corr_cov_semantic_profile(cases: list[dict[str, Any]]) -> dict[str, Any]:
```

Profile must inspect all cases whose name starts with `corr_cov_edge_`.

For each operator:
- collect all non-reference candidate results
- require every result to have `status == PASS` and `parity_pass is True`
- require no NaN-mask mismatches
- require no key-order mismatches

Output:

```json
{
  "version": "factorforge_corr_cov_semantic_profile_v1",
  "edge_cases_included": true,
  "corr_safe_for_opt_in_kernel": false,
  "cov_safe_for_opt_in_kernel": true,
  "reasons": [
    "rolling_corr edge cases passed but requires reviewer approval before RTA-07F",
    "rolling_cov edge cases passed but requires reviewer approval before RTA-07F"
  ],
  "by_operator": {
    "rolling_corr": {
      "edge_result_count": 0,
      "edge_failure_count": 0,
      "max_abs_diff": 0.0,
      "max_rel_diff": 0.0,
      "nan_mask_equal_all": true,
      "key_order_equal_all": true
    }
  }
}
```

If all edge cases pass, `*_safe_for_opt_in_kernel` may be `true`, but recommendations must still have `safe_to_wire_into_step3b=false`.

- [ ] **Step 2: Update recommendations**

For `rolling_corr` and `rolling_cov`, include:

```json
"semantic_profile_gate_passed": true,
"next_phase_required": "RTA-07F opt-in experimental kernel implementation with reviewer approval"
```

If semantic gate fails:

```json
"recommended_candidate": null,
"semantic_profile_gate_passed": false,
"next_phase_required": "fix corr/cov candidate semantics before wiring"
```

- [ ] **Step 3: Add diagnostics**

Add diagnostics:

```text
CORR_COV_EDGE_CASES_INCLUDED
CORR_COV_SEMANTIC_PROFILE_RECORDED
CORR_COV_NOT_WIRED_TO_RUNTIME
```

## Task 4: Add Performance Smoke Coverage

**Files:**
- Modify: `scripts/run_factorforge_performance_smoke.py`

- [ ] **Step 1: Add semantic profile smoke**

Add case:

```text
operator_candidate_benchmark_corr_cov_semantic_profile
```

Run:

```bash
python3 scripts/run_factorforge_operator_candidate_benchmark.py \
  --output /tmp/<fresh_root>/operator_candidate_corr_cov_semantic.json \
  --windows 3,5,10 \
  --ticker-count 24 \
  --days 60 \
  --seed 907
```

Assert:
- JSON version unchanged.
- `corr_cov_semantic_profile.version == factorforge_corr_cov_semantic_profile_v1`
- `edge_cases_included is True`
- diagnostics include `CORR_COV_EDGE_CASES_INCLUDED`
- diagnostics include `CORR_COV_NOT_WIRED_TO_RUNTIME`
- recommendations for corr/cov have `safe_to_wire_into_step3b=false`

- [ ] **Step 2: Add corr/cov edge parity smoke**

Add case:

```text
operator_candidate_benchmark_corr_cov_edge_parity
```

Assert for every non-reference result in `corr_cov_edge_sorted` and `corr_cov_edge_unsorted`:
- `status == PASS`
- `parity_pass is True`
- `row_count_equal is True`
- `key_order_equal is True`
- `nan_mask_equal is True`
- `allclose_pass is True`
- `max_abs_diff <= 1e-10`
- `max_rel_diff <= 1e-8` unless `finite_count == 0`

- [ ] **Step 3: Add runtime non-mutation smoke**

Add case:

```text
operator_candidate_benchmark_corr_cov_not_wired
```

Before and after the benchmark, hash:

```text
factor_factory/formula/operators.py
factor_factory/formula/kernels.py
factor_factory/formula/evaluator.py
skills/factor-forge-step3/scripts/run_step3b.py
```

Assert hashes unchanged.

- [ ] **Step 4: Keep non-/tmp guard**

Existing non-`/tmp` benchmark output block must still pass:

```text
BLOCK_OPERATOR_CANDIDATE_BENCHMARK_NON_TMP_OUTPUT
```

## Task 5: Verification

**Files:**
- Compile:
  - `factor_factory/formula/operator_candidate_benchmarks.py`
  - `scripts/run_factorforge_operator_candidate_benchmark.py`
  - `scripts/run_factorforge_performance_smoke.py`

- [ ] **Step 1: Compile**

Run:

```bash
python3 -m py_compile \
  factor_factory/formula/operator_candidate_benchmarks.py \
  scripts/run_factorforge_operator_candidate_benchmark.py \
  scripts/run_factorforge_performance_smoke.py
```

Expected: exit code 0.

- [ ] **Step 2: Run standalone semantic benchmark**

Run:

```bash
python3 scripts/run_factorforge_operator_candidate_benchmark.py \
  --output /tmp/factorforge_rta07e_corr_cov_semantic_benchmark.json \
  --windows 3,5,10 \
  --ticker-count 120 \
  --days 180 \
  --seed 907
```

Expected:
- exit code 0
- `canonical_pollution=false`
- `corr_cov_semantic_profile.edge_cases_included=true`
- recommendations remain `safe_to_wire_into_step3b=false`

- [ ] **Step 3: Run performance smoke**

Run:

```bash
python3 scripts/run_factorforge_performance_smoke.py --fresh --root /tmp/factorforge_rta07e_corr_cov_semantic_smoke
```

Expected:
- `verdict=ACCEPT`
- `canonical_pollution=false`
- all new RTA-07E cases pass

## Reviewer Checklist

Reviewer should verify:
- No runtime wiring was added for `rolling_corr` or `rolling_cov`.
- Edge cases include zero variance, near-constant values, NaNs, unsorted input, and perfect positive/negative correlation.
- Candidate output matches current pandas reference output-order contract.
- `corr` parity does not over-trust rank correlation in near-constant cases.
- semantic profile correctly blocks or permits the next opt-in phase.
- recommendations keep `safe_to_wire_into_step3b=false`.
- no clean data/search worker/official promotion path touched.

## Expected Handoff Summary

Coder should report:
- Changed files.
- Standalone semantic benchmark JSON path.
- Performance smoke summary path.
- `py_compile` result.
- Smoke verdict and canonical pollution.
- `corr_cov_semantic_profile` summary.
- Whether corr/cov are safe to propose for RTA-07F opt-in wiring, with reasons.
