# Step3 implementation routes

Read the selected route when generating/reviewing code. Failure returns to Step2 for a semantic decision; it does not authorize trying an unrelated estimator.

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

For implementations that mix pandas and Polars internally, declare the **input** frame type explicitly with `METADATA = {'input_dataframe_backend': 'pandas'}` or `'polars'` (also accepted as `FACTORFORGE_DATAFRAME_BACKEND`). This declaration controls the frames supplied by Step3/4, not the return type. Without it, the runtime infers Polars from imports, annotations and input usage; NumPy `select`, comments and strings do not select Polars. Use an explicit declaration whenever inference is ambiguous. Unknown declarations block execution. pandas and eager Polars return frames are normalized by the stage consumer.
