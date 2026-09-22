# Workspace knowledge and experience maintenance

Read at completion/interruption or when repairing maintenance. This describes the existing behavior; engineering edits to Skills do not authorize research, export or index refresh.

## Workspace Experience Reuse

After a successful Step6 run and validation, the wrapper rebuilds the active
workspace's derivative experience index. It also create-only exports selected
fields from that Step6 knowledge record to the local project's
`knowledge/因子工厂/workspace_experience_exports/` and refreshes the default index.
These exports are advisory candidates, not canonical memory or proven general
laws. Same-content re-export is idempotent; conflicting content is not overwritten.
A refresh/export error is visible but does not change the completed research
result or clear a usable old index. A rejected factor with a completed Step6
still writes experience. Dry runs never write experience. Executed local-IS
failures/pauses retain separate advisory `research_episode` facts and a visible
maintenance result; they do not manufacture a Step6 decision or economic cause.

Supported ordinary local-IS early exits include code-review handoff failures,
continuation-save failures and waiting for Council results. Planned commands
are not execution facts; no executed command produces a visible skip, not an
episode. Existing completion/failure maintenance is not run a second time.
Hosted-only next-derivation/synthesis exits are unchanged. A process killed
before cleanup still needs the existing maintenance CLI and durable report;
this is not an automatic background recovery service.

At a terminal outcome or a genuine interruption, the research agent must check
the maintenance result and read back the experience through the actual consumer.
No extra user reminder is needed. If substantive reviewed findings exist but
native Step6 could not complete, summarize those findings as a sourced advisory
note in `knowledge/因子工厂/research_notes/`, explicitly retaining the unfinished
Step6 status. Never promote wrapper errors to economic failure explanations.
Use `scripts/maintain_factorforge_knowledge.py` to repair maintenance from an
existing local-IS report without rerunning research or modifying its conclusion.

Useful notes connect the economic hypothesis, mathematical object, operator or
code, retained/lost information, applicability conditions, regime-detection
limits, observed treatment outcomes, counterexamples and evidence. Unknowns are
valid. Separate mathematical properties, empirical observations and hypotheses;
retrieval similarity is none of these. Withdrawn notes remain on disk but leave
the active index. Local embedding is optional infrastructure configured once;
the existing source-first order and graph/experience visibility remain intact.

New studies' Step1/2 helpers automatically retrieve these exported candidates
after source-first understanding; the user need not configure RAG paths. The
active workspace index stays separate from the default project index. The
Step6 experience reader resolves the active index, then an explicitly exported
shared index, then the repo index; an explicit override never silently falls
back. Source-only/A0 retrieval still uses its phase-specific graph projection,
never raw experience records. A prior case can suggest a rival, operator or
test; it cannot replace the new hypothesis, prove a cause, authorize a change,
or promote a factor. Host-private role memory remains a separate system.

## Knowledge Reference Contract

Formal runs must preserve prior-knowledge provenance from Step1 through Step6.
Step1 writes `knowledge_reference_contract.contract_version=factorforge_knowledge_reference_contract_v1`
alongside `similar_case_lessons_imported`; Step2 preserves it in
`research_contract` and `learning_and_innovation`; Step6/Council writes
retrieval context for each revision. Cold-start is allowed only when explicitly
recorded with checked index paths, query hash, hit count, and fallback reason.
Missing provenance blocks formal acceptance even if a human-readable lesson
string is present.
