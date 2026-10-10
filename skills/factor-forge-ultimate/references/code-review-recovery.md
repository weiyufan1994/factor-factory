# Code-review recovery for interrupted or legacy runs

Read this only for a concrete interruption or recording failure. The normal
review → test → Step4 sequence and record shape remain in
[Local code review](local-code-review.md). These repairs preserve the research
version and existing evidence; they do not rerun a producer, approve code or
replace a native validator.

The existing manager is `scripts/manage_factorforge_code_review.py`. All actions
below use the current study's `--workspace-root`, `--report-id`, `--repo-root`
and `--request-id`. Use only the operation matching the observed failure.

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

For a known successful writer blocked **only** by `ARTIFACT_REFERENCE_LIMIT`,
use `recover-artifacts --request-id <id> --step 4|5 --proof <original-failed-wrapper-report.json>
--reference <actual-tool/result-locator>`. This explicitly records a later
artifact capture; it does not execute code or synthesize a command result.
The saved zero-return writer must exactly match the original wrapper failure,
pending invocation and manifest binding. All review/test checkpoints and prior
input versions must remain current. Every declared concrete file is retained;
the JSON-size, directory and finite-count restrictions still apply. A file with
modification or change time after the original command finish blocks recovery,
including an unchanged-byte restore with backdated modification time. Filesystem
timestamps are ordinary change detection, not a substitute for a missing
historical content hash. Output hashes are explicitly captured at recovery time.

Recovery preserves the original command/runtime identity and old failure in
`artifact_recovery_history`, records the recovery module's own path/hash, and
returns the stage to `computed`. A fresh native validator is required before
`complete`; a second recovery, unknown execution, failed writer, changed artifact
or other blocker is refused without changing the journal. The original wrapper
report must be preserved before another wrapper invocation can replace it.

For a frozen runtime whose recorder cannot capture the declared finite set
(the maintained implementation defines the reference cap), use the reviewed
maintenance checkout for this one journal repair and explicitly record its
commit/hash separately. Do not replace a module in the frozen runtime while
claiming its identity is unchanged. The single Ultimate journal owner can then
call the maintenance library's existing `before_command("validate_step5", ...)`
with the original runtime's actual native validator argv/cwd and unchanged
manifest, execute that validator with the original local-IS environment through
the normal tool, and record its actual result with `command-result` from the
maintenance checkout. This avoids both producer replay and old recorder capacity.
After validation succeeds, the original runtime may continue at native Step6.
The recovery tool does not relax native validation, research or promotion gates.

For an actual zero-return writer blocked only by `ARTIFACT_FILE_REQUIRED`, the
same command accepts `--artifact-repair <explicit-repair.json>`. That JSON has
exactly `path` (the declared output payload), `sha256` (its original bytes),
`artifacts` (unchanged existing file roles plus explicit old files inside the
misdeclared directories), and `artifact_directories` (those original directory
roles plus any existing directory metadata). No metrics/status/identity fields,
directory discovery, newly computed files or unrelated file-role changes are
accepted. Every selected file must predate the original writer's finish.

The single journal owner runs the reviewed maintenance script with the original
research `--repo-root`, request and proof; do not change the study's runtime or
manifest. The tool first saves the exact original payload bytes at a create-only
audit path and records a `prepared` attempt, then atomically corrects only the
current payload's two reference fields. History records both versions and the
repair module hashes; actual result files and original failure proof stay intact.
An interrupted attempt remains blocked with its backup and prepared record for
inspection, never a guessed completion or automatic writer retry. Successful
recovery returns `computed`: the unchanged compatible native wrapper reuses the
bound writer result and must run its original native validator before Step5.

An older source archive may have produced `acceptance_summary.repo_sha="unknown"`.
If its original native Step4 validator failed **only** with
`BLOCK_ACCEPTANCE_SUMMARY_REPO_IDENTITY_INVALID`, use the same manager's
`recover-source-version --proof <preserved-failed-wrapper.json> --release-record
<original-assembly.json> --reference <actual-evidence>` (with the existing
workspace/report/request and original `--repo-root`). `--dry-run` is read-only.
The tool verifies that exact archive's inventoried source files, original
commands/runtime, unchanged outputs and the single validator error; it preserves
the old run master and failure before correcting only the unknown source commit.
The original writer stays cached, the failed validator remains in recovery
history, and a fresh original native validator must run. Do not insert the
maintenance tool's commit, create another research review request, or rerun data.

