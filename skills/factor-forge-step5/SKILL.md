---
name: factor-forge-step5
description: Step 5 of the Factor Forge pipeline — evaluation, archival, and knowledge writeback. Consumes factor_run_master, computes evaluation summary, archives artifacts, and writes the final factor_case_master for future retrieval and reuse.
---

# Factor Forge Step 5 Skill

## What This Skill Does

Step 5 closes the loop.
It takes the executed factor run, evaluates what happened, archives the result, and writes back reusable knowledge.

Step 5 preserves the exact upstream
`mechanism_conditioned_measurement_program` from Step 2 and records a compact
reference to its selected mathematical object, estimand, observation map and
market-outcome projection in `math_discipline_review`. It must not redo
mechanism inference or use mathematical explanation as a substitute for Step4/5
long-side evidence, provenance, or prewrite gates. Legacy
`mechanism_math_contract` objects are carried only when already present.

## Research Discipline

Step 5 is not just file archiving. It must compress Step4 evidence into a reusable case:
- which evidence is strong enough to reuse,
- which evidence is weak or should not be over-interpreted,
- where the factor seems to work or fail by regime, universe, turnover, or cost,
- what Step6 should inspect before deciding promote / iterate / reject,
- what future agents should learn from this case even if it failed.
- whether Step4 evidence itself is malformed, missing required artifacts, or implausible enough to indicate an execution/evaluator bug.

Lessons should not be generic status lines. They should be useful retrieval hooks for later factor research.

## Inputs

- `factorforge/objects/factor_run_master/factor_run_master__{report_id}.json`
- `factorforge/objects/factor_spec_master/factor_spec_master__{report_id}.json`
- `factorforge/objects/data_prep_master/data_prep_master__{report_id}.json`
- `factorforge/objects/handoff/handoff_to_step5__{report_id}.json`

## Outputs

- `factorforge/objects/factor_case_master/factor_case_master__{report_id}.json`
- `factorforge/objects/validation/factor_evaluation__{report_id}.json`
- `factorforge/objects/handoff/handoff_to_step6__{report_id}.json`
- archive directory:
  - `factorforge/archive/{report_id}/`

## factor_case_master schema

```json
{
  "report_id": "string",
  "factor_id": "string",
  "final_status": "validated|partial|failed",
  "evaluation_summary": {
    "artifact_ready": true,
    "row_count": 0,
    "date_count": 0,
    "ticker_count": 0
  },
  "math_discipline_review": {
    "information_set_legality": "explicit_lag_or_delay_documented|requires_researcher_confirmation_no_forward_leakage|illegal_potential_forward_reference",
    "spec_stability": {},
    "signal_vs_portfolio_gap": "string",
    "overfit_risk": ["string"]
  },
  "lessons": ["string"],
  "archive_paths": ["string"],
  "next_actions": ["string"]
}
```

## Core rules

1. Step 5 does not fake evaluation if Step 4 failed.
2. Archive whatever is real: success artifact, partial artifact, or failure artifact.
3. Write lessons and next actions explicitly.
4. Final status must match real outputs.
5. Step 5 must emit `math_discipline_review` so Step6 can judge information-set legality, spec stability, signal/portfolio gaps, and overfit risk before promotion.
6. `information_set_legality=illegal*` is a hard BLOCK. `requires_researcher_confirmation_no_forward_leakage` is a WARN that Step6 must resolve before official promotion.
7. Step 5 must run a Step4 quality gate before archive/close. If required Step4 metrics/plots are missing, non-finite, internally inconsistent, or obviously implausible, Step5 must set `final_status=failed`, record the suspected bug, and instruct a Step4 rerun instead of passing evidence to Step6.

## Execution chain

```bash
cd /home/ubuntu/.openclaw/workspace
python3 repos/factor-factory/scripts/build_factorforge_runtime_context.py --report-id <report_id> --write
python3 repos/factor-factory/scripts/run_factorforge_ultimate.py --report-id <report_id> --start-step 5 --end-step 5
```

Direct `run_step5.py` / `validate_step5.py` commands are developer-debug only and are blocked for formal writes by default. Official agent-led runs must use `scripts/run_factorforge_ultimate.py` so Step5 consumes exactly the Step4 outputs declared by the orchestrator and emits an `ultimate_run_report__<report_id>.json` proof.

## Repository alignment note

Current repository reproducibility docs for Step 5 live at:
- `docs/contracts/step5-contract.md`
- `docs/reproducibility/step5-gap-card.md`
- `scripts/run_step5_sample.sh`

Treat those files as the authoritative current repo-level reproducibility notes when deciding whether Step 5 is merely skill-visible or Bernard/Mac reproducible-level.

## Acceptance

- `factor_case_master` exists
- `final_status` is one of `validated|partial|failed`
- evaluation file exists
- archive directory exists
- archive paths listed are real
- no placeholders remain
- `math_discipline_review.information_set_legality` exists and is not illegal
- `math_discipline_review.spec_stability`, `signal_vs_portfolio_gap`, and `overfit_risk` exist
- validator output uses `PASS|WARN|BLOCK`
- `step4_quality_gate` exists in both `factor_evaluation` and `factor_case_master`
- a blocking Step4 quality gate forces `final_status=failed`
## Implementation and Factor Isolation Discipline

- Every formal factor artifact must carry `artifact_identity`.
- Every formal run must carry `manifest_identity`.
- `implementation_mode` is restricted to `operator`, `direct_code`, or `hybrid`.
- Artifacts must not be reused across mode, factor, report, branch, or run unless identity/hash lineage matches explicitly.
- Formal execution must consume manifest-specified paths only; do not pick files by `glob`, mtime, or "latest" guesses.
- If `report_id`, `factor_id`, `source_type`, `implementation_mode`, `branch_id`, `spec_hash`, or formula/code/hybrid hash does not match, BLOCK.
- Direct generated implementation files belong to one factor identity; shared helpers may be reused, factor-specific generated code may not be silently copied.

## Correctness Over Completion

Step5 must reject invalid or stale evidence. Case records must preserve strict `artifact_identity`, evidence identity, branch/run provenance, and long-only risk-adjusted evidence before any validated conclusion.

## Provenance Strengthening

- No provenance, no archive: `factor_case_master` must carry `artifact_identity`, `evidence_identity`, `implementation_mode_decision`, `source_evidence_refs`, and `evidence_quality`.
- No evidence identity, no case close: validated Step5 requires strict identity match to `factor_run_master`, successful Step4 backend evidence, self-quant long-side evidence, and mode-decision provenance.
- Similar-case evidence is not same-factor evidence. Step5 may preserve analogies, but it must not treat another factor/report/branch/run as this case's evidence.
- Downstream Step6 promotion is allowed only when Step5 records `identity_chain_verified=true` and long-only risk-adjusted metrics are present.
- The provenance gate runs before `archive_artifacts()`. If identity/evidence/mode-decision quality is incomplete, Step5 may write only a failed case plus `objects/validation/step5_prewrite_block__<report_id>.json`; it must not archive or hand off a validated-looking case.
