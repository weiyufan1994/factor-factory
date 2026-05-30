# Factor Forge Data/API And Dirac-Style Mechanism Task

Date: 2026-05-31

## Scope

Implement the first production slice of the updated Factor Forge architecture:

1. Step3A must resolve research data through an auditable Data API layer instead of ad hoc local/S3 assumptions.
2. Step3A readiness must distinguish schema acceptance from executable readiness.
3. Step3B direct_code validation must block signature drift and all-null smoke outputs.
4. Mechanism-math v2 and Step6 Council must include formula-implied information review, including unexpected implication / anomaly handling.
5. Installed Step1/Step2/Step3/Step6 skills must stay synced with the repository versions.

Out of scope:

- Building the full clean minute-bar production pipeline.
- Starting EC2 workers or modifying remote machines.
- Hand-patching any existing formal run artifacts.
- Rewriting historical Step1/Step2 raw outputs.

## Subtasks

### R1. Task Spec And Audit Entry

Goal: create this task document as the implementation contract.

Boundary: document only; no runtime behavior changes.

Test sample: reviewer can map each changed file and test command back to one subtask.

Proof target: final report lists goal, boundary, tests, and proof for every subtask.

### R2. Step3 Data API Resolution

Goal: add a small `factor_factory.data_access` Data API resolver for `clean_daily_bar` and `clean_minute_bar`, and have Step3A record the resolver output.

Boundary:

- Daily data may use the existing clean daily layer as the current backend.
- Minute data may report blocked if no clean minute dataset/catalog entry exists.
- The resolver must not fetch from S3 directly in Step3A.

Test samples:

- A temporary clean daily layer resolves to `ready` with path, policy, schema, and coverage.
- Missing minute clean layer resolves to `blocked`.
- Step3A materializes daily slices from the Data API resolution.

Proof target: unit tests plus Step3A validator checks for `data_api_resolution`.

### R3. Step3 Readiness Contract

Goal: prevent Step3A from claiming Step3B/Step4 readiness when data prep is blocked or when effective-day policy is absent for daily direct-code factors.

Boundary:

- Schema-valid Step3A artifacts can still exist.
- Executable readiness is false unless data API resolution, snapshots, and daily filter policy are valid.

Test samples:

- `feasibility=blocked` and `step3b_ready=true` must fail validation.
- `feasibility=ready` without `data_api_resolution.clean_daily_bar` must fail validation.
- ready daily-only output with local parquet and filter policy passes.

Proof target: validator tests and `validate_step3.py` behavior.

### R4. Step3B direct_code Contract

Goal: make direct_code smoke validation call only the declared keyword interface and reject all-null signal output.

Boundary:

- Do not rewrite generated factor implementations.
- Do not add positional fallback that masks signature mismatch.

Test samples:

- `compute_factor(df)` blocks with `BLOCK_STEP3B_DIRECT_CODE_SIGNATURE_MISMATCH`.
- `compute_factor(daily_df=..., minute_df=...)` returning all-null factor values blocks.
- Valid keyword interface with non-null values passes.

Proof target: unit tests for the direct_code smoke helper.

### R5. Dirac-Style Formula-Implied Review

Goal: extend mechanism_math v2 with a required `formula_implied_information_review` and Council anomaly classification.

Boundary:

- `stochastic_process` remains a benchmark/projection tool, not the default primary model for every factor.
- Unexpected formula implications are not automatically promoted; they must be classified.

Test samples:

- Missing `formula_implied_information_review` blocks.
- Unexpected implication without classification blocks.
- `tradable_anomaly` / `new_factor_seed` without child law, metric signature, and kill criteria blocks.
- Valid anomaly branch review passes.

Proof target: mechanism-math smoke plus direct validator tests.

### R6. Skill Sync

Goal: installed Step1/Step2/Step6/Ultimate SKILL.md files and installed Step3 runtime scripts match repository versions after code and prompt updates.

Boundary: sync skill files/scripts only; do not copy formal run artifacts.

Test sample: `diff -q` between installed and repository skill files/scripts returns no diff.

Proof target: diff command in final verification.

## Required Verification

Run at minimum:

```bash
python scripts/run_factorforge_unit_tests.py
python scripts/run_factorforge_mechanism_math_v2_smoke.py --fresh
python -m compileall factor_factory skills/factor-forge-step3/scripts scripts/run_factorforge_mechanism_math_v2_smoke.py
git diff --check
```
