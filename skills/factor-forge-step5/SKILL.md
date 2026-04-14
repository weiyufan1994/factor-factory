---
name: factor-forge-step5
description: Step 5 of the Factor Forge pipeline — evaluation, archival, and knowledge writeback. Consumes factor_run_master, computes evaluation summary, archives artifacts, and writes the final factor_case_master for future retrieval and reuse.
---

# Factor Forge Step 5 Skill

## What This Skill Does

Step 5 closes the loop.
It takes the executed factor run, evaluates what happened, archives the result, and writes back reusable knowledge.

## Inputs

- `factorforge/objects/factor_run_master/factor_run_master__{report_id}.json`
- `factorforge/objects/factor_spec_master/factor_spec_master__{report_id}.json`
- `factorforge/objects/data_prep_master/data_prep_master__{report_id}.json`
- `factorforge/objects/handoff/handoff_to_step5__{report_id}.json`

## Outputs

- `factorforge/objects/factor_case_master/factor_case_master__{report_id}.json`
- `factorforge/objects/validation/factor_evaluation__{report_id}.json`
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

## Execution chain

```bash
cd /home/ubuntu/.openclaw/workspace
python3 skills/factor-forge-step5/scripts/run_step5.py --report-id <report_id>
python3 skills/factor-forge-step5/scripts/validate_step5.py --report-id <report_id>
```

## Acceptance

- `factor_case_master` exists
- `final_status` is one of `validated|partial|failed`
- evaluation file exists
- archive directory exists
- archive paths listed are real
- no placeholders remain
