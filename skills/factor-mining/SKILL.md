---
name: factor-mining
description: Factor Mining / 挖因子 alias for the Factor Forge V2 research workflow. Use when the user says 挖因子, factor mining, 因子挖掘, asks to mine factors from an attached PDF research report, or asks Humphrey to run Factor Forge V2 dry-run or worker flow.
---

# Factor Mining

This is an alias skill for Factor Forge V2. It does not define a separate
pipeline. It routes short user commands like "挖因子" to the controlled Factor
Forge V2 workflow.

## Default Meaning

When the user says "挖因子" / "factor mining" and provides an attached PDF or
explicit new report source, treat it as:

```text
FactorForge V2 dry-run: 使用附件 PDF
```

Follow `docs/operations/factorforge-openclaw-runtime-v2.zh-CN.md`, especially
the "固定口令" section.

## Required Boundary

- Use only the current attachment / explicitly supplied new report as the source.
- Do not use repo fixtures, especially `fixtures/step1/kakushadze_101_formulas.pdf`,
  unless the user explicitly asks for a smoke test.
- Do not use old `/tmp` roots, old artifacts, old report ids, or old SSM/S3
  evidence in place of the active registry.
- Do not `show`, `find`, `grep`, or scan artifact roots to recover from a
  failed step. Recovery must start with `factorforgectl.py recover-block`.
- Do not call `prepare_factorforge_formal_artifacts.py` directly during factor
  mining. Formal writes are only valid when launched by `factorforgectl.py`.
- Do not use `sessions_spawn` or a sub-agent to produce Step1/Step2 raw JSON.
  Raw artifacts must come from the controlled PDF tool / formal LLM bridge and
  pass provenance validation.
- Step1 must use OpenClaw `tools.pdf` and then `resume-step1`.
- After `resume-step1`, Step1 raw SHA records are immutable control evidence.
  If any Step1 raw JSON changes before Step2, `run-local --start-step 2` must
  block with `BLOCK_AGENT_TOOL_STEP1_RAW_TAMPERED`; start a fresh run instead.
- Step2/3A must use `--formal-llm-provider command` by default, not `fixture`.
- Step2 `direct_code` must be semantically faithful, not merely schema-valid.
  If a formula says past `N=20` valid trading days / rolling lookback, full-history
  `rank().over('ts_code')`, full-history `count().over('ts_code')`, overlapping
  top/bottom buckets, or singleton `(ts_code, trade_date)` aggregation must block.
- `run-local` may only run `1->1`, `2->2`, or `3a->3a`. Never call
  `2->3a` or any other combined host-side range. After each completed host-side
  step, report the proof/verdict and wait for explicit user approval before the
  next host-side step.
- Never call
  `run-local --end-step 6`; Step6 requires completed worker Step3B/4/5 evidence
  and a separate post-worker authorization path.
- Stop at worker dry-run unless the user separately authorizes real worker
  execution.
- Real Step6 must enter through `factorforgectl.py run-step6` after Step5
  evidence exists in the active artifact root. Do not trigger Step6 by scanning
  old artifacts or by calling `run-local --end-step 6`.

## Executor Mode

During factor mining, Humphrey is an executor, not a free-form investigator.

After any `BLOCK`, tool failure, path-read failure, or preflight failure:

```bash
python3 scripts/factorforgectl.py recover-block --report-id <report_id>
```

Then follow only `allowed_next_commands` from the JSON output. Do not inspect
deprecated roots, do not patch registry or artifacts, do not skip preflight, and
do not use `--allow-deterministic-debug` in production factor-mining.

If `recover-block` reports identity mismatch, old SHA, missing active manifest,
or missing runtime_context, report that diagnosis to the user and wait for fresh
run authorization.

## If No PDF Is Provided

Ask the user for the PDF/report source. Do not substitute a fixture or previous
artifact.

## Real Worker Authorization

When the user says to continue to the research machine for a dry-run-passed
case, treat it as:

```text
FactorForge V2 worker: <report_id>
```

Only use the same `report_id/run_id/artifact_root` that passed dry-run, and only
run Step3B/4/5 on the worker. Once the user authorizes real worker execution,
the worker may run Step3B/4/5 continuously as `3b->5`; it does not need to stop
between worker-internal steps. After worker Step5 finishes, Step6 may run
locally through the controlled post-worker command below; it is not part of
`run-local`, and it still requires a new user approval after the worker report.

If the worker is stopped, the agent may start it with
`factorforgectl.py start-worker --poll` before sync/run. After the worker run
finishes, do not stop the worker automatically. Report proof and wait for the
user to accept the result. Only after explicit user acceptance may the agent run
`factorforgectl.py stop-worker --after-user-acceptance --poll`.

## Post-Worker Step6

When Step3B/4/5 has completed and the active artifact root contains
`factor_run_master`, `factor_case_master`, `factor_evaluation`, and
`handoff_to_step6`, use:

```bash
python3 scripts/factorforgectl.py run-step6 --report-id <report_id> --council-mode auto
```

Step6 is allowed to update economic hypothesis, math mechanism, and
`research_iteration_master`. If it proposes a Step3B revision, treat that as an
approval-gated revision proposal, not permission to edit generated code or
handoffs directly. Continue only through the contracts emitted by Step6/Council.
