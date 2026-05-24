> [中文版本](step3-contract.zh-CN.md)

# Step 3 contract

## Current judgment
Step 3 now has a first tiny committed reproducibility substrate design, but it is more demanding than Step 1/2 because current validation requires local input snapshots and Step 3B must emit first-run outputs when they exist.

## Current committed reproducibility inputs
- `fixtures/step3/factor_spec_master__sample.json`
- `fixtures/step3/alpha_idea_master__sample.json`
- `fixtures/step3/minute_input__sample.csv`
- `fixtures/step3/daily_input__sample.csv`
- `fixtures/step3/factor_impl__sample.py`

## Current committed sample runner
- `scripts/run_step3_sample.sh`
- `scripts/run_step3_sample.py`

## Input class
- `factor_spec_master__{report_id}.json`
- optional `handoff_to_step3__{report_id}.json`
- Step2 research fields: `thesis`, `research_contract`, `math_discipline_review`, `learning_and_innovation`
- `alpha_idea_master__{report_id}.json`
- tiny local minute/daily sample inputs
- runnable implementation file for Step 3B first-run generation

## Output class
- `data_prep_master__{report_id}.json`
- `qlib_adapter_config__{report_id}.json`
- `implementation_plan_master__{report_id}.json`
- generated/editable code artifacts
- first-run factor-value outputs
- `handoff_to_step4__{report_id}.json`

## Step3B / Step4 Boundary
Step3B only proves that the implementation can produce first-run `factor_values` from the prepared local snapshot. Step3B must not run Step4 responsibilities:
- no IC report,
- no quantile NAV,
- no portfolio charts,
- no backend evaluation.

Those belong to the standard Step4 evaluator. If Step3B times out while computing quantile tables, backtest charts, or portfolio diagnostics, treat it as a workflow-boundary error rather than a factor-implementation failure.

## Date-Key Standard
Step3A / Step3B / Step4 boundaries must tolerate:
- `YYYYMMDD` strings,
- `YYYYMMDD` integers,
- `YYYY-MM-DD` strings,
- pandas Timestamp values.

Step4 consumers must normalize dates with `factor_factory.data_access.normalize_trade_date_series()` instead of letting each factor script define its own parsing convention.

## Step 2 research context carry-through
Step 3B directly consumes Step 2's factor spec and handoff. It must write a consistent
`step2_research_context` into the implementation plan, qlib expression draft, hybrid scaffold,
Step4 handoff, generated code review comments, and first-run metadata when generated. The
context must preserve at least target statistic, economic mechanism, expected failure modes,
reuse instructions, and implementation invariants so Step4/5/6 evaluate the implemented thesis
rather than an isolated numeric column.

## Implementation and factor identity isolation
Formal Step3B must consume a runtime manifest with `manifest_identity` and explicit paths. It must reject path guessing, latest-mtime selection, and cross-report or cross-factor reuse. The `artifact_identity` chain must match from `factor_spec_master` to `implementation_plan_master`, generated code metadata, and `handoff_to_step4` on `report_id`, `factor_id`, `source_type`, `implementation_mode`, `contract_version`, `spec_hash`, and `branch_id`.

Allowed implementation modes are `operator`, `direct_code`, and `hybrid`. A mode mismatch, stale `spec_hash`, wrong branch, copied factor-specific generated code, or missing manifest identity is a contract failure.

## Implementation mode decision audit trail
Step3B must write `implementation_mode_decision` to `implementation_plan_master`, generated-code metadata, `handoff_to_step4`, first-run metadata when generated, and the ultimate proof summary. The decision record must use `factorforge_implementation_mode_decision_v1`, state the selected mode or `blocked`, record operator/hybrid/direct_code attempts or explicit not-applicable reasons, and preserve the final correctness reason. If the selected mode is `blocked`, Step3B must not write formal factor values.

## Correctness over completion
Step3B must try `operator`, then `hybrid`, then `direct_code`, and BLOCK if correctness cannot be proven. UBL/CPV/shadow/candle/Williams logic is allowed only as an explicit family plugin or fixture. Unsupported operator parity, missing `formula_ir`, unsafe direct code, or ambiguous proxy rewrites are BLOCK conditions, not warnings.

## Operator / Qlib engine
Operator mode is a Formula IR execution path, not a label. Step3B must consume `formula_ir`, verify `parse_status=success`, confirm all operators are registered, resolve required fields against the Step3A schema, generate a pandas `compute_factor`, and validate it against the pandas reference evaluator. Generated metadata must include `implementation_source=formula_ir_pandas_codegen`, `formula_hash`, `operator_set`, `required_fields`, `resolved_fields`, `code_hash`, and qlib bridge status.

The qlib expression bridge must declare supported or unsupported operators explicitly. Unsupported qlib operators may not be approximated. Parser failures, unsupported operators, missing aliases, code-hash mismatch, or parity failure must BLOCK and must not produce formal factor values.

## Hybrid execution engine
Hybrid mode is a bounded composition: Formula IR operator subgraph plus one or more declared custom Python blocks. Step3B must validate the operator subgraph with pandas reference parity, scan custom source with the direct-code leakage rules, verify `formula_hash`, `custom_block_hash`, and `hybrid_hash`, and validate the boundary before writing ready artifacts.

Generated hybrid code must expose separate operator and custom sections using `FACTORFORGE_OPERATOR_SUBGRAPH` and `FACTORFORGE_CUSTOM_BLOCK` markers. Custom blocks cannot overwrite protected operator outputs unless `allow_operator_output_overwrite=true`; unsafe or unsupported hybrid contracts must BLOCK.

## Direct-code and custom-block performance policy
Step3B must build `factorforge_high_speed_code_profile_v1` for `direct_code` implementations and hybrid custom blocks. Generated code should prefer vectorized NumPy and/or Polars; pandas vectorized APIs are acceptable as a compatibility or reference layer. Python row loops, `DataFrame.apply(axis=1)`, `groupby.apply`, and `rolling.apply` are slow-pattern risks and require `allow_slow_patterns=true` plus a non-empty performance justification in the relevant code contract or custom block. Unjustified slow patterns must BLOCK before fixture smoke or ready-artifact write.

## Family plugin boundary
Family-specific code such as UBL, CPV, shadow candlestick, candle, or Williams logic must live behind the `factor_factory.factor_families` registry. Step3B may execute it only when Step2 explicitly declares `factor_family`, `family_plugin`, `family_plugin_allowed=true`, and a `factorforge_family_plugin_decision_v1` record with non-free-text evidence. `factor_id`, formula prose, or thesis keywords may suggest human review, but must never trigger a plugin.

## Reproducibility warning
Step 3 tiny reproduction currently relies on a thin wrapper that installs fixture files into the runner-expected object and local-input paths, because the existing Step 3 scripts are built around that object contract.
