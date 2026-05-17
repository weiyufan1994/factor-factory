# Phase N.2 Factor Forge Performance Profile And Vectorization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make Factor Forge Step3B/Step4 performance measurable and improve the slow generic formula/self-quant paths without changing factor research semantics or promotion gates.

**Architecture:** Add timing/profiling evidence first, then optimize the generic Formula-IR pandas operators and self_quant analyzer hot paths behind parity checks. Keep Step1/2/5/6/Council unchanged; Step3B and Step4 outputs must remain semantically equivalent within explicit tolerances.

**Tech Stack:** Python stdlib, pandas, numpy, existing Factor Forge Formula-IR evaluator, existing Step3B/Step4 wrappers, `/tmp` smoke fixtures, optional real Alpha017 benchmark read-only comparison.

---

## Context From Alpha017

Real Alpha017 run evidence showed:

```text
run_step3:   2026-05-15T17:26:06 -> 17:27:32  ~ 85s
run_step3b:  2026-05-15T17:27:32 -> 17:35:42  ~ 490s
run_step4:   2026-05-15T17:35:42 -> 17:45:00  ~ 558s
run_step6:   2026-05-15T17:45:00 -> 17:45:01  < 1s
```

Alpha017 row scale:

```text
factor rows: 8,899,361
merged Step4 rows: 8,777,874
dates: 2,503
tickers: 5,067
factor parquet: ~75MB
factor CSV: ~338MB
```

Known likely hot spots:

- `factor_factory/formula/operators.py::ts_rank` uses `rolling(...).apply(lambda values: pd.Series(values).rank(...), raw=False)`.
- Step3B always writes both parquet and large CSV factor values.
- `skills/factor-forge-step4/scripts/self_quant_adapter.py` computes daily group assignment twice: `_build_quantile_nav()` and `_build_long_side_evidence()`.
- self_quant IC uses `groupby.apply(lambda df: corr(...))` for rank and Pearson correlations.
- self_quant quantile assignment uses per-day `pd.qcut` inside groupby transform.

---

## Non-Negotiable Constraints

- Do not change research decisions, promotion gates, Step6 Council semantics, or loop authorization.
- Do not process clean data in smoke.
- Do not run real factor full loop in smoke.
- Do not silently drop CSV output unless an explicit compatibility flag and validator support are added.
- Do not optimize only Alpha017 by special-casing its report id.
- Do not introduce approximation unless parity tolerance and validator evidence are explicit.
- Do not accept faster code unless output parity is proven against the old implementation on deterministic fixtures.

---

## Files

### Create

- `factor_factory/performance/__init__.py`
  - Lightweight performance helper exports.

- `factor_factory/performance/timing.py`
  - `PhaseTimer`, wall-time helpers, optional memory RSS helpers.

- `scripts/run_factorforge_performance_profile.py`
  - Read-only profiler for an existing report id; records Step3B factor compute/write timing and Step4 self_quant timing without changing canonical outputs unless `--write-report` is given.

- `scripts/run_factorforge_performance_smoke.py`
  - `/tmp` smoke for timing schema, formula operator parity, self_quant parity, and no canonical pollution.

### Modify

- `factor_factory/formula/operators.py`
  - Add faster generic `ts_rank` implementation and any safe vectorized helpers.

- `factor_factory/formula/evaluator.py`
  - Add optional evaluation timing hooks or metadata helpers, but keep public return shape unchanged.

- `skills/factor-forge-step3/scripts/run_step3b.py`
  - Record phase timing in run metadata: input read, compute, sort/normalize, parquet write, CSV write.

- `skills/factor-forge-step4/scripts/self_quant_adapter.py`
  - Record phase timing in payload and reduce repeated expensive operations.

- `skills/factor-forge-step4/scripts/validate_step4.py`
  - If new performance metadata is required, validate presence and schema. Do not block older artifacts unless this is behind a new contract version.

- `skills/factor-forge-step3/SKILL.md`
  - Document Step3B performance profile fields.

- `skills/factor-forge-step4/SKILL.md`
  - Document Step4 self_quant performance profile fields.

---

## Required Performance Metadata

Step3B `run_metadata__<report_id>.json` should include:

```json
"performance_profile": {
  "version": "factorforge_step3b_performance_profile_v1",
  "row_count": 8899361,
  "phase_seconds": {
    "read_inputs": 0.0,
    "compute_factor": 0.0,
    "normalize_sort": 0.0,
    "write_parquet": 0.0,
    "write_csv": 0.0,
    "total": 0.0
  },
  "rows_per_second_compute": 0.0,
  "output_bytes": {
    "parquet": 0,
    "csv": 0
  }
}
```

Step4 `self_quant_analyzer/evaluation_payload.json` should include:

```json
"performance_profile": {
  "version": "factorforge_self_quant_performance_profile_v1",
  "merged_rows": 8777874,
  "phase_seconds": {
    "load_factor_values": 0.0,
    "load_daily_snapshot": 0.0,
    "merge_forward_returns": 0.0,
    "ic_calculation": 0.0,
    "quantile_assignment": 0.0,
    "long_side_evidence": 0.0,
    "write_tables": 0.0,
    "write_plots": 0.0,
    "total": 0.0
  },
  "rows_per_second_total": 0.0,
  "parallelism": 1
}
```

---

## Tasks

### Task 1: Add timing helper

**Files:**
- Create: `factor_factory/performance/__init__.py`
- Create: `factor_factory/performance/timing.py`

- [ ] **Step 1: Create `factor_factory/performance/__init__.py`**

```python
"""Performance measurement helpers for Factor Forge."""

from .timing import PhaseTimer, safe_file_size

__all__ = ["PhaseTimer", "safe_file_size"]
```

- [ ] **Step 2: Create `factor_factory/performance/timing.py`**

```python
from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
import time
from typing import Iterator


class PhaseTimer:
    def __init__(self) -> None:
        self.phase_seconds: dict[str, float] = {}
        self._start = time.perf_counter()

    @contextmanager
    def phase(self, name: str) -> Iterator[None]:
        started = time.perf_counter()
        try:
            yield
        finally:
            self.phase_seconds[name] = self.phase_seconds.get(name, 0.0) + (time.perf_counter() - started)

    def finish(self) -> dict[str, float]:
        out = {key: round(value, 6) for key, value in self.phase_seconds.items()}
        out["total"] = round(time.perf_counter() - self._start, 6)
        return out


def safe_file_size(path: str | Path | None) -> int:
    if not path:
        return 0
    p = Path(path)
    try:
        return int(p.stat().st_size)
    except OSError:
        return 0
```

- [ ] **Step 3: Compile**

Run:

```bash
python3 -m py_compile factor_factory/performance/__init__.py factor_factory/performance/timing.py
```

Expected: rc 0.

### Task 2: Instrument Step3B phase timing

**Files:**
- Modify: `skills/factor-forge-step3/scripts/run_step3b.py`

- [ ] **Step 1: Import timer**

Add near imports:

```python
from factor_factory.performance import PhaseTimer, safe_file_size
```

- [ ] **Step 2: Wrap first-run phases in `generate_first_run_factor_values()`**

Inside `generate_first_run_factor_values()`, add:

```python
timer = PhaseTimer()
```

Wrap phases:

```python
with timer.phase('read_inputs'):
    minute_df = read_df(minute_path) if minute_path is not None else pd.DataFrame()
    daily_df = read_df(daily_path)

with timer.phase('compute_factor'):
    try:
        result_df = module.compute_factor(daily_df=daily_df, minute_df=minute_df)
    except TypeError:
        result_df = module.compute_factor(minute_df, daily_df)

with timer.phase('normalize_sort'):
    signal_col = infer_signal_column(result_df, factor_id=factor_id)
    result_df = result_df[['ts_code', 'trade_date', signal_col]].copy()
    result_df['trade_date'] = normalize_trade_date_series(result_df['trade_date']).dt.strftime('%Y%m%d')
    result_df = result_df.sort_values(['ts_code', 'trade_date']).reset_index(drop=True)

with timer.phase('write_parquet'):
    result_df.to_parquet(factor_parquet, index=False)

with timer.phase('write_csv'):
    result_df.to_csv(factor_csv, index=False)
```

Add metadata field:

```python
phase_seconds = timer.finish()
metadata['performance_profile'] = {
    'version': 'factorforge_step3b_performance_profile_v1',
    'row_count': int(len(result_df)),
    'phase_seconds': phase_seconds,
    'rows_per_second_compute': float(len(result_df) / phase_seconds['compute_factor']) if phase_seconds.get('compute_factor') else None,
    'output_bytes': {
        'parquet': safe_file_size(factor_parquet),
        'csv': safe_file_size(factor_csv),
    },
}
```

- [ ] **Step 3: Run py_compile**

```bash
python3 -m py_compile skills/factor-forge-step3/scripts/run_step3b.py
```

Expected: rc 0.

### Task 3: Optimize generic `ts_rank` with parity tests

**Files:**
- Modify: `factor_factory/formula/operators.py`
- Create or modify smoke in `scripts/run_factorforge_performance_smoke.py`

- [ ] **Step 1: Add old reference helper inside smoke, not production**

In smoke, define reference:

```python
def reference_ts_rank(series, window, frame):
    return series.groupby(frame['ts_code'], sort=False).transform(
        lambda s: s.rolling(window, min_periods=window).apply(
            lambda values: pd.Series(values).rank(method='average', pct=True).iloc[-1],
            raw=False,
        )
    )
```

- [ ] **Step 2: Replace production `ts_rank` with raw numpy implementation**

In `factor_factory/formula/operators.py`, replace `ts_rank()` with:

```python
def _last_value_pct_rank(values: np.ndarray) -> float:
    if len(values) == 0 or np.isnan(values).any():
        return np.nan
    last = values[-1]
    less = np.sum(values < last)
    equal = np.sum(values == last)
    # pandas rank(method='average', pct=True) for last value.
    average_rank = less + (equal + 1.0) / 2.0
    return float(average_rank / len(values))


def ts_rank(series: pd.Series, window: int, frame: pd.DataFrame) -> pd.Series:
    return series.groupby(frame['ts_code'], sort=False).transform(
        lambda s: s.rolling(window, min_periods=window).apply(_last_value_pct_rank, raw=True)
    )
```

- [ ] **Step 3: Add smoke parity case**

In `scripts/run_factorforge_performance_smoke.py`, create deterministic frame with ties and NaNs:

```python
def build_operator_parity_frame():
    rows = []
    for code in ['A', 'B', 'C']:
        for i in range(30):
            value = float((i * 7) % 11)
            if code == 'B' and i in {5, 6, 7}:
                value = 3.0
            if code == 'C' and i == 12:
                value = np.nan
            rows.append({'ts_code': code, 'trade_date': f'202001{i+1:02d}', 'x': value})
    return pd.DataFrame(rows)
```

Assert:

```python
actual = ts_rank(frame['x'], 5, frame)
expected = reference_ts_rank(frame['x'], 5, frame)
assert np.allclose(actual.fillna(-9999), expected.fillna(-9999), atol=1e-12)
```

- [ ] **Step 4: Compile and run smoke parity**

```bash
python3 -m py_compile factor_factory/formula/operators.py scripts/run_factorforge_performance_smoke.py
python3 scripts/run_factorforge_performance_smoke.py --fresh --root /tmp/factorforge_performance_phase_n2_ts_rank
```

Expected: rc 0, `ts_rank_parity=true`.

### Task 4: Instrument and de-duplicate self_quant expensive work

**Files:**
- Modify: `skills/factor-forge-step4/scripts/self_quant_adapter.py`

- [ ] **Step 1: Import timer**

```python
from factor_factory.performance import PhaseTimer
```

- [ ] **Step 2: Add helper to assign quantiles once**

Add:

```python
def _assign_quantile_groups_once(merged: pd.DataFrame, signal_col: str, group_count: int = 10) -> pd.DataFrame:
    working = merged[['datetime', 'trade_date', 'code', signal_col, 'future_return_1d']].copy()
    working['group_id'] = working.groupby('trade_date', sort=True)[signal_col].transform(
        lambda s: _assign_quantile_labels(s, groups=group_count)
    )
    return working.dropna(subset=['group_id', 'future_return_1d']).assign(group_id=lambda df: df['group_id'].astype(int))
```

- [ ] **Step 3: Refactor `_build_quantile_nav` to accept assigned data**

Change signature:

```python
def _build_quantile_nav_from_assigned(assigned: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
```

Implementation:

```python
grouped = assigned.groupby(['trade_date', 'group_id'], sort=True)['future_return_1d'].mean().unstack('group_id').sort_index()
counts = assigned.groupby(['trade_date', 'group_id'], sort=True).size().unstack('group_id').sort_index()
grouped.index = normalize_trade_date_series(grouped.index.to_series())
grouped.index.name = 'datetime'
grouped = grouped.sort_index()
grouped.columns = [f'G{int(col):02d}' for col in grouped.columns]
counts.index = normalize_trade_date_series(counts.index.to_series())
counts.index.name = 'datetime'
counts = counts.sort_index()
counts.columns = [f'G{int(col):02d}' for col in counts.columns]
nav = _normalize_nav_to_one((1.0 + grouped.fillna(0.0)).cumprod())
return grouped, nav, counts
```

Keep old `_build_quantile_nav()` as a wrapper for compatibility:

```python
def _build_quantile_nav(merged: pd.DataFrame, signal_col: str, group_count: int = 10):
    assigned = _assign_quantile_groups_once(merged, signal_col, group_count)
    return _build_quantile_nav_from_assigned(assigned)
```

- [ ] **Step 4: Refactor long-side evidence to use assigned data**

Add:

```python
def _build_long_side_evidence_from_assigned(assigned: pd.DataFrame, eval_dir: Path, report_id: str) -> tuple[dict[str, Any], dict[str, str], list[dict[str, Any]]]:
    # Move the existing body of _build_long_side_evidence after `assigned` creation here.
```

Keep `_build_long_side_evidence()` wrapper for compatibility:

```python
def _build_long_side_evidence(merged: pd.DataFrame, signal_col: str, eval_dir: Path, report_id: str, group_count: int = 10):
    assigned = _assign_quantile_groups_once(merged, signal_col, group_count)
    return _build_long_side_evidence_from_assigned(assigned, eval_dir, report_id)
```

In `run_self_quant_quick()`, compute once:

```python
with timer.phase('quantile_assignment'):
    assigned = _assign_quantile_groups_once(merged, signal_col=signal_col, group_count=10)
with timer.phase('quantile_nav'):
    quantile_returns, quantile_nav, quantile_counts = _build_quantile_nav_from_assigned(assigned)
with timer.phase('long_side_evidence'):
    long_side_metrics, long_side_artifacts, long_side_checks = _build_long_side_evidence_from_assigned(
        assigned=assigned,
        eval_dir=FF / 'evaluations' / report_id / 'self_quant_analyzer',
        report_id=report_id,
    )
```

- [ ] **Step 5: Add timing phases around run_self_quant_quick**

Use one `PhaseTimer()` in `run_self_quant_quick()` and wrap:

```text
load_factor_values
load_daily_snapshot
merge_forward_returns
ic_calculation
quantile_assignment
quantile_nav
long_side_evidence
write_tables
write_plots
```

Add `performance_profile` to summary.

- [ ] **Step 6: Compile**

```bash
python3 -m py_compile skills/factor-forge-step4/scripts/self_quant_adapter.py
```

Expected: rc 0.

### Task 5: Add performance profile script

**Files:**
- Create: `scripts/run_factorforge_performance_profile.py`

- [ ] **Step 1: Implement read-only profile summarizer**

Create script that reads existing artifacts and writes only when `--write-report` is provided:

```python
#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from factor_factory.runtime_context import resolve_factorforge_context


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding='utf-8')) if path.exists() else {}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--report-id', required=True)
    ap.add_argument('--factorforge-root', default=None)
    ap.add_argument('--write-report', action='store_true')
    args = ap.parse_args()
    ctx = resolve_factorforge_context(args.factorforge_root)
    rid = args.report_id
    run_meta = load(ctx.factorforge_root / 'runs' / rid / f'run_metadata__{rid}.json')
    self_quant = load(ctx.factorforge_root / 'evaluations' / rid / 'self_quant_analyzer' / 'evaluation_payload.json')
    wrapper = load(ctx.objects_root / 'runtime_context' / f'ultimate_run_report__{rid}.json')
    report = {
        'report_id': rid,
        'step3b_performance_profile': run_meta.get('performance_profile'),
        'self_quant_performance_profile': self_quant.get('performance_profile'),
        'wrapper_command_timing': [
            {
                'name': c.get('name'),
                'returncode': c.get('returncode'),
                'started_at_utc': c.get('started_at_utc'),
                'finished_at_utc': c.get('finished_at_utc'),
            }
            for c in wrapper.get('commands', [])
        ],
        'artifact_sizes': {
            'factor_parquet_bytes': (ctx.factorforge_root / 'runs' / rid / f'factor_values__{rid}.parquet').stat().st_size if (ctx.factorforge_root / 'runs' / rid / f'factor_values__{rid}.parquet').exists() else 0,
            'factor_csv_bytes': (ctx.factorforge_root / 'runs' / rid / f'factor_values__{rid}.csv').stat().st_size if (ctx.factorforge_root / 'runs' / rid / f'factor_values__{rid}.csv').exists() else 0,
        },
    }
    if args.write_report:
        out = ctx.objects_root / 'validation' / f'performance_profile__{rid}.json'
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + '\n', encoding='utf-8')
        print(f'[WRITE] {out}')
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
```

- [ ] **Step 2: Compile**

```bash
python3 -m py_compile scripts/run_factorforge_performance_profile.py
```

Expected: rc 0.

### Task 6: Add `/tmp` performance smoke

**Files:**
- Create: `scripts/run_factorforge_performance_smoke.py`

- [ ] **Step 1: Implement smoke root policy and operator parity**

The smoke must:

- block non-`/tmp` root with `BLOCK_NON_TMP_FACTORFORGE_ROOT`
- run py_compile
- test `ts_rank` parity with ties/NaNs
- run a tiny Step3B generated factor fixture and assert performance profile fields exist
- run a tiny self_quant fixture and assert performance profile fields exist
- assert canonical pollution false

- [ ] **Step 2: Smoke expected cases**

Required case names:

```text
py_compile
operator_ts_rank_parity
step3b_performance_profile_present
self_quant_performance_profile_present
performance_profile_script_readonly
non_tmp_root_blocks
```

- [ ] **Step 3: Run smoke**

```bash
python3 scripts/run_factorforge_performance_smoke.py --fresh --root /tmp/factorforge_performance_phase_n2
```

Expected: rc 0, verdict `ACCEPT`.

### Task 7: Run real Alpha017 profile after instrumentation

**Files:**
- No source changes unless findings require fixes.

- [ ] **Step 1: Rerun only Step3B->Step4 for Alpha017 if user approved real benchmark**

Use formal wrapper only:

```bash
python3 scripts/run_factorforge_ultimate.py \
  --report-id ALPHA017_CANONICAL_FORMULA_20160101_LOOP_HYP \
  --start-step 3b \
  --end-step 4 \
  --council-mode off
```

If user has not approved a real rerun, skip and state skipped.

- [ ] **Step 2: Write performance profile report**

```bash
python3 scripts/run_factorforge_performance_profile.py \
  --report-id ALPHA017_CANONICAL_FORMULA_20160101_LOOP_HYP \
  --write-report
```

Expected output path:

```text
objects/validation/performance_profile__ALPHA017_CANONICAL_FORMULA_20160101_LOOP_HYP.json
```

- [ ] **Step 3: Compare key metrics before/after**

Compare these fields from `evaluation_payload.json` against pre-optimization values:

```text
rank_ic_mean = 0.03390277736229302
rank_ic_ir = 0.3042306714312082
pearson_ic_mean = 0.0384010939790747
pearson_ic_ir = 0.41590123959989084
long_side_annual_return = -0.1388 approx
cost_adjusted_annual_return = -0.7870 approx
```

Tolerance:

```text
absolute tolerance <= 1e-10 for IC summary where deterministic same data
absolute tolerance <= 1e-8 for NAV/final return tables
```

If parity fails, BLOCK and revert optimization.

### Task 8: Final regression and installed sync

**Files:**
- Modified skills and scripts from tasks above.

- [ ] **Step 1: Compile all changed files**

```bash
python3 -m py_compile \
  factor_factory/performance/__init__.py \
  factor_factory/performance/timing.py \
  factor_factory/formula/operators.py \
  factor_factory/formula/evaluator.py \
  skills/factor-forge-step3/scripts/run_step3b.py \
  skills/factor-forge-step4/scripts/self_quant_adapter.py \
  skills/factor-forge-step4/scripts/validate_step4.py \
  scripts/run_factorforge_performance_profile.py \
  scripts/run_factorforge_performance_smoke.py
```

- [ ] **Step 2: Run smoke/regression**

```bash
python3 scripts/run_factorforge_performance_smoke.py --fresh --root /tmp/factorforge_performance_phase_n2_final
python3 scripts/run_step12_hypothesis_contract_smoke.py --fresh --root /tmp/factorforge_step12_hypothesis_contract_phase_n2_regression
python3 scripts/run_step6_intelligence_acceptance.py --fresh --root /tmp/factorforge_step6_intelligence_acceptance_phase_n2_regression
python3 scripts/run_factorforge_ultimate_loop_smoke.py --fresh --root /tmp/factorforge_ultimate_loop_phase_n2_regression
```

Expected:

```text
performance smoke ACCEPT
Step12 smoke ACCEPT
STEP6_INTELLIGENCE_ACCEPTED
Phase M loop smoke ACCEPT
```

- [ ] **Step 3: Non-`/tmp` root check**

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

Expected: all diff commands rc 0.

---

## Reviewer Acceptance Checklist

Reviewer should BLOCK if any condition fails:

- No optimization changes Step1/2/5/6/Council semantics.
- Performance profiles exist in Step3B metadata and Step4 self_quant payload.
- `ts_rank` optimized output matches old implementation on deterministic parity cases with ties and NaNs.
- self_quant quantile/long-side refactor does not change output tables beyond tolerance.
- Any real Alpha017 rerun uses formal wrapper and records proof.
- The optimization does not drop required CSV/parquet/chart artifacts.
- `/tmp` smoke has no canonical pollution.
- installed Step3/Step4/Ultimate skills are synced.

## Coder Final Report Must Include

```text
Step3B pre/post wall time if real benchmark was run.
Step4 pre/post wall time if real benchmark was run.
rows/sec before and after where available.
Which phase is still the bottleneck.
Metric parity summary.
No clean data processing unless explicitly approved.
No search worker execution.
No promotion gate changes.
No generated_code semantic changes outside regenerated formal Step3B artifacts.
```
