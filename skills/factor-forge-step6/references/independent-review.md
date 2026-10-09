# Independent Step6 research review

Read when requesting or performing independent review. Use a genuinely distinct
researcher context; a different role label in the author's context is not
independence. If unavailable, retain author analysis and the explicit gap.
Ordinary IS review does not require Host identity or a signed receipt.

## Give the reviewer sufficient raw evidence

Provide the task and frozen source/spec/measurement program, actual reviewed
implementation, Step4/5 tables and plots, evaluation assumptions and relevant
journal history. Identify the workspace, version, permitted data and review
output path. The reviewer inspects underlying evidence, not just the author's
summary or a builder's PASS.

`factor_factory.step6.packets.build_researcher_packet(report_id, workspace_root=...)`
returns an inventory/preview of existing material. The journal dossier is in
`factor_factory.step6.journal`. These helpers do not perform review and may
truncate previews; open original evidence as needed.

For a declared blind route, use the designated packet/approach visibility rules.
Do not add the author's desired answer, hidden results or other forbidden
context. Prior exposure remains visible; corrective replay is not a fresh blind test.
A frozen EVO pre-OOS task uses its purged-IS packet, not the normal post-Step5 dossier.

## Questions to resolve

The reviewer independently assesses:

- Whether the subject and code actually match the frozen source and hypothesis.
- Whether the object, derivation and observation map imply the tested prediction.
- Whether metrics/charts are trustworthy and distinguish material alternatives.
- What survives at the information layer and at the after-cost account layer.
- Which explanation is supported, contradicted or unidentified.
- Whether the next bounded question is worth its complexity and cost, or stop is better.

Select the relevant diagnostics; do not manufacture a payer, branch or new idea.
A novel estimator/model returns to Step2 induction before implementation.
A same-spec bug returns to Step3 and a new review/test cycle.

## Deliver and resume

Write a substantive memo at
`objects/research_iteration_master/researcher_memo__<report_id>.json` using
the [memo field guide](researcher-memo-schema.md).
Keep public assumptions, derivation summary, evidence, objections and decision
rationale. This is not a request for hidden chain-of-thought. Match the exact
report/factor/branch/run and evidence version.

Ultimate preserves it under `research_memo.researcher_agent_memo` and resumes
the study in its current mode. For ordinary IS the command is the existing
Ultimate entry with `--local-is-only --factor-workspace <workspace>
--report-id <report_id> --start-step 6 --end-step 6`.

If Council is active, use its actual task/result format, producer and route
identity; the ordinary memo does not replace Council results.
Follow [Council and revision](council-and-revision.md) and
[orchestration](../../factor-forge-ultimate/references/council-orchestration.md)
only for that action. Each independent result comes from its real assigned
context. The coordinator can collect it but cannot turn self-analysis or a mock
into `producer=real_agent` independent evidence.
