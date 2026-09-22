# Hosted organization and Console runtime

Read only for an existing hosted organization/Console/Web route; ordinary local IS does not activate this contract. Repository-relative docs paths resolve from the selected checkout.

## Research Organization Contract

For hosted organization-aware research, one user-facing task maps to one
factor workspace and one Host Research Director. This section does not impose
Host deployment on local IS research. Specialist Agents are internal isolated sessions, not separate
user-visible tasks. Read:

- `docs/architecture/factorforge-research-organization-v1.zh-CN.md`
- `docs/contracts/factorforge-research-org-plan-v1.zh-CN.md`
- `docs/contracts/factorforge-agent-task-result-v1.zh-CN.md`
- `docs/contracts/factorforge-research-org-runtime-v1.zh-CN.md`
- `docs/architecture/factorforge-researcher-memory-evolution-v1.zh-CN.md`

For organization-aware console runs, also use
`factor-forge-researcher-memory`. The Host freezes one role-specific memory
snapshot before dispatch and keeps specialist sessions disposable. Role memory
is advisory and cannot select the current estimand, prove the current factor,
or mutate skills. Agents may emit workspace-local learning candidates only;
final outcome recording, independent review, and canonical promotion remain
separate Host actions. A promotable candidate must carry the signed source
runtime and Host admission chain plus a Host-signed candidate materialization
receipt. Independent review freezes the current canonical role-memory snapshot,
runs through the dedicated disposable reviewer entrypoint, and requires its
adapter-signed full session receipt; the lower-level admission CLI cannot
manufacture session independence. The Host records only normalized terminal
`COMPLETED + ACCEPT/REJECT` outcomes; `ACCEPT` requires formal-proof eligibility.
A different reviewer session plus adapter- and Host-signed exact-binding
receipts are required, not just reviewer labels. Review and promotion bind the
exact parent manifest generation; stale or duplicate canonical content blocks.
A legacy memory-off plan stays memory-off on resume.

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
only when its deterministic Host information-policy attestation passes, while
explicitly deferring dataset QA/read-smoke to the normal Step3 gate. Free text
does not establish PIT legality. That does not authorize formal execution and
cannot be used for derived-state reuse.
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

New Knowledge Librarian tasks use `factorforge_knowledge_prior_record_v1`, not
the generic role record. Historical claims must copy exact text from an
admitted node/path in the frozen `factor_knowledge_summary.json`; historical
metrics must bind exactly to `evidence.key_metrics.<key>`. The Host reconstructs
query hash, top-k, cold-start state and ordered node IDs from the captured
payload. Agent-authored retrieval provenance, free claim prose, metric aliases,
or inference about the current factor must BLOCK. Keep file-byte artifact hashes
distinct from task snapshot content hashes. A task already frozen with the old
generic record remains resumable/cancellable only and must not be silently
migrated to the new shape. This migration accepts only the exact hash-bound
legacy registry whose sole policy difference is that old Knowledge output
contract; any other registry drift remains BLOCK. Claims have neither a free
ID nor a statement field, and captured provenance must contain a 64-hex query
hash plus a positive integer top-k.

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
   terminal decision, except when the EVO V2 pre-OOS gate has admitted a
   qualified contradiction; that branch must run its revision Council on
   purged IS before OOS and must never reopen revision after OOS release.

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

Evidence admission follows the frozen direct and transitive dependency graph.
A pre-formal role may cite an admitted dependency result or that result's
hash-bound public artifacts only when the exact file is also present in its
staged runtime manifest. Staged visibility alone grants no evidence authority;
the validator and context builder must compute the same dependency closure.

For an Independent Council runtime result, `independence_attestation` and
`formal_independent_verdict` are private-output envelope fields and exact
siblings of `public_research_record`. Never nest either field inside the public
record. The public record remains limited to its controlled design-review
shape.

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
