# Local IS: code review → tests → Step4

This is a compact record in the existing study journal, not a signed receipt or
new approval service. It applies to ordinary `--local-is-only` execution. Hosted
and OOS routes keep their existing behavior. No market data is read by this check.

## Normal sequence

1. Step2 completes the source-faithful spec and agent-authored research records.
2. Run Ultimate through Step3B to produce the implementation and proposed tests.
3. A researcher distinct from the implementer reads the source/spec, actual code
   and invoked helpers; records concrete findings; requests fixes and re-reviews.
4. After `proceed`, run deterministic/parity tests against that reviewed version.
5. Resume Ultimate at Step4. It checks the record before factor execution.

The wrapper does not generate a review or run commands found in the record.
Missing review returns work to the researcher, not to the user for another
routine approval. Code/spec/helper changes require re-review and new tests.
Generator self-checks and pre-review probes are preparation, not acceptance.

## Actual agent handoff and continuation

Ultimate uses `scripts/manage_factorforge_code_review.py` to keep the current
owner, material versions, findings, tool outcomes and resume point under
`research_journal__<report_id>.json` → `code_review_coordination`. The existing
`code_review__<report_id>.json` remains the review/test checkpoint. One Ultimate
agent writes the journal; reviewers write their own result files. This is not a
background dispatcher or an authenticated agent identity service.

Prepare a small input file in the active workspace, using actual paths and the
existing research scope. This illustrative shape is not evidence:

```json
{
  "issue_id": "stable-problem-id",
  "summary": "The concrete implementation question or suspected defect",
  "origin_step": "3b",
  "author_id": "actual-implementer",
  "reviewer_id": "actual-independent-Step2-reviewer",
  "spec": "objects/factor_spec_master/factor_spec_master__R1.json",
  "handoff": "objects/handoff/handoff_to_step4__R1.json",
  "helpers": [{"base": "repo", "path": "factor_factory/actual_helper.py"}],
  "context_files": [
    {"role": "source", "path": "source/actual-source.md"},
    {"role": "notes", "path": "implementation-assumptions.md"},
    {"role": "test", "path": "tests/actual-parity-test.py"}
  ],
  "materials_note": "Actual helper coverage, mapping, assumptions and test oracle",
  "resume": {
    "start_step": "4",
    "end_step": "5",
    "reason": "Reviewed code exists; Step3B must not be regenerated",
    "unusable_evidence": []
  }
}
```

`origin_step` may be `3b`, `4` or `5`. For Step4/5 feedback, name the unusable
outputs and safe replay/history boundary in `resume`; retain failed evidence.
Step2 distinguishes a code/spec/data defect from an empirical result. No weak
return alone authorizes a fix. Declare all invoked helpers, including shared
ones; an empty list needs an honest coverage explanation. A discovered missing
helper means preparing expanded materials and a real re-review. Preparation
does not infer helper completeness or mutate the source/spec.

All actions take `--workspace-root <workspace> --report-id <report_id>` and
optionally `--repo-root <active-checkout>`:

1. `prepare --request-file <input.json>` selects the actual implementation by
   the existing Step4 rules. Same issue/version/roles/resume deduplicates only
   against the active handoff. Returning to historical materials creates a new
   round with `previous_request_id` and `reuses_materials_from`; it never revives
   earlier tests or execution. Changed materials need a new review; previous
   findings and failed test/command evidence remain in the journal.
2. `delivery --request-id <id> --outcome begin --reference <intended-tool-call>`
   records intent **before** invoking the real agent tool. Send only when its
   `send_allowed` is true. Ultimate then calls the available spawn/message tool,
   giving the independent Step2 reviewer the actual source/spec/code/helpers,
   assumptions, tests, request ID and output path. The CLI sends nothing.
3. After the tool returns, record `delivery --outcome sent --reference <actual
   call/result locator>`. A confirmed non-delivery is `failed`; a timeout or lost
   response with unknown delivery is `unknown`. Neither is review evidence.
   Repeated `begin` cannot resend an in-flight/unknown/sent request. Resolve an
   unknown outcome from the tool/channel before changing it; retry a known
   failure only explicitly with `--retry-reason`. If no reviewer is available,
   preserve the failure and exact next action; never self-approve.
4. Reviewer writes the existing review shape below, plus `request_id`, with no
   `post_review_tests`. Ultimate uses `receive --request-id <id> --record <actual
   reviewer-result.json>`. It checks identity labels, dispatch timing and the
   complete material version; labels and hashes do not prove independence or
   semantic quality. Actual invocation and returned work are necessary.
5. `revise` returns ownership to Step3. Fix the identified issue, prepare the
   changed version, and send it for real Step2 re-review with earlier findings.
   A changed hypothesis/estimand remains a research revision, not a routine fix.
   Step2 explains how each earlier finding was resolved or remains open. A
   same-version clarification may receive a new review on the same request;
   `review_history` retains each full review, result path and reviewer-written
   disposition before updating the current review. Repeated receipt of either
   the current or a historical result is a no-op and never rewinds the review.
6. After `proceed`, Step3 runs the applicable tests through its normal tool and
   writes the actual `post_review_tests` object shown below to a file. Use
   `tests --request-id <id> --record <actual-test-result.json>`. This records
   results; it never executes a command found in a journal or result. A failed
   test remains visible and cannot release execution.
7. Read `status` and its `resume`/`remaining_steps`. Only `status=READY` with a
   non-null resume point permits the recorded continuation under existing scope.
   Use Ultimate at that start/end step, preserving the workspace and other
   frozen invocation options. Do not launch from an arbitrary recorded command.

The local wrapper binds a managed handoff to its manifest paths, records actual
Step4/5 command outcomes, and advances only after a stage validator passes.
Known completed commands can be reused from this journal on an explicit resume;
reuse binds the wrapper argv, working directory, runtime manifest (apart from
its creation timestamp), and the necessary declared input/output file versions.
It does not regenerate Step3B. Before a run, bind its inputs; before validation,
bind its inputs and outputs; require these to remain unchanged when collecting
the result. Return code zero without the required actual output files cannot
establish completion.

Artifact checks use the existing manifest and concrete files referenced by the
run/case/backend records. JSON files are content-hashed with an 8 MiB per-file
limit; other files use size, modification/change time and file identity, without
reading bulk data. The check visits at most 256 explicit files, skips aggregate
directory roots and the mutable journal, and never scans a directory tree.
Oversized JSON or directory references block reuse for inspection. File metadata
is ordinary change detection, not cryptographic proof of bulk data or a new data
admission gate; the existing validators and provenance checks still apply.

Missing or changed bound artifacts block `status` and cached command reuse.
`artifact_recovery` names the earliest affected step and exact file reasons.
Inspect or restore the bound versions, or prepare an explicit repair issue at
that step with Step2/Step3; retain failed evidence. Do not reuse the old validator
PASS or automatically recompute. A legacy completed command without artifact
versions also needs reconciliation before reuse.
An interrupted Step4/5 command with unknown outcome is
blocked for reconciliation, never automatically retried. A failed command needs
triage and, for a suspected defect, a new issue/version through the same review
path. Step6 is handed back to its native flow after checking the reviewed
Step4/5 prerequisites. It is never cached as a completed run/validate pair:
Council legitimately archives/removes provisional handoffs, attaches results
to the iteration and resumes its own finalization. `step6_followup` points to
the native wrapper report; a Step6 resume here is a handoff, not a claim that
Step6 is unfinished or finished. Any older Step6 cache is preserved as history
and excluded from continuation decisions. Native Step6 validators, pauses and
Council/terminal state remain authoritative. A legacy manual
checkpoint without this optional coordination field retains its existing check.

If a wrapper session was interrupted, inspect its actual tool/process result.
Only after the outcome is known may `command-result --request-id <id> --record
<actual-command-result.json> --reference <actual-tool/result-locator>` reconcile
the pending Step4/5 command. Step6 results use its native workflow and cannot be
reconciled through this CLI. Both normal result collection and reconciliation
check the saved actual argv, normalized working directory, name, chronology and
known return code. A mismatch records the rejection and keeps the command
pending. This executes nothing. Do not turn an unknown action into a guessed
failure or PASS. A known completed run can resume at its validator; failed
execution remains blocked for triage, with the original outcome retained.

Successful CLI recording may still return `status=BLOCK` (for example, awaiting
review). Exit code zero means the requested journal operation succeeded, not
that review, tests, research, OOS or promotion passed.

## Record

Save `objects/research_journal/code_review__<report_id>.json` in the active
factor workspace. Step2 owns the actual review fields; Step3 appends actual test
evidence afterward. Preserve earlier findings/results in the existing journal.
An existing narrative review may be linked in `summary`, but do not infer a new
approval, version or timestamp from a bare PASS. The following is an illustrative
shape, not runnable evidence; replace placeholders only from real work:

```json
{
  "report_id": "R1",
  "author_id": "implementation-agent",
  "reviewer_id": "step2-researcher",
  "reviewed_at": "<actual timezone-aware ISO8601 time>",
  "decision": "proceed",
  "summary": "Source/spec comparison, mathematical mapping, helpers, findings and conclusion.",
  "findings": [],
  "reviewed_files": [
    {"role": "spec", "path": "objects/factor_spec_master/factor_spec_master__R1.json", "sha256": "<actual file SHA256>"},
    {"role": "implementation", "path": "generated_code/R1/factor_impl__R1.py", "sha256": "<actual file SHA256>"},
    {"role": "helper", "base": "repo", "path": "factor_factory/example_helper.py", "sha256": "<actual file SHA256>"}
  ],
  "post_review_tests": {
    "status": "PASS",
    "started_at": "<actual start, strictly after review>",
    "completed_at": "<actual finish>",
    "tested_files": ["<copy the complete actually tested reviewed_files objects here>"],
    "evidence": [{"path": "logs/R1-acceptance.log", "sha256": "<actual log SHA256>"}]
  }
}
```

Exactly one `spec` and one `implementation` must match the files selected for
Step4. Add every helper actually reviewed, including relevant shared helpers;
remove the illustrative helper only if the implementation has none. Nonempty
`findings` entries contain `summary` and `status: resolved|closed`; open findings
or `decision: revise` block Step4. Distinct agent labels record responsibilities;
they do not authenticate independence. All times are real, timezone-aware and
not in the future; tests start strictly after review.

Spec, helper and log paths are workspace-relative or absolute. A helper with
`base: repo` resolves against the wrapper's active checkout. Implementation
resolution matches Step4: handoff `factor_impl_ref`, then `factor_impl_stub_ref`,
then `implementation_path`; missing/placeholder selection falls back to spec
`canonical_spec.implementation_path`, then spec `implementation_path`.
`generated_code/…` is workspace-relative; other relative implementation paths
are relative to the workspace's parent. Prefer an explicit absolute path for
external code. Do not select a different file because the first one is absent.

SHA256 here only detects stale versions. The checker verifies current files,
the entire tested/reviewed file-set equality, timestamps and existing nonempty
test logs; it cannot prove that tests ran, review quality or helper completeness.
The responsible agents must ensure those facts. PASS is not factor validity.

## Bug recovery

Step4 notifies both Step2 and Step3 through the existing task channels, records
the failure and pauses affected work. Step3 reproduces/fixes; Step2 checks the
spec and corrected code; post-review regression tests must pass. Resume only
the affected work from an appropriate clean state/history, retaining failed
results and marking them unusable. A weak return is not itself a bug. Neither
this record nor a successful toy replay authorizes a live retry or wider window.
