---
name: factor-forge-step3
description: Step 3 of the Factor Forge pipeline — Data/API preparation plus implementation planning and factor code generation. Consumes factor_spec_master from Step 2, resolves real data sources and qlib-normalized adapters (3A), then emits implementation plans and editable first-version factor code artifacts (3B) for Step 4 execution.
---

# Factor Forge Step 3 Skill

## What This Skill Does

Step 3 is the **engineering bridge** between abstract factor logic and runnable execution.
It has two internal layers:

- **Step 3A — Data Preparation / Data API / qlib Normalization**
  - resolves real data sources
  - writes field mappings, proxy rules, coverage checks
  - emits `data_prep_master` and `qlib_adapter_config`
  - emits a Step4 Data API contract and does not resolve raw/local clean paths itself
  - should prefer a qlib-friendly contract so later evaluation can reuse qlib operator / strategy / backtest interfaces with minimal reshaping
  - raw aliases may remain (`ts_code`, `trade_date`, `trade_time`), but semantic mapping to qlib-facing keys (`instrument`, `datetime`) must be explicit
  - feature columns are append-only and extensible; later additions such as `pe`, `pb`, `market_cap`, `industry_code`, or custom alpha/risk columns should not require redesign

- **Step 3B — Implementation Planning + Factor Code Generation + Sample Executability Proof**
  - consumes Step 2 products directly: `factor_spec_master__{report_id}.json` plus optional `handoff_to_step3__{report_id}.json`
  - inherits Step 2 research context (`thesis`, `research_contract`, `math_discipline_review`, `learning_and_innovation`)
  - chooses execution mode (`direct_code` / `operator` / `hybrid`)
  - writes `implementation_plan_master`
  - emits editable first-version factor code artifacts for IDE-side refinement
  - embeds `step2_research_context` in implementation plan, code review comments, expression draft, scaffold, handoff, and sample-run metadata
  - when Step 3A Data API sample queries are present, may generate only non-formal `step3b_sample_*` artifacts to prove executability and schema completeness

Step 3 does **not** perform full data execution or final backtest / evaluation itself. Step 4 owns full Data API fetch, formal `factor_values__{report_id}` outputs, execution diagnostics, and run-master creation; Step 5 remains the evaluation / archival layer.

For minute-bar factors, Step3A must write the full-data execution contract
instead of asking Step4 to infer raw minute paths. Formal minute factors that can
be reduced to daily/bucket flow state must declare
`minute_derived_state_requirements[]`, currently including
`minute_derived_flow_state_v1` with `trade_date` parquet partitions, cutoff time,
source data version, schema version, producer version, and artifact hash. Step3B
may still fetch only a small sample for executability proof, but full 2016-2026
Step4 execution requires the derived datamart or an explicit backfill. The
default current research window is in-sample through `2025-07-11`; data after
that date is OOS holdout and must not be used for repeated revision fitting.

## Research Discipline

Step 3 must protect the thesis during implementation:
- Step 3A records the gap between theoretical variables and real data proxies.
- Step 3A consumes the independent `factorforge_data_api` catalog contract; full-history cleaning is not a per-factor task.
- Step 3B records implementation invariants inherited from Step 2.
- Step 3B must not silently reduce Step 2 into only a formula column; it must preserve the target statistic, economic mechanism, expected failure modes, and reuse instructions for future agents.
- Step 3B must flag approximations that change economic meaning.
- Boundary handling, missing values, extreme values, and numerical stability must be explicit.
- Step3B sample factor values prove executability, not research validity; Step4/5/6 still decide whether the signal is worth keeping.

## Inputs

Required:
- `factorforge/objects/factor_spec_master/factor_spec_master__{report_id}.json`
- `factorforge/objects/alpha_idea_master/alpha_idea_master__{report_id}.json`

Optional:
- `factorforge/objects/handoff/handoff_to_step3__{report_id}.json`

## Outputs

### Step 3A outputs
- `factorforge/objects/data_prep_master/data_prep_master__{report_id}.json`
- `factorforge/objects/data_prep_master/qlib_adapter_config__{report_id}.json`
- `factorforge/objects/validation/data_feasibility_report__{report_id}.json`

### Step 3B outputs
- `factorforge/objects/implementation_plan_master/implementation_plan_master__{report_id}.json`
- `factorforge/generated_code/{report_id}/factor_impl__{report_id}.py` (preferred) or editable stub
- `factorforge/generated_code/{report_id}/qlib_expression_draft__{report_id}.json`
- `factorforge/generated_code/{report_id}/hybrid_execution_scaffold__{report_id}.json`
- all Step 3B plan/code/scaffold/handoff artifacts must expose `step2_research_context`
- all Step 3B plan/code/scaffold/handoff artifacts must expose `implementation_mode_decision`
- non-formal sample factor values when Step 3A Data API sample queries are available:
  - `factorforge/runs/{report_id}/step3b_sample_factor_values__{report_id}.parquet`
  - optional `factorforge/runs/{report_id}/step3b_sample_factor_values__{report_id}.csv`
  - `factorforge/runs/{report_id}/step3b_sample_run_metadata__{report_id}.json`
  - metadata must set `is_formal_factor_values=false`, `purpose=step3_executability_proof`, and `formal_factor_values_owner=Step4`
  - `run_metadata.performance_profile` with contract version
    `factorforge_step3b_performance_profile_v1`, row count, phase timings for
    input read / factor compute / normalize-sort / parquet write / CSV write,
    compute rows/sec, and output byte sizes.
  - For Formula-IR operator implementations, `run_metadata.performance_profile`
    should include `formula_engine_profile` showing the evaluator engine,
    reference engine, memoization/cache stats, deterministic parity status,
    sample size, max absolute diff, rank correlation, and sortedness flags.
    The pandas reference evaluator remains the correctness oracle; optimized
    execution must match it or block before sample factor values are written.
    Operator-level profiling is observation-only and can be enabled with
    `FACTORFORGE_ENABLE_OPERATOR_PROFILE=1` or `--operator-profile`; it records
    `formula_engine_profile.operator_profile` and `parity_profile` without
    changing formula semantics, the default pandas path, or parity enforcement.
  - CSV audit writes are controlled by the explicit policy
    `full_csv|sample_csv|no_csv` (`FACTORFORGE_CSV_OUTPUT_POLICY` or
    `--csv-output-policy`). The default remains `full_csv`. `sample_csv` writes
    deterministic head/tail sample CSV artifacts and `no_csv` writes no CSV;
    both are opt-in performance modes while parquet remains the formal
    high-performance read path.
  - Formula-IR execution defaults to pandas optimized with pandas reference as
    the correctness oracle. A reviewed subset of default NumPy time-series
    kernels may run inside this `pandas_optimized` path for `min`, `max`,
    `delta`, `delay`, `argmin`, `argmax`, `ts_rank`, `corr`, `correlation`,
    and `covariance`; rollback must be available through
    `FACTORFORGE_DISABLE_DEFAULT_NUMPY_TS_KERNEL=1`. This default kernel subset
    is production acceleration and must be active on Mac and EC2 unless a
    rollback/debug run records the reason. `sum`, `mean`, and
    `std/stddev` remain pandas fallback in the default path because tiny
    floating-point accumulation differences can be amplified by downstream
    cross-sectional `rank`. The
    experimental Polars backend is
    opt-in only (`FACTORFORGE_ENABLE_EXPERIMENTAL_POLARS=1` or
    `--formula-engine polars_experimental`), must record parity metadata, and
    must BLOCK on missing dependency or parity failure. Unsupported Polars
    operators may fall back to pandas only when the metadata records an explicit
    `polars_fallback_reason`. The adaptive selector is also explicit opt-in
    (`--formula-engine adaptive`); it may select lazy Polars only for native
    parquet Formula-IR subsets, otherwise it must choose pandas optimized and
    record `formula_engine_profile.adaptive_selector.reason`.
  - The experimental `ts_rank` engine is opt-in only
    (`FACTORFORGE_ENABLE_EXPERIMENTAL_TS_RANK_ENGINE=1` plus
    `FACTORFORGE_TS_RANK_ENGINE=numpy_sliding_window_experimental`, or
    `--ts-rank-engine numpy_sliding_window_experimental`). This independent
    engine remains separate from the default Formula-IR NumPy kernel subset;
    experimental runs must record `formula_engine_profile.ts_rank_engine_profile`,
    pass pandas-reference sample parity, and obey the runtime guard before
    writing factor values.
    The legacy `FACTORFORGE_ENABLE_EXPERIMENTAL_TS_RANK_FAST` flag must not
    enable or select an experimental engine; if present, metadata should record
    it only as an ignored stale environment flag.
  - Formula-IR operator kernels default to `pandas_optimized` with pandas
    reference as the correctness oracle and the default NumPy time-series kernel
    subset enabled. Experimental kernels beyond that reviewed default subset are
    opt-in only (`FACTORFORGE_ENABLE_EXPERIMENTAL_FORMULA_KERNEL=1` plus
    `FACTORFORGE_FORMULA_KERNEL_ENGINE=numpy_rolling_experimental`, or
    `--formula-kernel-engine numpy_rolling_experimental`). Step3B must record
    `formula_engine_profile.kernel_profile`; experimental kernels must not be
    marked `safe_to_make_default`, and must BLOCK on invalid engine, missing
    explicit enable gate, parity failure, dependency failure, or runtime guard
    failure.
  - Production Step3B runs must not enable experimental Polars, the independent
    experimental `ts_rank` engine, or future experimental Formula-IR kernel
    engines unless the user explicitly asks for a performance experiment. The
    production path is Formula-IR `pandas_optimized` with pandas reference
    parity, default NumPy time-series kernels, Parquet IO, and optional
    `sample_csv` audit output. Step3B is an executability proof and must use
    Data API sample queries or a capped deterministic local sample; it must not
    run a full formal data window or write formal factor values.
  - For `direct_code` or `hybrid` custom blocks that cannot be represented as
    Formula-IR, generated implementations should prefer vectorized NumPy and/or
    Polars. Pandas remains acceptable as a reference or compatibility layer, but
    Python row loops and pandas `groupby.apply` require explicit justification
    in the implementation plan and generated-code comments.
  - Direct-code and hybrid implementations over minute bars, tick data, or any
    large intraday source must expose a bounded batch path. The implementation
    plan must include `batch_execution_plan.version=factorforge_batch_execution_plan_v1`
    with memory budget, estimated peak memory, partition key, selected columns,
    predicate pushdown policy, rolling/lookback overlap or carried state,
    checkpoint/resume path, and reference/parity sample. If the estimator cannot
    be batch-safe, Step3B must BLOCK with `BLOCK_MEMORY_PRESSURE_BATCH_REQUIRED`
    instead of emitting all-in-memory code.
  - Batch-safe code must stream partitions and write per-batch Parquet/cache
    outputs; it must not build an unbounded list of intermediate DataFrames for
    final concat. Time-series windows require overlap or state carry, and
    cross-sectional operators require complete per-date cross-sections or a
    two-pass plan. This applies to future model-training scaffolds as well:
    use mini-batches, dataset streaming, checkpointing, and gradient
    accumulation rather than loading full tensors into RAM.
  - Child revision runs created by the ultimate loop must consume
    direct-code laws through a versioned law registry rather than pasting every
    moneyflow/Miller variant into `run_step3b.py`. The executable revision spec
    should carry `law_id` plus `code_law_hash`; Step3B resolves the law through
    `factor_factory.factor_laws.*` and must BLOCK with
    `BLOCK_FACTORFORGE_DIRECT_CODE_LAW_MISSING` or
    `BLOCK_FACTORFORGE_DIRECT_CODE_LAW_HASH_MISMATCH` when the registry entry is
    absent or identity-mismatched. Runner edits for a new law are a framework
    smell unless the adapter contract itself changes.
  - Child revision runs created by the ultimate loop must consume
    `objects/research_iteration_master/executable_revision_spec__{child_report_id}.json`
    before generating code or factor values. A child report id must not silently
    rerun the parent formula: missing specs must BLOCK, non-audit no-op formula
    hashes must BLOCK, and Step3B metadata/handoff must expose the applied
    executable revision spec and child formula hash.
  - Child revisions preserve implementation mode. `implementation_mode=operator`
    requires Formula-IR parse/parity. `implementation_mode=direct_code` or
    `hybrid` requires a `direct_code_revision_contract` or hybrid mutation
    contract with target function/block, required fields, data timing contract,
    code-law hash, and mutation scope. Step3B must not replace a native minute
    or tick law with an unrelated parseable operator formula merely to satisfy
    Formula-IR.

### Handoff
- `factorforge/objects/handoff/handoff_to_step4__{report_id}.json`

## Core rules

1. Step 3 must produce real on-disk artifacts, not just prose.
2. Step 3A must explicitly document:
   - data sources
   - field mappings
   - proxy rules
   - sample window
   - qlib-normalized access contract
3. Step 3B must explicitly document:
   - execution mode
   - required inputs
   - calculation steps
   - editable code artifact paths
4. Step 3B must emit real code-related artifacts; a pure plan without code artifacts is not enough.
5. If Step 3A has a Data API sample query contract, Step 3B must produce a non-formal sample factor-value proof when executable code exists. A plan-only PASS is not enough for business acceptance.
6. Step 3B must carry `step2_research_context` through implementation plan, generated code comments, qlib expression draft, hybrid scaffold, `handoff_to_step4`, and sample-run metadata if generated.
7. Step 3B validation must reject `missing_*` Step2 research-context sentinels; rerun Step2 rather than letting old or incomplete specs pass.
8. No silent guessing. Missing critical fields must be surfaced as `blocked` or `proxy_ready` with explicit rationale.
9. Step 3 must reject mixed sample/full execution packages. If minute and daily snapshots have materially inconsistent ticker coverage or sample scope, validation must fail explicitly rather than producing a deceptively small successful run.
10. `report_id` handling must be internally consistent. File naming, JSON internal `report_id`, and handoff artifact references must agree; alias shortcuts must not silently reuse long-id internals without explicit normalization.
11. If a Step 3 or downstream Step 4 run depends on user choices not already fixed in artifacts — e.g. benchmark, topk, n_drop, holding horizon, deal price, account size, cost model, universe filter, or whether to run sample vs wider window — the skill must ask for confirmation before launching execution.
12. Step 3B must not run Step4-style quantile NAV, IC analysis, portfolio charts, evaluator loops, full-data fetch, or formal factor-value generation. Step 3B's proof is non-formal sample `step3b_sample_factor_values` + metadata only; Step4 owns formal `factor_values`, metrics, quantile tables, NAV, and plots.
13. Step 3B inputs and outputs must respect the shared data contract: `trade_date` may be read from `YYYYMMDD`, `YYYY-MM-DD`, or Timestamp sources, but outputs should be stable `YYYYMMDD`-compatible keys and Step4 must normalize via `factor_factory.data_access.normalize_trade_date_series`.
14. Step 3B must write `implementation_mode_decision` with version `factorforge_implementation_mode_decision_v1` into implementation plan, generated-code metadata, handoff, sample-run metadata when generated, and ultimate proof summary. The decision must record selected mode or `blocked`, mode attempts, failure/not-applicable reasons, correctness risk, and human-review status.
15. Child loop execution must be revision-aware. If a report id is a loop child,
Step3B must require an executable revision spec, apply its child formula before
identity validation/code generation, and reject missing or no-effect specs with
hard BLOCK tokens. Reusing the parent formula in a child loop is research-chain
pollution, not a valid iteration.
16. If Step3A `data_prep_master.feasibility` is `blocked`, the Step3A handoff
must force `step3a_ready=false` and `step3b_ready=false`, and must clear or
overwrite stale execution-state fields such as `first_run_outputs`, Step3B
sample output references, generated implementation references, and run metadata
paths. A blocked Step3A handoff must not preserve old `step3b_ready=true`
state from a previous run.
17. Step3B must treat `Killed`, exit 137, OOM-kill logs, allocator failure, or
swap exhaustion as a design failure, not a transient retry. The next attempt
must attach a bounded `batch_execution_plan` or BLOCK with
`BLOCK_MEMORY_PRESSURE_BATCH_REQUIRED`.

## Recommended execution chain

```bash
cd /home/ubuntu/.openclaw/workspace
python3 repos/factor-factory/scripts/run_factorforge_ultimate.py --report-id <report_id> --start-step 3 --end-step 3b
```

Direct `run_step3.py` / `run_step3b.py` commands are debug-only and are blocked by default. Official agent-led runs must use `scripts/run_factorforge_ultimate.py` and produce an `ultimate_run_report__<report_id>.json` proof.

Legacy/sample Step3 entry points that look formal, including `scripts/run_step3_sample.py`, must hard block before writing canonical `objects/`, `runs/`, `generated_code/`, `evaluations/`, or `archive/` artifacts. Do not add environment bypasses to these sample blockers.

## Acceptance

A Step 3 run is acceptable only if all of the following are true:
- Step 3A artifacts exist
- Step 3B artifacts exist
- `handoff_to_step4__{report_id}.json` exists
- validators return PASS
- no `TODO` / `TO_BE_FILLED` / placeholder residue remains in final artifacts
- Step 4 can identify a real execution mode and real artifact paths from Step 3 outputs
- when Step 3A Data API sample queries exist, Step 3B emits non-formal `step3b_sample_factor_values` artifacts with non-trivial row count and explicit Step4 ownership for formal outputs
- minute/daily snapshot scope is internally consistent (no accidental full-minute + sample-daily mixed package)
- object naming is internally consistent (`report_id` in filename, JSON payload, and handoff refs do not conflict)

## Mechanical proof

- output paths exist
- validators return PASS
- `handoff_to_step4` references exact Step 3A / 3B artifact paths
- `step2_research_context` is identical across plan, handoff, expression draft, and scaffold
- at least one real code artifact exists under `factorforge/generated_code/{report_id}/`

## Repository alignment note

Current repository reproducibility docs for Step 3 live at:
- `docs/contracts/step3-contract.md`
- `docs/reproducibility/step3-gap-card.md`
- `scripts/run_step3_sample.sh` (blocked from canonical writes; use the ultimate wrapper for formal execution)

Treat those files as the authoritative current repo-level reproducibility notes when deciding whether Step 3 is merely skill-visible or Bernard/Mac reproducible-level.

## Publishing note

This skill is intended to be ClawHub-publishable after Step 3 references and contracts remain aligned with scripts. The release boundary is:
- Step 3A = data contract
- Step 3B = code contract + editable first-version factor code
- Step 4 = execute / backtest / diagnose
## Implementation and Factor Isolation Discipline

- Every formal factor artifact must carry `artifact_identity`.
- Every formal run must carry `manifest_identity`.
- `implementation_mode` is restricted to `operator`, `direct_code`, or `hybrid`.
- Artifacts must not be reused across mode, factor, report, branch, or run unless identity/hash lineage matches explicitly.
- Formal execution must consume manifest-specified paths only; do not pick files by `glob`, mtime, or "latest" guesses.
- If `report_id`, `factor_id`, `source_type`, `implementation_mode`, `branch_id`, `spec_hash`, or formula/code/hybrid hash does not match, BLOCK.
- Direct generated implementation files belong to one factor identity; shared helpers may be reused, factor-specific generated code may not be silently copied.

## Correctness Over Completion

FactorForge is a general-purpose factor research framework, not a named-factor or family-template calculator. Step3B must follow `operator -> hybrid -> direct_code -> BLOCK`; unsupported operators, missing `formula_ir`, missing field aliases, unavailable parity, or unsafe direct code must BLOCK. Family-plugin builders are explicit-contract-only and must never repair an unrelated spec.

## Operator / Qlib Engine

Operator mode is Formula-IR based. Step3B may select `operator` only when `formula_ir.parse_status=success`, every operator is registered, field aliases resolve against the Step3A data schema, and the generated pandas implementation passes reference parity. The generated metadata must state `implementation_source=formula_ir_pandas_codegen`, `formula_hash`, `operator_set`, `required_fields`, `resolved_fields`, and the qlib bridge result.

The pandas reference evaluator is the correctness oracle for operator mode. Qlib expressions are a bridge artifact with explicit `supported` or `unsupported` status; unsupported qlib operators are not approximated or rewritten. If parser, registry, alias resolution, code hash, or parity validation fails, Step3B must BLOCK and write no formal factor values.

Field alias resolution must prefer actual Step3A Data API schema columns, then legacy local snapshot header columns, and use the default schema only for plan-only/no-sample mode. If sample queries are absent, pending sample outputs must record the reason explicitly.

## Hybrid Execution Engine

Hybrid mode must execute as `operator_subgraph + custom_block`, not as unbounded Python. Step3B validates the operator subgraph through Formula IR/pandas parity, scans the custom block with the direct-code leakage rules, checks `formula_hash`, `custom_block_hash`, and `hybrid_hash`, and validates the boundary schema before writing ready artifacts.

Generated hybrid code must expose `compute_operator_subgraph()`, `apply_custom_block()`, and `compute_factor()`, separated by `FACTORFORGE_OPERATOR_SUBGRAPH` and `FACTORFORGE_CUSTOM_BLOCK` markers. Custom blocks may not overwrite protected operator outputs unless the boundary explicitly allows it.

Direct-code and hybrid custom implementations must also satisfy the high-speed code policy. Prefer vectorized NumPy or Polars, with pandas vectorized APIs acceptable for compatibility and reference parity. Python row loops, `DataFrame.apply(axis=1)`, `groupby.apply`, and `rolling.apply` require an explicit `allow_slow_patterns=true` plus a non-empty performance justification in the relevant code contract/custom block; otherwise Step3B must BLOCK with the high-speed profile evidence.

## Family Plugin Boundary

Family-specific implementations may run only through `factor_factory.factor_families` after Step2 explicitly declares `factor_family`, `family_plugin`, `family_plugin_allowed=true`, and a `factorforge_family_plugin_decision_v1` record with structured evidence. Do not trigger a family plugin from `factor_id`, keywords, formula prose, or thesis text. Free-text matches may create a suggestion for human review, not an executable plugin selection.

## Long-Term Production Contract Discipline

Step3A materializes formula-required standard fields into the report-local
snapshot and writes `derived_field_contract`. The contract must include unit
policy, lookback policy, leakage policy, source fields, report-local-only
status, and `clean_data_mutation=false`.

Step3B and Step4 consume these fields. They must not independently guess aliases
or derivations. The phrase "derive if needed" without source fields is banned.
Step3B formal factor values is also banned: Step3B may write sample-only
executability proof, while Step4 owns formal factor values and
`acceptance_summary`.

Prompt vocabulary required for downstream continuity: `standard_formula_fields_contract`,
`acceptance_summary`, `qlib_native_status`, `evidence_status`,
`formula_implied_information`, `metric_anomaly_review`,
`model_linked_metric_signature`, `volatility_drag`,
`drawdown_recovery_area`, `component_ablation`, and
`direction_losing_transform_review`.

Explicit bans: no "qlib partial success"; no "partial run without layer"; no
raw formula restatement as mechanism; no generic stochastic process as
explanation.

Required literal terms for validator coverage: unit policy; derive if needed without source fields; generic stochastic process as explanation.
