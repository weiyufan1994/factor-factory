# Within-study research continuity

Read when creating/updating a journal, handing off work or resuming a study.
Ultimate is the single journal writer; reviewers provide separate results.
Use the declared workspace, report/branch/run and selected source versions.

## Keep the question, not just file status

At source intake, save the author's idea and a source-only understanding before
historical retrieval. Distinguish interpretation, reconstruction and new ideas.
At Step2, record the economic hypothesis, selected object, key derivation,
observation map, information time, predictions, rivals and implementation invariants.

After implementation/review, record approximations, exact reviewed files, findings
and subsequent test outcomes. After evaluation, record what was predicted,
observed and still missing; separate signal evidence from account economics.
At Step6, retain the explanation supported by evidence, genuine unknowns,
failed branches, reusable lessons or the reason no lesson is justified.

Choose the next useful action by information gained and cost. A changed mechanism
or estimator returns to Step2; a same-spec defect returns to Step3 and review.
A new loop is not required to demonstrate initiative. Save the current round's
findings before continuing.

## Existing storage and helpers

The journal is `objects/research_journal/research_journal__<report_id>.json`
inside the factor workspace. Its maintained [field guide](research-journal-schema.md)
preserves the historical `producer=factor-forge-researcher`; this is a role
identity, not a requirement to install a separate Skill.

`factor_factory.step6.journal.build_researcher_dossier(report_id, workspace_root=...)`
returns a read-only inventory/preview of existing artifacts. Open the underlying
source when the preview is truncated. It does not author research or prove a run.
The old dossier CLI remains a compatible entry.

At interruption preserve the actual checkout, workspace, stage, current owner,
evidence, concrete blocker and scoped resume point. Record whether a task was
prepared, actually sent, returned, reviewed or failed. Unknown delivery/execution
requires reconciliation. The [code-review flow](local-code-review.md) stores
that coordination in the existing journal; it does not create another state store.

## Experience and limits

Record each prior case actually consulted, the source, applicability and decision
it changed or why it was rejected. A supplied suggestion is not independent
discovery; similarity is not same-factor evidence.

Deposit local lessons through [knowledge maintenance](knowledge-maintenance.md).
No supported new lesson, cold start and a failed retrieval are different outcomes.
The workspace record is not automatic canonical publication. Hosted role-memory
operations remain a separate optional route.

Continuity is durable evidence, not proof that one agent process remained alive.
Keep uncertainty and incomplete outputs visible; a journal cannot turn a planning
run into execution or an author review into independent acceptance.
