# Council orchestration

Read when a real revision/Council checkpoint is active. A script-generated dispatch is not a sent task; actual agent calls and returned results establish execution. For Step6 record/decision gates, also read [Council and revision](../../factor-forge-step6/references/council-and-revision.md). Ordinary code review uses [local-code-review.md](local-code-review.md).

## Agentic Revision Council

Step6 is the investment-committee layer of Factor Forge. When admissible
evidence leaves a non-obvious revision problem, the main agent using this skill
should form a Revision Council instead of inventing a single private proposal.
For ordinary research that evidence is Step1-5. For EVO V2 revision it is the
Host-qualified purged-IS feedback ledger before OOS; post-OOS evidence cannot
authorize a revision of that parent or any child.

The main agent owns Step1-5 and remains accountable for the final judgment. The
council is a research method inside Step6:

1. build a read-only council packet from Step1-5 evidence, mechanism math,
   metrics, charts, prior knowledge, human supplemental mechanism context,
   and the current loop brief;
2. define exploration directions and their dependency graph;
3. explore independent directions in parallel when the runtime supports
   subagents, and explore dependent directions sequentially;
4. require every main-agent or subagent proposal to write an explicit public
   `derivation_record`;
5. validate proposals, reject unsafe or under-derived proposals, and merge only
   advisory outputs;
6. let the main agent summarize accepted and rejected derivations before any
   Step3B revision brief is considered.

The council is role-based, not name-based. Any main agent using
`factor-forge-ultimate` may analyze advisory roles itself or delegate them to
available subagents. A formal independent/blind route requires the actual
distinct agent/context specified by the protocol; self-analysis cannot satisfy
that gate. Typical roles are `symbolic_law_discovery`, `evidence_auditor`,
`economic_mechanism`, `formula_engineer`, `cost_turnover`,
`regime_robustness`, and `knowledge_retrieval_critic`.

`symbolic_law_discovery` is not a fixed checklist. It treats the factor formula,
data fields, evidence, and knowledge base as a mathematical research object. It
may choose DCF or residual-income valuation, accounting identities, dimensional
or scaling analysis, stochastic processes, jump or stopping-time reasoning,
Fourier/spectral analysis, robust statistics, projection geometry, functional
analysis, causal models, dynamical systems, information theory, optimization,
market microstructure theory, a composition of these, or another justified
tool. It must reject tools that do not fit the economic hypothesis; neither
stochastic processes nor dimensional analysis is mandatory.

Every council proposal must include a visible `derivation_record` suitable for
knowledge-base writeback. This is a public research artifact, not hidden
chain-of-thought. It must record the research question, assumptions,
mathematical objects, selected and rejected tools with reasons, derivation
steps, formulas or symbolic relations, derived implications, revision
hypotheses, expected metric changes, falsification tests, kill criteria,
confidence limits, and an overclaim guard. A proposal without an explicit
research derivation is invalid.

No derivation record, no council proposal. No valid council proposal, no branch
template. No accepted derivation, no Step3B revision brief.

After Council merge, the wrapper or main agent must generate the public
derivation appendix before attach/finalization:

```bash
python3 skills/factor-forge-step6/scripts/build_council_derivation_appendix.py --report-id <report_id>
```

The appendix is the readable consolidation layer for selected Council results.
It must include assumptions, mathematical objects, selected tools, formula
claims, derivation steps, limiting cases, falsification tests, kill criteria,
and candidate revision laws. It is advisory-only evidence and must not authorize
or perform canonical writes.

Council output must remain advisory and isolated under
`objects/research_iteration_master/revision_council/{report_id}/`. Council
agents and subagents must not write canonical Step3B handoffs, generated code,
official library records, clean data, canonical factor expressions, runs,
evaluations, or archives. Returning to Step3B still requires main-agent
selection, validator approval, human approval, and the ultimate wrapper path.

The deterministic local council is only a scaffold/smoke/fallback path. Formal
research should prefer agentic council reasoning when the environment supports
it. If a proposal was produced by a deterministic scaffold, mark it as
`producer=deterministic_scaffold`, `research_depth=low`, and do not present it
as a deep mathematical research conclusion.

### Ultimate Wrapper Council Mode

`scripts/run_factorforge_ultimate.py` supports explicit Council integration with
`--council-mode off|auto|scaffold|agentic`. The default is `auto`: every formal
Step6 pass should expose the case to Council logic when revision is needed and
evidence/case comparison is not blocked. Use `off` only for isolated debugging
or legacy reproducibility checks. `scaffold` runs the deterministic Council chain
after successful Step6 core, attaches the Council summary back to the Step6
iteration, and reruns `validate_step6.py`. `auto` must not silently treat that
deterministic scaffold as formal agentic research. With the default
`--auto-council-policy dispatch_manifest`, auto builds packet/taskbook/dispatch
manifest artifacts and returns `awaiting_agent_results` when Step6 indicates
revision is needed and evidence/case comparison is not blocked. That wrapper
return is a machine checkpoint, not a user handoff. A main agent using this
skill must immediately continue the Council workflow by producing valid agent
result artifacts, collecting them, finalizing Council, and resuming the loop
unless the user explicitly asks to pause. Use
`--auto-council-policy scaffold` only for explicit smoke/fallback runs, and use
`--auto-council-policy block_without_agentic` when formal runs should hard-block
instead of awaiting agent results. `agentic` requires
`--agentic-council-executor`. With `none`, the
wrapper must block with `BLOCK_REVISION_COUNCIL_AGENTIC_EXECUTOR_REQUIRED`. With
`real_agent`, it must block with `BLOCK_REVISION_COUNCIL_REAL_AGENT_NOT_IMPLEMENTED`.
With `local_mock`, it runs the Phase K.1 contract path: agentic taskbook, mock
agent results, result validation, merge, attach, and `validate_step6.py`. The
mock executor validates artifact contracts only; it is not real subagent
research. With `dispatch_manifest`, the wrapper builds packet/taskbook/dispatch
manifest artifacts and returns `awaiting_agent_results`; with
`--agentic-dispatch-adapter manual_file`, it also writes manual assignment
markdown and result dropbox templates without merging or attaching.

Step6 core must first write a main-agent mechanism questionnaire:
`objects/research_iteration_master/main_agent_mechanism_questionnaire__<report_id>.json`
and `.md`. The runtime main agent currently using this skill must answer it as
`objects/research_iteration_master/main_agent_mechanism_memo__<report_id>.json`
and `.md` before Council work starts. This is a free-form mechanism answer, not
a multiple-choice classifier: it must connect formula state, economic
hypothesis, baseline mathematical model, model mutation, payer, payoff,
estimator mapping, metric signature, and falsification. If this memo is missing,
the wrapper must pause as `awaiting_main_agent_mechanism_memo` and must not
expose a final Step3B handoff or run Council. If the memo is invalid, the wrapper
must block. Council packet/taskbook artifacts must reference the accepted memo
and require subagents to critique its formula component map, payer derivation,
evidence contradictions, and revision-or-kill implications.

### Autonomous Council Continuation

`awaiting_main_agent_mechanism_memo` and `awaiting_agent_results` are internal
checkpoint states. They are not reasons to stop and ask the user for another
command during normal production research.
Any loop pause at `awaiting_main_agent_mechanism_memo`,
`awaiting_agent_results`, `awaiting_main_agent_council_synthesis`, or
`awaiting_next_derivation` must write
`objects/research_iteration_master/paused_research_note__<report_id>.json` and
`.md` with the pause reason, evidence paths, known backend/metric status,
lessons, and exact next questions. A paused run without this durable note is
not production-complete.

When the wrapper or loop returns `awaiting_main_agent_mechanism_memo`, the
current runtime main agent must read the questionnaire, write the free-form
main-agent mechanism memo JSON/MD, validate it, and resume the official loop.

When the wrapper or loop returns `awaiting_agent_results`, the current runtime
main agent must:

1. read the dispatch manifest and all task packets;
2. dispatch independent Council roles to available subagents when possible;
3. if independent execution is required and unavailable, record that limitation
   and BLOCK the affected review; sequential self-analysis may be advisory only
   and cannot satisfy distinct-agent or blind-session requirements;
4. write one `status=final`, `producer=real_agent` result JSON per required
   task to the exact `expected_result_path`;
5. include public derivation records, `economic_hypothesis_review`,
   `math_mechanism_derivation`, `model_to_formula_translation`,
   formula-specific critique, payer derivation critique, falsification tests,
   kill criteria, expected metric signatures, and any required
   `prior_revision_outcome_review` / `repeated_revision_guard`;
6. run `collect_agentic_council_results.py`,
   `validate_agentic_council_collection.py`, and
   `finalize_agentic_council_dispatch.py`;
7. resume the local Ultimate wrapper for local IS; use the hosted loop only
   for an authorized hosted child workflow. Continue within the frozen scope until `promote_official`, `reject`, `exhausted`,
   `max_loops_reached`, or a true BLOCK/failure requiring human judgment.

The main agent must not fabricate Council output by using `local_mock`, copying
old scaffold proposals, or writing generic result templates. It may only write
Council results that it or its delegated subagents actually researched from the
task packets. If valid Council results cannot be produced, BLOCK with a precise
reason instead of asking the user to drive the next command.

A unanimous Council terminal rejection closes a web research task only through
the terminal-rejection protocol. The close artifact must bind a validated
factor-proof certificate whose derived verdict is `REJECT`, the dispatch
manifest, Council summary and collection, every selected raw result, and the
iteration decision. Final replay must verify hashes, dispatch identities,
required-result counts and the exact terminal recommendation enum; prose and
substring matches are not decisions. If a distinct registered route is still
available, the wrapper must pause as `awaiting_next_derivation` and emit the
bounded questionnaire. Non-unanimous Council output must pause as
`awaiting_main_agent_council_synthesis`. Neither pause state is a terminal
factor verdict or formal proof.

Runtime dispatch is policy, not provider binding. `--runtime-dispatch
codex|openclaw|manual_file|unknown` records the runtime in taskbook, dispatch
manifest, task packets, manual manifest, and assignment markdown. If omitted,
manual-file dispatch records `manual_file`; otherwise the default is `unknown`.
Subagents inherit the current main model/provider by default. `--subagent-provider`
and `--subagent-model` may be recorded only as explicit user-requested
overrides; Factor Forge must not require or auto-select a provider.

Wrapper Council mode must remain advisory-only. It must not execute search
workers, write `handoff_to_step3b`, promote official records, modify
`generated_code/{report_id}`, or mutate `data/clean`. The wrapper records
before/after side-effect snapshots and must block with
`BLOCK_REVISION_COUNCIL_WRAPPER_FORBIDDEN_SIDE_EFFECT` if the Council chain
changes forbidden artifacts.
