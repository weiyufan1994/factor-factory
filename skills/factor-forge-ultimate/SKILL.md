---
name: factor-forge-ultimate
description: Ultimate top-level skill for the full Factor Forge research system. Use when running or supervising the end-to-end Step1-6 workflow, including data prep, execution, evaluation, reflection, review, revision proposal, and library/knowledge writeback.
---

# Factor Forge Ultimate

## What This Skill Is

This is the **top-level orchestration skill** for the entire Factor Forge system.

It does not replace the Step skills. It sits above them and tells the agent:
- which step(s) to run,
- in what order,
- when a case can skip earlier steps,
- how review and revision fit into Step6,
- and how the final result must be written back into the factor library and knowledge base.

In short:

> `factor-forge-ultimate` = the full research operating system
> `factor-forge-step1..6` = the step-level execution skills
> `factor-forge-research-brain` = the investment-logic layer used mainly inside Step6
> `factor-forge-researcher` = always-on researcher agent layer spanning Step1 through Step6
> `factor-forge-step6-researcher` = final independent review specialist that writes a deeper memo before Step6 finalizes library/knowledge writeback

## Researcher-Led Default

There is no ordinary batch mode for real factor research.
For every factor, the agent must behave like a researcher from the beginning:

1. read the report/paper/source idea and understand the author's thesis,
2. check that Step2 preserves the idea as a canonical factor spec,
3. supervise Step3 data and implementation choices,
4. interpret Step4 metrics, charts, and portfolio evidence,
5. use Step5/6 plus prior knowledge to reflect on whether the factor deserves promotion, iteration, or rejection,
6. apply the math discipline review so evidence is tied to a random object, target statistic, information set, and robustness logic,
7. preserve the experience chain, including failed branches, so future agents learn from the full search trajectory,
8. write durable lessons, transferable patterns, anti-patterns, and innovative idea seeds to the knowledge base and factor libraries,
9. if needed, loop back to Step3B with a research-motivated revision brief and a program-search policy.

Only use a mechanical/lightweight run if the user explicitly says this is a smoke test.

## The Full Workflow

### Step1
- ingest source report / idea
- identify canonical source and factor intent
- produce `alpha_idea_master`
- standardize and validate Step1 research fields: `step1_random_object`, `target_statistic_hint`, `information_set_hint`, `initial_return_source_hypothesis`, and `similar_case_lessons_imported`
- researcher records the author's thesis and what must be true for the idea to work

### Step2
- convert idea into canonical machine-readable spec
- produce `factor_spec_master`
- validate that Step2 preserves `target_statistic`, `economic_mechanism`, `expected_failure_modes`, `innovative_idea_seeds`, and `reuse_instruction_for_future_agents`
- write `handoff_to_step3`
- researcher verifies that the canonical spec still reflects the author's idea

### Step3
- prepare execution contract and implementation artifacts
- `Step3A`: data contract / adapters / step3a local inputs
- `Step3B`: implementation artifacts + first factor run when possible
- write `handoff_to_step4`
- researcher reviews whether data and code preserve the original thesis

### Step4
- run factor execution and evaluation backends
- produce evidence, metrics, diagnostics, and backend payloads
- researcher separates signal quality from tradable portfolio quality

### Step5
- close the case
- archive artifacts
- write lessons / next actions
- write `handoff_to_step6`
- researcher checks that case lessons are not merely status summaries

### Step6
- reflect on the evidence
- require the Step6 researcher agent to build a deep memo from metrics, charts, and prior cases
- retrieve similar prior cases
- classify the return source
- run `math_discipline_review`
- extract `learning_and_innovation`
- build `experience_chain`, `revision_taxonomy`, `program_search_policy`, and `diversity_position`
- decide `promote_official / iterate / reject / needs_human_review`
- write back:
  - factor library all
  - official factor library (if promoted)
  - knowledge base
  - research iteration record
- if iterate: generate `revision_proposal` and optionally send control back to Step3B

## Important Clarification

### Is review and revision part of Step6?

Yes.

Within the full Step1-6 system:
- **review** is part of Step6
- **revision proposal** is part of Step6
- **actual code modification** goes back to Step3B after Step6 decides to iterate

So the sequence is:

`Step4 evidence -> Step5 case close -> Step6 review -> Step6 revision proposal -> Step3B code modification -> Step4 again`

## When to Use Which Entry Path

### Path A: New research report
Use full Step1 -> Step6 when:
- the user provides a new PDF/report
- the factor idea is not yet canonicalized

Step1 PDF ingestion can still require the OpenClaw PDF route, but once the Step1 artifacts exist, Step2 and every later formal step must enter through the ultimate wrapper:

```bash
python3 scripts/run_factorforge_ultimate.py --report-id <report_id> --start-step 2 --end-step 2
```

Direct Step1/Step2 scripts are for isolated developer debugging only. Formal agent runs from Step2 onward must enter through `scripts/run_factorforge_ultimate.py` so the runtime context, proof manifest, and canonical artifact paths are fixed before later steps consume them.

### Path B: Canonical alpha / known formula
Start from Step3 when:
- formula is already known
- `alpha_idea_master`, `factor_spec_master`, and `handoff_to_step3` already exist

### Path C: Re-evaluation / library reflection
Start from Step4, Step5, or Step6 when:
- implementation already exists
- we only need updated evaluation or a new research judgment

## Data Rules

Always prefer the shared clean layer.
Do not re-clean full history per factor.

Default behavior:
1. reuse existing shared clean layer if it exists and covers the requested window
2. reuse an existing report-level slice if its metadata matches the requested report/window
3. only rebuild the shared clean layer when the user explicitly asks to update/refresh/sync data, or when the layer is missing/insufficient
4. only regenerate the report slice when it is missing, stale, or requested with a different window/provider option
5. then run Step3+

Never treat `build_clean_daily_layer.py` as a mandatory per-factor step.

## Mac / EC2 / S3 Knowledge Sync

Use this split for operational knowledge sharing:

- GitHub is the canonical source for code, skills, contracts, and SOP documents.
- Mac is the primary authoring and review environment for Factor Forge knowledge.
- S3 is the durable shared store for Factor Forge knowledge bundles.
- EC2 should pull the latest Mac-published knowledge bundle from S3 and keep a local cache for compute.
- Tailscale may be used as a convenience path, but it must not be the only way EC2 can access knowledge; Mac power/network state must not block EC2 from pulling the last published bundle.

Canonical Mac knowledge layout:

- structured source of truth: `/Users/humphrey/projects/factor-factory/objects/`
- human-readable vault: `/Users/humphrey/projects/factor-factory/knowledge/因子工厂/`
- retrieval index: `/Users/humphrey/projects/factor-factory/knowledge/retrieval/`

Do not use legacy duplicate roots as active knowledge stores:

- `/Users/humphrey/projects/factor-factory/knowledge/obsidian_vault/`
- `/Users/humphrey/projects/factor-factory/factorforge/objects/`

The S3 bundle must carry the same active layout: `objects/`, `knowledge/因子工厂/`, and `knowledge/retrieval/`.

Mac publishes the authoritative object bundle with:

```bash
python3 scripts/sync_factorforge_knowledge_bundle.py bundle \
  --runtime-root /Users/humphrey/projects/factor-factory \
  --upload \
  --update-latest \
  --bucket yufan-data-lake \
  --prefix factorforge-knowledge/mac-authoritative \
  --source-role mac_authoritative
```

EC2 pulls the authoritative object bundle with:

```bash
/home/ubuntu/.openclaw/workspace/.venvs/quant-research/bin/python \
  scripts/sync_factorforge_knowledge_bundle.py apply \
  --runtime-root /home/ubuntu/.openclaw/workspace/factorforge \
  --source s3://yufan-data-lake/factorforge-knowledge/mac-authoritative/latest.json \
  --apply \
  --rebuild-index
```

The sync tool must verify the latest manifest sha256 before applying a bundle. Protected records such as official library, factor cases, handoffs, and validation evidence must not be overwritten by default.

Full SOP: `docs/operations/factorforge-knowledge-sync-sop.zh-CN.md`.


## Mandatory Single Entry Wrapper

For Step3-6 execution, agents must use the single wrapper. Do not manually compose Step3B/Step4/Step5/Step6 commands unless explicitly debugging the wrapper itself.

Default command:

```bash
python3 scripts/run_factorforge_ultimate.py --report-id <report_id> --start-step 3 --end-step 6
```

Common restart command after Step1/2 are already complete:

```bash
python3 scripts/run_factorforge_ultimate.py --report-id <report_id> --start-step 3b --end-step 6
```

The wrapper is responsible for:
- creating the runtime manifest,
- invoking each step with explicit manifest paths,
- running validators immediately after each step,
- stopping on the first failed validator or failed step,
- writing `objects/runtime_context/ultimate_run_report__<report_id>.json` as the proof report.

A run is not considered complete unless the wrapper proof report exists and has `status: PASS`. Ad-hoc metric tables, hand-written handoffs, or post-hoc Step4/5/6 objects are not valid substitutes for wrapper proof.

Legacy handoff or one-off Step3/4/5 drivers, including `scripts/run_pipeline_with_agent_handoff.sh`, `scripts/run_alpha012_step345.py`, and sample Step3/4/5 scripts, must hard block before writing canonical `objects/`, `runs/`, `generated_code/`, `evaluations/`, or `archive/` artifacts. They must not add environment bypasses or swallow `SystemExit` to present a successful formal run.

Single-step or partial-step execution is allowed only when the user explicitly asks for it, and it must still use the wrapper. Examples:

```bash
python3 scripts/run_factorforge_ultimate.py --report-id <report_id> --start-step 4 --end-step 4
python3 scripts/run_factorforge_ultimate.py --report-id <report_id> --start-step 5 --end-step 6
```

Do not run a step-level script directly for normal user requests, even for a single step. Direct calls to `skills/factor-forge-step*/scripts/*.py` are reserved for debugging the wrapper or repairing a failing step after the wrapper proof identifies the failure.

## Long-Only Research Mandate

The current Factor Forge adoption rule is long-only:

- no short selling;
- no direct buying/selling deciles;
- no promotion based on long-short spread;
- no revision by changing portfolio expression, rebalance mechanics, or decile trading.

Step4 may still output decile tables, NAV curves, and long-short diagnostics, but they are diagnostics only. Step5 and Step6 must judge adoption by whether high factor values produce risk-adjusted long-side returns and whether the factor expression has a defensible monotonic economic relationship.

If the long side does not work, the next revision must modify the Step3B factor expression/code itself, or the factor must be rejected.

Long-side admission uses the factor-as-business lens:

- return/risk premium is `revenue`;
- trading COGS defaults to `turnover * 0.3%` when no better cost estimate exists;
- volatility is operating instability / risk-capital pressure, not direct COGS;
- stochastic-process volatility drag is `-0.5 * sigma^2`;
- max drawdown is capital expenditure / capital impairment;
- recovery time is depreciation or payback period;
- risk budget depends on Sharpe, max drawdown, recovery time, capacity, and confidence in repeatability.

Default promotion objective is `long_side_risk_adjusted_alpha`:

- candidate threshold: long-side Sharpe >= `0.50`;
- official threshold: long-side Sharpe >= `0.80`;
- drawdown soft limit: max drawdown no worse than `-35%`;
- recovery soft limit: <= `252` trading days.

Raw positive long-side return is necessary but not sufficient. A high-revenue factor with excessive volatility drag, drawdown, or recovery time should be iterated or rejected.

## Runtime Manifest And Step I/O

The top-level skill/agent owns path discovery. Individual step scripts should not independently search for artifacts when a runtime manifest is available.

Before running Step3/4/5/6, build or refresh the manifest:

```bash
python3 scripts/build_factorforge_runtime_context.py --report-id <report_id> --write
```

For normal execution, do not call individual Step3/4/5/6 scripts directly. Call the single wrapper instead:

```bash
python3 scripts/run_factorforge_ultimate.py --report-id <report_id> --start-step 3 --end-step 6
```

Individual manifest-driven step commands are reserved for wrapper debugging only.

Principles:
- Step3 has the fixed data entrance: shared clean layer plus report-level `step3a_local_inputs`.
- Step4 consumes Step3 outputs from the manifest and owns evaluation metrics / backend payloads.
- Step5 consumes Step4 outputs from the manifest and owns case closure / archive.
- Step6 consumes Step5 outputs from the manifest and owns reflection / revision / library writeback.
- Script-local path guessing is only a backward-compatible fallback. It must not override manifest paths.

## Step6 Review Logic

When Step6 is active, always use the research-brain logic:
1. identify return source
2. identify objective constraints
3. interpret metrics
4. check math discipline
5. extract transferable learning and idea seeds
6. separate macro revision, micro revision, portfolio revision, and stop/kill decisions
7. choose a search mode: genetic formula mutation, Bayesian parameter search, RL-policy advisory, or multi-agent parallel exploration
8. decide promote / iterate / reject

Do not use `DD-view-edge-trade` inside Factor Forge Step6. That framework belongs to individual-stock diligence, not factor-mining loop control.

Return source should be one of:
- `risk_premium`
- `information_advantage`
- `constraint_driven_arbitrage`
- `mixed`

If the user asks for a serious review, PM-style judgment, detailed analysis, or researcher-agent behavior, run the Step6 researcher path first:

```bash
python3 skills/factor-forge-step6-researcher/scripts/build_researcher_packet.py --report-id <report_id>
# researcher agent writes factorforge/objects/research_iteration_master/researcher_memo__<report_id>.json
python3 scripts/run_factorforge_ultimate.py --report-id <report_id> --start-step 6 --end-step 6
```

For normal factor research, also keep the full-workflow researcher journal:

```bash
python3 skills/factor-forge-researcher/scripts/build_researcher_dossier.py --report-id <report_id>
# researcher agent updates factorforge/objects/research_journal/research_journal__<report_id>.json
```

## Math Discipline And Learning

Use `docs/operations/factorforge-math-research-discipline.zh-CN.md` as the execution version of the math map.

Every serious Step6 output must include:
- `math_discipline_review`
- `learning_and_innovation`
- `experience_chain`
- `revision_taxonomy`
- `program_search_policy`
- `diversity_position`

The purpose is to make the researcher agents better over time. A case is not complete unless it teaches future Bernard/Humphrey/Codex at least one of:
- a transferable pattern,
- an anti-pattern,
- a similar-case retrieval cue,
- an innovative idea seed,
- or a clear reason why no learning can safely be extracted.

## Human Approval Rule

If Step6 decides `iterate`:
- first generate `revision_proposal__{report_id}.json`
- include candidate branches for exploit and explore when the evidence supports parallel exploration
- stop for human review
- only after explicit approval may the loop continue into Step3B modification

## What Good Usage Looks Like

Examples:
- "Use factor-forge-ultimate to run this new report from Step1 to Step6."
- "Use factor-forge-ultimate on alpha002 starting from Step3; if Step6 wants revision, stop and show me the proposal first."
- "Use factor-forge-ultimate to rerun Step4-6 for this factor and tell me whether it should be promoted."

## Required Pairing

When using this skill, also consult the relevant sub-skills:
- `skills/factor-forge-step1/SKILL.md`
- `skills/factor-forge-step2/SKILL.md`
- `skills/factor-forge-step3/SKILL.md`
- `skills/factor-forge-step4/SKILL.md`
- `skills/factor-forge-step5/SKILL.md`
- `skills/factor-forge-step6/SKILL.md`
- `skills/factor-forge-researcher/SKILL.md`
- `skills/factor-forge-step6-researcher/SKILL.md`
- `skills/factor-forge-research-brain/SKILL.md`

## References

- `references/playbook.md`
- `references/research-framework.md`
- `references/step6-contract.md`
- `docs/operations/factorforge-math-research-discipline.zh-CN.md`
## Implementation and Factor Isolation Discipline

- Every formal factor artifact must carry `artifact_identity`.
- Every formal run must carry `manifest_identity`.
- `implementation_mode` is restricted to `operator`, `direct_code`, or `hybrid`.
- Artifacts must not be reused across mode, factor, report, branch, or run unless identity/hash lineage matches explicitly.
- Formal execution must consume manifest-specified paths only; do not pick files by `glob`, mtime, or "latest" guesses.
- If `report_id`, `factor_id`, `source_type`, `implementation_mode`, `branch_id`, `spec_hash`, or formula/code/hybrid hash does not match, BLOCK.
- Direct generated implementation files belong to one factor identity; shared helpers may be reused, factor-specific generated code may not be silently copied.

## Correctness Over Completion

FactorForge is a general-purpose factor research framework, not a UBL/CPV/Alpha101-specific calculator. Step3B must follow `operator -> hybrid -> direct_code -> BLOCK`; unsupported or unsafe implementation must fail explicitly instead of borrowing sample/family code. UBL/CPV/shadow/candle/Williams code is fixture/plugin-only and never a fallback.

## Operator / Qlib Engine

Formal operator mode flows through `formula_text -> formula_ir -> operator registry -> pandas reference evaluator -> qlib bridge -> generated pandas implementation -> parity validation`. Qlib support is explicit: unsupported operators must be recorded as unsupported, not silently emulated. The pandas reference evaluator is the parity ground truth, and any parser, field-alias, code-hash, or parity failure must BLOCK before Step4.

## Hybrid Execution Engine

Formal hybrid mode is a controlled composition of a verified operator subgraph and a verified custom block. It requires `factorforge_hybrid_contract_v1`, boundary schema, protected operator outputs, `formula_hash`, `custom_block_hash`, and `hybrid_hash`. Unsafe custom code, boundary violations, missing schemas, or hash mismatch must BLOCK before Step4 and before factor values are written.

Family plugins require explicit Step2 declaration: `factor_family`, `family_plugin`, `family_plugin_allowed=true`, and a `factorforge_family_plugin_decision_v1` record with structured non-free-text evidence. `factor_id`, keywords, formula prose, and thesis text are not allowed to trigger plugins.

## Provenance Strengthening

- No provenance, no archive. No evidence identity, no promotion. Ultimate proof must preserve the identity chain from Step3B mode decision through Step4 evidence, Step5 case closure, and Step6 writeback.
- Step6 official promotion requires verified Step5 evidence quality, strict identity match, long-only risk-adjusted evidence, and no unresolved correctness risk.
- Similar case knowledge is not same-factor evidence unless artifact identity matches.
- Iterate creates a child branch with parent lineage; it must never overwrite `main` or silently reuse another run.

## Agentic Revision Council

Step6 is the investment-committee layer of Factor Forge. When Step1-5 evidence
leaves a non-obvious revision problem, the main agent using this skill should
form a Revision Council instead of inventing a single private proposal.

The main agent owns Step1-5 and remains accountable for the final judgment. The
council is a research method inside Step6:

1. build a read-only council packet from Step1-5 evidence, mechanism math,
   metrics, charts, prior knowledge, and the current loop brief;
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
`factor-forge-ultimate` may run the roles itself or delegate them to available
subagents. Typical roles are `symbolic_law_discovery`, `evidence_auditor`,
`economic_mechanism`, `formula_engineer`, `cost_turnover`,
`regime_robustness`, and `knowledge_retrieval_critic`.

`symbolic_law_discovery` is not a fixed checklist. It treats the factor formula,
data fields, evidence, and knowledge base as a mathematical research object. It
may choose dimensional analysis, scaling laws, stochastic processes, stochastic
calculus, jump processes, stopping-time reasoning, Fourier/spectral analysis,
robust statistics, tail-distribution analysis, projection geometry, functional
analysis, dynamical systems, information theory, market microstructure theory,
or other justified tools. It must also be allowed to reject tools as unjustified
when the formula/evidence does not support them.

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
`--council-mode off|auto|scaffold|agentic`. The default is `off` to preserve the
legacy official wrapper path. `scaffold` runs the deterministic Council chain
after successful Step6 core, attaches the Council summary back to the Step6
iteration, and reruns `validate_step6.py`. `auto` runs that same chain only when
Step6 indicates a revision is needed and evidence/case comparison is not
blocked. `agentic` requires `--agentic-council-executor`. With `none`, the
wrapper must block with `BLOCK_REVISION_COUNCIL_AGENTIC_EXECUTOR_REQUIRED`. With
`real_agent`, it must block with `BLOCK_REVISION_COUNCIL_REAL_AGENT_NOT_IMPLEMENTED`.
With `local_mock`, it runs the Phase K.1 contract path: agentic taskbook, mock
agent results, result validation, merge, attach, and `validate_step6.py`. The
mock executor validates artifact contracts only; it is not real subagent
research. With `dispatch_manifest`, the wrapper builds packet/taskbook/dispatch
manifest artifacts and stops in `awaiting_agent_results`; with
`--agentic-dispatch-adapter manual_file`, it also writes manual assignment
markdown and result dropbox templates without merging or attaching.

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
