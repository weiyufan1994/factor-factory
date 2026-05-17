# Phase N.3C Parquet IO Contract Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reduce Step3B/Step4 IO time by making report-local Step3A daily snapshots available as parquet and making Step3B/Step4 prefer parquet while retaining CSV for audit and compatibility.

**Architecture:** Keep CSV artifacts as audit/compatibility outputs, add parquet as the performance path, and record selected IO format in metadata. Do not change factor semantics, Step4 metrics, Step6/Council logic, or promotion gates.

**Tech Stack:** pandas parquet via existing pyarrow/fastparquet availability, Factor Forge Step3A/Step3B/Step4 scripts, `/tmp` smoke fixtures, formal wrapper for real Alpha017 benchmark only after approval.

---

## Context

Alpha017 benchmark after N.3B P1 restored stable default:

```text
Step3B read_inputs:       ~9-15s
Step3B write_csv:          ~7s
Step3B write_parquet:    ~0.7s
Step4 load_daily_snapshot: ~11-12s
Step4 load_factor_values:  ~5s
```

Current daily Step3A local snapshot is CSV-only for shared daily slice:

```text
runs/<report_id>/step3a_local_inputs/daily_input__<report_id>.csv
```

Step4 and Step3B already know how to read parquet if given a parquet path, but Step3A does not consistently produce daily parquet and shared loaders default to CSV path.

---

## Non-Negotiable Constraints

- Do not delete CSV outputs.
- Do not make parquet the only formal artifact.
- Do not alter factor values, IC/NAV, signal timing, or promotion gates.
- Do not process clean data in smoke.
- Do not execute search workers.
- Do not introduce Polars in this phase.
- Do not special-case Alpha017.
- Parquet/CSV parity must be proven for row count, key columns, date range, and selected numeric columns.

---

## Files

### Modify

- `skills/factor-forge-step3/scripts/run_step3.py`
  - Write `daily_input__<report_id>.parquet` alongside CSV for shared daily slices and CPV/daily snapshots where daily dataframe exists.
  - Add `daily_df_parquet` and IO metadata to `local_input_paths`.

- `skills/factor-forge-step3/scripts/validate_step3.py`
  - Validate declared parquet exists when present.
  - Validate CSV remains present.
  - Validate parquet/csv row count and basic schema parity for smoke-size inputs.

- `skills/factor-forge-step3/scripts/run_step3b.py`
  - Prefer `daily_df_parquet` over `daily_df_csv` when selecting local input.
  - Record selected input path/format in Step3B `performance_profile`.

- `skills/factor-forge-step4/scripts/run_step4.py`
  - Prefer `daily_df_parquet` over `daily_df_csv` in local input selection.
  - Record selected input path/format in run metadata or diagnostics.

- `factor_factory/data_access/step4.py`
  - Update `load_daily_snapshot()` to prefer report-local parquet when available; fallback to CSV.
  - Return or expose selected source if needed by Step4 payload.

- `skills/factor-forge-step4/scripts/self_quant_adapter.py`
  - Record daily snapshot selected format/path in `performance_profile` or `input_io_profile`.

- `scripts/run_factorforge_performance_smoke.py`
  - Add parquet IO smoke cases.

### Optional docs

- `skills/factor-forge-step3/SKILL.md`
- `skills/factor-forge-step4/SKILL.md`
- `docs/contracts/step3-contract.md`
- `docs/contracts/step4-contract.md`

---

## Required Artifact Contract

Step3A `local_input_paths` must include when daily snapshot is materialized:

```json
{
  "daily_df_parquet": "runs/<report_id>/step3a_local_inputs/daily_input__<report_id>.parquet",
  "daily_df_csv": "runs/<report_id>/step3a_local_inputs/daily_input__<report_id>.csv",
  "daily_input_meta_json": "runs/<report_id>/step3a_local_inputs/daily_input_meta__<report_id>.json",
  "preferred_daily_format": "parquet",
  "audit_daily_format": "csv",
  "daily_io_contract": {
    "version": "factorforge_step3a_daily_io_contract_v1",
    "performance_path": "parquet",
    "audit_path": "csv",
    "csv_required_for_audit": true,
    "parquet_required_for_performance": true
  }
}
```

Step3B `run_metadata.performance_profile` should include:

```json
"input_io_profile": {
  "daily_selected_format": "parquet",
  "daily_selected_path": "...daily_input__<report_id>.parquet",
  "daily_csv_path": "...daily_input__<report_id>.csv",
  "daily_parquet_path": "...daily_input__<report_id>.parquet"
}
```

Step4 self_quant `evaluation_payload.performance_profile` should include:

```json
"input_io_profile": {
  "daily_selected_format": "parquet",
  "daily_selected_path": "...daily_input__<report_id>.parquet",
  "factor_values_selected_format": "parquet"
}
```

---

## Tasks

### Task 1: Add Step3A daily parquet output

**Files:**
- Modify: `skills/factor-forge-step3/scripts/run_step3.py`

- [ ] **Step 1: In `materialize_shared_daily_slice()`, write parquet alongside CSV**

Current code writes only:

```python
daily_csv = local_dir / f'daily_input__{report_id}.csv'
daily_df.to_csv(daily_csv, index=False)
```

Change to:

```python
daily_csv = local_dir / f'daily_input__{report_id}.csv'
daily_parquet = local_dir / f'daily_input__{report_id}.parquet'
daily_meta = local_dir / f'daily_input_meta__{report_id}.json'
for path in [daily_csv, daily_parquet]:
    if path.exists() or path.is_symlink():
        path.unlink()

daily_df.to_parquet(daily_parquet, index=False)
daily_df.to_csv(daily_csv, index=False)
```

- [ ] **Step 2: Return parquet path and IO contract**

Add fields to return dict:

```python
'daily_df_parquet': str(daily_parquet.relative_to(WORKSPACE)),
'daily_df_csv': str(daily_csv.relative_to(WORKSPACE)),
'preferred_daily_format': 'parquet',
'audit_daily_format': 'csv',
'daily_io_contract': {
    'version': 'factorforge_step3a_daily_io_contract_v1',
    'performance_path': 'parquet',
    'audit_path': 'csv',
    'csv_required_for_audit': True,
    'parquet_required_for_performance': True,
},
```

- [ ] **Step 3: Apply same daily parquet pattern to CPV/local daily fallback path**

Find code paths writing:

```python
daily_df.to_csv(daily_csv, index=False)
```

When a report-local daily dataframe is produced, also write:

```python
daily_parquet = local_dir / f'daily_input__{report_id}.parquet'
daily_df.to_parquet(daily_parquet, index=False)
```

and include `daily_df_parquet` in `local_input_paths`.

- [ ] **Step 4: Compile**

```bash
python3 -m py_compile skills/factor-forge-step3/scripts/run_step3.py
```

Expected rc 0.

### Task 2: Update Step3 validation for parquet/csv contract

**Files:**
- Modify: `skills/factor-forge-step3/scripts/validate_step3.py`

- [ ] **Step 1: Prefer parquet but require CSV audit path**

Add checks:

```text
local_input_paths.daily_df_parquet exists when preferred_daily_format=parquet
local_input_paths.daily_df_csv exists for audit
local_input_paths.daily_io_contract.version == factorforge_step3a_daily_io_contract_v1
```

- [ ] **Step 2: Add small parity check**

For declared parquet and CSV:

```python
pq = pd.read_parquet(parquet_path)
cs = pd.read_csv(csv_path, nrows=len(pq) if len(pq) <= 10000 else 10000)
```

To avoid heavy full reads, for large canonical data only check:

```text
parquet row count > 0
csv exists and size > 0
required columns overlap
```

For `/tmp` smoke-size fixtures, check full row count and required key columns.

- [ ] **Step 3: BLOCK tokens**

Use clear messages/codes:

```text
STEP3_DAILY_PARQUET_MISSING
STEP3_DAILY_CSV_AUDIT_MISSING
STEP3_DAILY_IO_CONTRACT_MISSING
STEP3_DAILY_PARQUET_CSV_SCHEMA_MISMATCH
```

### Task 3: Make Step3B prefer daily parquet and record IO profile

**Files:**
- Modify: `skills/factor-forge-step3/scripts/run_step3b.py`

- [ ] **Step 1: Confirm local input selection already prefers parquet**

Current logic should be:

```python
daily_rel = local_inputs.get('daily_df_parquet') or local_inputs.get('daily_df_csv')
```

If not, change to this.

- [ ] **Step 2: Record selected input format**

After resolving `daily_path`, add:

```python
daily_selected_format = 'parquet' if daily_path and daily_path.suffix.lower() == '.parquet' else 'csv'
```

In `performance_profile`, add:

```python
'input_io_profile': {
    'daily_selected_format': daily_selected_format,
    'daily_selected_path': str(daily_path) if daily_path else None,
    'daily_parquet_path': str(resolve_local_input_path(local_inputs.get('daily_df_parquet'))) if local_inputs.get('daily_df_parquet') else None,
    'daily_csv_path': str(resolve_local_input_path(local_inputs.get('daily_df_csv'))) if local_inputs.get('daily_df_csv') else None,
}
```

- [ ] **Step 3: Smoke must assert selected format parquet when both exist**

Add assertion in performance smoke Step3B profile case.

### Task 4: Make Step4 and self_quant prefer daily parquet

**Files:**
- Modify: `factor_factory/data_access/step4.py`
- Modify: `skills/factor-forge-step4/scripts/run_step4.py`
- Modify: `skills/factor-forge-step4/scripts/self_quant_adapter.py`

- [ ] **Step 1: Add daily snapshot path resolver**

In `factor_factory/data_access/step4.py`, add:

```python
def resolve_daily_snapshot_path(report_id: str, runs_root: Path | None = None) -> tuple[Path, str]:
    root = runs_root or RUNS
    base = root / report_id / 'step3a_local_inputs'
    parquet_path = base / f'daily_input__{report_id}.parquet'
    csv_path = base / f'daily_input__{report_id}.csv'
    if parquet_path.exists():
        return parquet_path, 'parquet'
    if csv_path.exists():
        return csv_path, 'csv'
    raise FileNotFoundError(f'missing daily input: {parquet_path} or {csv_path}')
```

Update `load_daily_snapshot()`:

```python
path, fmt = resolve_daily_snapshot_path(report_id, runs_root=runs_root)
if fmt == 'parquet':
    return pd.read_parquet(path, columns=list(columns) if columns else None)
return pd.read_csv(path, usecols=list(columns) if columns else None)
```

Export `resolve_daily_snapshot_path` in `factor_factory/data_access/__init__.py`.

- [ ] **Step 2: Step4 run path already prefers `daily_df_parquet`**

Confirm `run_step4.py` has:

```python
daily_path = local_inputs.get('daily_df_parquet') or local_inputs.get('daily_df_csv')
```

Add run metadata/diagnostics field:

```python
'input_io_profile': {
    'daily_selected_format': 'parquet' if daily_file.suffix.lower() == '.parquet' else 'csv',
    'daily_selected_path': str(daily_file),
}
```

- [ ] **Step 3: self_quant payload records selected daily format/path**

In `self_quant_adapter.py`, import resolver:

```python
from factor_factory.data_access import resolve_daily_snapshot_path
```

Before loading daily snapshot:

```python
daily_snapshot_path, daily_snapshot_format = resolve_daily_snapshot_path(report_id)
```

Add to `performance_profile`:

```python
'input_io_profile': {
    'daily_selected_format': daily_snapshot_format,
    'daily_selected_path': str(daily_snapshot_path),
    'factor_values_selected_format': 'parquet',
}
```

### Task 5: Add performance smoke coverage

**Files:**
- Modify: `scripts/run_factorforge_performance_smoke.py`

- [ ] **Step 1: Update fixtures to write both CSV and parquet daily inputs**

Where smoke writes:

```python
daily.to_csv(daily_path, index=False)
```

also write:

```python
daily.to_parquet(parquet_path, index=False)
```

and include both in `local_input_paths`.

- [ ] **Step 2: Add cases**

Required case names:

```text
step3a_daily_parquet_and_csv_contract_present
step3b_prefers_daily_parquet_when_available
step4_self_quant_prefers_daily_parquet_when_available
step4_daily_csv_fallback_when_parquet_missing
step3_daily_parquet_csv_schema_parity
```

- [ ] **Step 3: Assert no false pass**

For parquet preference cases, assert:

```text
selected format == parquet
selected path endswith .parquet
```

For fallback case:

```text
remove parquet
selected format == csv
selected path endswith .csv
```

### Task 6: Final verification and sync

**Files:**
- All changed files.

- [ ] **Step 1: Compile**

```bash
python3 -m py_compile \
  factor_factory/data_access/__init__.py \
  factor_factory/data_access/step4.py \
  skills/factor-forge-step3/scripts/run_step3.py \
  skills/factor-forge-step3/scripts/validate_step3.py \
  skills/factor-forge-step3/scripts/run_step3b.py \
  skills/factor-forge-step4/scripts/run_step4.py \
  skills/factor-forge-step4/scripts/self_quant_adapter.py \
  scripts/run_factorforge_performance_smoke.py
```

- [ ] **Step 2: Run smoke/regression**

```bash
python3 scripts/run_factorforge_performance_smoke.py --fresh --root /tmp/factorforge_performance_phase_n3c
python3 scripts/run_step12_hypothesis_contract_smoke.py --fresh --root /tmp/factorforge_step12_hypothesis_contract_phase_n3c_regression
python3 scripts/run_step6_intelligence_acceptance.py --fresh --root /tmp/factorforge_step6_intelligence_acceptance_phase_n3c_regression
python3 scripts/run_factorforge_ultimate_loop_smoke.py --fresh --root /tmp/factorforge_ultimate_loop_phase_n3c_regression
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

- [ ] **Step 4: Installed sync**

```bash
rsync -a --delete skills/factor-forge-step3/ /Users/humphrey/.codex/skills/factor-forge-step3/
rsync -a --delete skills/factor-forge-step4/ /Users/humphrey/.codex/skills/factor-forge-step4/
rsync -a --delete skills/factor-forge-ultimate/ /Users/humphrey/.codex/skills/factor-forge-ultimate/
diff -qr -x __pycache__ skills/factor-forge-step3 /Users/humphrey/.codex/skills/factor-forge-step3
diff -qr -x __pycache__ skills/factor-forge-step4 /Users/humphrey/.codex/skills/factor-forge-step4
diff -qr -x __pycache__ skills/factor-forge-ultimate /Users/humphrey/.codex/skills/factor-forge-ultimate
```

---

## Optional Real Alpha017 Benchmark After Review

Only after reviewer acceptance, run:

```bash
python3 scripts/run_factorforge_ultimate.py \
  --report-id ALPHA017_CANONICAL_FORMULA_20160101_LOOP_HYP \
  --start-step 3 \
  --end-step 4 \
  --council-mode off

python3 scripts/run_factorforge_performance_profile.py \
  --report-id ALPHA017_CANONICAL_FORMULA_20160101_LOOP_HYP \
  --write-report
```

Use `--start-step 3`, not `3b`, because Step3A must regenerate the report-local parquet daily snapshot.

Expected improvement target:

```text
Step3B read_inputs lower than previous 9-15s
Step4 load_daily_snapshot lower than previous 11-12s
Step3B write_csv unchanged unless separate CSV policy is added later
metrics unchanged
```

---

## Reviewer Acceptance Checklist

BLOCK if any item fails:

- CSV audit output remains present.
- Daily parquet is produced by Step3A where daily snapshot exists.
- Step3B prefers parquet when both parquet and CSV are declared.
- Step4/self_quant prefers parquet when both exist and falls back to CSV when parquet is absent.
- Parquet/CSV schema/key parity is checked in smoke.
- No Step6/Council/promotion gate changes.
- No clean data processing in smoke.
- No Polars introduced in this phase.

