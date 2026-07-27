---
name: factor-forge-step6
description: Perform Factor Forge Step6 research judgment, dynamic Council review, factor-proof verification, revision control, and library/knowledge writeback after Step4/5 evidence.
---

# Factor Forge Step6

## Purpose

Step6 is the research judge and loop controller. It interprets Step4/5 evidence,
attacks the active thesis, compares prior knowledge, decides
`promote_official|iterate|reject|needs_human_review`, and writes durable records.
It does not manufacture missing metrics.

Formal execution is through `scripts/run_factorforge_ultimate.py`. All artifacts
stay under the active factor workspace.

## Required Inputs

- factor run/case/spec masters and formal Step5 handoff;
- Step4/5 metric, chart and backend evidence;
- researcher journal or independent researcher memo;
- knowledge-reference provenance;
- research state, conjecture and approach registry;
- before revision: proof-obligation and counterexample ledgers;
- before promotion/final approval: factor proof certificate.

Missing formal evidence is BLOCK, not a fixture or narrative fallback.

## Research Judgment

Step6 must state:

1. the preferred, null and alternative hypotheses;
2. the economic game: payer/receiver, binding constraint, persistence,
   price-path transfer and observable falsifier;
3. the mathematical object: state, observation, estimator, return equation,
   information set, limiting cases and alternative models;
4. formula-component mappings and ablation results;
5. evidence quality, failure regimes and what would change the decision;
6. the current mechanism claim level.

Allowed claim levels rise only with evidence:

```text
narrative_only
-> math_framed
-> metric_candidate
-> metric_consistent
-> component_validated
-> stochastic_validated | payer_validated
```

`metric_consistent` requires an accepted factor-proof certificate.
`component_validated` additionally requires verified measurement-validity and
component-ablation obligations from
`factorforge_component_obligation_verifier_v1`. Stochastic and payer claims
require their own trusted executable verifiers; until such a verifier exists,
retain the evidence as falsifiable research and do not label the obligation
`passed`.

## Factor Proof Policy

Read `docs/contracts/factorforge-factor-proof-certificate-v2.zh-CN.md`.

Common proof obligations:

- IC and ICIR, with conventions and arithmetic reconciliation;
- realized volatility drag and half-variance benchmark;
- gross-to-net transaction-cost reconciliation;
- maximum drawdown and recovery geometry;
- executable after-cost long-end return;
- metric-matching evidence file, exact metric-payload equality, verifier and
  SHA256 binding;
- one shared dataset-snapshot and window hash across required metrics;
- actual observed OOS dates and at least 60 daily periods;
- `verification_scope=production` plus an explicit calendar snapshot id bound
  to the approved trusted-registry Git commit/blob; `SMOKE` naming is never an
  authority;
- frozen search-trial ledger, locked threshold registration and one-time OOS
  release manifest in strict sequence;
- trusted metric-verifier identity and verifier-report contract;
- locked threshold-file hash bound to factor/report/claim/window and search
  ledger identity before the OOS panel is bound;
- one verdict rule on a core decision field per required metric family, and an
  automatically derived verdict.

Formal `promote_official` is blocked before official writeback unless the
certificate verdict is `ACCEPT`.

Build required evidence from the frozen OOS panel with
`scripts/build_factorforge_metric_verifier_reports.py`; its bundle is the
source of certificate metrics and evidence bindings. Researcher-written metric
JSON or Council prose is not a trusted verifier report.

Before that verifier, use
`scripts/write_factorforge_evaluation_release_chain.py` in this exact order:
`freeze-search`, `register-threshold`, `release-oos`. Formal threshold
registration must not use `--identity-only` to inspect the OOS panel. The
release command binds its actual dates, period count and dataset hash. This is a
local tamper-evident chain, not an external trusted timestamp.

For `measurement_validity` and `component_ablation`, freeze a same-window panel
containing full signal, ablated signal and legal forward return, register the
delta rules, and run:

```bash
python3 scripts/build_factorforge_component_obligation_report.py \
  --workspace-root <factor_workspace> \
  --panel <full_vs_ablated_oos_panel> \
  --spec <component_obligation_spec.json>
```

Both metric and component evidence are replayed from their panel/spec by the
final kernel. A copied verifier ID, source hash, or hand-authored PASS file is
not proof.

Only `claim_class=risk_premium` requires Fama-MacBeth risk-price evidence and
quintile/decile monotonicity. Do not reject an event, threshold, liquidity-rent
or information-rent factor merely because all buckets are not monotonic.
Long-short spread and the short leg never substitute for long-end admission.
Formal long-end admission uses net geometric return and positive wealth, not
the arithmetic gross-minus-cost reconciliation. Ties may not be broken by asset
order to manufacture full quantile buckets.

## Dynamic Council

Council tasks must be generated from open approach-registry routes. Required
route families include economic game, latent-state measurement and null/alias
attack. Add cost, regime, implementation, data or symbolic-law routes when the
actual gaps require them.

At least two early routes must be blind to the favored thesis. Each dispatch and
result binds task ID, route ID/family, route fingerprint, blind-context hash,
expected agent identity, task-packet SHA256 and result SHA256. Reusing one agent
identity across supposedly independent blind routes is invalid.

Council results must contain:

- assumptions and attempted derivation;
- proof obligations addressed;
- counterexample attack;
- candidate executable law or exact blocker;
- evidence references and uncertainty;
- no canonical write permission.

Every source result selected by root synthesis is re-run through the formal
Council result validator against its dispatch/task packet. Matching hashes alone
are insufficient. A local contract mock is labeled `contract_mock_completed`
and is never independent-agent research evidence.

## Root Synthesis

The main agent must cover every registered route and state:

- disposition and exact gap/closed obligation;
- incompatible assumptions;
- discriminating evidence;
- dissent resolution;
- selected route/result hashes and law hash;
- open proof obligations;
- why the next action is exploit, explore, audit or stop.

Majority vote and automatic approval are forbidden. An explicit
`--approval-source` is required. Approval must pass both `validate_step6.py` and
the final research protocol verifier before a Step3B handoff remains active.

## Revision Rules

An `iterate` decision may propose one bounded mechanism-linked revision:

- preserve parent formula/code/data identity;
- name the mathematical object being changed;
- state expected metric signature, ablations, falsifiers and kill criteria;
- allocate a fresh trial budget;
- keep OOS sealed;
- require human approval before code mutation.

Forbidden repairs:

- portfolio-expression tuning;
- adopting the short leg;
- decile trading as factor logic;
- implicit clean-data or baseline Step3 mutation;
- reopening a blocked route without new mechanism, data, invariant or
  counterexample evidence.

## Validation and Writeback

Before Council:

```bash
python3 scripts/validate_factorforge_research_protocol.py \
  --workspace-root <factor_workspace> \
  --report-id <report_id> \
  --stage pre_council
```

Before revision:

```bash
python3 scripts/validate_factorforge_research_protocol.py \
  --workspace-root <factor_workspace> \
  --report-id <report_id> \
  --stage pre_revision
```

Before any official write, including a no-revision promotion:

```bash
python3 scripts/validate_factorforge_research_protocol.py \
  --workspace-root <factor_workspace> \
  --report-id <report_id> \
  --stage pre_promotion
```

Final synthesis approval runs `--stage final`.

Every attempt enters the full experiment library. Only verified promotion enters
the official library. Rejections and blocked routes still write workspace-local
knowledge with identity, evidence boundary, anti-pattern and reopen condition.
Repo-root knowledge is an explicit audited export only.

## On-Demand Reference

Read `references/legacy-operations-reference.md` only for historical schemas,
legacy Council modes, detailed field lists or compatibility debugging.
