---
name: factor-forge-ultimate
description: Run or supervise formal end-to-end Factor Forge research. Use for Step1-6, universal conjecture and falsification work, Council synthesis, factor proof certificates, revision loops, and official research decisions.
---

# Factor Forge Ultimate

## Role

Ultimate is the formal deep-research orchestrator. It combines the Step skills,
the current main agent's research judgment, dynamic Council routes, executable
evidence, and durable knowledge writeback.

Miner is a separate candidate factory. A report-led or named factor idea may
enter Ultimate directly; do not force it through Miner.

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

## Research Protocol

Every non-smoke run uses
`factorforge_research_conjecture_protocol_v1`. Read:

- `docs/contracts/factorforge-research-conjecture-protocol-v1.zh-CN.md`
- `docs/contracts/factorforge-factor-proof-certificate-v1.zh-CN.md`

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

Each run must preserve preferred, null and alternative hypotheses; at least
three mechanism-distinct routes; null/alias and boundary/regime/payer attacks;
explicit test budgets; sealed OOS; and evidence-hash lineage.

## Staged Workflow

### 1. Intake and Formalization

Run Step1-2, then stop and inspect their artifacts. The main agent must:

- state who pays/receives, the persistent constraint and observable falsifier;
- define latent state, observation equation, estimator, return law and
  information set;
- map every formula component to model term, preserved/deleted information and
  an ablation;
- freeze `claim_class`, IS/OOS windows, purge/embargo, trial budget,
  multiplicity policy, cost/impact/capacity policy and terminal criteria;
- register at least three routes, including a null/alias route.

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

The release command binds actual OOS dates, at least 60 daily periods, panel
hash, locked rules and the frozen trial ledger. The full verifier must consume
that same panel and threshold file. The certificate validator replays the
panel/spec with the current verifier source. Do not hand-author passed metric
evidence. This is a tamper-evident local ordering contract, not an external
trusted timestamp; hard OOS secrecy requires an independently controlled data
release service.

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

This verifier must close both `measurement_validity` and
`component_ablation`. Economic-game, payer and stochastic claims without a
dedicated trusted verifier remain open; Council prose cannot convert them to
passed.

### 4. Council and Synthesis

Council routes come from the approach registry, not fixed ceremonial roles.
Early critic routes must be blind to the favored thesis. Dispatch must bind:

- report/task/route/role identity;
- route fingerprint and blind-context hash;
- expected agent identity;
- task-packet and result SHA256.

The root agent compares assumptions and evidence. No majority vote, average
opinion or automatic synthesis is allowed. It must address every route,
dissent, exact gaps, source result hashes, the selected law hash and open proof
obligations.

Final semantic validation independently opens the selected Council result
files, runs the formal result validator against their dispatch/task packets,
recomputes their hashes, and confirms that the selected law is present in the
bound source result. A syntactically valid but invented result hash is not
sufficient. Local Council mocks prove only the contract and must report
`contract_mock_completed`, never agentic completion.

Only an explicit main-agent approval source may activate a revision. Approval
runs Step6 validation and the final research protocol verifier; failure rolls
back active handoff writes.

### 5. Decision and Loop

- `promote_official`: requires accepted factor proof, component validation,
  after-cost long-side evidence and no unresolved blocker. Step6 runs the
  `pre_promotion` semantic gate before any official write, including a
  no-revision promotion path.
- `iterate`: one mechanism-linked revision, frozen parent identity, explicit
  expected metric signature, falsifiers, kill criteria and new trial budget.
- `reject`: preserve the failed law, evidence, anti-pattern and conditions for a
  genuinely new branch.
- `blocked`: name the exact missing data, identity, proof or authorization.

Do not turn portfolio construction, short-leg adoption, decile trading or
shared-data mutation into a factor-expression repair.

## Completion Standard

Report separately:

- formal wrapper status;
- research protocol verdict;
- factor proof verdict;
- Council/root-synthesis status;
- production evidence boundary;
- modified workspace/repository state.

A passing smoke, completed artifact set or Council file is not production
research proof.

## On-Demand Reference

Read `references/legacy-operations-reference.md` only for historical artifact
schemas, old command variants, compatibility behavior or detailed operational
troubleshooting. Search it by the relevant script or blocker token instead of
loading it wholesale.
