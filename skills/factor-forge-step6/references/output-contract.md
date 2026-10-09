# Step6 output and evidence

All paths below are relative to the declared factor workspace.

| Output | Path / purpose |
|---|---|
| Iteration | `objects/research_iteration_master/research_iteration_master__{report_id}.json` |
| Research record | `objects/factor_library_all/factor_record__{report_id}.json` |
| Local experience candidate | `objects/research_knowledge_base/knowledge_record__{report_id}.json` |
| Revision handoff, when actually selected | `objects/handoff/handoff_to_step3b__{report_id}.json` |
| Official record, formal mode only | `objects/factor_library_official/factor_record__{report_id}.json` |

Decisions are `promote_official|iterate|reject|needs_human_review`; validator
statuses are `PASS|WARN|BLOCK`. Ordinary local IS never promotes officially.

The memo connects the frozen economic hypothesis, derivation and predicted
observations to actual Step4/5 evidence. It carries limitations, competing
explanations, disposition and the next mathematical question or stopping reason.
Keep signal evidence, incomplete account evidence and research acceptance
distinct. Illegal information time remains an error, not a weak result.

For new ordinary studies, use the versioned
[content rules](../../factor-forge-ultimate/references/compatibility-constraints.md).
V2 allows a sufficient single prediction/test/stopping condition and explicit
empty revision/learning/search outputs with reasons. Missing or invalid content
is different from an authored empty result.

The iteration preserves the experience chain and distinguishes mechanism,
estimator, implementation, evaluation-assumption and stop decisions. Record only
the search methods actually considered or run; an empty method library is valid
for a justified non-iterate stop. The four historical method keys remain a
compatibility requirement only for unmarked/hosted records, not a claim that RL
or every search algorithm ran.

An actual revision retains the selected mathematical object, public derivation,
falsifier, implementation review and applicable approval state. Independent
Council results keep their actual producer and context. A draft, mock or
author-only review is not independent execution. Local experience records are
candidates for the knowledge owner's maintenance flow, not automatic canonical
publication.
