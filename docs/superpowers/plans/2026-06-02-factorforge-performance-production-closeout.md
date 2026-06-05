# Factor Forge Performance Production Closeout Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the Factor Forge high-performance Step3B/Step4 path production-proven on Mac and EC2, with strict reuse gates, explicit runtime branch handling, and clear remaining-kernel default rules.

**Architecture:** Factor Forge remains a Data API consumer. Step3A resolves data requirements and writes contracts; Step3B computes sample/proof factor values with default safe acceleration; Step4 owns formal factor values and reuses only identity-matched compute artifacts. Mac `main` and EC2 runtime branches may differ only for orchestration/control-plane glue, not for factor computation semantics.

**Tech Stack:** Python 3, pandas, NumPy, Parquet, Factor Forge skills under `skills/factor-forge-step3` and `skills/factor-forge-step4`, performance smoke scripts under `scripts/`, Git branches for Mac/main and Humphrey EC2 runtime.

---

## Required Branch Discipline

Work from a clean worktree. Do not continue in `/Users/humphrey/projects/factor-factory` if it is dirty.

Recommended setup:

```bash
cd /Users/humphrey/projects/factor-factory
git fetch origin
git worktree add /tmp/factorforge-performance-closeout origin/main
cd /tmp/factorforge-performance-closeout
git switch -c codex/factorforge-performance-production-closeout
```

Do not modify:
- raw market data
- Data API package internals except client-facing metadata checks explicitly needed by this plan
- Step1/Step2 economic hypothesis contracts
- Step5/Step6 mathematical research contracts
- portfolio construction rules

Do not run:
- full unbounded production research jobs without a human-approved report id and run id
- EC2 destructive commands
- data cleaning jobs inside Factor Forge

---

## Files Map

Likely modified files:

- `skills/factor-forge-step3/scripts/run_step3b.py`
  - Add/verify metadata proving default acceleration, sampling caps, IO policy, and compute-cache identity.
- `skills/factor-forge-step4/scripts/run_step4.py`
  - Enforce strict reuse gates and expose why Step4 reused or recomputed factor values.
- `scripts/run_factorforge_performance_smoke.py`
  - Add regression cases for real-run metadata requirements, strict reuse identity, and remaining-kernel default policy.
- `scripts/run_factorforge_performance_profile.py`
  - Surface production diagnostics for compute reuse, CSV policy, default kernels, and recompute fallback.
- `scripts/run_factorforge_operator_candidate_benchmark.py`
  - Ensure remaining operator candidates report enough evidence to decide default vs opt-in.
- `scripts/run_factorforge_operator_kernel_inventory.py`
  - Report default-enabled, opt-in-only, blocked, and not-yet-reviewed operator classes.
- `docs/operations/factorforge-entrypoint-registry.json`
  - Add any new executable smoke/profile scripts.
- `docs/operations/factorforge-performance-production-closeout.md`
  - Create final operator/reuse/runtime evidence report.

Avoid changing these unless tests prove they are the right location:

- `factor_factory/data_api/`
- `factor_factory/data_access/`
- `skills/factor-forge-step1/`
- `skills/factor-forge-step2/`
- `skills/factor-forge-step5/`
- `skills/factor-forge-step6/`

---

### Task 1: Real Run Performance Proof On Mac And EC2

**Objective:** Prove high-performance defaults work in real Step3B/Step4 runs, not only synthetic smoke fixtures.

**Boundary:** Use one approved existing report/run fixture or create a small formal test run through the wrapper. Do not alter factor formulas, raw data, Data API cleaning, or Step5/Step6 research conclusions.

**Files:**
- Modify: `skills/factor-forge-step3/scripts/run_step3b.py`
- Modify: `skills/factor-forge-step4/scripts/run_step4.py`
- Modify: `scripts/run_factorforge_performance_profile.py`
- Modify: `scripts/run_factorforge_performance_smoke.py`
- Create: `docs/operations/factorforge-performance-production-closeout.md`

- [ ] **Step 1: Add a RED smoke case requiring production-run performance evidence**

Add a case to `scripts/run_factorforge_performance_smoke.py` that builds a temporary Step3B/Step4 run and fails unless the run metadata includes these fields:

```json
{
  "performance_profile.version": "factorforge_step3b_performance_profile_v1",
  "performance_profile.formula_kernel_profile.default_numpy_ts_profile.enabled": true,
  "performance_profile.phase_seconds.compute_factor": "number >= 0",
  "input_io_profile.daily_selected_format": "parquet",
  "step4_factor_io_profile.version": "factorforge_step4_factor_io_profile_v1",
  "step4_factor_io_profile.selected_factor_format": "parquet",
  "step4_factor_io_profile.recomputed_factor": "boolean"
}
```

Use a case name exactly:

```python
"real_run_performance_metadata_contract"
```

- [ ] **Step 2: Run the RED case**

Run:

```bash
python3 scripts/run_factorforge_performance_smoke.py
```

Expected before implementation:

```text
"case": "real_run_performance_metadata_contract"
"ok": false
```

- [ ] **Step 3: Implement missing metadata writes**

Ensure Step3B writes:

```python
performance_profile = {
    "version": "factorforge_step3b_performance_profile_v1",
    "phase_seconds": phase_seconds,
    "formula_kernel_profile": evaluator_profile.get("kernel_profile"),
    "normalize_sort_profile": normalize_sort_profile,
    "sample_cap": sample_cap_profile,
    "input_io_profile": input_io_profile,
}
```

Ensure Step4 writes:

```python
step4_factor_io_profile = {
    "version": "factorforge_step4_factor_io_profile_v1",
    "source": selected_factor_source,
    "selected_factor_format": "parquet",
    "selected_factor_path": str(parquet_path),
    "recomputed_factor": recomputed_factor,
    "parquet_written_by_step4": parquet_written_by_step4,
    "reuse_gate": reuse_gate_profile,
}
```

If equivalent fields already exist, do not duplicate them. Extend the existing dicts.

- [ ] **Step 4: Add real-run profile report output**

Update `scripts/run_factorforge_performance_profile.py` so it emits diagnostic codes:

```text
DEFAULT_NUMPY_TS_KERNELS_ENABLED
STEP3B_PERFORMANCE_PROFILE_PRESENT
STEP4_FACTOR_REUSE_PROFILE_PRESENT
STEP4_RECOMPUTE_FALLBACK
PARQUET_FORMAL_EVIDENCE_OK
FULL_CSV_ABSENT_BY_POLICY
```

The script must not require CSV if Parquet formal evidence exists.

- [ ] **Step 5: Verify locally**

Run:

```bash
python3 -m py_compile \
  skills/factor-forge-step3/scripts/run_step3b.py \
  skills/factor-forge-step4/scripts/run_step4.py \
  scripts/run_factorforge_performance_profile.py \
  scripts/run_factorforge_performance_smoke.py
python3 scripts/run_factorforge_performance_smoke.py
```

Expected:

```text
"verdict": "ACCEPT"
"case": "real_run_performance_metadata_contract"
"ok": true
```

- [ ] **Step 6: Run one Mac proof job**

Use an approved existing small report/run. If no approved real report is supplied, run only the synthetic smoke and mark this item blocked with:

```text
BLOCK_REAL_MAC_REPORT_NOT_PROVIDED
```

When a real report is approved, collect:

```text
report_id
run_id
repo_sha
artifact_root
step3b run_metadata path
step4 run_metadata path
performance_profile.phase_seconds
step4_factor_io_profile.source
```

- [ ] **Step 7: Run one EC2 worker proof job**

Use the same report and compare metadata. If EC2 is not available or the user has not approved worker startup, mark blocked with:

```text
BLOCK_EC2_WORKER_NOT_APPROVED_OR_UNAVAILABLE
```

Do not start EC2 without explicit approval.

- [ ] **Step 8: Write final evidence report**

Create `docs/operations/factorforge-performance-production-closeout.md` with sections:

```markdown
## Mac Proof
## EC2 Proof
## Default Acceleration Evidence
## Reuse Evidence
## CSV/Parquet IO Evidence
## Remaining Blocks
```

- [ ] **Step 9: Commit**

```bash
git add \
  skills/factor-forge-step3/scripts/run_step3b.py \
  skills/factor-forge-step4/scripts/run_step4.py \
  scripts/run_factorforge_performance_profile.py \
  scripts/run_factorforge_performance_smoke.py \
  docs/operations/factorforge-performance-production-closeout.md
git commit -m "Verify Factor Forge production performance path"
```

---

### Task 2: EC2 Runtime Branch Reconciliation

**Objective:** Reconcile `humphrey-ec2/factorforge-step3-step4-data-api-runtime` with current `main` while preserving EC2-only OpenClaw/SSM/control-plane behavior.

**Boundary:** Do not fast-forward or overwrite the EC2 runtime branch until the diff is classified and smoke-tested. Do not remove control-plane scripts unless a test proves they are obsolete.

**Files:**
- Modify: `docs/operations/factorforge-performance-production-closeout.md`
- Modify if needed: `docs/operations/factorforge-entrypoint-registry.json`
- Modify if needed: EC2 runtime control scripts already present on the EC2 runtime branch

- [ ] **Step 1: Create a runtime reconciliation worktree**

```bash
cd /Users/humphrey/projects/factor-factory
git fetch origin
git worktree add /tmp/factorforge-ec2-runtime-reconcile origin/humphrey-ec2/factorforge-step3-step4-data-api-runtime
cd /tmp/factorforge-ec2-runtime-reconcile
git switch -c humphrey-ec2/factorforge-runtime-reconcile-20260602
```

- [ ] **Step 2: Classify branch delta**

Run:

```bash
git log --oneline --left-right --cherry-pick origin/main...HEAD
git diff --name-only origin/main..HEAD
```

Create a table in `docs/operations/factorforge-performance-production-closeout.md`:

```markdown
| File/Commit | Class | Keep/Merge/Drop | Reason | Verification |
| --- | --- | --- | --- | --- |
| scripts/factorforgectl.py | EC2 control-plane | Keep | required by Humphrey/OpenClaw runtime | control-plane smoke |
```

Allowed classes:

```text
EC2 control-plane
worker dispatch
artifact sync
already merged into main
obsolete duplicate
needs human review
```

- [ ] **Step 3: Merge current main into runtime branch**

```bash
git merge origin/main
```

Resolve conflicts by preserving:

```text
Step3/Step4 computation semantics from origin/main
EC2/OpenClaw orchestration glue from runtime branch
```

Do not preserve older Step3/Step4 compute logic if it conflicts with `origin/main`.

- [ ] **Step 4: Verify entrypoint registry**

Run:

```bash
python3 scripts/run_factorforge_entrypoint_hygiene_smoke.py
```

Expected:

```text
"verdict": "ACCEPT"
```

If new runtime scripts are legitimate, add them to `docs/operations/factorforge-entrypoint-registry.json`.

- [ ] **Step 5: Verify control-plane smoke**

Run the available control-plane smoke scripts if present:

```bash
python3 scripts/run_factorforge_v2_control_plane_smoke.py
python3 scripts/run_factorforge_run_isolation_smoke.py
python3 scripts/run_factorforge_formal_artifact_smoke.py
```

Expected for each:

```text
ACCEPT or zero failed cases
```

If a script is absent on the branch, record:

```text
BLOCK_CONTROL_PLANE_SMOKE_SCRIPT_ABSENT: <script>
```

- [ ] **Step 6: Verify performance smoke on reconciled runtime branch**

```bash
python3 scripts/run_factorforge_performance_smoke.py
```

Expected:

```text
"verdict": "ACCEPT"
```

- [ ] **Step 7: Push reconciled runtime branch**

```bash
git push origin humphrey-ec2/factorforge-runtime-reconcile-20260602
```

Do not update `origin/humphrey-ec2/factorforge-step3-step4-data-api-runtime` directly until review approval.

- [ ] **Step 8: Commit**

```bash
git add docs/operations/factorforge-performance-production-closeout.md docs/operations/factorforge-entrypoint-registry.json
git commit -m "Reconcile Factor Forge EC2 runtime performance branch"
```

---

### Task 3: Remaining Operator Default Policy

**Objective:** Decide which remaining high-performance operators can become default and which must stay opt-in.

**Boundary:** Do not default an operator without parity, edge-case, smoke, and rollback evidence. Do not default Polars or broad formula-kernel execution as a single switch.

**Files:**
- Modify: `factor_factory/formula/operators.py`
- Modify: `factor_factory/formula/fast_rolling.py`
- Modify: `factor_factory/formula/operator_candidate_benchmarks.py`
- Modify: `scripts/run_factorforge_operator_candidate_benchmark.py`
- Modify: `scripts/run_factorforge_operator_kernel_inventory.py`
- Modify: `scripts/run_factorforge_performance_smoke.py`
- Modify: `docs/operations/factorforge-performance-production-closeout.md`

- [ ] **Step 1: Add explicit inventory classes**

Update `scripts/run_factorforge_operator_kernel_inventory.py` to classify every operator into one of:

```text
default_enabled
opt_in_only
blocked_by_parity
blocked_by_edge_case
blocked_by_benchmark
not_reviewed
not_applicable
```

The report must include at least:

```text
ts_min
ts_max
ts_delta
ts_delay
ts_argmin
ts_argmax
ts_rank
rolling_corr
rolling_cov
ts_sum
ts_mean
ts_std
ts_stddev
polars_formula_engine
experimental_formula_kernel
```

- [ ] **Step 2: Add RED smoke case for remaining default policy**

In `scripts/run_factorforge_performance_smoke.py`, add:

```python
"operator_default_policy_is_explicit"
```

It must fail unless:

```text
default-enabled operators are explicitly listed
non-default operators have a blocking reason
rollback env exists for any newly defaulted operator
```

- [ ] **Step 3: Benchmark candidate operators**

Run:

```bash
python3 scripts/run_factorforge_operator_candidate_benchmark.py --output /tmp/factorforge_operator_candidates.json --allow-tmp-output
```

Expected:

```text
diagnostic_codes include OPERATOR_CANDIDATE_BENCHMARK_READ_ONLY
```

If `ts_sum`, `ts_mean`, `ts_std`, or `ts_stddev` do not pass parity and edge cases, keep them `opt_in_only` or `blocked_*`.

- [ ] **Step 4: Default only proven operators**

If an operator passes, wire it behind existing default kernel profile and rollback env:

```text
FACTORFORGE_DISABLE_DEFAULT_NUMPY_TS_KERNEL=1
```

If it does not pass, do not wire it. Add a reason to inventory output.

- [ ] **Step 5: Verify no accidental Polars default**

Add or preserve a smoke assertion:

```text
Polars remains opt-in unless FACTORFORGE_ENABLE_EXPERIMENTAL_POLARS=1
experimental formula kernel remains opt-in unless FACTORFORGE_ENABLE_EXPERIMENTAL_FORMULA_KERNEL=1
```

- [ ] **Step 6: Run verification**

```bash
python3 -m py_compile \
  factor_factory/formula/operators.py \
  factor_factory/formula/fast_rolling.py \
  factor_factory/formula/operator_candidate_benchmarks.py \
  scripts/run_factorforge_operator_candidate_benchmark.py \
  scripts/run_factorforge_operator_kernel_inventory.py \
  scripts/run_factorforge_performance_smoke.py
python3 scripts/run_factorforge_operator_kernel_inventory.py --output /tmp/factorforge_operator_inventory.json --allow-tmp-output
python3 scripts/run_factorforge_performance_smoke.py
```

Expected:

```text
"verdict": "ACCEPT"
"case": "operator_default_policy_is_explicit"
"ok": true
```

- [ ] **Step 7: Commit**

```bash
git add \
  factor_factory/formula/operators.py \
  factor_factory/formula/fast_rolling.py \
  factor_factory/formula/operator_candidate_benchmarks.py \
  scripts/run_factorforge_operator_candidate_benchmark.py \
  scripts/run_factorforge_operator_kernel_inventory.py \
  scripts/run_factorforge_performance_smoke.py \
  docs/operations/factorforge-performance-production-closeout.md
git commit -m "Close Factor Forge operator default policy"
```

---

### Task 4: Strict Reuse Gate For Step3B/Step4 Artifacts

**Objective:** Enforce “reuse when legal, recompute when identity differs” for factor values and compute caches.

**Boundary:** Reuse may only happen when identity and data contracts match. Step3B sample proof parquet must never become formal Step4 factor values by accident.

**Files:**
- Modify: `skills/factor-forge-step3/scripts/run_step3b.py`
- Modify: `skills/factor-forge-step4/scripts/run_step4.py`
- Modify: `scripts/run_factorforge_performance_smoke.py`
- Modify: `scripts/run_factorforge_performance_profile.py`
- Modify: `docs/operations/factorforge-performance-production-closeout.md`

- [ ] **Step 1: Add reusable artifact identity profile**

When Step3B writes a compute cache, include:

```json
{
  "producer": "step3b_sample_proof",
  "is_formal_factor_values": false,
  "report_id": "<report_id>",
  "factor_id": "<factor_id>",
  "implementation_mode": "<operator|direct_code|hybrid>",
  "spec_hash": "<hash>",
  "formula_hash": "<hash-or-null>",
  "code_hash": "<hash-or-null>",
  "data_catalog_hash": "<hash-or-null>",
  "data_api_contract_version": "factorforge_step4_data_contract_v1",
  "window": {"start": "YYYYMMDD", "end": "YYYYMMDD"},
  "universe_hash": "<hash-or-null>",
  "frequency": "daily"
}
```

If a field is unavailable, write `null` and force Step4 recompute rather than unsafe reuse.

- [ ] **Step 2: Add RED smoke cases**

Add these cases to `scripts/run_factorforge_performance_smoke.py`:

```text
step4_reuses_when_identity_matches
step4_recomputes_when_code_hash_differs
step4_recomputes_when_data_window_differs
step4_recomputes_when_catalog_hash_differs
step4_blocks_sample_proof_as_formal_factor_values
```

- [ ] **Step 3: Implement reuse gate**

In `skills/factor-forge-step4/scripts/run_step4.py`, make reuse require exact match on:

```text
report_id
factor_id
implementation_mode
spec_hash
formula_hash or code_hash
data_catalog_hash
data_api_contract_version
window.start
window.end
universe_hash
frequency
```

Allowed outcomes:

```text
reuse_allowed
recompute_required
block_invalid_formal_reuse
```

Never treat `producer=step3b_sample_proof` as formal factor values.

- [ ] **Step 4: Add reuse gate profile to Step4 metadata**

Step4 metadata must include:

```json
{
  "reuse_gate": {
    "version": "factorforge_reuse_gate_v1",
    "decision": "reuse_allowed|recompute_required|block_invalid_formal_reuse",
    "matched_fields": [],
    "mismatched_fields": [],
    "missing_fields": [],
    "source_artifact": "<path>",
    "reason": "<short token>"
  }
}
```

- [ ] **Step 5: Add profile diagnostics**

Update `scripts/run_factorforge_performance_profile.py` to report:

```text
REUSE_GATE_ALLOWED
REUSE_GATE_RECOMPUTE_REQUIRED
REUSE_GATE_BLOCKED_INVALID_FORMAL_REUSE
```

- [ ] **Step 6: Run verification**

```bash
python3 -m py_compile \
  skills/factor-forge-step3/scripts/run_step3b.py \
  skills/factor-forge-step4/scripts/run_step4.py \
  scripts/run_factorforge_performance_smoke.py \
  scripts/run_factorforge_performance_profile.py
python3 scripts/run_factorforge_performance_smoke.py
```

Expected:

```text
"verdict": "ACCEPT"
"case": "step4_reuses_when_identity_matches"
"ok": true
"case": "step4_recomputes_when_code_hash_differs"
"ok": true
"case": "step4_recomputes_when_data_window_differs"
"ok": true
"case": "step4_recomputes_when_catalog_hash_differs"
"ok": true
"case": "step4_blocks_sample_proof_as_formal_factor_values"
"ok": true
```

- [ ] **Step 7: Commit**

```bash
git add \
  skills/factor-forge-step3/scripts/run_step3b.py \
  skills/factor-forge-step4/scripts/run_step4.py \
  scripts/run_factorforge_performance_smoke.py \
  scripts/run_factorforge_performance_profile.py \
  docs/operations/factorforge-performance-production-closeout.md
git commit -m "Enforce Factor Forge artifact reuse identity gate"
```

---

## Final Verification

Run all of these before claiming completion:

```bash
python3 -m py_compile \
  skills/factor-forge-step3/scripts/run_step3b.py \
  skills/factor-forge-step4/scripts/run_step4.py \
  scripts/run_factorforge_performance_smoke.py \
  scripts/run_factorforge_performance_profile.py \
  scripts/run_factorforge_operator_kernel_inventory.py \
  scripts/run_factorforge_operator_candidate_benchmark.py
python3 scripts/run_factorforge_unit_tests.py
python3 scripts/run_factorforge_entrypoint_hygiene_smoke.py
python3 scripts/run_factorforge_performance_smoke.py
python3 scripts/run_factorforge_mechanism_math_v2_smoke.py
```

Expected:

```text
unit tests: failed=[]
entrypoint hygiene: verdict=ACCEPT
performance smoke: verdict=ACCEPT
mechanism math v2 smoke: verdict=ACCEPT
```

If `pytest` is unavailable, do not report pytest as skipped silently. Report:

```text
PYTEST_UNAVAILABLE: pytest not installed in active Python
```

---

## Final Deliverables

The coder must provide:

```text
branch
commit list
changed files
verification commands and results
Mac real-run proof path or BLOCK token
EC2 real-run proof path or BLOCK token
runtime branch reconciliation result
operator default/opt-in/block table
reuse gate smoke results
remaining risks
```

Completion requires all non-environmental tests to pass. If Mac/EC2 real proof cannot run because approval or infrastructure is missing, the implementation can be code-complete only with explicit `BLOCK_REAL_*` tokens recorded in the final report.
