---
name: factor-forge-step4
description: Step 4 of the Factor Forge pipeline — factor implementation, execution, and diagnostics. Consumes data_prep_master and factor_spec_master, runs the factor construction, writes factor_run_master plus execution diagnostics, and prepares evaluation handoff for Step 5.
---

# Factor Forge Step 4 Skill

## What This Skill Does

Step 4 is the **execution + evaluation orchestration layer**.
It keeps the existing execution shell (input validation, run-status discipline, artifact writeback), but upgrades the old single-path runner into a backend-driven evaluation framework.

Concretely, Step 4 now does three things:
1. executes or loads the factor-value result prepared by Step 3 / implementation code
2. dispatches one or more evaluation backends
3. writes a unified run envelope plus backend-specific result payloads

Current intended backend structure:
- `self_quant_analyzer` for lightweight / quick factor checks
- `qlib_backtest` for more standard portfolio / backtest workflows
- future custom evaluators without forcing a fixed metric schema

Current practical backend maturity:
- `self_quant_analyzer` quick mode is production-usable on the current EC2 resource envelope
- `qlib_backtest` now has both a sample-stub layer and a native minimal backtest path; native execution depends on qlib-friendly signal formatting, especially `instrument` / `datetime` semantics

## Inputs

- `factorforge/objects/factor_spec_master/factor_spec_master__{report_id}.json`
- `factorforge/objects/data_prep_master/data_prep_master__{report_id}.json`
- `factorforge/objects/handoff/handoff_to_step4__{report_id}.json`

## Outputs

- `factorforge/objects/factor_run_master/factor_run_master__{report_id}.json`
- `factorforge/objects/validation/factor_run_diagnostics__{report_id}.json`
- optional factor values / parquet / csv under:
  - `factorforge/runs/{report_id}/`
- optional backend-specific evaluation artifacts under:
  - `factorforge/evaluations/{report_id}/{backend}/`
- `factorforge/objects/handoff/handoff_to_step5__{report_id}.json`

## factor_run_master schema

```json
{
  "report_id": "string",
  "factor_id": "string",
  "run_status": "success|partial|failed",
  "implementation_path": "string",
  "output_paths": ["string"],
  "sample_window": {"start": "string", "end": "string"},
  "runtime_notes": ["string"],
  "diagnostic_summary": {
    "row_count": 0,
    "date_count": 0,
    "ticker_count": 0
  },
  "evaluation_plan": {
    "backends": [{"name": "string", "mode": "string"}],
    "metric_policy": "extensible"
  },
  "evaluation_results": {
    "backend_runs": [
      {
        "backend": "string",
        "status": "success|partial|failed|skipped",
        "summary": {},
        "artifact_paths": ["string"],
        "payload_path": "string|null"
      }
    ]
  },
  "failure_reason": "string|null"
}
```

## Core rules

1. Step 4 must produce a real on-disk run artifact or fail explicitly.
2. If execution fails, write `run_status=failed` plus exact failure reason.
3. If only part of the window runs, mark `partial`.
4. Diagnostics are mandatory even on failure.
5. Evaluation backend selection must be explicit or defaulted in a visible way; it must not be silently hard-coded into a single metrics regime.
6. Step 4 must allow multiple evaluation backends over time (`self_quant_analyzer`, `qlib_backtest`, future custom evaluators).
7. Metric schemas must remain extensible: Step 4 standardizes the envelope, not a frozen universal metric list.
8. No polished prose counts as completion.
9. If execution depends on user-selectable run parameters not already frozen in handoff/artifacts — e.g. benchmark, account size, topk, n_drop, deal price, cost model, universe, sample vs wider window, or whether to run quick-only vs deeper/native backtest — the skill must ask and confirm before launching the run.
10. qlib-native evaluators must treat signal formatting as a first-class contract item; if `instrument` / `datetime` naming or market-code normalization is unresolved, the run should be marked blocked rather than silently coercing inconsistent semantics.

## Execution chain

```bash
cd /home/ubuntu/.openclaw/workspace
python3 skills/factor-forge-step4/scripts/run_step4.py --report-id <report_id>
python3 skills/factor-forge-step4/scripts/validate_step4.py --report-id <report_id>
```

## Repository alignment note

Current repository reproducibility docs for Step 4 live at:
- `docs/contracts/step4-contract.md`
- `docs/reproducibility/step4-gap-card.md`
- `scripts/run_step4_sample.sh`

Treat those files as the authoritative current repo-level reproducibility notes when deciding whether Step 4 is merely skill-visible or Bernard/Mac reproducible-level.

## Acceptance

- `factor_run_master` exists
- `run_status` is one of `success|partial|failed`
- output paths exist when run_status is success/partial
- diagnostics file exists
- handoff_to_step5 exists
- `evaluation_plan` is explicit in the run envelope
- `evaluation_results.backend_runs` exists even if some backends are skipped
- backend-specific payload paths are real when a backend claims success/partial
- no placeholders remain
