---
name: factor-forge-ultimate
description: Run or supervise formal end-to-end Factor Forge research. Use for Step1-6, domain-specialist research organization, universal conjecture and falsification work, Council synthesis, factor proof certificates, revision loops, and official research decisions.
---

# Factor Forge Ultimate

## Role

Ultimate is the formal deep-research orchestrator. It combines the Step skills,
the current main agent's research judgment, dynamic Council routes, executable
evidence, and durable knowledge writeback.

Miner is a separate candidate factory. A report-led or named factor idea may
enter Ultimate directly; do not force it through Miner.

## Research Organization Contract

One user-facing task maps to one factor workspace and one Host Research
Director. Specialist Agents are internal isolated sessions, not separate
user-visible tasks. Read:

- `docs/architecture/factorforge-research-organization-v1.zh-CN.md`
- `docs/contracts/factorforge-research-org-plan-v1.zh-CN.md`
- `docs/contracts/factorforge-agent-task-result-v1.zh-CN.md`
- `docs/contracts/factorforge-research-org-runtime-v1.zh-CN.md`

For a new organization-aware run, the Host must freeze and validate
`identity/research_organization_plan.json` before specialist work. All input
snapshots, task packets, dispatch manifests, data requests and Agent results
must remain under
`objects/research_organization/<report_id>/`. The Host is the only canonical
merger; specialists return proposals or verification records and never mutate
Step artifacts, another role's result, shared data or canonical knowledge.

Route from the economic hypothesis and frozen estimand, not from field names,
operator availability or a preferred mathematical family. Fundamental and
Price-Volume are active domain plugins. Event/Text and Macro/Cross-Asset are
capability-gated until their skills and runtime routes exist. A required
unavailable domain is `WAITING_CAPABILITY`, not silent reassignment.

Only mechanism-bearing user evidence may activate a domain: an economic
hypothesis, research direction, explicit decision, or report argument. A title,
formula, operator list, field list, or code fragment may create auditable
exploratory candidates, but cannot select a domain by lexical resemblance. If
mechanism-bearing evidence is absent, set `NEEDS_CLARIFICATION`; do not let an
OHLCV-looking expression silently become a Price-Volume thesis.
Descriptive data-availability prose is also insufficient. A routed mechanism
must contain a causal or measurement predicate, a genuine economic actor/state,
and a payoff, valuation, pressure, reversal, premium, or other falsifiable
target state. The predicate must form an actual relational clause; co-occurrence
of one token from each marker family is not a mechanism. Noun phrases such as
`support levels` or `discount rate` are not relational clauses. Container wording such
as "this report contains evidence" does
not disqualify a statement that contains that complete mechanism triple; a
field inventory without the triple remains exploratory only.

The minimum organization is Research Director, applicable domain researcher,
Knowledge Librarian, Data Liaison, Quant Implementation, Validation & Evidence,
and Independent Council. Data Liaison may resolve catalogs, embed a proposed
`data_request_v1`, and verify delivery evidence; it may not write the staged
workspace or materialize data. The Host validates and atomically publishes an
embedded request under the current report before result admission.
`WAITING_DATA` is nonterminal and resumes only after catalog/QA/receipt
validation. The current implementation does not yet provide delivery import,
plan revision/current-pointer publication, in-place clarification resume, or
automatic data resume; do not claim those capabilities exist. A pre-formal
clarification pause must retain `factor_verdict=UNKNOWN` and instruct the user
to start a new isolated task with the added mechanism evidence.

Do not confuse pre-formal design feasibility with formal data acceptance. A
Host-validated active catalog may admit a base market dataset for plan authoring
while explicitly deferring dataset QA/read-smoke to the normal Step3 gate. That
does not authorize formal execution and cannot be used for derived-state reuse.
Derived datamarts and state dependencies remain `WAITING_DATA` until their QA,
lookahead, coverage, URI, provenance and required worker-read evidence are
actually bound.

Every role consumes `factorforge_agent_task_v1` and returns a
`factorforge_agent_result_v1` envelope. Public artifacts contain reproducible
definitions, decisive derivation steps, citations, assumptions and falsifiers;
private chain-of-thought is neither requested nor persisted. A
`single_agent_fallback` must be declared truthfully and cannot satisfy an
independent-session requirement. Independent Council requires a distinct real
session, must attest review of every role frozen in its task, and cannot be
impersonated by the Director or an authoring Agent.
The current v1 plan sets `single_agent_fallback=false`; therefore no current
specialist task may use fallback mode. A later contract may enable it only by
making that permission explicit in the frozen task.

A valid plan and dispatch manifest prove routing and workspace governance only.
They do not prove that multiple Agents executed, that Council independence was
satisfied, or that the factor passed research. Claim those stronger states only
after the Host validates every bound result and the normal Step1-6 evidence.

For a runtime-aware run, the Host uses
`scripts/run_factorforge_research_org_runtime.py`. Workspace runtime JSON is a
rebuildable projection only; the Host-private SQLite ledger and signed adapter /
Host receipts are authoritative. Each specialist must receive a staged,
role-scoped read-only context and a distinct provider session. The Independent
Council must have no parent author session. Retry, cancellation and recovery
must use ledger-owned attempt/runtime handles; never terminate sessions by a
global process/model-name match.

Keep these assurance levels distinct:

- `workspace_runtime_projection_valid_only`: workspace history is structurally valid;
- `transactional_runtime_unverified_sessions`: private ledger is valid, but formal signed/pinned session evidence is absent;
- `signed_specialist_runtime_complete_host_director_external`: all required roles PASS with signed, pinned, causally bound specialist sessions and signed Host admissions.

Only the last level may set runtime `formal_independence_verified=true`. It
still does not prove factor ACCEPT. To bind this proof into an Ultimate wrapper,
use `--research-org-runtime-mode formal-complete` with the private root, trust
root and installation ID. The default is `off` for backward compatibility;
do not silently upgrade a legacy run. Contract smoke output is never production
research proof.

For a production web task, the required order is fixed:

1. run signed Knowledge, Data and routed Domain intake sessions;
2. let the external Host Research Director synthesize their admitted public
   records into a validator-PASS web research plan;
3. require an agent-authored Director record that binds every intake result
   path/hash, the plan, public ledger and private Agent receipt; then admit that
   Host result with its real session identity;
4. run isolated Quant Implementation, pre-execution Validation & Evidence, and
   Independent Council sessions over the transitive, staged dependency context;
5. require runtime `COMPLETE` plus signed formal independence;
6. only then materialize and invoke Ultimate with
   `--research-org-runtime-mode formal-complete`;
7. run the normal post-execution Step6 empirical Council before any factor
   terminal decision.

The organization Council in step 4 audits research design and preregistration;
it is not the empirical Step6 Council and cannot claim backtest evidence or a
factor verdict. Web `COMPLETED` requires both the signed organization proof and
the normal Ultimate terminal evidence. A completed Ultimate report alone must
not bypass this gate.

Quant, pre-execution Validation, and organization Council must use the v3
pre-formal controlled-check contract. Their `claim_scope` is exactly
design-only, realized performance evidence is false, empirical verdict is
`NOT_ISSUED`, and promotion authority is false. The public record has a closed
shape: its claims exactly equal the ordered checks, and each check contains only
the frozen check ID, status, controlled finding/falsifier codes, and hash-bound
task/dependency evidence paths. Executive summaries are canonical, blockers
are check IDs, and free-text claims/findings/falsifiers or extra fields are
forbidden. Preregistered thresholds belong in the frozen Host plan or bound
design artifact, not in this pre-formal verdict record.

This closure extends to adjacent channels. The outer Agent result envelope and
its authority-bearing identity are exact-shape by independence class; Council attestation and formal verdict,
every `artifact_refs[]` item, and each canonical Data Liaison request ref reject
unknown fields. Rehashing a result does not authorize an extra note, verdict,
or claim outside the controlled v3 record.

The external Host Director receipt is not trusted merely because it is inside
the private job directory. Before admission, validate its exact agent-run
contract, job/factor/research/report identity, session-key hash, provider,
model, timestamps, return code, stdout/stderr tails, and equality to the
adapter-returned `AgentRunResult`.

Before Host Director admission, freeze exact IS/OOS windows, purge and embargo,
trial budget, multiple-testing policy, signal timestamp, entry/exit timing,
transaction/capacity model IDs, terminal success/reject/block conditions,
component ablations, falsifiers and promotion evidence. Vague experiment plans
do not satisfy specialist validation or Council.

For a recognized external formula dialect, implementation choices are not the
same as verified source meaning. Formal intake must bind either specific source
evidence (a locatable reference plus the actual excerpt, with its hash recomputed
or checked by the Host) or an explicit user research
override (reference, rationale and override reason), and attest that the choice
was not selected from backtest performance. Legacy semantic-choice-only
artifacts may be recognized for migration but cannot satisfy a new formal run
until v2 authority is supplied. An embedded request excerpt verifies submitted
content integrity, not external source authenticity; hash-only evidence is
invalid.

## Non-Negotiable Entry Contract

Before research:

1. inspect the repository status and active worktrees;
2. create or select exactly one
   `factor_research/<factor_id>/<research_id>/` workspace;
3. validate its manifest and identity;
4. keep code, results, Step3 runtime copy, Council, knowledge, branches and
   wrapper proof/report outputs under that workspace; an explicit
   `--proof-output` outside the active workspace is BLOCK;
5. read the relevant factor knowledge before formulating the conjecture;
6. never use `git add .`, mutate shared clean data, or write the repo-root
   knowledge vault implicitly.

Formal Step3-6 execution uses only:

```bash
python3 scripts/run_factorforge_ultimate.py ...
```

Direct Step scripts may be used only by bounded smokes or when Ultimate invokes
them. Unsupported data, identity, implementation parity or evidence is BLOCK.

`--dry-run` is an execution plan, never research proof. Its wrapper and loop
reports must use `status=DRY_RUN`, `formal_proof_eligible=false`, and
`proof_semantics=execution_plan_only`. A formal consumer accepts `PASS` only
when `dry_run=false`, the exact command contract executed with every command at
`PASS`, and Step6 actually ran the research-protocol verifier. Contract smokes
remain explicitly `contract_smoke_only` and are not promotion evidence.

## State Datamart Reuse Contract

Formal Step4 production must be state-dependency-aware. A factor law or child
spec that depends on reusable intraday/daily state must declare
`state_dependency_contract.contract_version=factorforge_state_dependency_contract_v1`.
Before Step4, Ultimate must either consume an existing
`state_resolution__<report_id>.json` or resolve the dependency contract against
the Data API catalog with `scripts/validate_factorforge_state_dependency.py`.

If the required datamart is missing, not QA ACCEPT, schema-mismatched,
coverage-insufficient, or lacks a lookahead/no-future-minutes policy, Ultimate
must BLOCK or return an awaiting-data outcome with `data_request_v1`; it must
not let Step4 fall back to a full-window raw minute scan. Bounded smoke can use
small fixtures, but it is not production evidence. Raw full-window minute
production is Data API work, not a Factor Forge Step4 fallback.

## Knowledge Reference Contract

Formal runs must preserve prior-knowledge provenance from Step1 through Step6.
Step1 writes `knowledge_reference_contract.contract_version=factorforge_knowledge_reference_contract_v1`
alongside `similar_case_lessons_imported`; Step2 preserves it in
`research_contract` and `learning_and_innovation`; Step6/Council writes
retrieval context for each revision. Cold-start is allowed only when explicitly
recorded with checked index paths, query hash, hit count, and fallback reason.
Missing provenance blocks formal acceptance even if a human-readable lesson
string is present.

## Math-First Authority Contract

Before Step3, Ultimate must verify the complete authority chain:

```text
economic hypothesis -> open mathematical-tool search
-> competing model families / selection -> primary math mechanism
-> market-outcome projection -> applicable audits
-> observation equation -> measurement program
-> operator | direct code | hybrid -> empirical falsification
```

Read and apply
`docs/contracts/mechanism_conditioned_measurement_program_v1.zh-CN.md` as the
current authority. Read `docs/contracts/mechanism_math_contract_v2.zh-CN.md`
only to validate or migrate an artifact that already contains the legacy v2
contract; never generate that legacy contract for a new run.

Knowledge/history/data may supply advisory priors, counterexamples and tool
candidates, but cannot override the math contract. The search space is open:
fundamental factors may select DCF, residual-income or accounting-identity
models; path-dependent or microstructure factors may select stochastic,
spectral, information-theoretic, functional, causal, optimization or newly
composed objects when justified. No family is a universal default. Specialized
audits such as dimensional analysis or stochastic-process diagnostics are used
only when the selected mechanism makes them relevant. Operators are optional;
direct code and hybrid are valid when each component is bound to a mathematical
term, measurement semantics, legal information set, expected metric signature
and falsifier.
Ultimate must BLOCK reverse-engineered economic stories, data-convenience
estimand drift, decorative math and missing public derivation records. Public
records contain reproducible definitions and decisive derivation steps, not
private chain-of-thought.

## Memory Pressure and Batch Execution Protocol

Every non-smoke run uses
`factorforge_research_conjecture_protocol_v1`. Read:

- `docs/contracts/factorforge-research-conjecture-protocol-v1.zh-CN.md`
- `docs/contracts/factorforge-factor-proof-certificate-v2.zh-CN.md`

The current agent must author the semantic artifacts. Deterministic scripts may
validate and materialize them, but must not invent the hypothesis, payer,
mathematical object, proof obligation, counterexample or synthesis.

Required protocol artifacts:

```text
objects/research_protocol/
  research_state__<report_id>.json
  research_conjecture__<report_id>.json
  approach_registry__<report_id>.json
  proof_obligation_ledger__<report_id>.json
  counterexample_registry__<report_id>.json
  factor_proof_certificate__<report_id>.json
  semantic_verifier_report__<report_id>.json
```

The protocol state machine is:

```text
FORMULATE -> DIVERSIFY -> ATTACK|DERIVE -> TEST
-> SYNTHESIZE -> REDIRECT|VERIFY -> ACCEPT|REJECT|BLOCK
```

### Step1
- ingest source report / idea
- identify canonical source and factor intent
- produce `alpha_idea_master`
- standardize and validate Step1 research fields: `step1_mathematical_object`, `target_statistic_hint`, `information_set_hint`, `initial_return_source_hypothesis`, `economic_hypothesis`, `math_hypothesis_candidates`, and `similar_case_lessons_imported`; the old `step1_random_object` name is read only as a legacy alias
- `economic_hypothesis` must first classify the broad source as `risk_premium`, `information_advantage`, `market_structure_arbitrage`, or `mixed`, then state the second-layer mechanism and the likely counterparty paying the return
- `math_hypothesis_candidates` must map the economic mechanism to report-specific mathematical tools. Do not use fixed mappings like "price-volume means microstructure"; use DCF/FCF/PEG, stochastic processes, jumps, cointegration, copulas, wavelets/Fourier, projection, dimensional/scaling analysis, or other tools only when they explain the report-specific counterparty and asset-price logic
- every candidate model must state its own `mathematical_object`,
  `mechanism_equation_or_functional`, `target_functional`,
  `market_outcome_projection`, and `observation_mapping`; keep the core
  mechanism distinct from its market-outcome projection into the executable payoff
- every formal research pass must include a flexible math-forced insight step:
  choose the mathematical object and tools from the economic hypothesis, state
  what the tools reveal, what information they preserve or discard, how the
  insight maps to an observable estimator, and what evidence would falsify it.
  This is a menu of justified tools, not a fixed checklist.
- researcher records the author's thesis and what must be true for the idea to work

## Staged Workflow

### 1. Intake and Formalization

Run Step1-2, then stop and inspect their artifacts. The main agent must:

- state who pays/receives, the persistent constraint and observable falsifier;
- define the selected mathematical object, mechanism equation or functional,
  market-outcome projection, observation/estimation map and information set;
- map every formula component to model term, preserved/deleted information and
  an ablation;
- freeze `claim_class`, IS/OOS windows, purge/embargo, trial budget,
  multiplicity policy, cost/impact/capacity policy and terminal criteria;
- register at least three routes, including a null/alias route.
- freeze the mechanism-conditioned measurement program and verify that route
  choice follows mathematical/numerical need rather than operator availability.

Materialize only agent-authored inputs with:

```bash
python3 scripts/write_factorforge_research_protocol.py \
  --workspace-root <factor_workspace> \
  --report-id <report_id> \
  --state <state.json> \
  --conjecture <conjecture.json> \
  --approaches <approaches.json>
```

Validate `--stage pre_council` before expensive research.

### 2. Implementation and Evidence

Run Step3-5 through Ultimate. Audit:

- formula/code identity and legal-time information;
- Data API catalog/state reuse before raw scans;
- implementation parity and component ablations;
- exact universe/masks/window/sample;
- IS evidence without OOS search leakage;
- long-side economics after volatility, transaction cost and capacity.

Update the obligation and counterexample ledgers with actual executable tests,
verifier identities, workspace-local evidence paths and SHA256 hashes.

### 3. Factor Proof Certificate

All claim classes require IC, ICIR, volatility cost, transaction cost, maximum
drawdown and long-end return. Fama-MacBeth and quintile/decile monotonicity are
mandatory only for `claim_class=risk_premium`.

For non-risk-premium factors, bucket plots may diagnose shape but must not be a
universal acceptance gate. Long-short and short-leg results are diagnostic only.

Thresholds must be registered before evaluation. The verifier recomputes metric
identities and the final verdict. Every required metric must bind to its own
trusted-verifier report, exact metric payload, and the same dataset-snapshot
and window hashes. The locked rule set must bind factor/report/claim/window and
the frozen search-trial ledger, and contain at least one rule on a core decision
field for every required metric family. A formal
`promote_official` decision is blocked before official writeback unless this
certificate derives `ACCEPT`.

Use the formal release sequence. Do not inspect the OOS panel through
`--identity-only` before threshold registration:

```bash
python3 scripts/write_factorforge_evaluation_release_chain.py freeze-search ...
python3 scripts/write_factorforge_evaluation_release_chain.py register-threshold \
  --workspace-root <factor_workspace> \
  --spec <metric_verifier_spec.json> \
  --decision-rules <decision_rules.json>
python3 scripts/write_factorforge_evaluation_release_chain.py release-oos \
  --workspace-root <factor_workspace> \
  --panel <frozen_oos_panel> \
  --spec <metric_verifier_spec.json>

python3 scripts/build_factorforge_metric_verifier_reports.py \
  --workspace-root <factor_workspace> \
  --panel <frozen_oos_panel> \
  --spec <metric_verifier_spec.json>

python3 scripts/validate_factorforge_factor_proof.py \
  --workspace-root <factor_workspace> \
  --report-id <report_id>
```

For a web-created task, its plan materializer performs the freeze-search and
threshold-registration stages before Step4. The formal wrapper must run
`scripts/finalize_factorforge_web_factor_proof.py` immediately after Step4
validation. That finalizer releases and replays the exact plan-bound panel,
writes the factor-proof certificate and bound verifier, and fails closed on
plan, calendar, label, risk-control, panel or hash drift. Re-running an already
finalized proof is permitted only as an identical verified replay.

The release command binds actual OOS dates, at least 60 daily periods, panel
hash, locked rules and the frozen trial ledger. The full verifier must consume
that same panel and threshold file. The certificate validator replays the
panel/spec with the current verifier source. Do not hand-author passed metric
evidence. This is a tamper-evident local ordering contract, not an external
trusted timestamp; hard OOS secrecy requires an independently controlled data
release service.

Formal metric-verifier v2 accepts only a disjoint one-trading-day return path:
`forward_return_horizon_days=1`, `holding_period_days=1`,
`return_path_mode=daily_one_period_forward_return`, daily rebalance, and
`execution_timestamp=label_start_timestamp`. The atomic panel must also carry
signal date, label start/end dates, and label start/end prices. The verifier
must use the complete authoritative calendar independently resolved by
`factorforge_data_access.trade_cal_csv`; its actual file must be outside the
factor workspace. Its normalized open-date snapshot must match the repo-tracked
trusted calendar registry as read from its approved Git anchor commit/blob.
Formal specs must declare `verification_scope=production`, and the release/proof
chain must bind the raw file SHA, normalized snapshot SHA, registry SHA, anchor
commit/blob, and explicit snapshot id. A task or directory name containing
`SMOKE` cannot relax this scope. The verifier must
prove consecutive trading dates and daily signal coverage, and recompute
`label_end_price/label_start_price-1`; self-reporting horizon 1 is insufficient.
Multi-day rolling labels may
support IC/Fama-MacBeth/mechanism diagnostics, but must not be compounded as
daily long-end returns. Until a daily holding/NAV cohort engine or an explicit
non-overlapping stride contract exists, a `t+5` formal portfolio proof is
BLOCK. A locked threshold registration is immutable: identical retry is
idempotent, while different content at the same path is BLOCK.

Long-end admission uses geometrically compounded net return plus positive
terminal/minimum wealth. Arithmetic gross-minus-cost return is reconciliation,
not a substitute. Risk-premium quantiles are value based; unresolved ties that
collapse 5/10 buckets BLOCK rather than being split by asset order.

`component_validated` also requires deterministic full-versus-ablated evidence:

```bash
python3 scripts/build_factorforge_component_obligation_report.py \
  --workspace-root <factor_workspace> \
  --panel <full_vs_ablated_oos_panel> \
  --spec <component_obligation_spec.json>
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
- under a log-growth model, variance drag may be diagnosed with
  `-0.5 * sigma^2`; this portfolio diagnostic does not make a stochastic
  process the factor's core mechanism;
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

Math discipline is mandatory, but tool choice is flexible. Agents must not
decorate reports with generic SDE/physics language or force every candidate
through the same checklist. They must instead justify the selected mathematical
object from the economic hypothesis, use the smallest tool set that forces a
testable insight, and record information preserved, removed, aliased, or made
untradeable by the transformation.

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

FactorForge is a general-purpose factor research framework, not a named-factor or family-template calculator. Step3B must execute the implementation route frozen by the measurement program; it must not prefer an operator when the selected mathematical object requires trusted hybrid or direct code, and it must not change routes after a failure. Unsupported or unsafe implementation must fail explicitly instead of borrowing sample/family code. Family plugins are explicit-contract only and never a fallback.

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

Factor Forge treats a factor as a falsifiable market-process model first and an
implementation second. The authoritative chain and stage obligations are in the
two contracts referenced under `Math-First Authority Contract`; do not duplicate
or weaken them here. Council revisions must name the exact failed/revised layer,
preserved invariants and new discriminating evidence before any child execution.
