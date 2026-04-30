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
  - prepares normalized local execution snapshots when available
  - should prefer a qlib-friendly contract so later evaluation can reuse qlib operator / strategy / backtest interfaces with minimal reshaping
  - raw aliases may remain (`ts_code`, `trade_date`, `trade_time`), but semantic mapping to qlib-facing keys (`instrument`, `datetime`) must be explicit
  - feature columns are append-only and extensible; later additions such as `pe`, `pb`, `market_cap`, `industry_code`, or custom alpha/risk columns should not require redesign

- **Step 3B — Implementation Planning + Factor Code Generation + First Factor Value Run**
  - consumes Step 2 products directly: `factor_spec_master__{report_id}.json` plus optional `handoff_to_step3__{report_id}.json`
  - inherits Step 2 research context (`thesis`, `research_contract`, `math_discipline_review`, `learning_and_innovation`)
  - chooses execution mode (`direct_python` / `qlib_operator` / `hybrid`)
  - writes `implementation_plan_master`
  - emits editable first-version factor code artifacts for IDE-side refinement
  - embeds `step2_research_context` in implementation plan, code review comments, expression draft, scaffold, handoff, and first-run metadata
  - when Step 3A local snapshots are present, must generate a first runnable factor value artifact (`factor_values`) rather than stopping at a pure planning document

Step 3 does **not** perform the final backtest / evaluation itself. Step 4 remains the execution-diagnostics / run-master layer and Step 5 remains the evaluation / archival layer. But Step 3B must now be strong enough to hand over both code artifacts and a first factor-value output when local execution inputs are already prepared.

## Research Discipline

Step 3 must protect the thesis during implementation:
- Step 3A records the gap between theoretical variables and real data proxies.
- Step 3A reuses the shared clean layer by default; full-history cleaning is not a per-factor task.
- Step 3B records implementation invariants inherited from Step 2.
- Step 3B must not silently reduce Step 2 into only a formula column; it must preserve the target statistic, economic mechanism, expected failure modes, and reuse instructions for future agents.
- Step 3B must flag approximations that change economic meaning.
- Boundary handling, missing values, extreme values, and numerical stability must be explicit.
- First-run factor values prove executability, not research validity; Step4/5/6 still decide whether the signal is worth keeping.

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
- first runnable factor values when Step 3A local snapshots are available:
  - `factorforge/runs/{report_id}/factor_values__{report_id}.parquet`
  - `factorforge/runs/{report_id}/factor_values__{report_id}.csv`
  - `factorforge/runs/{report_id}/run_metadata__{report_id}.json`

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
5. If Step 3A has local execution snapshots, Step 3B must produce a first factor-value run artifact. A plan-only PASS is not enough for business acceptance.
6. Step 3B must carry `step2_research_context` through implementation plan, generated code comments, qlib expression draft, hybrid scaffold, `handoff_to_step4`, and first-run metadata if generated.
7. Step 3B validation must reject `missing_*` Step2 research-context sentinels; rerun Step2 rather than letting old or incomplete specs pass.
8. No silent guessing. Missing critical fields must be surfaced as `blocked` or `proxy_ready` with explicit rationale.
9. Step 3 must reject mixed sample/full execution packages. If minute and daily snapshots have materially inconsistent ticker coverage or sample scope, validation must fail explicitly rather than producing a deceptively small successful run.
10. `report_id` handling must be internally consistent. File naming, JSON internal `report_id`, and handoff artifact references must agree; alias shortcuts must not silently reuse long-id internals without explicit normalization.
11. If a Step 3 or downstream Step 4 run depends on user choices not already fixed in artifacts — e.g. benchmark, topk, n_drop, holding horizon, deal price, account size, cost model, universe filter, or whether to run sample vs wider window — the skill must ask for confirmation before launching execution.
12. Step 3B must not run Step4-style quantile NAV, IC analysis, portfolio charts, or evaluator loops. Step 3B's proof is first-run `factor_values` + metadata only; Step4 owns all metrics, quantile tables, NAV, and plots.
13. Step 3B inputs and outputs must respect the shared data contract: `trade_date` may be read from `YYYYMMDD`, `YYYY-MM-DD`, or Timestamp sources, but outputs should be stable `YYYYMMDD`-compatible keys and Step4 must normalize via `factor_factory.data_access.normalize_trade_date_series`.

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
- when Step 3A local snapshots exist, Step 3B also emits first-run `factor_values` artifacts with non-trivial row count
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
