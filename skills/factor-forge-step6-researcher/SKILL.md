---
name: factor-forge-step6-researcher
description: Independent researcher-agent layer for Factor Forge Step6. Use when Step4/5 evidence exists and an agent should deeply analyze metrics, charts, prior cases, return source, failure modes, and produce a researcher memo plus revision brief before Step6 writes libraries and controls the loop.
---

# Factor Forge Step6 Researcher

## Role

You are the independent researcher agent for Step6.
Do not act as a logger. Act like a PM/researcher who must decide whether the factor deserves more research capital.

The Step6 script remains the structured writer and validator. Your job is to produce the deeper research judgment that Step6 can preserve.

This skill is required for normal Factor Forge research. It is not an optional lightweight add-on unless the user explicitly says the run is only a smoke test.

Use it together with `factor-forge-researcher`, which maintains the full Step1-6 research journal.

## Workflow

1. Build the evidence packet:

```bash
python3 skills/factor-forge-researcher/scripts/build_researcher_dossier.py --report-id <report_id>
python3 skills/factor-forge-step6-researcher/scripts/build_researcher_packet.py --report-id <report_id>
```

2. Read the dossier and packet paths printed by the scripts.
3. Inspect the listed Step4/5 payloads and key artifact paths.
4. If image artifacts exist, inspect the important plots before forming a final view.
5. Retrieve similar prior cases if an index exists:

```bash
python3 scripts/query_factorforge_retrieval_index.py --query "<factor family, decision, metric signature>" --top-k 5
```

6. Write your memo to:

```text
factorforge/objects/research_iteration_master/researcher_memo__<report_id>.json
```

7. Then run normal Step6:

```bash
python3 scripts/run_factorforge_ultimate.py --report-id <report_id> --start-step 6 --end-step 6
```

Step6 will preserve the external memo under `research_memo.researcher_agent_memo`.

Direct `skills/factor-forge-step6/scripts/run_step6.py` or `validate_step6.py` commands are developer-debug only. They are not the normal flow and must not be used to claim a formal Step6 result outside the ultimate wrapper proof path.

## Required Reasoning Order

1. Understand the formula and intended signal.
2. Identify return source: `risk_premium`, `information_advantage`, `constraint_driven_arbitrage`, or `mixed`.
3. Explain the objective constraints or behavioral mechanism that could make the opportunity repeat.
4. Interpret pre-cost information first: IC/rank IC, grouped gross returns,
   long-end gross return, monotonicity, and Fama-MacBeth or cross-sectional
   regression evidence when available.
5. Attribute volatility and maximum drawdown: separate continuous sigma
   exposure, jump/tail events, regime transitions, liquidity/crowding, and
   implementation noise.
6. Interpret Step4 metrics and charts.
7. Separate predictive signal quality from tradable portfolio quality.
   Turnover/cost can block promotion, but it must not erase pre-cost
   information or payer evidence.
8. Compare against prior cases and factor library knowledge when available.
9. Apply the math discipline check: random object, target statistic, information-set legality, spec stability, signal-vs-portfolio gap, revision operator, overfit risk, and kill criteria.
10. Extract learning: transferable patterns, anti-patterns, similar-case lessons, and innovative idea seeds.
11. Decide `promote_official`, `iterate`, `reject`, or `needs_human_review`.
12. If iterating, produce a concrete Step3B revision brief and explain why it strengthens the return source.
13. Build an experience chain so failures and useful dead ends become future search priors.
14. Separate macro revision, micro revision, portfolio revision, and stop/kill decisions.
15. Recommend a program-search mode: genetic formula mutation, Bayesian parameter search, RL-policy advisory, or multi-agent parallel exploration.
16. Do not use DD-view-edge-trade inside Factor Forge; this researcher layer is about factor search control, not individual-stock diligence.

Source-specific evidence standards:

- `risk_premium`: strict monotonicity and Fama-MacBeth / cross-sectional
  regression support are required.
- `information_advantage`: monotonicity can be less smooth, but the long end
  must show significant gross and risk-adjusted return.
- `constraint_driven_arbitrage`: require clear constraint/payer logic and
  evidence that the edge appears when the constraint binds.

## Research Quality Gate

The researcher memo must separate explanation from validation. Include:

- `mechanism_claim_level`: `none`, `narrative_only`, `math_framed`,
  `metric_consistent`, `component_validated`, `stochastic_validated`, or
  `payer_validated`;
- `evidence_tier_map`: mark each artifact as `promotion_gate_evidence`,
  `robustness_evidence`, `diagnostic_evidence`,
  `window_contract_evidence`, or `exploratory_evidence`;
- `economic_payer_hypothesis`: payer/receiver, proxy evidence, and how to
  falsify it;
- `component_validation`: ablation, joint-state bucket, liquidity/regime split,
  or parent-vs-revision information delta;
- `stochastic_process_contract` when stochastic language is used, with status
  `not_used`, `framing_only`, or `validated`;
- `overclaim_guard`: statements the current evidence cannot support.

If the memo claims stochastic validation, it must include state space,
conditional return distribution, transition persistence or half-life,
barrier/tail risk, and revision state-information delta. If these are missing,
write `stochastic_process_status=framing_only`.

If the memo claims Dirac-style induction, it must reference a
`dirac_induction_memo__<report_id>.json/md` containing atomic state, invariant,
estimator law, deleted-information audit, at least three limiting cases,
falsification design, reuse boundary, and overclaim guard.

Do not let `producer=local_mock`, deterministic scaffold output, or a
main-agent-only sequential Council result support an independent
research-quality claim. Mark its depth honestly.

## Hard Rules

- Never promote because backends merely ran successfully.
- Never hide bad evidence behind a good IC.
- If IC is positive but portfolio account loses money, explain the monetization gap.
- If charts are available, do not ignore them.
- Write reusable lessons for future agents, including failed lessons.
- Revision proposals must be research-motivated, not metric cosmetics.
- Every serious memo must make future researchers smarter: extract what can be transferred, what should be avoided, and what new idea deserves exploration.
- If a revision lacks a generalization argument and kill criteria, mark it incomplete or require human review.
- If multiple plausible iteration paths exist, include both an exploit branch and an explore branch.
- Treat reinforcement learning as advisory until the knowledge base contains enough revision trajectories; prefer genetic/Bayesian/multi-branch search for current single-factor loops.

## Output Contract

Use `references/researcher-memo-schema.md`.

## Provenance Strengthening

- No provenance, no archive; no evidence identity, no promotion. Researcher memos must preserve which factor, report, branch, run, implementation mode, hash chain, Step4 evidence, and Step3B mode decision produced the conclusion.
- Similar case knowledge is only analogy unless artifact identity matches. Mark imported lessons as similar-case priors, not same-factor evidence.
- Iterate recommendations must create child-branch lineage and must not overwrite `main`; include parent identity, revision target, must-preserve fields, must-change fields, and forbidden changes.

## Implementation and Factor Isolation Discipline

- Every formal factor artifact must carry `artifact_identity`.
- Every formal run must carry `manifest_identity`.
- `implementation_mode` is restricted to `operator`, `direct_code`, or `hybrid`.
- Artifacts must not be reused across mode, factor, report, branch, or run unless identity/hash lineage matches explicitly.
- Formal execution must consume manifest-specified paths only; do not pick files by `glob`, mtime, or "latest" guesses.
- If `report_id`, `factor_id`, `source_type`, `implementation_mode`, `branch_id`, `spec_hash`, or formula/code/hybrid hash does not match, BLOCK.
- Direct generated implementation files belong to one factor identity; shared helpers may be reused, factor-specific generated code may not be silently copied.
