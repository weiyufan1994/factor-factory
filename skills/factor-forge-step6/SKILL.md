---
name: factor-forge-step6
description: Step 6 of the Factor Forge pipeline — research reflection, library writeback, and loop control. Consumes Step 4/5 evidence, writes experiment/library/knowledge records, and decides whether to promote, iterate, or reject a factor.
---

# Factor Forge Step 6 Skill

## What This Skill Does

Step 6 is the **research reflection + loop controller** layer.
It does not generate raw metrics itself. Instead it:
1. reads Step 4 / Step 5 evidence,
2. retrieves similar historical cases from the structured library,
3. judges the factor,
4. writes back experiment/library/knowledge records,
5. and decides whether Step 3B should be modified and rerun.

## Inputs

- `factorforge/objects/factor_run_master/factor_run_master__{report_id}.json`
- `factorforge/objects/factor_case_master/factor_case_master__{report_id}.json`
- `factorforge/objects/validation/factor_evaluation__{report_id}.json`
- required for formal runs: `factorforge/objects/handoff/handoff_to_step6__{report_id}.json`
- legacy debug-only fallback: `factorforge/objects/handoff/handoff_to_step5__{report_id}.json` with `FACTORFORGE_ALLOW_LEGACY_STEP6_HANDOFF=1`; this path cannot be used to claim official completion or promotion
- optional backend payloads under `factorforge/evaluations/{report_id}/{backend}/`

## Outputs

- `factorforge/objects/research_iteration_master/research_iteration_master__{report_id}.json`
- `factorforge/objects/factor_library_all/factor_record__{report_id}.json`
- optional `factorforge/objects/factor_library_official/factor_record__{report_id}.json`
- one or more knowledge records under `factorforge/objects/research_knowledge_base/`
- optional `factorforge/objects/handoff/handoff_to_step3b__{report_id}.json`
- optional `factorforge/objects/research_iteration_master/revision_proposal__{report_id}.json`
- optional `factorforge/objects/research_iteration_master/program_search_plan__{report_id}.json`
- optional `factorforge/objects/research_iteration_master/search_branch_ledger__{report_id}.json`
- optional `factorforge/objects/research_iteration_master/search_branch_result__{report_id}__{branch_id}.json`
- optional `factorforge/objects/research_iteration_master/program_search_merge__{report_id}.json`

## Core rules

1. Step 6 is responsible for reflection and decision, not raw metric generation.
2. Every attempt must enter the full experiment library.
3. Only explicitly promoted factors may enter the official library.
4. If the decision is `iterate`, Step 6 must point back to Step 3B with explicit modification targets.
5. Step 6 must preserve failed lessons, not only successful ones.
6. Step 6 should prefer structured retrieval before proposing modifications and should surface similar historical cases in the proposal.
7. Step 6 must emit a concrete `research_memo`: formula understanding, return-source hypothesis, metric interpretation, evidence quality, failure/risk analysis, decision rationale, and next research tests.
8. `research_memo` must include `math_discipline_review`: random object, target statistic, information-set legality, spec stability, signal-vs-portfolio gap, revision operator, generalization argument, overfit risk, and kill criteria.
9. `research_memo` must include `learning_and_innovation`: transferable patterns, anti-patterns, similar-case lessons, innovative idea seeds, and reuse instructions for future agents.
10. `research_memo` must include `experience_chain`, `revision_taxonomy`, `program_search_policy`, and `diversity_position`.
11. Do not use or emit `dd_view_edge_trade`; that belongs to individual-stock diligence, not Factor Forge.
12. Backend success is not enough for official promotion. If IC/group diagnostics are positive but native portfolio/account evidence is weak, Step 6 should usually choose `iterate` and explain the monetization gap.
13. Step 6 is the research analyst agent of the pipeline. It must behave like an independent PM/researcher: form a thesis, challenge it, compare it with prior cases, preserve lessons, and hand Step 3B a concrete revision brief when iteration is warranted.
14. Step6 may borrow search methods from program-level factor mining: genetic formula mutation, Bayesian parameter search, reinforcement-learning policy learning, and multi-agent parallel exploration.
15. Reinforcement learning is not the first automatic tool for a cold-start factor; treat it as an advisory policy learner until enough iteration trajectories exist in the knowledge base.
16. If `decision=iterate`, Step6 must propose exploration branches and keep a human approval gate before any code modification.
17. `validate_step6.py` is a strict gate. A Step6 output that lacks a substantive `research_memo`, `math_discipline_review`, `learning_and_innovation`, or `program_search_policy` must fail validation even if all files exist.
18. If `factorforge/objects/research_iteration_master/researcher_memo__{report_id}.json` exists, Step6 must preserve it under `research_memo.researcher_agent_memo`.
19. If `factorforge/objects/research_journal/research_journal__{report_id}.json` exists, Step6 must preserve it under `research_memo.researcher_journal`.
20. Normal research validation requires external researcher context: either a full-workflow researcher journal or a Step6 researcher memo. Pure script-only Step6 analysis is not sufficient for real factor research.
21. `validate_step6.py` must report `PASS|WARN|BLOCK`; `BLOCK` means the factor cannot claim promote, archive final, or closed-loop completion.
22. `information_set_legality=illegal*`, missing `kill_criteria`, missing `reuse_instruction_for_future_agents`, or unknown overfit risk under `promote_official` are governance blocks, not cosmetic validation failures.
23. Program search is a supplement to researcher judgment, not a replacement. Search branches must start from Step6 return-source analysis, market-structure hypothesis, knowledge-base priors, and falsification tests before any GA/Bayesian/multi-agent execution.
24. Current mandate is long-only. Step6 must not use short selling, long-short spread, or direct decile trading as an adoption basis.
25. Decile/quantile outputs are diagnostics only: use them to inspect monotonicity and top-group long-side behavior, never as a proposed trading instrument.
26. Revision must modify the factor expression and Step3B implementation itself. Do not “fix” a weak factor by changing portfolio expression, short-leg exposure, rebalance mechanics, or decile trading.
27. Official promotion requires risk-adjusted positive long-side evidence. If a factor is strictly monotonic but the high-score long side does not make money with acceptable Sharpe/drawdown/recovery, Step6 must choose `iterate` or `reject`, not `promote_official`.
28. Preferred revision direction is economic linearity: make higher factor values correspond more directly and monotonically to the economic state expected to earn risk-adjusted long-side returns.
29. Treat every factor like a business: long-side return is revenue, trading COGS defaults to `turnover * 0.3%`, volatility is operating instability/risk-capital pressure, `-0.5 * sigma^2` is volatility drag on geometric growth, max drawdown is capital impairment, and recovery time is payback/depreciation. Risk budget follows Sharpe, drawdown, recovery, capacity, and confidence.
30. Default Step6 promotion objective is `long_side_risk_adjusted_alpha`: candidate Sharpe >= `0.50`, official Sharpe >= `0.80`, max drawdown no worse than `-35%`, and recovery days preferably <= `252`.

## Research Analyst Standard

Treat Step 6 as a durable research brain, not a logger.
Every serious Step6 run should answer:

1. What is this factor trying to monetize: risk premium, information advantage, constraint-driven arbitrage, or a mixture?
2. Why should the other side behave predictably, and what objective constraints make the pattern repeatable?
3. Do the Step4 metrics support the return-source thesis, or only a fragile implementation?
4. Is this factor reusable enough for a library, or still a local feature experiment?
5. What exactly should be learned, written to the knowledge base, and reused by future agents?
6. If iterating, what should Step3B change and why is that change economically/research-wise justified?
7. What mathematical object and target statistic does the factor claim to predict?
8. What transferable pattern, anti-pattern, or innovative idea seed should future agents reuse?
9. Which search mode is appropriate next: genetic expression mutation, Bayesian parameter search, mechanism challenge, or multi-agent parallel exploration?
10. Is the next loop exploiting a promising current thesis, exploring a nearby family, or both?

## Recommended execution chain

```bash
cd /home/ubuntu/.openclaw/workspace
python3 repos/factor-factory/scripts/run_factorforge_ultimate.py --report-id <report_id> --start-step 5 --end-step 6
python3 skills/factor-forge-step6/scripts/build_program_search_plan.py --report-id <report_id>
python3 skills/factor-forge-step6/scripts/validate_program_search_plan.py --report-id <report_id>
# after the user approves a branch direction:
python3 skills/factor-forge-step6/scripts/approve_program_search_branch.py --report-id <report_id> --branch-id <branch_id> --decision approve --notes '<human notes>'
python3 skills/factor-forge-step6/scripts/prepare_approved_search_branch.py --report-id <report_id> --branch-id <branch_id>
# audit branches may be executed by the built-in local evidence-chain auditor:
python3 skills/factor-forge-step6/scripts/run_program_search_audit_worker.py --report-id <report_id> --branch-id audit_evidence_and_thesis
# after approved branch work is completed:
python3 skills/factor-forge-step6/scripts/record_search_branch_result.py --report-id <report_id> --branch-id <branch_id> ...
python3 skills/factor-forge-step6/scripts/validate_search_branch_result.py --report-id <report_id> --branch-id <branch_id>
python3 skills/factor-forge-step6/scripts/merge_program_search_branches.py --report-id <report_id>
```

Direct `run_step6.py`, `validate_step6.py`, and `run_step6_controller.py` calls are debug-only. Official agent runs must produce the `ultimate_run_report__<report_id>.json` proof emitted by `scripts/run_factorforge_ultimate.py`.

Deep researcher-agent path:

```bash
python3 skills/factor-forge-researcher/scripts/build_researcher_dossier.py --report-id <report_id>
# researcher agent updates factorforge/objects/research_journal/research_journal__<report_id>.json
python3 skills/factor-forge-step6-researcher/scripts/build_researcher_packet.py --report-id <report_id>
# researcher agent writes factorforge/objects/research_iteration_master/researcher_memo__<report_id>.json
python3 repos/factor-factory/scripts/run_factorforge_ultimate.py --report-id <report_id> --start-step 6 --end-step 6
python3 skills/factor-forge-step6/scripts/build_program_search_plan.py --report-id <report_id>
python3 skills/factor-forge-step6/scripts/validate_program_search_plan.py --report-id <report_id>
```

`--report-id` remains accepted for legacy/manual debugging, but official agent-led runs should use `--manifest` so Step6 consumes the exact Step5 evidence bundle selected by the orchestrator.

## Program Search Engine V1

`build_program_search_plan.py` converts Step6 researcher judgment into an approval-gated search plan. It does not run algorithms, modify Step3B, or touch shared data.

The plan must keep the research hierarchy:

1. Step6 explains return source: `risk_premium`, `information_advantage`, `constraint_driven_arbitrage`, or `mixed`.
2. Step6 states the market-structure / objective-constraint mechanism and expected failure regimes.
3. Step6 retrieves prior knowledge and anti-patterns.
4. Only then may the plan propose search branches.

Default branch roles:

- `audit`: check whether the iterate decision is caused by evidence, data, contract, or implementation bugs.
- `exploit`: Bayesian-style local parameter search that preserves the current thesis.
- `explore`: genetic-style nearby formula mutation that must preserve or explicitly challenge the thesis.
- `macro`: challenge or sharpen the return-source / market-structure hypothesis.

Every branch must carry a research question, hypothesis, knowledge priors, success criteria, falsification tests, budget, hard guards, and expected outputs. Human approval is required before any branch executes code changes.

Branch execution reports are recorded with `record_search_branch_result.py`. A branch result must include its research assessment, falsification result, overfit assessment, evidence or failure signature, and recommendation. `merge_program_search_branches.py` only writes an advisory merge report; it never updates Step3B or canonical code by itself.

`approve_program_search_branch.py` and `prepare_approved_search_branch.py` create the safe handoff for Humphrey/Bernard. The taskbook gives each branch an isolated write scope under `factorforge/research_branches/{report_id}/{branch_id}/` and explicitly forbids editing canonical Step3B handoffs or shared clean data.

`run_program_search_audit_worker.py` is the first concrete branch worker. It does not need external web research. It checks local Factor Forge evidence: Step4/5/6 objects, handoffs, backend payloads, first-run outputs, referenced data/code contracts, information-set legality, and legacy out-of-contract fields. It writes a normal `search_branch_result` and updates the branch ledger.

`run_program_search_bayesian_worker.py` is the second concrete branch worker. It only runs after a `bayesian_search` / `exploit` branch has been approved and prepared. It performs bounded, thesis-preserving local parameter search over existing first-run factor values and Step3A daily snapshots. It may test delay, smoothing, winsorization, direction, and cross-sectional transform choices, but it must not rewrite canonical Step3B, handoffs, shared clean data, portfolio expression, short-leg mechanics, or direct decile trading. Its output is advisory until Step6 merge and human approval.

Bayesian branch usage:

```bash
python3 skills/factor-forge-step6/scripts/approve_program_search_branch.py \
  --report-id <report_id> \
  --branch-id exploit_parameter_tuning \
  --decision approve \
  --notes "bounded parameter search only; preserve current thesis"

python3 skills/factor-forge-step6/scripts/prepare_approved_search_branch.py \
  --report-id <report_id> \
  --branch-id exploit_parameter_tuning

python3 skills/factor-forge-step6/scripts/run_program_search_bayesian_worker.py \
  --report-id <report_id> \
  --branch-id exploit_parameter_tuning \
  --max-trials 12

python3 skills/factor-forge-step6/scripts/validate_bayesian_search_trials.py \
  --report-id <report_id> \
  --branch-id exploit_parameter_tuning
```

Automatic loop runner (Step4 -> Step5 -> Step6 -> apply Step3B refinement -> repeat):

Official loop execution must enter through `scripts/run_factorforge_ultimate.py`. `run_step6_autoloop.py` is a developer-debug orchestrator only and must not be used by Bernard/Humphrey for formal factor research or for canonical writes.

Human approval gate for automatic modification:

```bash
# 1) generate proposal and stop for review
python3 repos/factor-factory/scripts/run_factorforge_ultimate.py --report-id <report_id> --start-step 6 --end-step 6

# 2) after human review, explicitly approve or reject
python3 skills/factor-forge-step6/scripts/approve_step6_revision.py --report-id <report_id> --decision approve --notes "focus on robustness first"

# 3) apply approved revision only through the ultimate wrapper
python3 repos/factor-factory/scripts/run_factorforge_ultimate.py --report-id <report_id> --apply-approved-revision --start-step 4 --end-step 6
```

Optional manual retrieval check:

```bash
python3 scripts/query_factorforge_retrieval_index.py --query "UBL monotonicity partial validation" --top-k 5
```

## References

- `references/input-contract.md`
- `references/output-contract.md`
- `docs/contracts/step6-contract.zh-CN.md`
- `docs/operations/factor-research-loop.zh-CN.md`
- `docs/operations/factorforge-math-research-discipline.zh-CN.md`
