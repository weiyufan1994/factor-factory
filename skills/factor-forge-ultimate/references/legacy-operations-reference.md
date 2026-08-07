---
name: factor-forge-ultimate
description: Ultimate top-level skill for the full Factor Forge research system. Use when running or supervising the end-to-end Step1-6 workflow, including data prep, execution, evaluation, reflection, review, revision proposal, and library/knowledge writeback.
---

# Factor Forge Ultimate Legacy Operations Reference

> Compatibility boundary: this file documents historical schemas and operating
> modes. It is not the current math authority. For new research use
> `mechanism_conditioned_measurement_program_v1`. Historical random-object,
> stochastic-benchmark, unit/dimension, or claim-stage fields are validated only
> when an upstream artifact already contains them; never synthesize them as
> universal requirements.

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

1. read the report/paper/source idea and understand the author's thesis, including a two-layer economic hypothesis and one or more justified math hypotheses,
2. check that Step2 preserves the idea as a canonical factor spec,
3. supervise Step3 data and implementation choices,
4. interpret Step4 metrics, charts, and portfolio evidence,
5. use Step5/6 plus prior knowledge to reflect on whether the factor deserves promotion, iteration, or rejection,
6. apply the math discipline review so evidence is tied to a random object, target statistic, information set, and robustness logic,
7. preserve the experience chain, including failed branches, so future agents learn from the full search trajectory,
8. write durable lessons, transferable patterns, anti-patterns, and innovative idea seeds to the knowledge base and factor libraries,
9. if needed, loop back to Step3B with a research-motivated revision brief and a program-search policy.

Only use a mechanical/lightweight run if the user explicitly says this is a smoke test.

## Research Quality Gate

Artifact completion is not research completion. A formal run can be
engineering-complete while still research-quality-blocked. The main agent must
not present Step6 PASS, Council files, window evidence, or library absence as
proof that the factor was deeply researched.

### Universal Idea Quality Gate

Every non-smoke factor idea must pass an idea-quality checkpoint before it is
allowed to consume expensive Step3/Step4/Step6 runtime. This applies to report
intake, oral ideas, formula-only intake, Miner candidates promoted from a
campaign, and Council revision ideas.

The checkpoint is universal; it is not specific to crowding, moneyflow, or any
other factor family. The active factor workspace must carry an auditable
`research_quality_gate` packet, either inside Step1/Step2/Step6 artifacts or as
workspace objects under `objects/idea_quality_gate/`:

```text
idea_quality_gate__<idea_id>.json
economic_mechanism_contract__<idea_id>.json
mathematical_object_contract__<idea_id>.json
alias_elimination_matrix__<idea_id>.json
falsification_plan__<idea_id>.json
claim_level_assessment__<idea_id>.json
reviewer_attack_memo__<idea_id>.md
```

The packet must answer:

- `economic_mechanism_contract`: who pays or receives the return, why the
  behavior should persist, what institutional, liquidity, information, risk, or
  behavioral constraint creates the effect, and what observable proxy would
  falsify it;
- `mathematical_object_contract`: the random object or state variable, target
  statistic, information set, horizon, formula-to-state mapping, and whether
  the formula is an estimator rather than a restatement of raw fields;
- `alias_elimination_matrix`: plausible lookalike explanations such as size,
  liquidity, volatility, reversal, beta, industry, microcap, missing-data,
  limit-up/down, or rebalance artifacts, plus the discriminating test for each;
- `falsification_plan`: at least one test that would kill the mechanism, one
  component or ablation test, and one regime or payer/receiver proxy test when
  data exists;
- `claim_level_assessment`: current allowed claim level and the evidence still
  missing for the next level;
- `reviewer_attack_memo`: the strongest skeptical explanation and how the run
  will distinguish it from the preferred mechanism.

Allowed next step is determined by claim level:

```text
narrative_only or math_framed -> Miner queue or stop; no formal Step3/Step4.
metric_candidate -> cheap screen or bounded exploratory screen only.
metric_consistent -> formal Ultimate may proceed, but no promotion claim.
component_validated -> formal revision/promotion discussion may start.
stochastic_validated or payer_validated -> strong mechanism claim may be made.
```

Missing payer hypothesis, mathematical object, alias-elimination tests, or
falsification design means `research_quality_blocked`. Do not continue to
formal Step3/Step4 by filling prose templates with generic market language.

Every serious Step6, Council synthesis, or final research answer must declare a
`mechanism_claim_level`:

```text
none
narrative_only
math_framed
metric_consistent
component_validated
stochastic_validated
payer_validated
```

The agent may claim only the level proven by evidence. `math_framed` means a
mathematical object or tool was selected; it is not validation.
`metric_consistent` means aggregate metrics fit the story; it is not component
or payer validation. `component_validated` requires at least one real
component, joint-state, regime/liquidity, or parent-vs-revision information
delta test. `stochastic_validated` requires state-space, conditional return
distribution, transition/persistence, or barrier/tail evidence.
`payer_validated` requires falsifiable payer/receiver evidence.

If a run lacks the evidence for the claimed level, label it
`research_quality_blocked` or lower the claim level. Do not use polished prose,
Council scaffolds, or deterministic templates to upgrade the claim.

For each evidence artifact, state its role:

```text
promotion_gate_evidence
robustness_evidence
diagnostic_evidence
window_contract_evidence
exploratory_evidence
```

Only `promotion_gate_evidence` can support promotion. Window-contract and
supplemental robustness evidence can prove coverage or stability, but cannot
replace formal Step4 promotion evidence.

When using stochastic-process language, declare
`stochastic_process_status=not_used|framing_only|validated`. A validated claim
must include state space, conditional return distribution, transition
persistence or half-life, barrier/tail risk evidence, and parent-vs-revision
state-information delta. Otherwise call it `framing_only`.

When claiming Dirac-style induction or reusable symbolic law discovery, write a
public `dirac_induction_memo__<report_id>.json/md` under the active factor
workspace. It must contain `atomic_state`, `invariant`, `estimator_law`,
`deleted_information_audit`, at least three `limiting_cases`,
`falsification_design`, `reuse_boundary`, and `overclaim_guard`. Without this
memo, say the run has a mechanism hypothesis, not Dirac induction.

Council output must declare research depth:

```text
contract_placeholder_result
deterministic_scaffold
main_agent_sequential_result
independent_agent_result
human_reviewed_result
```

Only `independent_agent_result` or `human_reviewed_result` can support a formal
research-quality claim. Scaffold and placeholder output can satisfy contract
shape only; they cannot prove independent mechanism validation.

## Workspace And Git Hygiene Discipline

Before any Factor Forge Ultimate work, inspect `git status --short --branch`.
If the worktree is not clean, classify it before running research:

- framework/skill/test changes;
- repo-root `knowledge/因子工厂` export changes;
- `factor_research` workspace artifacts;
- clean/raw data changes;
- unrelated user changes.

Do not start a new factor run from a dirty framework worktree unless the user
explicitly accepts that boundary. Do not clean or revert user changes without
explicit approval.

Every new factor research must start by creating a factor workspace:
`factor_research/<factor_id>/<research_id>/` or the runtime equivalent selected
by the workspace manifest. Step3 runtime copies, Step3B code, results, objects,
human-readable notes, canonical knowledge, and retrieval artifacts belong under
that workspace. Baseline Step3 code is a template only; factor-specific logic
must never be written back into the baseline Step3 runtime.

`factor_research/**` is runtime/artifact space by default. Large generated
files, caches, PDFs, Parquet/HDF files, result CSVs, and `step3_runtime/` are
not normal git inputs. Promote only reviewed small provenance files such as
`manifest.json`, final reports, and canonical knowledge, and only with explicit
paths, usually `git add -f <path>` when the file is intentionally ignored.
Never use `git add .`.

Repo-root `knowledge/因子工厂` is an explicit export/vault target only. A formal
export must be user-approved, provenance-backed, and accompanied by an export
manifest. Default knowledge writes stay inside the factor workspace.

When multiple researcher threads are active, assume they may write new
workspace files concurrently. Keep framework changes in a separate branch or
worktree from live research runs; do not mix framework PRs, knowledge exports,
and production factor artifacts in one commit.

## Knowledge-First Research Gate

Every real Factor Forge research round must deposit knowledge before the next
round starts. This applies to successful runs, failed runs, BLOCKs, performance
failures, data-quality findings, weak-alpha results, and abandoned branches.

## Factor Research Workspace Gate

Every non-smoke factor study must start by creating or selecting one active
factor workspace under:

```text
factor_research/<factor_or_report_id>/<research_id>/
```

or, for an already established single-folder study, the nearest existing
`factor_research/<research_id>/` workspace with a `manifest.json`.

Single-factor scripts, ad-hoc evaluators, worker launch helpers, research
reports, data requests, result snapshots, and scratch state must stay inside
that active workspace, normally under `scripts/`, `docs/`, `results/`,
`objects/`, or `runs/`. Do not write new factor-specific files into repo-root
`scripts/`, repo-root `docs/operations/`, or baseline Step3/Step4 runner files.

Repo-root `scripts/` is reserved for reusable framework tooling, validators,
smokes, and explicitly promoted shared utilities. A factor-specific helper may
move there only after a deliberate framework promotion, tests, and documentation
that prove it is no longer tied to one factor or branch.

If a real research request has no active workspace, create the workspace and
manifest before Step3/4/5/6 work. If historical files are found outside their
factor workspace, migrate or quarantine them before continuing unless the user
explicitly asks for a read-only inspection.

Before launching a new child loop, branch, revision, portfolio-policy test, or
follow-on backtest, the main agent must write or update durable knowledge under
the active Factor Forge knowledge surfaces:

- `objects/research_journal/research_journal__<report_id>.json`
- `objects/research_knowledge_base/`
- `knowledge/因子工厂/`
- an operations/research note under `docs/operations/` when the lesson is
  framework-level, data-layer, performance, or human-forwardable

The writeback must preserve enough context for a future Bernard/Humphrey/Codex
researcher to avoid repeating the same work:

- report id, factor id, branch id, law id, and formula/code-law hash when
  available
- artifact roots and S3/local proof paths
- data window, IS/OOS split, universe, portfolio policy, and cost assumptions
- economic hypothesis and math mechanism, including the selected random object
  or state variable
- executable formula or direct-code law summary
- factor-complexity delta: added/removed primitives, interactions, thresholds,
  nonlinear gates, data dependencies, and free parameters; plus whether OOS
  long-side evidence or residual IC paid for the added complexity
- key metrics, long-side evidence, turnover/cost, drawdown/recovery, and
  benchmark comparison when available
- what improved, what failed, what was falsified, and what must not be repeated
- next research questions and any required data/framework fixes

If the newest evidence only exists in `/tmp`, a temporary S3 prefix, a worker
scratch path, or untracked scripts, it is not fully deposited. The agent must
say so and write the missing knowledge record before presenting the branch as
research-complete or continuing into another formal iteration.

## Production vs Experimental Performance Boundary

This skill is production-ready for new factor research only on the default
Factor Forge path. Production runs must use the reviewed default acceleration
surface wherever the contract matches: Data API/catalog reads, Parquet IO,
Formula-IR `pandas_optimized`, and the reviewed NumPy time-series kernel subset
for supported operators. These reviewed accelerators are no longer optional
experiments; Mac and EC2 must keep them enabled unless a named rollback/debug
gate is being exercised and recorded.

For production factor research, do not set these environment variables unless
the user explicitly asks for a performance experiment or benchmark:

```bash
FACTORFORGE_ENABLE_EXPERIMENTAL_POLARS=1
FACTORFORGE_ENABLE_EXPERIMENTAL_TS_RANK_ENGINE=1
FACTORFORGE_TS_RANK_ENGINE=numpy_sliding_window_experimental
FACTORFORGE_ENABLE_EXPERIMENTAL_FORMULA_KERNEL=1
FACTORFORGE_FORMULA_KERNEL_ENGINE=<experimental_engine>
```

Experimental Polars, the independent experimental `ts_rank` engine, and any
kernel beyond the reviewed default NumPy subset are not production defaults.
They require explicit opt-in, pandas-reference parity, runtime guards, `/tmp`
smoke evidence, reviewer acceptance, and separate user approval before any full
canonical-factor benchmark. They must not alter Step6, Council, promotion
gates, clean data, search workers, or official library writeback.

Reuse is mandatory: if a valid artifact with matching report/factor identity,
implementation path/hash, data window, row/date/ticker counts, and producer
lineage already exists, downstream steps must consume it as a cache or evidence
source instead of recomputing. Recompute only when the implementation, data
contract, identity, or required formal-evidence ownership differs.

## Memory Pressure and Batch Execution Protocol

The "no ordinary batch mode" research rule means no shallow mechanical research
shortcut. It does not permit all-in-memory execution when data are too large.
For minute bars, tick data, large cross-sectional universes, or future deep
learning/model-training jobs, the production default is bounded batch execution.

Before launching a heavy Step3B/Step4 or training run, the agent must estimate
peak memory from row count, selected columns, dtype size, join/window expansion,
and expected intermediate materialization. If estimated peak memory exceeds
about 50-60% of available RAM, or if a prior run shows `Killed`, exit code 137,
OOM-kill logs, memory allocator failure, or swap exhaustion, the run must not be
retried with the same all-in-memory path. It must either switch to a batch plan
or BLOCK with `BLOCK_MEMORY_PRESSURE_BATCH_REQUIRED`.

The batch plan must be explicit in the run proof or implementation plan:

- `batch_execution_plan.version=factorforge_batch_execution_plan_v1`
- memory budget and estimated peak memory
- partition key (`trade_date`, month, instrument shard, or model mini-batch)
- selected columns and predicate pushdown policy
- rolling/lookback overlap or carried state
- output format, checkpoint/resume path, and cache identity
- validation sample/parity policy against a smaller reference run

Batch execution must stream each partition to Parquet or a bounded model
checkpoint and release intermediates between batches. It must not accumulate a
list of all batch DataFrames for final concat unless the post-concat size is
already proven within budget. Rolling time-series factors need lookback overlap
or per-instrument carry state; cross-sectional ranks need complete per-date
cross-sections or an explicit two-pass algorithm. Deep learning training must
use dataset streaming, mini-batches, gradient accumulation/checkpointing, and
resumeable checkpoints rather than materializing the full tensor dataset.

The current production/experimental split is documented in
`docs/operations/factorforge-production-vs-experimental-performance.zh-CN.md`.

## The Full Workflow

### Step1
- ingest source report / idea
- identify canonical source and factor intent
- produce `alpha_idea_master`
- standardize and validate Step1 research fields: `step1_random_object`, `target_statistic_hint`, `information_set_hint`, `initial_return_source_hypothesis`, `economic_hypothesis`, `math_hypothesis_candidates`, and `similar_case_lessons_imported`
- `economic_hypothesis` must first classify the broad source as `risk_premium`, `information_advantage`, `market_structure_arbitrage`, or `mixed`, then state the second-layer mechanism and the likely counterparty paying the return
- `math_hypothesis_candidates` must map the economic mechanism to report-specific mathematical tools. Do not use fixed mappings like "price-volume means microstructure"; use DCF/FCF/PEG, stochastic processes, jumps, cointegration, copulas, wavelets/Fourier, projection, dimensional/scaling analysis, or other tools only when they explain the report-specific counterparty and asset-price logic
- researcher records the author's thesis and what must be true for the idea to work

### Step2
- convert idea into canonical machine-readable spec
- produce `factor_spec_master`
- validate that Step2 preserves `target_statistic`, `economic_mechanism`, `economic_hypothesis`, `math_hypothesis_candidates`, `expected_failure_modes`, `innovative_idea_seeds`, and `reuse_instruction_for_future_agents`
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
- apply the factor-complexity penalty: useful complexity is allowed, but every
  added state, interaction, gate, threshold, parameter, and data dependency must
  be justified by a named economic/mathematical object and by OOS long-side or
  residual-information evidence
- extract `learning_and_innovation`
- build `experience_chain`, `revision_taxonomy`, `program_search_policy`, and `diversity_position`
- decide `promote_official / iterate / reject / needs_human_review`
- write back:
  - factor library all
  - official factor library (if promoted)
  - knowledge base
  - research iteration record
- if iterate: generate `revision_proposal` and optionally send control back to Step3B

### Loop Child Revisions

When Step6/Council approves a revision loop, the ultimate loop must not merely
switch to a child report id and rerun Step3B. It must first materialize an
auditable child revision package:

- main-agent Council orchestration synthesis:
  `objects/research_iteration_master/revision_council/<report_id>/main_agent_council_synthesis__<report_id>.json`
  and `.md`, authored by the currently running main agent after reading the
  Council results
- main-agent synthesis approval bridge:
  `skills/factor-forge-step6/scripts/approve_main_agent_council_synthesis.py`
  must validate the synthesis, record the approval artifact, activate
  `final_revision_strategy.loop_authorization=approved_for_step3b_handoff`,
  write the active `handoff_to_step3b`, refresh the loop brief Council section,
  and rerun `validate_step6.py`
- child `alpha_idea_master`, `factor_spec_master`, `data_prep_master`, and
  optional handoffs/configs
- report-local child daily snapshots copied from the parent Step3A slice
- `objects/research_iteration_master/executable_revision_spec__<child_report_id>.json`
  containing the executable child formula or direct-code law statement from the
  synthesis, implementation mode, parent/child formula or code-law hashes,
  selected revision law ids, expected metric signature, falsification tests,
  kill criteria, and the synthesis path/hash

Child Step3B must consume this executable revision spec and BLOCK if it is
missing or if a non-audit revision leaves the formula hash unchanged. A loop that
recomputes the same parent formula under a child report id is invalid.
The materializer must not invent a fallback formula from generic handoff text.
If Council results are only advisory templates and no main-agent synthesis with
`selected_revision.child_formula` exists, the loop must BLOCK instead of
materializing `negate(parent_formula)` or any other inferred default.
If a completed Council summary and a valid main-agent synthesis already exist,
`run_factorforge_ultimate_loop.py` may invoke the approval bridge automatically
before classifying the iteration as ready for child materialization. If the
bridge validation fails, the loop must BLOCK and must not leave an active
approved handoff behind.

Direct-code and native minute/tick child revisions are first-class revisions.
The ultimate loop must not force them through Formula-IR or operator mode. If
the parent implementation is `direct_code` or `hybrid`, the child revision spec
must carry `implementation_mode`, `revision_type=direct_code_mutation` or
`hybrid_mutation`, `direct_code_revision_contract`, required data contracts,
target function/block, code-law hash, and executable mutation scope. A
human-readable child law such as an intraday moneyflow state equation is valid
only when paired with an executable direct-code mutation contract. Replacing it
with an unrelated parseable formula such as `rank(close)` is research pollution
and must BLOCK.
Moneyflow/Miller-style executable laws must be referenced by `law_id` and
`code_law_hash` through the versioned law registry, not copied into
`run_step3b.py` for every child. Step3B should import/resolve the law by id and
block missing or hash-mismatched laws; adding a new law should normally be a
registry entry plus tests, not a runner rewrite.
Direct-code child materialization must also carry qlib adapter semantics: copy
the parent qlib adapter config when supported, or write child-local
`qlib_native_status=not_applicable` with an explicit reason so Step4 qlib is
skipped rather than reported as missing-input failure.

If a completed real-agent Council collection unanimously recommends terminal
rejection and no main-agent synthesis selects a child formula, the loop may
invoke the terminal Council rejection bridge instead of waiting forever for
another handoff. This bridge must update Step6 to `decision=reject`, keep
`loop_authorization=advisory_only`, leave `handoff_to_step3b` absent, and rerun
`validate_step6.py`. A terminal Council rejection is a stop condition, not an
executable revision.

If a root loop is resumed after a child revision has already been materialized,
the loop must reuse the existing child materialization only when the
materialization report and core child artifacts still exist. It must not call
the materializer again and fail on already-existing child targets.

When the child reaches Step6, the next Council packet must carry the prior
revision outcome as first-class negative or positive evidence. It must compare
parent-vs-child metrics, record the executable derivation rule and formula
hashes, and label the prior revision as `falsified`, `improved`, or
`inconclusive`. If the child worsened key evidence, subsequent agentic Council
tasks must explicitly review that failed revision and must not repeat the same
derivation rule or re-create an ancestor formula hash.

Multi-branch Council synthesis is a guarded production-loop path when, and only
when, a completed Council has a valid
`main_agent_multibranch_synthesis__<report_id>.json/md`. The main agent may use
that artifact to preserve one exploit branch plus up to two exploration branches
from Council results. The artifact must pass
`validate_main_agent_multibranch_synthesis.py` before any multi-child
materialization work. If no valid multi-branch synthesis exists, the ultimate
loop stays on the single-child synthesis path.

The production loop may consume the validated multi-branch synthesis
automatically:

1. approve the synthesis with `approve_main_agent_multibranch_synthesis.py`;
2. materialize all approved children with
   `materialize_step6_multibranch_children.py`;
3. run each child through the normal wrapper from Step3B through Step6;
4. build and validate
   `objects/research_iteration_master/branch_comparison__<parent_report_id>__loopNN.json`
   and `.md`;
5. continue only from the selected next-parent child.

Each child receives a distinct report id, child-local Step3A snapshot paths, a
unique formula hash, and branch context in
`executable_revision_spec__<child_report_id>.json`. The branch comparison must
cover every sibling child, parent-vs-child metric deltas, branch outcome, and
the selected next-parent child. If a child executable spec has `branch_group_id`
and `sibling_branch_count>1`, `build_revision_council_packet.py` must refuse to
build the next Council packet until a valid comparison exists. Once present, the
packet carries `sibling_branch_memory`, including unselected sibling outcomes,
metric deltas, and forbidden repeat formula/law evidence. This prevents the
loop from silently choosing a next parent from multiple children while dropping
exploration evidence.

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

`objects/runtime_context/runtime_context__<report_id>.json` is the worker-entry
contract. It must not be written before the relevant Step1/2/3A validators have
all passed. The ultimate wrapper may use a temporary manifest to run local
validators, but a BLOCKed Step1/Step2/Step3A run must leave the worker-entry
runtime context absent and must not be described as runnable.

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

Canonical production knowledge layout:

- each formal factor research owns a factor workspace created before Step3+ execution.
- structured source of truth: `<factor_workspace>/objects/`
- human-readable production notes: `<factor_workspace>/knowledge/human_readable/`
- canonical structured knowledge: `<factor_workspace>/knowledge/canonical/`
- retrieval index: `<factor_workspace>/knowledge/retrieval/`
- repo-root `/Users/humphrey/projects/factor-factory/knowledge/因子工厂/` is an explicit export/vault target only; it is not the default production write path.

Do not use legacy duplicate roots as active knowledge stores:

- `/Users/humphrey/projects/factor-factory/knowledge/obsidian_vault/`
- `/Users/humphrey/projects/factor-factory/factorforge/objects/`

The S3 bundle may carry exported vault material, but production writes must originate from the workspace layout and include export provenance when copied to repo-root or S3-facing vault paths.

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


## Data Request Handoff

When Step3/Step4/Step6 blocks on missing Data API coverage, missing fields,
slow reusable minute state, absent full-window datamart proof, or an expensive
raw-minute recomputation that should become a reusable derived state, the
Ultimate agent must create a structured Data API request instead of asking the
user to forward requirements.

Use the Data API inbox contract:

```bash
python3 scripts/data_request_inbox.py new \
  --report-id <report_id> \
  --dataset-id <dataset_id> \
  --request-type new_datamart \
  --output factorforge/data/requests/inbox/data_request__<report_id>__<dataset_id>.json
```

The research loop should then report the `request_id` and wait for:

```bash
python3 scripts/data_request_inbox.py status <request_id>
```

Data API side should run the scanner instead of relying on the user to notify it:

```bash
python3 scripts/data_request_scanner.py once
```

Status handling:

- `PENDING`: do not ask the user to relay the data request; Data API has not closed it.
- `ACCEPT`: resume research only through the returned catalog/datamart/QA/worker-smoke proof.
- `BLOCK`: report the blocker and do not run proxy/full-window research unless the user explicitly approves a degraded scope.
- `INVALID` or `NOT_FOUND`: fix the request artifact or inbox sync before continuing.

This handoff does not authorize clean data mutation, search worker, official
promotion, Factor Forge production loop execution, or writing research
artifacts outside the active factor workspace.

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

The proof report is not worker authorization. If a validator fails, the proof
report may record the failure, but `runtime_context__<report_id>.json` must
remain absent and no agent should launch worker Step3B/Step4 from that run.

A run is not considered complete unless the wrapper proof report exists and has `status: PASS`. Ad-hoc metric tables, hand-written handoffs, or post-hoc Step4/5/6 objects are not valid substitutes for wrapper proof.

Legacy handoff or one-off Step3/4/5 drivers, including sample or factor-specific scripts, must hard block before writing canonical `objects/`, `runs/`, `generated_code/`, `evaluations/`, or `archive/` artifacts. They must not add environment bypasses or swallow `SystemExit` to present a successful formal run.

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

## Pre-Cost Information Before Trading-Cost Judgment

High turnover and trading cost must not be a one-vote veto on whether a factor
contains useful information. Step5/Step6 must first judge the factor's economic
structure and pre-cost information, then judge tradability and promotion.

Before rejecting a factor because turnover cost overwhelms current net NAV,
answer these questions:

- return source: is the factor mainly `risk_premium`,
  `information_advantage`, `constraint_driven_arbitrage` /
  `market_structure_arbitrage`, or `mixed`?
- economic logic and profit payer: who pays the premium, why does that party
  keep paying, and what observable proxy would falsify the payer story?
- pre-cost premium: do IC/rank IC, grouped returns, long-end gross returns, and
  Fama-MacBeth or cross-sectional regression evidence show a premium before
  cost?
- monotonicity: is the signal monotonic across groups and stable across full IS,
  IS subsamples, and OOS diagnostics?
- stochastic risk source: are volatility and max drawdown driven by continuous
  diffusion-like `sigma` exposure, jump/tail events, regime transitions, or
  liquidity/crowding state?
- implementation implication: is the factor a standalone candidate, a feature
  or risk state, a slower-horizon variant candidate, or a false mechanism?

For `risk_premium` factors, require stricter monotonicity and Fama-MacBeth /
cross-sectional regression support because the premium should be broadly priced
across the cross-section. For `information_advantage` factors, monotonicity may
be weaker, but the long end must show significant gross and risk-adjusted
return because the edge should concentrate where information is strongest.
For `constraint_driven_arbitrage` or market-structure arbitrage, require clear
constraint/payer logic, regime or event conditioning, and evidence that the
gross edge appears where the constraint binds.

Trading cost remains decisive for official promotion and live tradability. It
does not erase pre-cost information. A high-turnover factor with robust
pre-cost premium should usually be classified as `feature_candidate`,
`state_descriptor`, `needs_horizon_repair`, or `execution_research_needed`
rather than dismissed as no-information.

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
- "Use factor-forge-ultimate on this canonical formula starting from Step3; if Step6 wants revision, stop and show me the proposal first."
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

FactorForge is a general-purpose factor research framework, not a named-factor or family-template calculator. Step3B must execute the implementation route frozen by the measurement program and must not silently change routes after a failure. Unsupported or unsafe implementation must fail explicitly instead of borrowing sample/family code. Family plugins are explicit-contract only and never a fallback.

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
3. if subagents are unavailable, perform the Council roles sequentially itself
   as real research work, not as a deterministic scaffold;
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
7. resume `scripts/run_factorforge_ultimate_loop.py` until a terminal outcome
   is reached: `promote_official`, `reject`, `exhausted`,
   `max_loops_reached`, or a true BLOCK/failure requiring human judgment.

The main agent must not fabricate Council output by using `local_mock`, copying
old scaffold proposals, or writing generic result templates. It may only write
Council results that it or its delegated subagents actually researched from the
task packets. If valid Council results cannot be produced, BLOCK with a precise
reason instead of asking the user to drive the next command.

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

### Default Loop Objective

The default research objective is to run the formal Factor Forge path through
Step6, let Council decide promote/reject/revise, and continue through guarded
child-report revision loops until one of these stop conditions is reached:
`promote_official`, validated no-derived-revision proof blocks further work,
evidence/case comparison blocks further work, or 10 Council revision loops have
been reached.
At the 10-loop cap, if the factor is still not promotable but Council believes
substantial upside remains, stop and report the state to the user instead of
silently continuing.

### Ultimate Loop Orchestrator

`scripts/run_factorforge_ultimate_loop.py` is the thin Phase M orchestrator above
the existing official wrapper. It must call `scripts/run_factorforge_ultimate.py`
for every formal pass and must not call Step1-6 scripts directly.

The loop runner writes:

- `objects/runtime_context/ultimate_loop_report__{root_report_id}.json`
- `objects/runtime_context/ultimate_loop_brief__{root_report_id}.md`

It stops on promotion, true factor rejection, blocked evidence/prewrite state,
Council script checkpoint `awaiting_agent_results`, `awaiting_next_derivation`,
wrapper failure, missing approved child revision, forbidden side effects, or the
10-loop cap. It may continue to a child report only when a validated
`handoff_to_step3b__{report_id}.json` explicitly authorizes
`approved_for_step3b_handoff`; child report ids must be derived from the parent
as `{parent}__LOOPNN__{revision_id}`. A failed child branch before max loops is
`revision_branch_only` falsification, not factor-level rejection, unless Council
provides validated terminal authority. The orchestrator itself must not write
Step3B handoffs, official records, generated code, clean data, or search-worker
outputs.

At the skill level, `awaiting_agent_results` must be handled by autonomous
Council continuation above. The agent should not present it as the final answer
to the user unless it is technically unable to create valid Council results in
the current runtime.

## Mechanism Math Contract v2

Factor Forge treats a factor as a falsifiable market model first and a formula
second. Step1/2/6 artifacts preserve the chain: market behavior -> economic
hypothesis -> open tool search -> primary mechanism model -> market-outcome
projection -> observable estimator -> expected metric signature ->
falsification or revision logic. The primary model is selected from the
economic hypothesis; neither stochastic processes nor dimensional analysis is
universal. Formula explanations that merely restate the formula, or decorative
math without model objects, observable proxies and falsification, must BLOCK.
