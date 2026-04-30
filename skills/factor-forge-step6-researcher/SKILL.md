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
4. Interpret Step4 metrics and charts.
5. Separate predictive signal quality from tradable portfolio quality.
6. Compare against prior cases and factor library knowledge when available.
7. Apply the math discipline check: random object, target statistic, information-set legality, spec stability, signal-vs-portfolio gap, revision operator, overfit risk, and kill criteria.
8. Extract learning: transferable patterns, anti-patterns, similar-case lessons, and innovative idea seeds.
9. Decide `promote_official`, `iterate`, `reject`, or `needs_human_review`.
10. If iterating, produce a concrete Step3B revision brief and explain why it strengthens the return source.
11. Build an experience chain so failures and useful dead ends become future search priors.
12. Separate macro revision, micro revision, portfolio revision, and stop/kill decisions.
13. Recommend a program-search mode: genetic formula mutation, Bayesian parameter search, RL-policy advisory, or multi-agent parallel exploration.
14. Do not use DD-view-edge-trade inside Factor Forge; this researcher layer is about factor search control, not individual-stock diligence.

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
