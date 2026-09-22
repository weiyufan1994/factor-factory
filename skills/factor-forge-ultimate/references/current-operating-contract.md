# Ultimate current operating contract

This is the shared execution contract, with the ordinary local IS route below.
Read only the mode-specific references selected by [SKILL.md](../SKILL.md).
Hosted/OOS/child contracts remain binding when that mode is active; their
presence in the source tree does not make them local prerequisites.

## Workspace and evidence

Inspect repository status and choose one declared
`factor_research/<factor_id>/<research_id>/` workspace. Validate the manifest and
keep code, Step artifacts, runtime copies, reports, Council and local knowledge
under that workspace. `--proof-output` outside it is invalid. Preserve
`artifact_identity` and `manifest_identity`: factor, report, source type, mode,
branch, run, spec and formula/code/hybrid identity must agree. Use manifest
paths, never latest/glob guesses or another factor's generated implementation.

Source understanding precedes retrieval, which precedes knowledge-informed
formalization. See [source-first advisory](epistemic-advisory-operating-delta-v1.md)
for a new intake. Empty retrieval with truthful provenance is valid; a missing
source overlay is not an empty search. Historical cases remain advisory, not
same-factor evidence. See [research protocol](research-protocol.md) when freezing
records and [knowledge maintenance](knowledge-maintenance.md) at completion.

The frozen economic hypothesis and mathematical object determine measurement,
data and `operator|direct_code|hybrid`; convenience cannot reverse that authority.
Unsupported semantics, identity, timing or parity BLOCK rather than substitute a
runnable template. Family plugins require explicit Step2 structured permission,
never factor names or keywords. Shared clean data and canonical knowledge are
not implicit per-factor write targets.

## Local IS sequence

Use the current checkout's wrapper. It invokes this checkout's Step scripts;
installed scripts or hardcoded remote paths are not substitutes. After Step1/2
and agent-authored research records:

```sh
python3 scripts/run_factorforge_ultimate.py --local-is-only \
  --report-id <report_id> --factor-workspace <factor_workspace> \
  --start-step 3 --end-step 3b
# Step2 reviews actual code/helpers; Step3 fixes; Step2 re-reviews.
# Step3 runs post-review deterministic/parity tests on that exact version.
python3 scripts/run_factorforge_ultimate.py --local-is-only \
  --report-id <report_id> --factor-workspace <factor_workspace> \
  --start-step 4 --end-step 6
```

Use `--start-step 3b` only after Step3A is complete. Do not regenerate reviewed
code just to resume Step4. Internal segmentation preserves the requested full
study scope; it is not a reduced-study request or a new user-approval gate.
A deliberately reduced scope needs the user's instruction.

Before local Step3/3B/4/5, including segmented invocations without Step6, the
wrapper validates existing pre-result state/conjecture/approaches. Step2 may
complete them first. Before Step4 it checks
`objects/research_journal/code_review__<report_id>.json`: real Step2 review of
current spec/code/helpers, closed findings, and later tests of the same files.
Use [local-code-review.md](local-code-review.md) to write/check the record.
Generator self-checks, coder self-review and sample output are not this approval.
For actual handoff, use that reference's journal CLI and real agent-tool sequence.
Read its current owner, findings and bounded resume point after interruption;
unknown delivery/execution results require reconciliation, not automatic retry.

Local scope rejects Host/carrier/OOS/recovery arguments, hosted/child
workspaces and recovery/finalization state. It does not call the Host incident
store or OOS finalizer. Do not invent credentials, deployment or signed receipts
for it. Preserve the study's frozen IS boundary; for current minute research the
existing default IS end is `2025-07-11`, with later data held out. A code-review
PASS does not widen the window or authorize another live retry.

## Step ownership and return paths

| Stage | Owns | Returns when |
|---|---|---|
| Step2 | Canonical source/hypothesis spec and semantic code review | Source ambiguity, unresolved material dispute or changed estimand |
| Step3A | Catalog, field/proxy mapping, Data API and state resolution | Missing/invalid data or unsupported observation map |
| Step3B | Implementation and bounded non-formal sample proof | Spec mismatch, unsafe code, parity/numerical/batch failure |
| Step4 | Formal factor values, metrics, backends and diagnostics | Suspected implementation/spec/data defect; notify Step2/3 |
| Step5 | Evidence-quality gate, case and archive | Invalid/missing/stale Step4 evidence; route defect before rerun |
| Step6 | Evidence interpretation, decision, bounded revision and local lessons | Unresolved evidence, semantic dispute or missing formal authority |

State-dependent laws require catalog-first `state_dependency_contract` and
`state_resolution__<report_id>.json`; daily/no-state factors declare the explicit
no-op resolution. Missing state requires a `data_request_v1` or BLOCK, never a
full-window raw-minute fallback. Transport errors are transport evidence; they
do not establish missing coverage or justify new datamarts. Worker/QA admission
procedures are conditional in [worker/canary](worker-and-canary.md) and the
Data Liaison skill, not ordinary local startup steps.

## Completion and authority

The wrapper owns manifest construction, explicit Step paths, validators after
each stage and fail-fast reporting to
`objects/runtime_context/ultimate_run_report__<report_id>.json`. A failed
validator cannot release worker execution or a ready runtime context. Direct
Step scripts are for bounded debug/repair after identifying the failure, not
normal formal execution; sample/legacy drivers cannot bypass canonical gates.

A completed local run needs its actual wrapper report and native Step evidence.
`proof_semantics=local_is_research_execution` is IS execution, not a signed OOS
certificate, Host assurance or promotion. `--dry-run` must remain `DRY_RUN`,
`formal_proof_eligible=false`, `execution_plan_only`; a smoke is
`contract_smoke_only`. Neither is research completion. Missing protocol evidence
cannot be repaired by a successful wrapper or a hand-written result table.

Keep the long-only mandate: no short-leg/long-short promotion, decile trading or
portfolio/rebalance changes to rescue factor adoption. Freeze evaluation design,
costs, trials and thresholds before metrics. Distinguish signal ordering, absolute
long performance and after-cost relative performance; only `risk_premium`
requires broad bucket monotonicity and Fama–MacBeth as formal obligations.
Default long-side policies are documented in Step6's current contract; they do
not override a study's frozen design or replace a formal certificate.

At a real interruption or terminal outcome, preserve journal findings, exact
remaining action and maintenance status. Local rejection, formal certificate
verdict, Council validity, human approval and canonical promotion are distinct.
Use [Step6](../../factor-forge-step6/SKILL.md) for the applicable decision route.
