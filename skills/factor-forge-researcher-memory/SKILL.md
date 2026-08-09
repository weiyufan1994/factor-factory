---
name: factor-forge-researcher-memory
description: Govern persistent Factor Forge researcher-role memory across otherwise ephemeral agent sessions. Use when initializing or validating the Host-private memory store, freezing role-specific memory into an isolated factor workspace, reviewing learning candidates, promoting approved lessons, auditing role performance, or diagnosing memory isolation and provenance blockers.
---

# Factor Forge Researcher Memory

Use persistent **role memory** with disposable model sessions. Treat memory as
historical advisory evidence, never as authority over the current economic
hypothesis, mathematical mechanism, data contract, or formal backtest.

## Non-Negotiable Boundaries

- Keep the canonical store outside the Git repository and every factor workspace.
- Freeze one immutable snapshot per required role before dispatch. Never refresh
  it during retry or resume.
- Stage only the current role's snapshot. Never expose peer-role snapshots as
  shared task inputs.
- Let agents write at most three workspace-local candidates. Never let an agent
  write canonical memory, edit skills, change its role policy, or self-promote.
- Require the Host-signed candidate materialization receipt. A candidate content
  hash alone is not authorization and must not survive lesson-content changes.
- Require an admitted terminal Host outcome before review. Only normalized
  `COMPLETED + ACCEPT/REJECT` outcomes enter memory. `ACCEPT` requires formal
  proof eligibility; an evidence-bound `REJECT` may still yield a reusable
  falsification lesson. Require verified COMPLETE organization runtime evidence
  for organization-aware Console outcomes, and dereference the formal receipt
  plus every evidence-tree binding rather than accepting path-shaped strings.
- Require a real, disposable reviewer session launched through
  `run_factorforge_researcher_memory_review.py`. It must produce an Ed25519
  runtime-adapter receipt, followed by a Host admission receipt bound to the
  exact source session, candidate, outcome, reviewer-selected decision, and
  rationale. Freeze the current canonical role-memory snapshot into the review
  context, and bind the full reviewer request/output, model, transport,
  isolation, completion receipt, review parent, and expected parent generation.
  Caller-supplied reviewer labels alone are not independence evidence.
- Require explicit Host promotion. A stale parent generation must block instead
  of silently rebasing. Reject a second conflicting review of one candidate and
  semantically duplicate canonical lessons. Outcome, review and promotion
  writes use a recovery journal and must be idempotent after interruption.
- Do not store private chain-of-thought, credentials, absolute host paths, or
  unreferenced claims. Store concise lessons, applicability/failure conditions,
  and public evidence references only.
- Never use repo-root `knowledge/因子工厂` as the runtime memory store. That tree
  is an explicit export surface only.

## Workflow

1. Inspect `git status --short --branch` and the target workspace manifest.
2. Initialize the Host-private store with
   `scripts/init_factorforge_researcher_memory.py`.
3. Build the research organization plan through the formal console or
   `scripts/build_factorforge_research_org_plan.py --researcher-memory-root ...
   --installation-id ...`. Confirm each task has exactly one `role_memory`
   snapshot reference.
4. Run the normal research organization. The canonical
   `factorforge_agent_result_v1` remains unchanged; candidate proposals are
   stripped from that result and materialized separately under
   `objects/research_organization/<report_id>/memory_candidates/`.
5. Let the normal Console/runtime record the final outcome event after Host
   attestation byte readback and status normalization. Candidate/outcome APIs are
   Host internals; do not manually fabricate those records or infer an outcome
   from specialist `PASS` results. Treat memory write failure as a secondary,
   retryable governance failure; never rewrite the already published factor
   verdict.
6. Run `scripts/run_factorforge_researcher_memory_review.py`. It creates a
   read-only staged context, launches a genuinely separate adapter-owned Agent
   container, lets that reviewer select `APPROVE_CANONICAL` or `REJECT`, signs
   the exact claim, and admits it with the Host countersignature. The lower-level
   `review_factorforge_researcher_memory_candidate.py` remains receipt-admission
   only; never use it to invent a reviewer identity or an operator-authored
   decision. If the formal reviewer runtime is unavailable, leave the candidate
   pending.
7. Promote only an `APPROVE_CANONICAL` review with
   `scripts/promote_factorforge_researcher_memory_candidate.py`.
8. Run `scripts/validate_factorforge_researcher_memory.py` and validate the
   factor workspace bundle after every review or promotion.

## Decision Rules

- Use `REJECT` review for unsupported, overfit, duplicated, private, or
  non-transferable lessons.
- Use `APPROVE_CANONICAL` only when the candidate is evidence-bound, concise,
  reusable beyond the source factor, and states where it should fail.
- Do not promote a numerical performance claim as a universal lesson. Preserve
  its sample, verdict, proof eligibility, and applicable regime.
- A terminal `REJECT` may teach a bounded failure pattern even when formal proof
  eligibility is false. An `ACCEPT` outcome without formal proof eligibility is
  never admissible memory evidence.
- If the external store is unavailable or invalid, block memory-enabled plan
  construction. Existing memory-off plans remain valid and must not be upgraded
  in place.
- Do not repair or populate an arbitrary existing directory. Root, lock,
  temporary-write directory, transaction journal, file modes, official Host
  attestation semantics, formal receipt/evidence-tree contents, source runtime
  receipts, candidate materialization signature, full reviewer runtime chain,
  and both review signatures must all pass readback validation.

## Required Readback

Report the store ID and generation, frozen snapshot generation, candidate and
review IDs, promotion generation, validator verdict, and factor verdict that
produced the lesson. Never describe candidate creation as canonical learning.
