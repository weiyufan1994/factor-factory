---
name: factor-forge-step3
description: Bind Factor Forge specifications to governed data and implementation. Step3A resolves data/state contracts; Step3B produces code and bounded sample proof, then returns it for Step2 review before Step4.
---

# Factor Forge Step3

Step3 implements the mathematical object frozen by Step2. It does not infer a
new economic mechanism or rescue results. Step3A owns data/field/proxy/state
contracts; Step3B owns implementation and bounded non-formal sample proof.
Step4 owns full execution, formal factor values, metrics, backtests and charts.
Use the selected checkout's Ultimate wrapper and manifest-bound workspace.

## Step3A: measurement to available data

Consume `factor_spec_master`, `alpha_idea_master` and the Step3 handoff. Resolve
the approved Data API catalog before paths; bind fields, units/semantics,
availability times, coverage, sample scope, proxies and qlib-facing
`instrument`/`datetime` mappings. Additional features may extend this mapping.
Missing exact data returns to Step2/Data Liaison for explicit proxy-error review,
a data request or BLOCK. Never let a convenient proxy change the estimand.

State-dependent factors declare `factorforge_state_dependency_contract_v1` and
write `state_resolution__<report_id>.json`. A missing/not-ready datamart produces
`data_request_v1`, not a raw-minute scan. No-state factors explicitly declare
`no_state_required=true`. Minute-derived contracts bind cutoff time, data/schema/
producer version, coverage and artifact identity. Keep the frozen study window;
the existing minute-research IS default ends `2025-07-11`.

Write `data_prep_master`, `qlib_adapter_config`, feasibility validation and the
Step4 Data API contract. A blocked Step3A clears stale readiness, generated-code
and sample-output refs rather than retaining an earlier `step3b_ready=true`.
Do not mix incompatible minute/daily scopes. Normalize dates through the shared
contract, not factor-specific parsing. Standard derived fields need explicit
source fields, unit/lookback/leakage policy and `clean_data_mutation=false`;
Step3B/4 must not independently guess derivations.

## Step3B: implement the selected object

Use the mechanism-selected `operator|direct_code|hybrid` route. An unsupported
operator, invalid boundary, missing alias, unsafe code or failed parity returns
for correction or BLOCK; it does not authorize a convenient alternate factor.
Formula-IR uses pandas-reference parity and an explicit qlib supported/unsupported
bridge. Direct code and hybrid remain first-class for methods outside the operator
catalog. Family plugins require explicit structured Step2 permission.

Carry `step2_research_context` and `implementation_mode_decision` through plan,
code metadata/comments, expression/scaffold, handoff and sample metadata. Preserve
target statistic, economic mechanism, failure modes, reuse guidance and invariants;
`missing_*` sentinels are failures. Numerical conventions, missing/zero behavior,
readiness and approximations must be explicit. Any change in economic/mathematical
meaning returns to Step2 before implementation proceeds.

Canonical Step3 scripts are templates, not per-factor scratchpads. Formal entry
creates/re-executes their copies under
`<factor_workspace>/step3_runtime/<report_id>/`; factor-specific changes belong in
specs, reviewed local runtime/code artifacts or versioned law/data contracts.
Do not edit shared runners for one factor or reuse another factor's generated code.

With a Step3A sample-query contract and runnable code, produce only bounded
`step3b_sample_factor_values` plus metadata:
`is_formal_factor_values=false`, `purpose=step3_executability_proof`,
`formal_factor_values_owner=Step4`. Record a reason if a sample cannot run; a
plan-only PASS is not completed executability evidence. No full-window fetch,
formal `factor_values`, IC/NAV/chart/evaluator loop belongs in Step3B.

## Researcher review and release

Send Step2 the frozen source/spec/measurement program, code and invoked helpers,
code-to-math mapping, numerical assumptions and proposed deterministic/parity
checks. Use the existing journal/handoff to identify the exact version and
concrete questions. The reviewer is distinct from the implementer.

The order is code → Step2 review → Step3 fixes → Step2 re-review → acceptance/
parity tests → Step4. Generator self-checks and defect probes may prepare the
work but cannot serve as approval. Rerun applicable tests on the reviewed version.
A behavior-changing edit reopens review. For ordinary local IS stop Ultimate at
Step3B, then resume at Step4 after the version-bound checkpoint passes; do not
regenerate Step3B and reuse the old approval.

When Step4/5 reports a suspected defect, respond through the existing channel to
both execution and Step2. Reproduce the smallest useful case, propose a spec-based
regression oracle and repair within the existing factor scope. Step2 reviews any
semantic change and re-reviews corrected code before new tests. Identify affected
outputs/state and a safe restart point; recursive errors may require clean history
replay. Retain failed evidence. Do not change hypothesis, sign, window, universe,
thresholds or trading policy to rescue metrics, or repeat live actions beyond scope.

## Conditional references

| Task | Read |
|---|---|
| Bind/check input or output artifacts | [Input](references/input-contract.md), [output](references/output-contract.md) |
| Data API/qlib field mapping | [Data contract](references/step3a-data-api-contract.md) |
| Selected operator/direct-code/hybrid route | Relevant section of [implementation routes](references/implementation-routes.md) |
| Sparse/event, recursive or partitioned estimator | [Numerical semantics](references/numerical-semantics.md) |
| Large data, batching, engine/profile options | Relevant section of [performance and batching](references/performance-and-batching.md) |
| Existing approved child revision | [Child revisions](references/child-revisions.md) |
| Local code-review record/release | [Ultimate review checkpoint](../factor-forge-ultimate/references/local-code-review.md) |
| Debug/reproducibility check | [Current checklist](references/execution-checklist-v2.md) and [repository contract](../../docs/contracts/step3-contract.md) |

For large intraday inputs require a bounded batch plan: memory, partitions,
columns, pushdown, lookback/state, checkpoint and parity sample. OOM/exit 137/
Killed is a design failure requiring that plan or
`BLOCK_MEMORY_PRESSURE_BATCH_REQUIRED`, not a blind retry. Experimental engines
need explicit experiment scope; ordinary production keeps the current reviewed
pandas/NumPy path and reference parity.

Use existing frozen/user-authorized choices. Ask only for a material unresolved
choice such as a new data window, proxy, benchmark or cost policy that cannot be
resolved from current authority; ordinary implementation decisions need no new
approval. Validators check identities/readiness and exact paths; researchers
judge semantics. Release needs both, plus actual post-review passing tests.
