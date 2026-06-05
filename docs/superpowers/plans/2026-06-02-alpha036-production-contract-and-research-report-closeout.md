# Factor Forge Alpha036 Production Contract And Research Report Closeout Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` or `superpowers:executing-plans` to implement this plan task-by-task. Track progress with the checkbox items below. Do not skip RED tests. Do not make this a documentation-only patch.

**Goal:** Convert the Alpha036 production-acceptance feedback into hard Factor Forge contracts, validators, smokes, and prompt requirements so future Alpha101-style runs do not depend on researcher improvisation for standard fields, Step3B/Step4 artifact ownership, qlib backend status, performance acceptance summaries, or Dirac-style research judgment.

**Why this matters:** Alpha036 reached `wrapper PASS` and Step3-6 validators passed, but production acceptance exposed contract gaps. The current report is acceptable as a production acceptance note, but it is not yet a complete Dirac-style research report because formula-implied information, anomaly review, model-linked metrics, volatility drag, and drawdown recovery-area diagnostics are not fully enforced.

**Architecture:** Keep Factor Forge as a Data API consumer. Step2 declares formula-required standard fields; Step3A materializes and validates report-local standard fields; Step3B proves executability with sample-only artifacts; Step4 owns formal factor values and backend evaluation status; Step5/6 interpret evidence through long-only financial economics and Dirac-style model discipline. Prompts and validators must agree on the same field names and failure modes.

**Tech Stack:** Python 3, pandas/NumPy/Parquet, Factor Forge skills Step2/3/4/6, formula field alias/evaluator modules, Step3/Step4 validators, Step6 research prompts, smoke scripts under `scripts/`, docs under `docs/operations` and `docs/contracts`.

---

## Required Branch Discipline

Use a clean worktree. Do not implement in `/Users/humphrey/projects/factor-factory` if it is dirty.

Recommended setup:

```bash
cd /Users/humphrey/projects/factor-factory
git fetch origin
git worktree add /tmp/factorforge-alpha036-contract-closeout origin/main
cd /tmp/factorforge-alpha036-contract-closeout
git switch -c codex/factorforge-alpha036-contract-closeout
```

Do not modify:

- raw market data;
- S3 data;
- generated raw LLM JSON;
- completed Alpha036 artifacts under `/Users/humphrey/projects/factorforge`;
- portfolio construction rules or the long-only mandate;
- Data API cleaning logic;
- EC2/OpenClaw orchestration glue unless explicitly needed for installed skill sync after review.

Do not claim completion unless:

- all P0/P1 contract fields are written by producers and checked by validators;
- negative smoke cases prove bad artifacts are blocked;
- skill prompts instruct LLMs to produce the new fields instead of relying on downstream inference;
- the Alpha036-style research report template includes model-linked metrics, Dirac-style anomaly review, volatility drag, drawdown recovery days, and drawdown recovery-area;
- existing performance and mechanism smokes still pass.

---

## Source Feedback To Address

Reference documents:

- `docs/operations/factorforge-skill-feedback-alpha036-production-acceptance.zh-CN.md`
- `docs/operations/factorforge-long-term-contract-gaps-feedback-20260603.zh-CN.md`
- `docs/operations/alpha036-production-acceptance-research-report.zh-CN.md`
- `docs/operations/factorforge-dirac-style-research-contract.zh-CN.md`
- `docs/superpowers/plans/2026-06-02-factorforge-dirac-math-contract-closeout.md`
- `docs/superpowers/plans/2026-06-02-factorforge-performance-production-closeout.md`

The implementation must address these specific findings:

1. Alpha101 canonical formulas require standard fields such as `volume`, `returns`, `vwap`, `adv20`, but clean daily data often exposes `vol`, `amount`, `pct_chg`. This must be a Step2/Step3A contract, not a Step3B/Step4 guessing exercise.
2. Step3B sample output and Step4 formal factor values must remain separate by filename, metadata, ownership, validator checks, and reuse gates.
3. Step4 qlib native status must distinguish `not_attempted`, `preflight_ready`, `partial_payload`, and `native_backtest_success`; `partial` must not be misread as qlib success.
4. Performance evidence must include a compact acceptance summary, not force researchers to manually join Step3B metadata, Step4 metadata, backend payloads, and wrapper timings.
5. Formal master artifacts must surface top-level acceptance identifiers: `report_id`, `run_id`, `artifact_root`, `producer`, and status/verdict fields where applicable.
6. Step6 must split `wrapper_validation_status`, `self_quant_evidence_status`, `qlib_native_status`, and `research_decision`.
7. Alpha036 research reporting must move beyond generic stochastic language and include formula-implied information, anomaly classification, model-linked metrics, volatility drag, drawdown recovery area, and component-level Council instructions.

Already closed by the Alpha037 Step3B gate hotfix, and therefore should not be reworked unless regression tests fail:

```text
Step3B must not upgrade a blocked Step3A handoff to step3b_ready=true.
BLOCK_STEP3B_REQUIRES_READY_STEP3A must fire before codegen/write when Step3A is not ready.
```

The remaining work in this plan is the broader long-term production contract closure, not another fix for that already-accepted gate.

---

## Files Map

Likely modified files:

- `factor_factory/formula/field_aliases.py`
- `factor_factory/formula/evaluator.py`
- `factor_factory/formula/parity.py`
- `skills/factor-forge-step2/SKILL.md`
- `skills/factor-forge-step2/references/prompts.md`
- `skills/factor-forge-step3/SKILL.md`
- `skills/factor-forge-step3/scripts/run_step3.py`
- `skills/factor-forge-step3/scripts/run_step3b.py`
- `skills/factor-forge-step3/scripts/validate_step3.py`
- `skills/factor-forge-step3/scripts/validate_step3b.py`
- `skills/factor-forge-step4/SKILL.md`
- `skills/factor-forge-step4/scripts/run_step4.py`
- `skills/factor-forge-step4/scripts/validate_step4.py`
- `skills/factor-forge-step4/scripts/self_quant_adapter.py`
- `skills/factor-forge-step4/scripts/qlib_backtest_adapter.py`
- `skills/factor-forge-step6/SKILL.md`
- `skills/factor-forge-step6/references/prompts.md`
- `skills/factor-forge-step6/scripts/run_step6.py`
- `skills/factor-forge-step6/scripts/validate_step6.py`
- `factor_factory/revision_council/validator.py`
- `scripts/run_factorforge_performance_smoke.py`
- `scripts/run_factorforge_mechanism_math_v2_smoke.py`
- `scripts/run_factorforge_prompt_contract_smoke.py`
- `scripts/run_step6_intelligence_acceptance.py`
- `docs/contracts/step2-contract.zh-CN.md`
- `docs/contracts/step3-contract.zh-CN.md`
- `docs/contracts/step4-contract.md`
- `docs/contracts/step6-contract.zh-CN.md`
- `docs/operations/factorforge-dirac-style-research-contract.zh-CN.md`

Create if absent:

- `docs/operations/factorforge-alpha101-standard-field-contract.zh-CN.md`
- `docs/operations/factorforge-production-acceptance-report-template.zh-CN.md`
- `scripts/run_factorforge_alpha101_standard_field_contract_smoke.py`
- `scripts/run_factorforge_production_acceptance_contract_smoke.py`

Avoid changing unless required by tests:

- `factor_factory/data_api/`
- `factor_factory/data_access/`
- `scripts/publish_qlib_daily_provider.py`
- EC2 worker dispatch scripts

---

## Task 1: P0 Standard Formula Fields Contract

**Objective:** Make `required_standard_formula_fields` a formal Step2 -> Step3A -> Step3B/Step4 contract for Alpha101-style formulas.

**Boundary:** This task derives formula-standard fields from already-clean data. It must not clean raw data, query raw paths directly, or compute factor values in Step3A.

**Required behavior:**

- Step2 must emit `required_standard_formula_fields` for formula/operator mode when the formula references standard fields not guaranteed by raw clean daily schema.
- Step3A must materialize those fields into the report-local daily snapshot or BLOCK.
- Step3A must write `derived_field_contract` with source fields, derived fields, formulas, lookback windows, leakage policy, and validation result.
- Step3B and Step4 must consume the already-materialized report-local fields instead of independently guessing aliases.

**Minimum field rules:**

```text
volume  <- vol
returns <- pct_chg / 100, or close/pre_close - 1 when pct_chg absent
vwap    <- amount / vol with documented unit handling; BLOCK on ambiguous units unless contract records scale
advN    <- rolling mean(volume, N) computed with past/current-window policy explicitly declared
```

**Prompt requirements:**

Update Step2 prompts so the LLM must produce:

```json
{
  "standard_formula_fields_contract": {
    "required_standard_formula_fields": ["volume", "returns", "vwap", "adv20"],
    "source_field_candidates": {
      "volume": ["vol"],
      "returns": ["pct_chg", "close", "pre_close"],
      "vwap": ["amount", "vol"],
      "adv20": ["volume"]
    },
    "derivation_rules": {},
    "lookback_policy": "no future data; rolling fields may use data up to factor timestamp only",
    "block_if_unavailable": true
  }
}
```

The prompt must explicitly forbid vague language like "derive if needed" without naming the source fields and leakage policy.

**Validator requirements:**

Add RED/GREEN cases:

- `missing_required_standard_formula_fields_blocks`
- `adv20_without_volume_source_blocks`
- `vwap_without_amount_or_volume_source_blocks`
- `step3a_snapshot_missing_required_field_blocks`
- `valid_alpha101_standard_field_contract_passes`

Expected blocker tokens:

```text
BLOCK_STANDARD_FORMULA_FIELDS_MISSING
BLOCK_STANDARD_FORMULA_FIELD_SOURCE_MISSING
BLOCK_STEP3A_STANDARD_FIELD_NOT_MATERIALIZED
BLOCK_STANDARD_FORMULA_FIELD_LEAKAGE_POLICY_MISSING
```

**Acceptance proof:**

Run:

```bash
python3 -m py_compile \
  factor_factory/formula/field_aliases.py \
  factor_factory/formula/evaluator.py \
  factor_factory/formula/parity.py \
  skills/factor-forge-step3/scripts/run_step3.py \
  skills/factor-forge-step3/scripts/validate_step3.py
python3 scripts/run_factorforge_alpha101_standard_field_contract_smoke.py
python3 scripts/run_factorforge_prompt_contract_smoke.py
```

The smoke summary must show all negative cases blocked and the valid Alpha036-like case accepted.

---

## Task 2: P0 Step3B Sample-Only Ownership Contract

**Objective:** Make it impossible for Step3B sample/proof outputs to masquerade as Step4 formal factor values.

**Boundary:** Step3B may prove executability and write sample outputs. Step4 remains the only owner of formal `factor_values__<report_id>` artifacts.

**Required behavior:**

- Step3B sample files must use only:

```text
step3b_sample_factor_values__<report_id>.parquet
step3b_sample_factor_values__<report_id>.csv
step3b_sample_run_metadata__<report_id>.json
```

- Step3B metadata must include:

```json
{
  "is_formal_factor_values": false,
  "purpose": "step3_executability_proof",
  "formal_factor_values_owner": "Step4",
  "sample_cap": {},
  "sample_window": {},
  "lineage": {}
}
```

- Step3B must remove stale formal-looking sample outputs it created in the same run root, but must not delete unrelated user files or Step4 formal outputs.
- Step4 reuse may only use Step3B output as compute cache when identity/hash/window/row/date/ticker counts prove full formal coverage. Even then Step4 must rewrite/own the formal artifact.

**Prompt requirements:**

Update Step3 skill/prompt text so agents are told:

```text
Step3B output is executability evidence only. Never report Step3B sample parquet/csv as formal factor values. Formal factor values are owned by Step4.
```

**Validator requirements:**

Add cases:

- `step3b_formal_named_output_blocks`
- `step3b_missing_sample_ownership_blocks`
- `step4_reuse_sample_without_full_coverage_blocks`
- `step4_reuse_full_coverage_cache_passes`
- `step4_recomputed_when_identity_mismatch_passes`

Expected blocker tokens:

```text
BLOCK_STEP3B_FORMAL_FACTOR_VALUES_OUTPUT
BLOCK_STEP3B_SAMPLE_OWNERSHIP_MISSING
BLOCK_STEP4_REUSE_FULL_COVERAGE_NOT_PROVEN
```

**Acceptance proof:**

Run:

```bash
python3 -m py_compile \
  skills/factor-forge-step3/scripts/run_step3b.py \
  skills/factor-forge-step3/scripts/validate_step3b.py \
  skills/factor-forge-step4/scripts/run_step4.py
python3 scripts/run_factorforge_performance_smoke.py
```

The performance smoke must include a tampered/mismatched Step3B parquet negative case that falls back to recompute or blocks, never silently reuses.

---

## Task 3: P0 Step4 Qlib Native Status Taxonomy

**Objective:** Replace ambiguous `qlib_backtest=partial` reporting with explicit qlib-native status taxonomy.

**Boundary:** This task clarifies backend evidence. It does not require qlib full success for every research run unless the run config declares qlib full success mandatory.

**Required taxonomy:**

```text
not_attempted
preflight_blocked
preflight_ready
partial_payload
native_minimal_success
native_backtest_success
failed
```

**Required fields:**

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
  "failure_reason": null,
  "blocking_for_acceptance": false
}
```

**Validator requirements:**

- `validate_step4.py` must reject backend payloads that use `partial` without a taxonomy status.
- If wrapper config says qlib full success is mandatory, `partial_payload` must block formal Step4 acceptance.
- If qlib is optional, Step4 can PASS with `self_quant=success` and `qlib_native_status=partial_payload`, but reports must state the split.

**Prompt requirements:**

Update Step4 skill prompt so agents must say:

```text
self_quant_analyzer=success, qlib_native_status=<taxonomy>, wrapper_validation_status=<PASS/BLOCK>
```

Never write "Step4 complete with qlib success" unless `native_backtest_success`.

**Acceptance proof:**

Run:

```bash
python3 -m py_compile \
  skills/factor-forge-step4/scripts/run_step4.py \
  skills/factor-forge-step4/scripts/validate_step4.py \
  skills/factor-forge-step4/scripts/qlib_backtest_adapter.py
python3 scripts/run_factorforge_production_acceptance_contract_smoke.py
```

Smoke cases must include:

- qlib not attempted optional pass;
- qlib preflight blocked optional pass with explicit status;
- qlib partial optional pass with explicit status;
- qlib partial mandatory block;
- qlib native success pass.

---

## Task 4: P0 Performance Acceptance Summary

**Objective:** Add a compact `acceptance_summary` so production acceptance can be reviewed without manually stitching five artifacts.

**Boundary:** This summary is evidence organization. It must not change factor values, metrics, or promotion gates.

**Required shape:**

```json
{
  "acceptance_summary": {
    "report_id": "...",
    "run_id": "...",
    "artifact_root": "...",
    "repo_sha": "...",
    "wrapper_validation_status": "PASS",
    "step_status": {
      "step3": "PASS",
      "step3b": "PASS",
      "step4": "PASS",
      "step5": "PASS",
      "step6": "PASS"
    },
    "step3b": {
      "backend": "operator|direct_code|hybrid",
      "input_format": "parquet",
      "sample_only": true,
      "phase_seconds": {},
      "formula_engine_profile": {},
      "cache": {}
    },
    "step4": {
      "formal_factor_values_owner": "Step4",
      "formal_factor_values_path": "...",
      "input_format": "parquet",
      "self_quant_status": "success|partial|failed|skipped",
      "qlib_native_status": "not_attempted|preflight_ready|partial_payload|native_backtest_success|...",
      "phase_seconds": {}
    },
    "reuse": {
      "step3b_cache_reused_by_step4": false,
      "reuse_gate_status": "recomputed|reused|blocked",
      "reuse_reason": "..."
    },
    "side_effects": {
      "generated_code_digest_changed": false,
      "clean_data_digest_changed": false,
      "official_record_written": false,
      "search_worker_started": false
    },
    "financial_metrics": {
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

**Prompt requirements:**

Update Step4/Step6 report prompts so acceptance reports must present this summary first. Researchers should not have to infer `run_id` from `artifact_identity`.

**Validator requirements:**

Add smoke cases:

- `acceptance_summary_missing_blocks`
- `acceptance_summary_missing_backend_split_blocks`
- `acceptance_summary_missing_reuse_status_blocks`
- `valid_acceptance_summary_passes`

**Acceptance proof:**

Run:

```bash
python3 -m py_compile \
  scripts/run_factorforge_performance_profile.py \
  skills/factor-forge-step4/scripts/run_step4.py \
  skills/factor-forge-step6/scripts/run_step6.py
python3 scripts/run_factorforge_production_acceptance_contract_smoke.py
```

---

## Task 5: P1 Formal Artifact Top-Level Acceptance Fields

**Objective:** Keep `artifact_identity` as the full provenance object, but expose common acceptance identifiers at top level to reduce audit ambiguity.

**Boundary:** Do not remove or weaken `artifact_identity`. This task adds redundant top-level audit fields for formal master artifacts.

**Required fields for formal masters:**

```json
{
  "report_id": "...",
  "run_id": "...",
  "artifact_root": "...",
  "producer": "...",
  "status": "...",
  "verdict": "PASS|ACCEPT|ITERATE|REJECT|BLOCK|..."
}
```

Apply where appropriate:

- `data_prep_master`
- `implementation_plan_master`
- `factor_run_master`
- `factor_case_master`
- `factor_evaluation`
- `research_iteration_master`
- handoff artifacts
- ultimate run report/proof if it currently lacks `artifact_root`

**Validator requirements:**

Validators must accept the existing `artifact_identity` but warn/block according to artifact maturity:

- P0 formal write artifacts must include `report_id`, `run_id`, `artifact_root`, `producer`;
- `verdict` is required where the artifact is a validation/research-decision artifact;
- missing top-level field must not be silently ignored.

**Acceptance proof:**

Run relevant validators and smokes:

```bash
python3 -m py_compile \
  skills/factor-forge-step3/scripts/validate_step3.py \
  skills/factor-forge-step4/scripts/validate_step4.py \
  skills/factor-forge-step6/scripts/validate_step6.py
python3 scripts/run_factorforge_acceptance_smoke.py
python3 scripts/run_factorforge_production_acceptance_contract_smoke.py
```

---

## Task 6: P1 Step6 Backend Evidence Status Split

**Objective:** Prevent Step6 from describing an entire run as "partial" when only one backend is partial.

**Boundary:** This task improves evidence interpretation and reporting. It does not promote or reject factors automatically.

**Required fields:**

```json
{
  "evidence_status_split": {
    "wrapper_validation_status": "PASS|BLOCK|FAILED",
    "self_quant_evidence_status": "complete|partial|missing|failed",
    "qlib_native_status": "not_attempted|preflight_ready|partial_payload|native_backtest_success|failed",
    "long_side_evidence_status": "complete|partial|missing|failed",
    "cost_model_status": "complete|partial|missing",
    "drawdown_geometry_status": "complete|partial|missing",
    "research_decision": "promote|iterate|reject|needs_human_review"
  }
}
```

**Prompt requirements:**

Update Step6 prompt so the LLM must:

- state wrapper validation separately from backend evidence;
- state long-side evidence separately from long-short diagnostics;
- state qlib status using the Step4 taxonomy;
- never use a single word like "partial" for the whole run without explaining which evidence layer is partial.

**Validator requirements:**

Add cases:

- `step6_generic_partial_status_blocks`
- `step6_missing_backend_status_split_blocks`
- `step6_valid_status_split_passes`

**Acceptance proof:**

Run:

```bash
python3 -m py_compile \
  skills/factor-forge-step6/scripts/run_step6.py \
  skills/factor-forge-step6/scripts/validate_step6.py
python3 scripts/run_step6_intelligence_acceptance.py
python3 scripts/run_factorforge_prompt_contract_smoke.py
```

---

## Task 7: Research Report Upgrade - Dirac-Style Formula-Implied Information

**Objective:** Upgrade the Alpha036-style report contract from "production acceptance plus interpretation" to a true Dirac-style research report.

**Boundary:** This task changes research reporting, prompts, and validators. It must not hand-edit Alpha036 artifacts or fabricate Council results.

**Required report section:**

```text
Dirac-Style Mechanism Audit

1. Research equation / soft law
   - strict identity, institutional constraint, behavioral feedback equation,
     empirical invariance, or research conjecture
   - equation text
   - assumptions
   - validity scope

2. Formula-implied information
   - formula component
   - observable
   - implied latent/model state
   - payer/constraint source
   - expected sign
   - falsification metric

3. Anomaly review
   - observed anomaly
   - candidate explanation
   - classification:
     bug | data artifact | implementation artifact | direction/sign error |
     formula measures avoid-state | tradable anomaly | new factor seed |
     kill signal
   - next test

4. Metric-to-model linkage
   - which metric supports or refutes which layer:
     economic hypothesis, primary model, stochastic benchmark,
     observable estimator, implementation, portfolio expression

5. Financial geometry
   - turnover COGS
   - volatility drag
   - max drawdown
   - recovery days
   - drawdown recovery area
```

**Prompt requirements:**

Update Step6/researcher prompts so LLMs must produce all five subsections. The prompt must explicitly require:

- do not merely restate formula terms;
- infer what market relation must be true if the formula works;
- classify unexpected implications rather than discard them;
- if main model is weak, use T+0/T+1 stochastic benchmark to derive or falsify implications;
- tie every metric back to a model layer;
- propose Council tasks at component level, not only whole-formula level.

**Alpha036-specific examples the prompt should force:**

- `abs(corr(vwap, adv20, 6))` must trigger a direction-loss review.
- A weak positive `RankIC` plus negative high-score long side must trigger anomaly classification.
- Five-term weighted formulas must trigger component ablation and component sign/dimensional consistency review.
- High turnover must trigger cost and volatility-drag review before iteration.

**Validator requirements:**

Add cases:

- `research_report_missing_dirac_audit_blocks`
- `formula_implied_information_raw_formula_restatement_blocks`
- `anomaly_review_missing_classification_blocks`
- `metrics_without_model_layer_linkage_blocks`
- `alpha036_like_report_with_direction_loss_review_passes`

**Acceptance proof:**

Run:

```bash
python3 -m py_compile \
  skills/factor-forge-step6/scripts/run_step6.py \
  skills/factor-forge-step6/scripts/validate_step6.py \
  factor_factory/revision_council/validator.py
python3 scripts/run_factorforge_mechanism_math_v2_smoke.py
python3 scripts/run_factorforge_prompt_contract_smoke.py
python3 scripts/run_step6_intelligence_acceptance.py
```

---

## Task 8: Financial Metrics Upgrade - Volatility Drag And Drawdown Recovery Area

**Objective:** Add missing long-only financial economics metrics so the factor is evaluated like a business, not only as an IC series.

**Boundary:** This task computes diagnostics from Step4/Step5 evidence. It must not change the factor formula, ranking method, or portfolio construction.

**Required metrics:**

```json
{
  "turnover_cogs": "turnover_mean * cost_rate, annualized according to existing policy",
  "volatility_drag": "-0.5 * annualized_volatility^2",
  "gross_profit_proxy": "long_side_annual_return + volatility_drag_adjustment, with sign documented",
  "max_drawdown": "...",
  "drawdown_recovery_days": "...",
  "drawdown_recovery_area": "area between peak NAV and recovery NAV over max drawdown recovery interval",
  "cost_adjusted_drawdown_recovery_area": "same metric on cost-adjusted NAV when available"
}
```

**Drawdown recovery-area definition:**

For the max drawdown event:

```text
peak_date = date where NAV reaches pre-drawdown peak
trough_date = date where drawdown is deepest
recovery_date = first later date where NAV >= peak_NAV, else final available date and mark unrecovered=true
drawdown_recovery_area = sum over [peak_date, recovery_date] of max(0, peak_NAV - NAV_t) / peak_NAV
drawdown_recovery_area_days = number of trading days in that interval
```

Interpretation:

```text
Smaller area means better holder experience. Large area means capital was both deeply and persistently impaired.
```

**Prompt requirements:**

Update Step6 and research-brain prompts so agents must discuss:

- turnover cost as COGS;
- volatility drag as stochastic second-order growth penalty;
- max drawdown as capital impairment;
- recovery days and recovery area as holder-experience/payback metrics.

**Validator requirements:**

Add cases:

- `missing_volatility_drag_blocks_when_nav_available`
- `missing_drawdown_recovery_area_blocks_when_nav_available`
- `unrecovered_drawdown_area_marked_passes`
- `valid_financial_geometry_passes`

**Acceptance proof:**

Run:

```bash
python3 -m py_compile \
  skills/factor-forge-step4/scripts/self_quant_adapter.py \
  skills/factor-forge-step6/scripts/run_step6.py \
  skills/factor-forge-step6/scripts/validate_step6.py
python3 scripts/run_step6_intelligence_acceptance.py
python3 scripts/run_factorforge_production_acceptance_contract_smoke.py
```

---

## Task 9: Council Prompt Upgrade For Composite Formula Revision

**Objective:** Make Council automatically produce component-level revision tasks for composite formulas like Alpha036.

**Boundary:** Council may propose branches and tests. It must not directly promote, write official records, or bypass Step3/4 validation.

**Required Council tasks for composite formulas:**

```text
component_ablation
component_sign_split
direction_loss_review
dimensional_consistency_review
latent_state_independence_review
turnover_smoothing_review
drift_vs_volatility_branch_split
stochastic_benchmark_falsification
```

**Prompt requirements:**

Update Step6/Council prompts so:

- `abs(corr(...))` triggers `direction_loss_review`;
- weighted-sum formulas trigger `component_ablation`;
- mixed time scales trigger `time_scale_consistency_review`;
- high turnover triggers `turnover_smoothing_review`;
- negative long side with positive IC triggers `anomaly_review` and sign/direction branch tests;
- Council must output kill criteria for each branch.

**Validator requirements:**

Add cases:

- `composite_formula_without_component_ablation_blocks`
- `abs_corr_without_direction_loss_review_blocks`
- `positive_ic_negative_long_side_without_anomaly_branch_blocks`
- `valid_alpha036_council_taskbook_passes`

**Acceptance proof:**

Run:

```bash
python3 -m py_compile factor_factory/revision_council/validator.py
python3 scripts/run_factorforge_prompt_contract_smoke.py
python3 scripts/run_step6_intelligence_acceptance.py
```

---

## Task 10: Documentation And Installed Skill Sync

**Objective:** Make repository docs, installed Mac skills, OpenClaw/Bernard skills, and EC2/Humphrey skill copies consistent after the code is reviewed and accepted.

**Boundary:** Do not sync installed skills until tests pass and reviewer accepts the code branch.

**Required docs:**

- `docs/operations/factorforge-alpha101-standard-field-contract.zh-CN.md`
- `docs/operations/factorforge-production-acceptance-report-template.zh-CN.md`
- update `docs/operations/factorforge-dirac-style-research-contract.zh-CN.md`
- update `docs/contracts/step2-contract.zh-CN.md`
- update `docs/contracts/step3-contract.zh-CN.md`
- update `docs/contracts/step4-contract.md`
- update `docs/contracts/step6-contract.zh-CN.md`

**Required installed skill targets after review:**

```text
/Users/humphrey/.codex/skills/factor-forge-step2
/Users/humphrey/.codex/skills/factor-forge-step3
/Users/humphrey/.codex/skills/factor-forge-step4
/Users/humphrey/.codex/skills/factor-forge-step6
/Users/humphrey/.openclaw/workspace/skills/factor-forge-step2
/Users/humphrey/.openclaw/workspace/skills/factor-forge-step3
/Users/humphrey/.openclaw/workspace/skills/factor-forge-step4
/Users/humphrey/.openclaw/workspace/skills/factor-forge-step6
```

EC2/Humphrey production sync must remain branch-aware. Do not force Mac and EC2 branches to be byte-identical if EC2 carries legitimate orchestration glue, but factor computation semantics and skill contracts must match.

**Acceptance proof:**

After reviewer acceptance only:

```bash
diff -qr --exclude='__pycache__' skills/factor-forge-step2 /Users/humphrey/.codex/skills/factor-forge-step2
diff -qr --exclude='__pycache__' skills/factor-forge-step3 /Users/humphrey/.codex/skills/factor-forge-step3
diff -qr --exclude='__pycache__' skills/factor-forge-step4 /Users/humphrey/.codex/skills/factor-forge-step4
diff -qr --exclude='__pycache__' skills/factor-forge-step6 /Users/humphrey/.codex/skills/factor-forge-step6
```

For EC2 sync, record:

```text
repo_sha
branch
installed_skill_diff_status
worker_not_started_unless_explicitly_requested
```

---

## Final Verification Matrix

Before asking for review, run at minimum:

```bash
git diff --check
python3 -m py_compile \
  factor_factory/formula/field_aliases.py \
  factor_factory/formula/evaluator.py \
  factor_factory/formula/parity.py \
  skills/factor-forge-step3/scripts/run_step3.py \
  skills/factor-forge-step3/scripts/run_step3b.py \
  skills/factor-forge-step3/scripts/validate_step3.py \
  skills/factor-forge-step3/scripts/validate_step3b.py \
  skills/factor-forge-step4/scripts/run_step4.py \
  skills/factor-forge-step4/scripts/validate_step4.py \
  skills/factor-forge-step4/scripts/self_quant_adapter.py \
  skills/factor-forge-step4/scripts/qlib_backtest_adapter.py \
  skills/factor-forge-step6/scripts/run_step6.py \
  skills/factor-forge-step6/scripts/validate_step6.py \
  factor_factory/revision_council/validator.py
python3 scripts/run_factorforge_alpha101_standard_field_contract_smoke.py
python3 scripts/run_factorforge_production_acceptance_contract_smoke.py
python3 scripts/run_factorforge_qlib_status_taxonomy_smoke.py
python3 scripts/run_factorforge_step6_evidence_status_smoke.py
python3 scripts/run_factorforge_dirac_research_report_contract_smoke.py
python3 scripts/run_factorforge_performance_smoke.py
python3 scripts/run_factorforge_mechanism_math_v2_smoke.py
python3 scripts/run_factorforge_prompt_contract_smoke.py
python3 scripts/run_step6_intelligence_acceptance.py
```

Optional but recommended if runtime is available:

```bash
python3 scripts/run_factorforge_acceptance_smoke.py
```

---

## Required Review Request Format

When implementation is complete, send reviewer a concise request:

```text
Role: Factor Forge Ultimate 二号 coder / 程序员2号

Scope:
- Alpha101 standard_formula_fields_contract
- Step3B sample-only ownership hardening
- Step4 qlib_native_status taxonomy
- acceptance_summary
- formal artifact top-level acceptance fields
- Step6 backend evidence split
- Dirac-style research report prompt/validator upgrade
- volatility drag and drawdown recovery-area metrics
- composite formula Council taskbook prompts

Changed files:
<list>

Verification:
<commands and PASS summaries>

Negative cases proven:
<list blocker cases>

Not done / intentionally out of scope:
- no raw data cleaning
- no Alpha036 artifact rewrite
- no official promotion
- no worker launch unless separately authorized

Review questions:
1. Do standard field contracts block missing/ambiguous Alpha101 fields early enough?
2. Can Step3B sample outputs still be confused with Step4 formal factor values?
3. Is qlib partial status impossible to misreport as full qlib success?
4. Do Step6 prompts force formula-implied information and anomaly classification instead of generic stochastic prose?
5. Are volatility drag and drawdown recovery-area metrics correctly defined and reported?
```
