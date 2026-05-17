# Phase N.3D CSV Output Policy Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reduce avoidable Step3A/Step3B full-CSV write cost while preserving a deterministic audit path and validator-visible output contract.

**Architecture:** Keep parquet as the formal performance path and keep CSV as an audit artifact governed by an explicit policy. Do not remove CSV globally. Add policy fields to Step3A daily IO and Step3B factor output metadata, then update validators/smokes so full CSV, sampled CSV, and disabled CSV behavior are explicit and safe.

**Tech Stack:** Python, pandas, parquet, existing Factor Forge Step3/Step3B validators, `/tmp` performance smoke, existing `PhaseTimer` metadata.

---

## Boundary

This phase is only about Step3A/Step3B CSV output policy and performance metadata.

Do not change:
- Step6 / Council / promotion gate semantics.
- Factor formula semantics or Alpha017-specific logic.
- Clean data processing.
- Search worker behavior.
- Step4 label timing contract.
- Pandas correctness oracle / experimental Polars backend.

## Policy Contract

Add a CSV policy with exactly these modes:

```text
full_csv      write full CSV audit artifact, current behavior
sample_csv    write deterministic sample CSV audit artifact plus schema/header metadata
no_csv        write no CSV artifact; allowed only when explicit performance mode is enabled
```

Default behavior must remain `full_csv` unless the caller explicitly requests a different policy.

For formal research, `full_csv` remains safest. For performance benchmark runs, `sample_csv` is the intended mode. `no_csv` must be opt-in and must not be silently selected by default.

## Files

Modify:
- `/Users/humphrey/projects/factor-factory/skills/factor-forge-step3/scripts/run_step3.py`
- `/Users/humphrey/projects/factor-factory/skills/factor-forge-step3/scripts/validate_step3.py`
- `/Users/humphrey/projects/factor-factory/skills/factor-forge-step3/scripts/run_step3b.py`
- `/Users/humphrey/projects/factor-factory/scripts/run_factorforge_performance_smoke.py`
- `/Users/humphrey/projects/factor-factory/scripts/run_factorforge_performance_profile.py`
- `/Users/humphrey/projects/factor-factory/skills/factor-forge-step3/SKILL.md`

Do not modify unless tests prove it is necessary:
- `/Users/humphrey/projects/factor-factory/skills/factor-forge-step4/scripts/run_step4.py`
- `/Users/humphrey/projects/factor-factory/skills/factor-forge-step4/scripts/self_quant_adapter.py`

## Task 1: Add Shared CSV Policy Helpers

**Files:**
- Modify: `/Users/humphrey/projects/factor-factory/skills/factor-forge-step3/scripts/run_step3.py`
- Modify: `/Users/humphrey/projects/factor-factory/skills/factor-forge-step3/scripts/run_step3b.py`

- [ ] Add a small local helper in each script or a duplicated minimal helper if avoiding a new shared module is simpler.

Required behavior:

```python
CSV_POLICY_VALUES = {"full_csv", "sample_csv", "no_csv"}


def resolve_csv_policy(explicit_policy: str | None = None) -> str:
    policy = explicit_policy or os.getenv("FACTORFORGE_CSV_OUTPUT_POLICY") or "full_csv"
    if policy not in CSV_POLICY_VALUES:
        raise SystemExit(f"BLOCK_FACTORFORGE_INVALID_CSV_OUTPUT_POLICY:{policy}")
    return policy
```

- [ ] Add deterministic sample helper.

Required behavior:

```python
def deterministic_csv_sample(df: pd.DataFrame, *, max_rows: int = 10000) -> pd.DataFrame:
    if len(df) <= max_rows:
        return df.copy()
    # Deterministic by preserving sorted/order-stable head/tail coverage.
    head_n = max_rows // 2
    tail_n = max_rows - head_n
    return pd.concat([df.head(head_n), df.tail(tail_n)], ignore_index=True)
```

Do not use random sampling for this phase.

## Task 2: Step3A Daily CSV Policy

**Files:**
- Modify: `/Users/humphrey/projects/factor-factory/skills/factor-forge-step3/scripts/run_step3.py`
- Modify: `/Users/humphrey/projects/factor-factory/skills/factor-forge-step3/scripts/validate_step3.py`

- [ ] Add CLI flag if Step3 parser already exists:

```text
--csv-output-policy full_csv|sample_csv|no_csv
```

- [ ] If Step3 is invoked by wrapper without this flag, default must be `full_csv`.

- [ ] Update Step3A daily IO metadata to include:

```json
{
  "daily_io_contract": {
    "version": "factorforge_step3a_daily_io_contract_v1",
    "performance_path": "parquet",
    "audit_path": "csv",
    "csv_output_policy": "full_csv|sample_csv|no_csv",
    "csv_rows_written": 0,
    "parquet_rows_written": 0,
    "csv_sample_strategy": "full|head_tail|none",
    "full_csv_available": true,
    "schema_parity_required": true,
    "value_parity_required": true
  }
}
```

Required semantics:
- `full_csv`: write current full daily CSV; `full_csv_available=true`; `csv_sample_strategy=full`; schema parity and value parity can be validated for small fixtures.
- `sample_csv`: write `daily_input_sample__<report_id>.csv`; do not write full `daily_input__<report_id>.csv`; set `audit_daily_format=csv_sample`; set `full_csv_available=false`; schema parity required against sample header; value parity not required globally.
- `no_csv`: write no CSV; set `audit_daily_format=none`; `full_csv_available=false`; schema parity/value parity cannot be required.

- [ ] Preserve parquet output path exactly as currently used.

- [ ] Validator changes:
  - full_csv: current parquet/CSV schema check remains required.
  - sample_csv: require sample CSV exists, header matches parquet schema, sample row count equals metadata `csv_rows_written`, and no full CSV is required.
  - no_csv: require metadata says no audit CSV and no CSV path is claimed.
  - invalid/missing policy: BLOCK with `STEP3_DAILY_CSV_POLICY_INVALID`.
  - sample metadata claims file exists but file missing: BLOCK with `STEP3_DAILY_CSV_AUDIT_MISSING`.
  - sample schema mismatch: BLOCK with `STEP3_DAILY_PARQUET_CSV_SCHEMA_MISMATCH`.

## Task 3: Step3B Factor CSV Policy

**Files:**
- Modify: `/Users/humphrey/projects/factor-factory/skills/factor-forge-step3/scripts/run_step3b.py`

- [ ] Add CLI/environment policy resolution using the same modes.

- [ ] In `generate_first_run_factor_values(...)`, keep parquet write unchanged.

- [ ] Replace unconditional full factor CSV write with policy-aware output:

Required semantics:
- `full_csv`: write current `factor_values__<report_id>.csv`.
- `sample_csv`: write `factor_values_sample__<report_id>.csv` using deterministic head/tail sample; do not write full CSV.
- `no_csv`: do not write factor CSV.

- [ ] Update returned output paths and run metadata:

```json
{
  "performance_profile": {
    "csv_output_profile": {
      "version": "factorforge_step3b_csv_output_policy_v1",
      "csv_output_policy": "full_csv|sample_csv|no_csv",
      "parquet_rows_written": 0,
      "csv_rows_written": 0,
      "csv_sample_strategy": "full|head_tail|none",
      "full_csv_available": true,
      "csv_path": "... or null",
      "csv_sample_path": "... or null",
      "write_csv_seconds": 0.0
    }
  }
}
```

- [ ] Keep the top-level `phase_seconds.write_csv` key for backward compatibility. For `no_csv`, it should exist and be near zero, not missing.

- [ ] If any downstream artifact currently requires `factor_csv_path`, keep the key but set it to the sample path only when policy is `sample_csv` and name it clearly in metadata. Do not let Step4 read factor CSV if parquet is available.

## Task 4: Performance Profile Script

**Files:**
- Modify: `/Users/humphrey/projects/factor-factory/scripts/run_factorforge_performance_profile.py`

- [ ] Include Step3B `csv_output_profile` in the written report.

Required top-level summary fields:

```json
{
  "step3b_csv_output_profile": {...},
  "step3b_write_csv_seconds": 0.0,
  "step3b_factor_parquet_bytes": 0,
  "step3b_factor_csv_bytes": 0
}
```

- [ ] If policy is `sample_csv`, report sample CSV bytes separately and do not mislabel it as full CSV bytes.

## Task 5: Performance Smoke Coverage

**Files:**
- Modify: `/Users/humphrey/projects/factor-factory/scripts/run_factorforge_performance_smoke.py`

Add these smoke cases under `/tmp`:

1. `step3a_daily_full_csv_policy_contract`
   - Build Step3A fixture with default policy.
   - Assert full daily CSV and parquet exist.
   - Assert validator rc=0.
   - Assert policy metadata says `full_csv`.

2. `step3a_daily_sample_csv_policy_contract`
   - Run Step3A with `FACTORFORGE_CSV_OUTPUT_POLICY=sample_csv` or CLI flag.
   - Assert parquet exists.
   - Assert full `daily_input__<report_id>.csv` does not exist.
   - Assert `daily_input_sample__<report_id>.csv` exists.
   - Assert validator rc=0.
   - Assert sample CSV header equals parquet schema.

3. `step3a_daily_sample_schema_mismatch_block`
   - Mutate sample CSV header.
   - Assert validator rc=1 and token `STEP3_DAILY_PARQUET_CSV_SCHEMA_MISMATCH`.

4. `step3b_factor_sample_csv_policy_contract`
   - Run real `generate_first_run_factor_values(...)` fixture with `sample_csv`.
   - Assert factor parquet exists.
   - Assert full factor CSV absent.
   - Assert sample factor CSV exists.
   - Assert metadata `csv_output_profile.csv_output_policy=sample_csv`.
   - Assert `phase_seconds.write_csv` exists.

5. `step3b_factor_no_csv_policy_contract`
   - Run fixture with `no_csv`.
   - Assert factor parquet exists.
   - Assert no factor CSV/sample CSV exists.
   - Assert metadata policy `no_csv` and `csv_rows_written=0`.

6. `csv_policy_invalid_blocks`
   - Set policy to `bad_policy`.
   - Assert rc=1 and token `BLOCK_FACTORFORGE_INVALID_CSV_OUTPUT_POLICY` or corresponding validator token.

- [ ] The smoke verdict must require all new cases plus canonical pollution false.

## Task 6: Regression Commands

Run exactly these after implementation:

```bash
python3 -m py_compile \
  skills/factor-forge-step3/scripts/run_step3.py \
  skills/factor-forge-step3/scripts/validate_step3.py \
  skills/factor-forge-step3/scripts/run_step3b.py \
  scripts/run_factorforge_performance_profile.py \
  scripts/run_factorforge_performance_smoke.py
```

Expected: rc=0.

```bash
python3 scripts/run_factorforge_performance_smoke.py --fresh --root /tmp/factorforge_performance_phase_n3d_csv_policy
```

Expected:
- rc=0
- `verdict=ACCEPT`
- `canonical_pollution.polluted=false`

```bash
python3 scripts/run_factorforge_performance_smoke.py --fresh --root /Users/humphrey/tmp_factorforge_bad_n3d
```

Expected:
- rc=1
- token `BLOCK_NON_TMP_FACTORFORGE_ROOT`

Regression commands:

```bash
python3 scripts/run_step12_hypothesis_contract_smoke.py --fresh --root /tmp/factorforge_step12_n3d_regression
python3 scripts/run_step6_intelligence_acceptance.py --fresh --root /tmp/factorforge_step6_intelligence_acceptance_n3d_regression
python3 scripts/run_factorforge_ultimate_loop_smoke.py --fresh --root /tmp/factorforge_ultimate_loop_n3d_regression
```

Expected:
- Step12 verdict `ACCEPT`
- Step6 token `STEP6_INTELLIGENCE_ACCEPTED`
- Loop smoke verdict `ACCEPT`

## Task 7: Installed Skill Sync

After tests pass, sync installed Step3 skill only if Step3 scripts/docs changed:

```bash
rsync -a --delete --exclude '__pycache__' \
  /Users/humphrey/projects/factor-factory/skills/factor-forge-step3/ \
  /Users/humphrey/.codex/skills/factor-forge-step3/

diff -qr -x __pycache__ \
  /Users/humphrey/projects/factor-factory/skills/factor-forge-step3 \
  /Users/humphrey/.codex/skills/factor-forge-step3
```

Expected: diff rc=0 / no diff.

## Task 8: Real Alpha017 Benchmark Is Separate

Do not run Alpha017 benchmark in this implementation phase unless explicitly approved after reviewer accepts the smoke-level implementation.

If later approved, use formal wrapper only:

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

Expected benchmark output must report:
- Step3B `write_csv` before/after.
- Step3B total before/after.
- Whether full CSV/sample/no CSV was used.
- Metric parity: Rank IC, Pearson IC, long-side annual return, cost-adjusted annual return.
- Confirm no clean data processing, no search worker, no Step6/Council/promotion gate, no official promotion.

## Review Checklist For Reviewer

Reviewer should specifically check:
- Default remains `full_csv`.
- `sample_csv` and `no_csv` are explicit opt-ins.
- Parquet remains the formal performance path.
- Validators understand policy and do not falsely require full CSV when policy is sample/no CSV.
- Validators do not silently pass missing sample audit files.
- Smoke has negative coverage for schema mismatch and invalid policy.
- No Step6/Council/promotion gate changes.
- No clean data/search worker execution.
- No Alpha017 benchmark unless separately approved.
