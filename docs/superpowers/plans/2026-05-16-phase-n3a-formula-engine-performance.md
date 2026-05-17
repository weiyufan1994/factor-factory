# Phase N.3A Formula Engine Performance Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reduce Step3B `compute_factor` and `normalize_sort` time for all Formula-IR operator-mode factors without changing factor semantics.

**Architecture:** Keep pandas Formula-IR as the correctness oracle. Add deterministic profiling, subexpression caching, sort/copy reduction, and operator-level parity checks. Do not introduce Polars in this phase; Polars remains a later optional backend.

**Tech Stack:** Python stdlib, pandas, numpy, existing `factor_factory.formula` evaluator/operators, `/tmp` smoke fixtures, formal wrapper only for real benchmark reruns.

---

## Context

Alpha017 Phase N.2 benchmark after quick wins:

```text
Step3B total:          121.816880s
Step3B read_inputs:      9.616416s
Step3B compute_factor:  84.461924s
Step3B normalize_sort:  19.577860s
Step3B write_parquet:    0.729674s
Step3B write_csv:        7.430134s
```

Main bottleneck is now the Formula-IR evaluator and redundant DataFrame sorting/copying.

---

## Non-Negotiable Constraints

- Do not change Step1/2/4/5/6/Council research semantics.
- Do not change promotion gates.
- Do not introduce Polars in this phase.
- Do not special-case Alpha017 or any report id.
- Do not silently approximate formula output.
- Every optimization must have parity against the current pandas reference.
- If parity fails, BLOCK or fall back to reference path with explicit evidence.
- No clean data processing in smoke.
- No search worker execution.

---

## Files

### Modify

- `factor_factory/formula/evaluator.py`
  - Add reference/optimized evaluator mode, node memoization, and avoid duplicate top-level sort/copy.

- `factor_factory/formula/operators.py`
  - Add safe fast paths for rolling operators where parity can be proven.

- `skills/factor-forge-step3/scripts/run_step3b.py`
  - Avoid redundant normalize/sort when evaluator already returns sorted output; record evaluator mode and parity summary in metadata.

- `scripts/run_factorforge_performance_smoke.py`
  - Add evaluator parity and cache behavior tests.

- `scripts/run_factorforge_performance_profile.py`
  - Include formula evaluator mode/cache stats if present.

### Optional docs

- `skills/factor-forge-step3/SKILL.md`
  - Document Formula-IR performance mode and parity requirement.

---

## Required Output Contract

Step3B `run_metadata.performance_profile` should add:

```json
"formula_engine_profile": {
  "engine": "pandas_formula_ir_optimized",
  "reference_engine": "pandas_formula_ir_reference",
  "memoization_enabled": true,
  "cache_hits": 0,
  "cache_misses": 0,
  "input_presorted": true,
  "output_presorted": true,
  "parity_checked": true,
  "parity_sample_rows": 0,
  "max_abs_diff": 0.0,
  "rank_corr": 1.0
}
```

For production full runs, parity can be sampled deterministically rather than recomputing the full dataset twice, but smoke must include full deterministic parity fixtures.

---

## Tasks

### Task 1: Add reference evaluator path and optimized evaluator path

**Files:**
- Modify: `factor_factory/formula/evaluator.py`

- [ ] **Step 1: Preserve existing behavior as reference**

Refactor current evaluator into explicit reference functions:

```python
def evaluate_formula_ir_reference(formula_ir: dict, frame: pd.DataFrame) -> pd.Series:
    if formula_ir.get('parse_status') != 'success':
        raise ValueError(f'BLOCK_UNSUPPORTED_FORMULA_SYNTAX: {formula_ir.get("parse_errors")}')
    required = {'ts_code', 'trade_date'}
    missing = required - set(frame.columns)
    if missing:
        raise KeyError(f'BLOCK_MISSING_REFERENCE_KEYS: {sorted(missing)}')
    working = frame.sort_values(['ts_code', 'trade_date']).reset_index(drop=True).copy()
    return _eval(formula_ir['root'], working)
```

- [ ] **Step 2: Add optimized evaluator skeleton**

Add:

```python
def evaluate_formula_ir_optimized(formula_ir: dict, frame: pd.DataFrame, return_profile: bool = False):
    if formula_ir.get('parse_status') != 'success':
        raise ValueError(f'BLOCK_UNSUPPORTED_FORMULA_SYNTAX: {formula_ir.get("parse_errors")}')
    required = {'ts_code', 'trade_date'}
    missing = required - set(frame.columns)
    if missing:
        raise KeyError(f'BLOCK_MISSING_REFERENCE_KEYS: {sorted(missing)}')

    input_presorted = bool(frame[['ts_code', 'trade_date']].equals(frame[['ts_code', 'trade_date']].sort_values(['ts_code', 'trade_date']).reset_index(drop=True))) if len(frame) else True
    working = frame if input_presorted else frame.sort_values(['ts_code', 'trade_date']).reset_index(drop=True)
    if working.index.has_duplicates or not isinstance(working.index, pd.RangeIndex):
        working = working.reset_index(drop=True)

    cache: dict[str, object] = {}
    stats = {'cache_hits': 0, 'cache_misses': 0, 'input_presorted': input_presorted, 'output_presorted': True}
    result = _eval_cached(formula_ir['root'], working, cache, stats)
    if return_profile:
        return result, stats
    return result
```

- [ ] **Step 3: Add stable node cache key**

Add:

```python
import json
import hashlib


def _node_key(node: dict) -> str:
    blob = json.dumps(node, sort_keys=True, ensure_ascii=False, separators=(',', ':'))
    return hashlib.sha256(blob.encode('utf-8')).hexdigest()
```

- [ ] **Step 4: Add cached evaluator**

Add `_eval_cached(node, frame, cache, stats)` mirroring `_eval()`, but cache operator/field nodes by `_node_key(node)`. Constants do not need cache.

Rules:

```text
- Cache only immutable result Series/scalars from pure Formula-IR nodes.
- Return cached Series directly; do not mutate Series in downstream operators.
- Increment cache_hits/cache_misses.
```

- [ ] **Step 5: Keep public API compatible**

Modify existing public function:

```python
def evaluate_formula_ir(formula_ir: dict, frame: pd.DataFrame, engine: str = 'optimized'):
    if engine == 'reference':
        return evaluate_formula_ir_reference(formula_ir, frame)
    if engine == 'optimized':
        return evaluate_formula_ir_optimized(formula_ir, frame)
    raise ValueError(f'BLOCK_UNSUPPORTED_FORMULA_ENGINE: {engine}')
```

Modify `evaluate_formula_frame()` to accept `engine` and optional `return_profile`.

- [ ] **Step 6: Compile**

```bash
python3 -m py_compile factor_factory/formula/evaluator.py
```

Expected: rc 0.

### Task 2: Add evaluator parity smoke

**Files:**
- Modify: `scripts/run_factorforge_performance_smoke.py`

- [ ] **Step 1: Add deterministic formula fixtures**

Add fixtures covering:

```text
rank(ts_rank(close, 10))
delta(delta(close, 1), 1)
ts_rank(volume / mean(volume, 20), 5)
full Alpha017-like formula
formula with repeated identical subexpression to prove cache hit
NaN and ties
multiple tickers
unsorted input frame
```

- [ ] **Step 2: Compare reference vs optimized**

For every fixture:

```python
ref = evaluate_formula_ir(formula_ir, frame, engine='reference')
opt = evaluate_formula_ir(formula_ir, frame, engine='optimized')
assert np.allclose(ref.fillna(-999999.0), opt.fillna(-999999.0), atol=1e-12)
```

- [ ] **Step 3: Assert cache stats**

For repeated subexpression fixture:

```python
opt, profile = evaluate_formula_ir_optimized(formula_ir, frame, return_profile=True)
assert profile['cache_hits'] > 0
assert profile['cache_misses'] > 0
```

- [ ] **Step 4: Add smoke case names**

Required cases:

```text
formula_evaluator_reference_optimized_parity
formula_evaluator_cache_hits_present
formula_evaluator_unsorted_input_parity
```

### Task 3: Avoid redundant sort/copy in Step3B

**Files:**
- Modify: `factor_factory/formula/evaluator.py`
- Modify: `skills/factor-forge-step3/scripts/run_step3b.py`

- [ ] **Step 1: Ensure evaluator returns sorted key order**

`evaluate_formula_frame()` should return `ts_code/trade_date/factor_value` in sorted order and include profile when requested:

```python
def evaluate_formula_frame(formula_ir: dict, frame: pd.DataFrame, engine: str = 'optimized', return_profile: bool = False) -> pd.DataFrame | tuple[pd.DataFrame, dict]:
    working = frame.sort_values(['ts_code', 'trade_date']).reset_index(drop=True)
    if return_profile:
        values, profile = evaluate_formula_ir_optimized(formula_ir, working, return_profile=True)
    else:
        values = evaluate_formula_ir(formula_ir, working, engine=engine)
        profile = {}
    out = working[['ts_code', 'trade_date']].copy()
    out['factor_value'] = values
    if return_profile:
        profile['output_presorted'] = True
        return out, profile
    return out
```

- [ ] **Step 2: In generated code path, request profile if possible**

Generated factor code currently calls `evaluate_formula_frame(FORMULA_IR, daily_df)`. Do not require regenerated code. Instead, in `run_step3b.py`, after calling `module.compute_factor()`, if module metadata says `implementation_source=formula_ir_pandas_codegen`, optionally compute with profile by directly calling `evaluate_formula_frame()` from metadata `FORMULA_IR`. If this is too invasive, leave code path unchanged and only record available profile from evaluator when generated code is regenerated.

Preferred narrow approach:

```text
Do not change generated code contract in N.3A unless smoke proves compatibility.
```

- [ ] **Step 3: Skip redundant normalize/sort only if already sorted**

In `run_step3b.py`, before sorting `result_df`:

```python
keys = result_df[['ts_code', 'trade_date']]
already_sorted = keys.equals(keys.sort_values(['ts_code', 'trade_date']).reset_index(drop=True))
if already_sorted:
    result_df = result_df.reset_index(drop=True)
else:
    result_df = result_df.sort_values(['ts_code', 'trade_date']).reset_index(drop=True)
```

Record `normalize_sort.already_sorted` in performance profile.

- [ ] **Step 4: Parity smoke**

Ensure Step3B smoke still emits identical rows in same order.

### Task 4: Add operator-level timing/cache profile to Step3B metadata

**Files:**
- Modify: `skills/factor-forge-step3/scripts/run_step3b.py`
- Modify: `scripts/run_factorforge_performance_profile.py`

- [ ] **Step 1: Record formula engine profile when available**

Add to `performance_profile`:

```python
'formula_engine_profile': formula_engine_profile or {
    'engine': 'pandas_formula_ir_reference_or_unknown',
    'memoization_enabled': False,
    'cache_hits': None,
    'cache_misses': None,
    'parity_checked': False,
}
```

- [ ] **Step 2: Read profile script field**

`run_factorforge_performance_profile.py` should display `formula_engine_profile` under Step3B profile.

### Task 5: Run real Alpha017 benchmark only after approval

**Files:**
- No source change required.

Do not run this unless user explicitly approves.

Command:

```bash
python3 scripts/run_factorforge_ultimate.py \
  --report-id ALPHA017_CANONICAL_FORMULA_20160101_LOOP_HYP \
  --start-step 3b \
  --end-step 4 \
  --council-mode off

python3 scripts/run_factorforge_performance_profile.py \
  --report-id ALPHA017_CANONICAL_FORMULA_20160101_LOOP_HYP \
  --write-report
```

Expected comparison target from N.2:

```text
Step3B compute_factor baseline: 84.461924s
Step3B normalize_sort baseline: 19.577860s
Step4 total baseline: 24.062138s
```

### Task 6: Final verification

**Files:**
- All changed files.

- [ ] **Step 1: Compile**

```bash
python3 -m py_compile \
  factor_factory/formula/evaluator.py \
  factor_factory/formula/operators.py \
  skills/factor-forge-step3/scripts/run_step3b.py \
  scripts/run_factorforge_performance_smoke.py \
  scripts/run_factorforge_performance_profile.py
```

- [ ] **Step 2: Run smoke/regression**

```bash
python3 scripts/run_factorforge_performance_smoke.py --fresh --root /tmp/factorforge_performance_phase_n3a
python3 scripts/run_step12_hypothesis_contract_smoke.py --fresh --root /tmp/factorforge_step12_hypothesis_contract_phase_n3a_regression
python3 scripts/run_step6_intelligence_acceptance.py --fresh --root /tmp/factorforge_step6_intelligence_acceptance_phase_n3a_regression
python3 scripts/run_factorforge_ultimate_loop_smoke.py --fresh --root /tmp/factorforge_ultimate_loop_phase_n3a_regression
```

Expected:

```text
performance smoke ACCEPT
Step12 smoke ACCEPT
STEP6_INTELLIGENCE_ACCEPTED
Phase M loop smoke ACCEPT
```

- [ ] **Step 3: Non-`/tmp` root block**

```bash
python3 scripts/run_factorforge_performance_smoke.py --fresh --root /Users/humphrey/tmp_factorforge_bad
```

Expected:

```text
BLOCK_NON_TMP_FACTORFORGE_ROOT
```

- [ ] **Step 4: Installed skill sync**

```bash
rsync -a --delete skills/factor-forge-step3/ /Users/humphrey/.codex/skills/factor-forge-step3/
rsync -a --delete skills/factor-forge-step4/ /Users/humphrey/.codex/skills/factor-forge-step4/
rsync -a --delete skills/factor-forge-ultimate/ /Users/humphrey/.codex/skills/factor-forge-ultimate/
diff -qr -x __pycache__ skills/factor-forge-step3 /Users/humphrey/.codex/skills/factor-forge-step3
diff -qr -x __pycache__ skills/factor-forge-step4 /Users/humphrey/.codex/skills/factor-forge-step4
diff -qr -x __pycache__ skills/factor-forge-ultimate /Users/humphrey/.codex/skills/factor-forge-ultimate
```

---

## Reviewer Acceptance Checklist

BLOCK if any item fails:

- Optimized evaluator is parity-equivalent to reference evaluator on all smoke fixtures.
- Cache hits are proven on repeated subexpression fixture.
- Unsorted input produces same sorted output as reference.
- Step3B metadata records evaluator profile without deleting existing performance profile fields.
- `normalize_sort` optimization does not change output ordering or row count.
- Step12, Step6 acceptance, and Phase M loop smoke still pass.
- No Polars backend was introduced in this phase.
- No Step6/Council/promotion gate logic changed.

