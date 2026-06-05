# Factor Forge Long-Term Production Contract Closeout Task Spec

> **For coder:** This is a production-contract closure task, not a single Alpha036/Alpha037 bugfix. Implement with a clean branch, RED/GREEN smokes, validators, producer code, and skill prompts. Do not treat documentation as completion.

**Date:** 2026-06-03

**Primary audience:** Factor Forge Ultimate coder / reviewer

**Goal:** Close the long-term Factor Forge production-contract gaps exposed by Alpha036 and Alpha037 so future Alpha101-style formulas and report-derived factors have auditable, repeatable behavior across Step2, Step3A, Step3B, Step4, Step6, and research reports.

**Core principle:** A formal run can only be trusted if the system can prove:

```text
formula requirements -> data-field contract -> report-local snapshot ->
sample-only executability -> formal Step4 ownership -> backend evidence split ->
model-linked research judgment
```

This task must make that chain explicit in artifacts, validators, smokes, and prompts.

---

## 0. Required Branch And Work Discipline

Start from a clean worktree. Do not implement in a dirty workspace.

Recommended:

```bash
cd /Users/humphrey/projects/factor-factory
git fetch origin
git worktree add /tmp/factorforge-long-term-contract-closeout origin/main
cd /tmp/factorforge-long-term-contract-closeout
git switch -c codex/factorforge-long-term-production-contract-closeout
```

Before editing, record:

```bash
git rev-parse HEAD
git status --short
```

### Hard Boundaries

Do **not**:

- start EC2 worker;
- run Step3B/Step4 production jobs unless explicitly authorized;
- mutate raw data, S3 raw data, clean data, qlib provider data, or existing formal artifacts;
- hand-edit Alpha036/Alpha037 artifact JSON to make tests pass;
- bypass validators with environment flags;
- weaken existing blockers to get a green run;
- move Data API cleaning into Factor Forge;
- change portfolio construction rules or the long-only mandate;
- promote any factor or write official library records.

### Required Engineering Standard

Every contract change must include:

1. producer code that writes the field;
2. validator code that rejects bad/missing fields;
3. positive and negative smoke cases;
4. skill/prompt updates so LLM agents know to produce/report the field;
5. docs explaining the contract;
6. py_compile + diff-check + smoke evidence.

If any part cannot be implemented correctly, leave a precise `BLOCK` with file, token, and missing prerequisite. Do not paper over it.

---

## 1. Source Feedback

Use these files as the source of truth for requirements:

- `docs/operations/factorforge-long-term-contract-gaps-feedback-20260603.zh-CN.md`
- `docs/operations/factorforge-skill-feedback-alpha036-production-acceptance.zh-CN.md`
- `docs/operations/alpha036-production-acceptance-research-report.zh-CN.md`
- `docs/superpowers/plans/2026-06-02-alpha036-production-contract-and-research-report-closeout.md`
- `docs/operations/factorforge-dirac-style-research-contract.zh-CN.md`

Already accepted and should not be reworked unless regression fails:

```text
Alpha037 Step3B gate:
- Step3B cannot upgrade a blocked Step3A handoff to step3b_ready=true.
- BLOCK_STEP3B_REQUIRES_READY_STEP3A fires before codegen/write.
```

This plan is for the remaining long-term contracts.

---

## 2. Priority Matrix

### P0

1. `standard_formula_fields_contract`
2. Step3A derived-field unit/lookback/leakage contract
3. production `acceptance_summary`
4. `qlib_native_status` taxonomy
5. Step4 must keep full factor CSV disabled by default and record that policy in proof/profile

### P1

6. `backtest_base_dataset_contract`
7. Step4 backtest-base reuse gate and stable identity
8. formal artifact top-level acceptance fields
9. Step6 evidence status split
10. Step3B sample/formal ownership regression hardening beyond the accepted gate

### P2

11. self-quant and qlib diagnostics share the same evaluation context/backtest base
12. Step4 profile separates factor I/O, base load, evaluation, and output
13. Dirac-style research report validator
14. component-level Council packet requirements
15. prompt contract smokes covering Step2/3/4/6 language

P0 must be completed before asking for production use. P1 should be completed in the same branch unless blocked by schema migration risk. P2 is required for research-standard completeness and should not be silently dropped.

---

## 3. File Map

Likely modified:

```text
factor_factory/formula/field_aliases.py
factor_factory/formula/evaluator.py
factor_factory/formula/parity.py

skills/factor-forge-step2/SKILL.md
skills/factor-forge-step2/references/prompts.md
skills/factor-forge-step2/scripts/validate_step2.py

skills/factor-forge-step3/SKILL.md
skills/factor-forge-step3/scripts/run_step3.py
skills/factor-forge-step3/scripts/validate_step3.py
skills/factor-forge-step3/scripts/run_step3b.py
skills/factor-forge-step3/scripts/validate_step3b.py

skills/factor-forge-step4/SKILL.md
skills/factor-forge-step4/scripts/run_step4.py
skills/factor-forge-step4/scripts/validate_step4.py
skills/factor-forge-step4/scripts/self_quant_adapter.py
skills/factor-forge-step4/scripts/qlib_backtest_adapter.py

skills/factor-forge-step6/SKILL.md
skills/factor-forge-step6/references/prompts.md
skills/factor-forge-step6/scripts/run_step6.py
skills/factor-forge-step6/scripts/validate_step6.py

factor_factory/revision_council/validator.py

scripts/run_factorforge_alpha101_standard_field_contract_smoke.py
scripts/run_factorforge_production_acceptance_contract_smoke.py
scripts/run_factorforge_step4_backtest_base_contract_smoke.py
scripts/run_factorforge_qlib_status_taxonomy_smoke.py
scripts/run_factorforge_step6_evidence_status_smoke.py
scripts/run_factorforge_dirac_research_report_contract_smoke.py
scripts/run_factorforge_prompt_contract_smoke.py
scripts/run_factorforge_performance_smoke.py

docs/contracts/step2-contract.zh-CN.md
docs/contracts/step3-contract.zh-CN.md
docs/contracts/step4-contract.md
docs/contracts/step6-contract.zh-CN.md
docs/operations/factorforge-alpha101-standard-field-contract.zh-CN.md
docs/operations/factorforge-production-acceptance-report-template.zh-CN.md
docs/operations/factorforge-step4-backtest-base-contract.zh-CN.md
docs/operations/factorforge-dirac-style-research-contract.zh-CN.md
docs/operations/factorforge-entrypoint-registry.json
```

Avoid unless tests prove necessary:

```text
factor_factory/data_api/
factor_factory/data_access/
scripts/publish_qlib_daily_provider.py
OpenClaw/EC2 worker dispatch scripts
```

---

## 4. Task A - P0 Standard Formula Fields Contract

### Objective

Make formula-required standard fields a hard Step2 -> Step3A -> Step4 contract.

### Required Artifact Field

Step2 `factor_spec_master` must include:

```json
{
  "standard_formula_fields_contract": {
    "version": "factorforge_standard_formula_fields_contract_v1",
    "required_standard_formula_fields": ["volume", "returns", "vwap", "adv20"],
    "formula_fields_detected": ["close", "open", "volume", "returns", "vwap", "adv20"],
    "source_field_candidates": {
      "volume": ["vol", "volume"],
      "returns": ["pct_chg", "return", "close", "pre_close"],
      "vwap": ["amount", "vol", "volume"],
      "adv20": ["volume"]
    },
    "derivation_rules": {
      "volume": {"rule": "vol", "source_unit": "shares_or_lots_from_catalog", "output_unit": "documented_volume_unit"},
      "returns": {"rule": "pct_chg / 100 if pct_chg is percent", "output_unit": "decimal_return"},
      "vwap": {"rule": "amount / volume after unit normalization", "output_unit": "price"},
      "advN": {"rule": "rolling_mean(volume, N)", "lookback": "N", "include_current_day": true}
    },
    "lookback_policy": "uses data available at factor timestamp only",
    "leakage_policy": "no future data",
    "block_if_unavailable": true
  }
}
```

If the formula does not require derived standard fields, write an explicit empty contract:

```json
{
  "version": "factorforge_standard_formula_fields_contract_v1",
  "required_standard_formula_fields": [],
  "block_if_unavailable": true
}
```

### Producer Requirements

- Step2 must infer required standard fields from canonical formula and implementation mode.
- Step3A must consume the Step2 contract and materialize every required field into the report-local snapshot.
- Step4 must verify the formal input snapshot contains required fields before computing or evaluating.
- Step3B may use the fields but must not invent undocumented derivations.

### Unit / Dimension Requirements

Explicitly handle:

- `pct_chg` percent vs decimal;
- `amount` unit;
- `vol` unit;
- `vwap` price unit;
- `advN` rolling window and whether t day is included;
- missing values at early rolling windows.

If unit policy is ambiguous and cannot be inferred from catalog metadata, block with:

```text
BLOCK_STANDARD_FORMULA_FIELD_UNIT_AMBIGUOUS
```

### Prompt Requirements

Step2 prompt must say:

```text
For every canonical formula, list all formula-required standard fields.
If the formula contains Alpha101 conventions such as volume, returns, vwap, advN,
emit standard_formula_fields_contract with source fields, derivation rules,
unit policy, lookback policy, and leakage policy. Do not write "derive if needed".
If a field cannot be derived from the data contract, BLOCK instead of guessing.
```

Step3 prompt must say:

```text
Step3A materializes formula-required standard fields into the report-local snapshot.
Step3B and Step4 consume these fields. They must not independently guess aliases.
```

### Validator And Smoke Cases

Create/extend `scripts/run_factorforge_alpha101_standard_field_contract_smoke.py`.

Required cases:

```text
missing_standard_formula_fields_contract_blocks
adv20_without_volume_source_blocks
vwap_without_amount_or_volume_source_blocks
returns_without_unit_policy_blocks
vwap_without_unit_policy_blocks
adv20_without_lookback_policy_blocks
step3a_snapshot_missing_required_field_blocks
step4_input_missing_required_field_blocks
valid_alpha101_standard_field_contract_passes
```

Required blocker tokens:

```text
BLOCK_STANDARD_FORMULA_FIELDS_MISSING
BLOCK_STANDARD_FORMULA_FIELD_SOURCE_MISSING
BLOCK_STANDARD_FORMULA_DERIVATION_POLICY_MISSING
BLOCK_STANDARD_FORMULA_FIELD_UNIT_AMBIGUOUS
BLOCK_STANDARD_FORMULA_FIELD_LEAKAGE_POLICY_MISSING
BLOCK_STANDARD_FORMULA_DERIVED_FIELD_NOT_IN_SNAPSHOT
```

### Done Evidence

```bash
python3 -m py_compile \
  factor_factory/formula/field_aliases.py \
  factor_factory/formula/evaluator.py \
  factor_factory/formula/parity.py \
  skills/factor-forge-step2/scripts/validate_step2.py \
  skills/factor-forge-step3/scripts/run_step3.py \
  skills/factor-forge-step3/scripts/validate_step3.py \
  skills/factor-forge-step4/scripts/run_step4.py \
  skills/factor-forge-step4/scripts/validate_step4.py
python3 scripts/run_factorforge_alpha101_standard_field_contract_smoke.py
```

---

## 5. Task B - P0 Derived Field Audit Contract

### Objective

Turn Step3A derived fields from an implementation detail into an auditable report-local contract.

### Required Step3A Field

`data_prep_master.local_input_paths.derived_field_contract` must include:

```json
{
  "version": "factorforge_derived_field_contract_v1",
  "report_local_only": true,
  "clean_data_mutation": false,
  "required_fields": [],
  "source_fields": [],
  "derived_fields": {
    "vwap": {
      "sources": ["amount", "vol"],
      "rule": "amount / normalized_volume",
      "source_units": {"amount": "...", "vol": "..."},
      "output_unit": "price",
      "lookback_window": null,
      "include_current_day": true,
      "leakage_policy": "no future data",
      "null_policy": "..."
    }
  },
  "validation_result": "PASS|BLOCK",
  "blocked_items": []
}
```

### Requirements

- This contract must be written even when no derived fields are needed.
- `clean_data_mutation` must be `false`.
- Step3A must not write back to clean data or Data API.
- `sample_schema_parity` must prove report-local parquet and optional CSV sample share schema.

### Smoke Cases

```text
derived_field_contract_missing_blocks
derived_field_unit_missing_blocks
derived_field_leakage_policy_missing_blocks
derived_field_claims_clean_data_mutation_blocks
valid_no_derived_fields_contract_passes
valid_vwap_adv20_derived_fields_contract_passes
```

---

## 6. Task C - P0 Production Acceptance Summary

### Objective

Add one top-level `acceptance_summary` that can answer production acceptance questions without manual artifact stitching.

### Required Location

At minimum:

- `performance_profile__<report_id>.json`
- `ultimate_run_report__<report_id>.json` or referenced summary object
- Step6 research packet / research iteration should consume it if available

### Required Shape

```json
{
  "acceptance_summary": {
    "version": "factorforge_production_acceptance_summary_v1",
    "report_id": "...",
    "factor_id": "...",
    "run_id": "...",
    "artifact_root": "...",
    "repo_sha": "...",
    "wrapper_status": "PASS|BLOCK|FAILED",
    "validator_verdicts": {
      "step1": "PASS|BLOCK|...",
      "step2": "PASS|BLOCK|...",
      "step3": "PASS|BLOCK|...",
      "step3b": "PASS|BLOCK|...",
      "step4": "PASS|BLOCK|...",
      "step5": "PASS|BLOCK|...",
      "step6": "PASS|BLOCK|..."
    },
    "step3b": {
      "backend": "...",
      "input_format": "parquet|csv|...",
      "sample_only": true,
      "is_formal_factor_values": false,
      "phase_seconds": {},
      "formula_engine_profile": {},
      "parity_checked": true
    },
    "step4": {
      "formal_factor_values_owner": "Step4",
      "formal_factor_values_path": "...",
      "self_quant_status": "success|partial|failed|skipped",
      "qlib_native_status": "not_attempted|preflight_blocked|preflight_ready|partial_payload|native_minimal_success|native_backtest_success|failed",
      "phase_seconds": {}
    },
    "reuse": {
      "step3b_cache_reused_by_step4": false,
      "reuse_gate_status": "recomputed|reused|blocked|not_applicable",
      "reuse_reason": "..."
    },
    "side_effects": {
      "clean_data_mutated": false,
      "generated_code_digest_changed": false,
      "official_record_written": false,
      "search_worker_started": false
    },
    "metrics": {
      "rank_ic_mean": null,
      "long_side_annual_return": null,
      "turnover_mean": null,
      "cost_adjusted_annual_return": null,
      "volatility_drag": null,
      "max_drawdown": null,
      "recovery_days": null,
      "drawdown_recovery_area": null
    }
  }
}
```

### Prompt Requirements

Step4/Step6 report prompts must instruct agents:

```text
Start production acceptance reports from acceptance_summary.
Do not infer run_id/artifact_root from nested artifact_identity when acceptance_summary exists.
Do not say "run succeeded" unless wrapper status, backend status, and research decision are separately stated.
```

### Smoke Cases

Create/extend `scripts/run_factorforge_production_acceptance_contract_smoke.py`.

```text
missing_acceptance_summary_blocks
acceptance_summary_missing_run_identity_blocks
acceptance_summary_missing_backend_split_blocks
acceptance_summary_missing_reuse_status_blocks
acceptance_summary_missing_side_effects_blocks
valid_acceptance_summary_passes
```

---

## 7. Task D - P0 Qlib Native Status Taxonomy

### Objective

Prevent `partial` qlib payloads from being reported as qlib success.

### Required Status Values

```text
not_attempted
preflight_blocked
preflight_ready
partial_payload
native_minimal_success
native_backtest_success
failed
```

### Required Rules

- `partial_payload` is not qlib success.
- `sample_stub` is not qlib native success.
- `native_minimal_success` must prove qlib provider + signal load + minimal native path.
- `native_backtest_success` must prove real portfolio/backtest payload, not just import/preflight.
- If qlib full success is mandatory in run config, `partial_payload` must block formal acceptance.
- If qlib is optional, wrapper may PASS with explicit `qlib_native_status=partial_payload`.

### Required Fields

```json
{
  "qlib_native_status": "partial_payload",
  "qlib_native_attempted": true,
  "qlib_preflight": {
    "provider_present": true,
    "qlib_import_ok": true,
    "qlib_python": "..."
  },
  "native_minimal_status": "...",
  "native_backtest_status": "...",
  "blocking_for_acceptance": false,
  "failure_reason": null
}
```

### Prompt Requirements

Step4 prompt must say:

```text
Report qlib as qlib_native_status=<taxonomy>. Never call qlib success unless status=native_backtest_success or explicitly native_minimal_success for a minimal-only run.
```

### Smoke Cases

Create/extend `scripts/run_factorforge_qlib_status_taxonomy_smoke.py`.

```text
qlib_partial_labeled_success_blocks
qlib_sample_stub_labeled_native_success_blocks
qlib_partial_optional_passes_with_explicit_status
qlib_partial_mandatory_blocks
qlib_preflight_ready_passes_as_preflight_only
qlib_native_backtest_success_passes
```

---

## 8. Task E - P1 Step4 Backtest Base Dataset Contract

### Objective

Separate factor-specific work from reusable backtest-base work. After a revision, Step4 should recompute only the new `factor_values`; forward-return labels, tradable masks, calendars, cost-model inputs, and backend base context should be reusable when the data/version/window/universe/policies match.

### Boundary

This task must not move clean-data construction into Factor Forge. The backtest-base producer is a Data API consumer. It may materialize reusable label/mask/calendar/cost datasets from published clean/canonical data, but it must not clean raw data or mutate Data API outputs.

### Required Architecture

Step4 formal evaluation must consume two inputs:

```text
1. factor_values.parquet
   - factor/revision specific
   - owned by Step4 formal run
   - recomputed when formula, implementation, data identity, or run identity changes

2. backtest_base_dataset
   - factor independent under the same source_data_version/window/universe/label_policy/tradable_policy/cost_policy
   - reusable across parent, child, sibling, and rerun evaluations
   - contains labels, masks, calendar, cost inputs, and optional exposure/backend context
```

Step4 must not rebuild the backtest base if a matching validated base exists.

### Required Contract

Add a `backtest_base_dataset_contract` object and persist it in Step4 profile/evidence, and optionally as a standalone artifact under `objects/backtest_base_dataset/` or `runs/_shared/backtest_base/`.

Minimum shape:

```json
{
  "version": "factorforge_backtest_base_dataset_contract_v1",
  "backtest_base_dataset_id": "sha256-or-stable-id",
  "source_data_version": "...",
  "clean_data_hash": "...",
  "window_start": "YYYYMMDD",
  "window_end": "YYYYMMDD",
  "universe_id": "a_share_all",
  "universe_hash": "...",
  "label_policy": {
    "horizon": "T+1",
    "return_field": "pct_chg",
    "alignment": "factor_date_t_to_return_t_plus_1",
    "same_day_return_forbidden": true
  },
  "tradable_policy": {
    "exclude_st": true,
    "exclude_suspended": true,
    "exclude_limit_up_down": true,
    "exclude_new_stock_days": null
  },
  "cost_policy": {
    "version": "...",
    "default_cost_rate": 0.003,
    "turnover_cost_formula": "turnover * cost_rate"
  },
  "calendar_hash": "...",
  "artifact_paths": {
    "labels": "...",
    "tradable_mask": "...",
    "calendar": "...",
    "cost_inputs": "..."
  },
  "artifact_hashes": {},
  "producer_step": "backtest_base_producer",
  "producer_repo_sha": "...",
  "created_at": "...",
  "validator_verdict": "PASS"
}
```

### Required Reuse Profile

Step4 performance profile must include:

```json
{
  "backtest_base_profile": {
    "version": "factorforge_backtest_base_profile_v1",
    "backtest_base_dataset_id": "...",
    "backtest_base_reuse_hit": true,
    "backtest_base_reuse_reason": "identity_match",
    "backtest_base_load_seconds": 0.0,
    "backtest_base_validate_seconds": 0.0,
    "factor_values_load_seconds": 0.0,
    "evaluation_seconds": 0.0,
    "write_outputs_seconds": 0.0
  }
}
```

If reuse misses, the reason must be auditable:

```text
missing_dataset
source_data_version_mismatch
clean_data_hash_mismatch
window_mismatch
universe_hash_mismatch
label_policy_mismatch
tradable_policy_mismatch
cost_policy_mismatch
artifact_hash_mismatch
ambiguous_identity
```

### Required Blockers

```text
BLOCK_BACKTEST_BASE_DATASET_MISSING
BLOCK_BACKTEST_BASE_LABEL_POLICY_MISMATCH
BLOCK_BACKTEST_BASE_UNIVERSE_MISMATCH
BLOCK_BACKTEST_BASE_DATA_VERSION_MISMATCH
BLOCK_BACKTEST_BASE_TRADABLE_POLICY_MISMATCH
BLOCK_BACKTEST_BASE_COST_POLICY_MISMATCH
BLOCK_BACKTEST_BASE_ARTIFACT_HASH_MISMATCH
BLOCK_STEP4_REUSE_GATE_AMBIGUOUS
BLOCK_STEP4_FULL_FACTOR_CSV_FORBIDDEN
```

### Full CSV Policy

Formal Step4 must default to parquet factor values plus small sample CSV only.

Required:

```json
{
  "factor_output_policy": {
    "formal_format": "parquet",
    "full_factor_csv_written": false,
    "sample_csv_written": true,
    "full_csv_disabled_reason": "production_default"
  }
}
```

Full CSV may be enabled only by explicit debug/audit policy, and must be recorded as non-default. Large formal production runs must block if they silently write full CSV:

```text
BLOCK_STEP4_FULL_FACTOR_CSV_FORBIDDEN
```

### Shared Evaluation Context

Self-quant and qlib diagnostics must be able to consume the same backtest-base/evaluation context:

```json
{
  "shared_evaluation_context": {
    "version": "factorforge_shared_evaluation_context_v1",
    "backtest_base_dataset_id": "...",
    "label_table_path": "...",
    "tradable_mask_path": "...",
    "calendar_path": "...",
    "cost_inputs_path": "...",
    "used_by": ["self_quant_analyzer", "qlib_backtest"]
  }
}
```

Qlib must not redo the same big forward-return merge if the shared context already contains the aligned labels/masks needed for diagnostics.

### Performance Profile Requirements

Step4 profile must split:

```text
factor_io:
  load_factor_values
  normalize_align_factor_index

backtest_base:
  resolve_base_dataset
  validate_identity
  load_labels
  load_mask
  load_calendar
  load_cost_inputs

evaluation:
  ic
  rank_ic
  quantile_assignment
  quantile_nav
  long_side
  cost_adjusted
  qlib_diagnostics

output:
  write_parquet_evidence
  write_csv_sample
  write_plots
  write_profile
```

Also preserve wrapper wall time because adapter-internal timing can understate real cost.

### Producer And Validator Files

Likely create:

```text
skills/factor-forge-step4/scripts/backtest_base_dataset.py
scripts/run_factorforge_step4_backtest_base_contract_smoke.py
docs/operations/factorforge-step4-backtest-base-contract.zh-CN.md
```

Likely modify:

```text
skills/factor-forge-step4/scripts/run_step4.py
skills/factor-forge-step4/scripts/validate_step4.py
skills/factor-forge-step4/scripts/self_quant_adapter.py
skills/factor-forge-step4/scripts/qlib_backtest_adapter.py
scripts/run_factorforge_performance_profile.py
scripts/run_factorforge_performance_smoke.py
skills/factor-forge-step4/SKILL.md
```

### Smoke Cases

Create/extend `scripts/run_factorforge_step4_backtest_base_contract_smoke.py`.

Required cases:

```text
backtest_base_missing_blocks_when_required
backtest_base_label_policy_mismatch_blocks
backtest_base_universe_hash_mismatch_blocks
backtest_base_data_version_mismatch_blocks
backtest_base_artifact_hash_mismatch_blocks
backtest_base_ambiguous_identity_blocks
full_factor_csv_default_forbidden_blocks
sample_csv_only_policy_passes
self_quant_and_qlib_share_context_passes
same_base_second_run_reuse_hit_passes
factor_revision_recomputes_factor_values_but_reuses_base_passes
```

### Real-Run Acceptance Requirement

Synthetic smokes are required but not sufficient for this task. Before claiming production readiness, run one approved real report proof with two Step4 executions under the same data/window/universe/policies:

```text
Run 1:
- base dataset may be built
- backtest_base_reuse_hit may be false with reason=missing_dataset

Run 2:
- factor values may be recomputed if formula/implementation changed
- backtest_base_reuse_hit must be true
- label/mask/calendar/cost preparation must not be rebuilt
```

Report:

```text
repo_sha
report_id
run_id
artifact_root
backtest_base_dataset_id
backtest_base_reuse_hit
backtest_base_reuse_reason
factor_values_path
factor_values_hash
full_factor_csv_written
sample_csv_written
Step4 phase breakdown
self_quant status
qlib_native_status
validator verdict
wrapper proof status
clean_data_mutated=false
search_worker_started=false
official_promotion_written=false
```

Do not run this real proof without explicit user authorization.

---

## 9. Task F - P1 Formal Artifact Top-Level Acceptance Fields

### Objective

Keep full `artifact_identity`, but expose acceptance fields at top level.

### Required Fields

For formal master artifacts:

```json
{
  "report_id": "...",
  "factor_id": "...",
  "run_id": "...",
  "artifact_root": "...",
  "producer": "...",
  "status": "...",
  "verdict": "...",
  "artifact_identity": {}
}
```

### Artifact Targets

```text
alpha_idea_master
factor_spec_master
data_prep_master
implementation_plan_master
factor_run_master
factor_case_master
factor_evaluation
research_iteration_master
ultimate_run_report
ultimate_loop_report
performance_profile
handoff artifacts
```

### Validator Requirements

- Missing `artifact_identity` remains a hard block.
- Missing top-level acceptance fields must block for formal master artifacts.
- If `artifact_identity.run_id` exists and top-level `run_id` differs, block.

Blocker:

```text
BLOCK_FORMAL_ARTIFACT_TOP_LEVEL_IDENTITY_MISSING
BLOCK_FORMAL_ARTIFACT_TOP_LEVEL_IDENTITY_MISMATCH
```

---

## 10. Task G - P1 Step6 Evidence Status Split

### Objective

Step6 must never describe the whole run as "partial" when only one backend is partial.

### Required Field

```json
{
  "evidence_status": {
    "version": "factorforge_step6_evidence_status_v1",
    "wrapper_validation_status": "PASS|BLOCK|FAILED",
    "self_quant_evidence_status": "complete|partial|missing|failed",
    "qlib_native_status": "not_attempted|preflight_blocked|preflight_ready|partial_payload|native_minimal_success|native_backtest_success|failed",
    "long_side_evidence_status": "complete|partial|missing|failed",
    "cost_model_status": "complete|partial|missing",
    "drawdown_geometry_status": "complete|partial|missing",
    "research_decision": "promote|iterate|reject|needs_human_review",
    "promotion_gate_status": "open|blocked_by_long_side|blocked_by_cost|blocked_by_drawdown|blocked_by_evidence|not_applicable"
  }
}
```

### Prompt Requirements

Step6 prompt must require:

```text
State wrapper validation separately from backend evidence.
State self-quant separately from qlib.
State long-side evidence separately from long-short diagnostics.
State research decision separately from backend status.
Never use "partial" without naming the layer.
```

### Smoke Cases

Create/extend `scripts/run_factorforge_step6_evidence_status_smoke.py`.

```text
generic_partial_status_blocks
missing_wrapper_status_blocks
missing_self_quant_status_blocks
missing_qlib_status_blocks
missing_research_decision_blocks
valid_evidence_status_passes
```

---

## 11. Task H - P2 Dirac-Style Research Report Validator

### Objective

Make Dirac-style research reporting a production standard, not optional prose.

### Required Report Sections

```text
1. research_equation_or_soft_law
2. formula_implied_information
3. metric_anomaly_review
4. model_linked_metric_signature
5. stochastic_projection_consistency_check
6. volatility_drag_review
7. drawdown_recovery_area_review
8. component_level_revision_axes
9. direction_losing_transform_review
10. dimensional_or_unit_consistency_review
```

### Formula-Implied Information Table

Every report must include a table/list:

```json
{
  "formula_component": "...",
  "observable": "...",
  "implied_latent_state": "...",
  "payer_or_constraint": "...",
  "expected_sign": "...",
  "falsification_metric": "..."
}
```

It is not enough to restate `close`, `volume`, or the formula text.

### Anomaly Review

Required classifications:

```text
bug
data_artifact
implementation_artifact
direction_or_sign_error
formula_measures_avoid_state
tradable_anomaly
new_factor_seed
kill_signal
under_specified
```

Alpha036-like case requirement:

```text
positive RankIC + negative high-score long side
```

must trigger anomaly classification.

### Stochastic Projection Rule

The primary model does not have to be stochastic. But for T+0/T+1 or short-horizon price factors, require a stochastic projection check:

```text
price process term affected
conditional distribution implication
drift vs volatility vs jump/impact separation
metric expected if projection is true
metric that falsifies it
```

### Smoke Cases

Create/extend `scripts/run_factorforge_dirac_research_report_contract_smoke.py`.

```text
missing_formula_implied_information_blocks
raw_formula_restatement_blocks
missing_anomaly_classification_blocks
positive_ic_negative_long_without_anomaly_blocks
missing_model_linked_metrics_blocks
missing_stochastic_projection_check_blocks
missing_volatility_drag_review_blocks
missing_drawdown_recovery_area_review_blocks
valid_dirac_research_report_passes
```

---

## 12. Task I - P2 Component-Level Council Packet

### Objective

Composite formulas must produce component-level revision tasks for Council.

### Required Triggers

```text
weighted sum formula -> component_ablation
abs(corr(...)) -> direction_losing_transform_review
mixed horizons -> time_scale_consistency_review
high turnover -> turnover_smoothing_review
positive IC and negative long side -> sign/direction anomaly branch
price-volume formula -> drift_vs_volatility_branch_split
```

### Required Council Taskbook Fields

```json
{
  "component_revision_axes": [],
  "component_ablation_plan": [],
  "direction_losing_transform_review": {},
  "dimensional_consistency_review": {},
  "latent_state_independence_review": {},
  "stochastic_projection_falsification": {},
  "branch_kill_criteria": []
}
```

### Smoke Cases

```text
composite_formula_without_ablation_blocks
abs_corr_without_direction_review_blocks
mixed_horizon_without_time_scale_review_blocks
positive_ic_negative_long_without_branch_blocks
valid_composite_council_packet_passes
```

---

## 13. Task J - Prompt Contract Completeness

### Objective

Ensure Step2/3/4/6 prompts ask for the same fields validators require.

### Required Prompt Coverage

`scripts/run_factorforge_prompt_contract_smoke.py` must confirm prompts mention:

```text
standard_formula_fields_contract
derived_field_contract
unit policy
lookback policy
leakage policy
acceptance_summary
qlib_native_status
backtest_base_dataset_contract
backtest_base_reuse_hit
full factor CSV disabled
shared_evaluation_context
evidence_status
formula_implied_information
metric_anomaly_review
model_linked_metric_signature
volatility_drag
drawdown_recovery_area
component_ablation
direction_losing_transform_review
```

### Anti-Pattern Bans

Prompts must explicitly ban:

```text
"derive if needed" without source fields
"qlib partial success"
"Step3B formal factor values"
"Step4 rebuilds labels/masks/calendar/cost for every factor"
"full factor CSV as default production output"
"partial run" without layer
raw formula restatement as mechanism
generic stochastic process as explanation
```

---

## 14. Final Verification Matrix

Run all of the following before review:

```bash
git diff --check

python3 -m py_compile \
  factor_factory/formula/field_aliases.py \
  factor_factory/formula/evaluator.py \
  factor_factory/formula/parity.py \
  skills/factor-forge-step2/scripts/validate_step2.py \
  skills/factor-forge-step3/scripts/run_step3.py \
  skills/factor-forge-step3/scripts/validate_step3.py \
  skills/factor-forge-step3/scripts/run_step3b.py \
  skills/factor-forge-step3/scripts/validate_step3b.py \
  skills/factor-forge-step4/scripts/run_step4.py \
  skills/factor-forge-step4/scripts/validate_step4.py \
  skills/factor-forge-step4/scripts/backtest_base_dataset.py \
  skills/factor-forge-step4/scripts/self_quant_adapter.py \
  skills/factor-forge-step4/scripts/qlib_backtest_adapter.py \
  skills/factor-forge-step6/scripts/run_step6.py \
  skills/factor-forge-step6/scripts/validate_step6.py \
  factor_factory/revision_council/validator.py

python3 scripts/run_factorforge_alpha101_standard_field_contract_smoke.py
python3 scripts/run_factorforge_production_acceptance_contract_smoke.py
python3 scripts/run_factorforge_step4_backtest_base_contract_smoke.py
python3 scripts/run_factorforge_qlib_status_taxonomy_smoke.py
python3 scripts/run_factorforge_step6_evidence_status_smoke.py
python3 scripts/run_factorforge_dirac_research_report_contract_smoke.py
python3 scripts/run_factorforge_prompt_contract_smoke.py
python3 scripts/run_factorforge_performance_smoke.py
python3 scripts/run_factorforge_mechanism_math_v2_smoke.py
python3 scripts/run_step6_intelligence_acceptance.py
```

If any script is too slow or blocked by missing optional dependencies, document:

```text
command
reason
whether blocker is P0/P1/P2
what evidence remains unproven
```

Do not call the task complete if P0 smokes did not run.

---

## 15. Reviewer Handoff Requirements

The final response to reviewer must include:

```text
Role: Factor Forge Ultimate 一号 coder

Scope:
- standard_formula_fields_contract
- derived_field_contract unit/lookback/leakage
- production acceptance_summary
- qlib_native_status taxonomy
- backtest_base_dataset_contract
- Step4 backtest-base reuse gate
- full factor CSV default-disabled proof
- formal artifact top-level identity fields
- Step6 evidence status split
- Dirac-style report validator
- component-level Council packet
- prompt contract completeness

Commits:
- <sha>

Verification:
- <command>: PASS

Negative cases proven:
- <case list and blocker tokens>

Out of scope:
- no worker launch
- no production Step3B/Step4
- no raw/clean data mutation
- no Alpha036/Alpha037 artifact hand-edit
- no promotion or official library write

Known remaining risks:
- <only if any>

Reviewer questions:
1. Are Step2/3A/Step4 standard field responsibilities unambiguous?
2. Can qlib partial still be misread as qlib success?
3. Does Step4 recompute only factor_values after revision while reusing label/mask/calendar/cost base data?
4. Can Step4 still silently write full factor CSV in production mode?
5. Can Step6 still collapse wrapper/self-quant/qlib/research decision into one status?
6. Do prompts force formula-implied information rather than generic mechanism prose?
7. Are P0 negative cases strong enough to prevent a repeat of Alpha036/Alpha037 manual debugging?
```

---

## 16. Installed Skill Sync Policy

Do not sync installed skills until reviewer accepts the repo-side changes.

After acceptance, sync only the affected skills:

```text
factor-forge-step2
factor-forge-step3
factor-forge-step4
factor-forge-step6
```

Targets:

```text
/Users/humphrey/.codex/skills/
/Users/humphrey/.openclaw/workspace/skills/
Humphrey EC2 runtime skill path, branch-aware
```

After sync, report:

```text
repo_sha
installed skill diff clean status
Mac branch
Humphrey runtime branch
worker_started=false
```

Do not launch worker as part of sync.
