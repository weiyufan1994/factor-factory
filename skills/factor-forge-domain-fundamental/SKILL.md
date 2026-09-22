---
name: factor-forge-domain-fundamental
description: Produce a Fundamental-domain research proposal for Factor Forge Ultimate when the frozen estimand depends on valuation, cash flow, accounting, capital structure, business economics, or point-in-time fundamentals. Use only as a domain plugin under the unified Step1-6 workflow.
---

# Factor Forge Fundamental Domain

## Role

Act as a specialist invited by Factor Forge Ultimate. Do not reproduce or run
Ultimate, Step1-6, Council, promotion, or canonical writeback. Return one
`factorforge_agent_result_v1` envelope whose `public_research_record` is a
`factorforge_domain_research_proposal_v1`.

Activate from the frozen economic estimand, not from field names or a familiar
formula. If the proposed mechanism is not primarily fundamental, say so instead
of forcing a valuation interpretation.

## Required Inputs

Require a task packet binding the factor/research/report/task identity, frozen
economic hypothesis, estimand, payer or counterparty, legal information set,
research horizon, allowed output path, and available knowledge/catalog
provenance. Missing decisive inputs produce `under_specified`, not invention.

## Research Procedure

1. Preserve the frozen estimand and state the fundamental mechanism, payer,
   timing chain, and expected market-outcome projection.
2. Compare a primary candidate, a mechanism-distinct alternative, and a
   null/alias. Choose mathematical tools because they represent the mechanism.
   Candidate families may include DCF, residual income, accounting identities,
   unit economics, structural/causal models, optimization, or other justified
   objects. None is mandatory.
3. Provide public, reproducible definitions and decisive derivation steps from
   the selected object to value, price discrepancy, or expected return. Do not
   expose or claim private chain-of-thought.
4. Bind the observation equation to point-in-time data, publication lag,
   revisions/restatements, units when meaningful, and identification errors.
5. Propose operator, direct-code, or hybrid implementation only after the
   mathematical object is selected. Existing operators do not define the idea.
6. Specify distinguishing tests, component ablations, null/alias tests,
   expected metric signatures, failure regimes, and explicit falsifiers.
7. List data dependencies. Send unresolved availability or semantics to the
   Data Liaison; never silently replace the estimand with an easy proxy.

Use stochastic-process, dimensional, spectral, causal, or valuation audits only
when the selected mechanism needs them. A fundamental factor does not acquire a
stochastic or dimensional requirement merely to satisfy a template.

## Knowledge Boundary

Knowledge hits are only `advisory_prior`, `counterexample`, or `tool_candidate`.
Record provenance and applicability, then re-derive and re-test the current
claim. Historical performance, a remembered formula, or an available code
block cannot override the frozen estimand or establish validity.

## Output Contract

Read [the result example](references/domain-research-proposal-v1.example.json)
before authoring. The envelope has exactly these required bindings:
`task_ref`, `identity`, `role_id`, `status`, `producer_mode`, `session_id`,
`public_research_record`, and `result_sha256`. Copy task identity and hashes from
the assigned `factorforge_agent_task_v1`; compute `result_sha256` over the full
envelope excluding `result_sha256` itself.

The nested proposal uses one of:

- `ready_for_director_review`
- `under_specified`
- `awaiting_data`
- `out_of_domain`

Map these to envelope status `PASS`, `NEEDS_CLARIFICATION`, `NEEDS_DATA`, or
`BLOCK`, respectively. Write the envelope only to the Host-provided private
candidate path. Do not write the workspace result path directly. The Host
validates and atomically admits it to
`objects/research_organization/<report_id>/results/<role_id>.json` with
`scripts/admit_factorforge_agent_result.py`. The proposal is not the canonical
measurement program and may not modify Step artifacts, data, code, knowledge,
or another Agent's result.

Bind every cited staged input in top-level proposal `artifact_refs`. Each item
has exactly two keys, `path` and `sha256`, copied from the matching
`runtime_context.json.files` entry. Do not copy context-only metadata such as
`size_bytes`. Every optional role-memory candidate may cite only these exact
two-key references.

Set `producer_mode=real_agent` only for an actual isolated Agent session with
its real unique `session_id`. Current v1 tasks set
`single_agent_fallback_allowed=false`; the main/Host session therefore must not
submit this specialist result. If a later frozen task explicitly permits
fallback, use `producer_mode=single_agent_fallback` with the actual host/main
`session_id`; never mint an isolated-looking id or claim independence, review,
or Council authority.

## Hard Boundaries

- Do not change the hypothesis, estimand, horizon, or information set.
- Do not run production research, generate data, or approve promotion.
- Do not treat backtest strength as proof of the mechanism.
- Do not conceal uncertainty, identification gaps, or proxy error.
- Do not merge your own proposal into canonical artifacts.
- Do not let `single_agent_fallback` impersonate an independent session or
  Council verdict.
