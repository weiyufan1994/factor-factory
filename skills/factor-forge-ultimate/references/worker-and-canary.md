# Authorized reduced samples and hosted canaries

Read only when a reduced sample, hosted canary or worker execution is actually in scope.

When the user explicitly authorizes a reduced local sample because formal data
transport is slow or unavailable, keep it outside canonical `objects/`, `runs/`,
`evaluations/` and `archive/`, label it `PROVISIONAL_NON_FORMAL_SAMPLE`, freeze
its dates/formula/label/cost before metrics, hash its inputs and outputs, and
state which eligibility masks, controls and diagnostics are absent. It may
reject a clearly uneconomic implementation or guide runtime repair; it can
never issue formal OOS `ACCEPT` or official promotion.

An authorized reduced sample may exercise the complete non-production
organization closure with
`scripts/run_factorforge_small_batch_canary_closure.py`: require the already
signed seven-role pre-formal organization; dispatch distinct post-execution
Portfolio Manager, Risk Officer and Execution/Capacity sessions; then dispatch
an independent Investment Council with no parent session; and let the Host sign
the terminal certificate. Validate it with
`scripts/validate_factorforge_small_batch_canary_closure.py`. The closed result
set is only `CANARY_REJECT | CANARY_ITERATE | CANARY_BLOCK`; its formal factor
verdict is always `NOT_ISSUED`, and both `production_eligible` and
`official_promotion_allowed` must be false. A completed canary proves workflow
closure and can reject an implementation, but does not satisfy formal Step4-6
or the frozen OOS proof certificate.

When that canary runs on a research worker, use the versioned
`worker_task_spec_v1 -> SSM transport -> remote runner -> worker_command_report_v1`
contract. Preflight the exact instance identity, idle-resource guard, free space
and approved data object; stage code only in an isolated run directory on the
worker data volume; bind the current source bundle or Git identity; and ensure
the launched script places that isolated source root ahead of any machine-wide
`PYTHONPATH`. Never overwrite the worker production checkout or protected
caches. AWS-RunShellScript bootstrap commands must be POSIX `/bin/sh`
compatible unless an explicit shell is invoked. Validate the business report
together with the authoritative SSM command id/status envelope and the declared
side-effect contract. Transport success, an old globally imported runtime, an
external instance stop, or a worker report lacking its transport envelope is
infrastructure evidence only, never a factor verdict. Preserve the bounded
artifacts and stop an on-demand worker after evidence readback.


## Catalog QA admission when applicable

When an approved S3 catalog entry has PIT semantics but lacks a formal QA
receipt, the Host may create a factor-workspace-local catalog admission with
`scripts/build_factorforge_catalog_qa_admission.py`. It must bind the live S3
object identity, parquet schema/date coverage, and zero nulls for every required
factor field before assigning `qa_verdict=ACCEPT`; a stale object identity,
missing statistics, null required field, or uncovered window remains BLOCK.
