> [中文版本](README.zh-CN.md)

# FactorForge

FactorForge is a **Step1-Step6 factor research system** for turning research reports, papers, formulas, and exploratory ideas into durable factor research assets. It is not designed as a blind formula-mining script. It is designed as a researcher-led loop: understand the idea, canonicalize the factor, implement it, evaluate it, reflect on the evidence, write lessons back to the knowledge base, and iterate only when the research case justifies doing so.

In one sentence:

> FactorForge = report/paper understanding + canonical factor specs + code generation + long-only evaluation + Step6 researcher reflection + reusable factor/knowledge libraries.

## Formal Entry Point

Formal runs must enter through the ultimate wrapper:

```bash
python3 scripts/run_factorforge_ultimate.py --report-id <report_id> --start-step 3 --end-step 6
```

Restart from Step3B when Step1/Step2/Step3A already exist:

```bash
python3 scripts/run_factorforge_ultimate.py --report-id <report_id> --start-step 3b --end-step 6
```

Rerun Step4-Step6 through the same wrapper:

```bash
python3 scripts/run_factorforge_ultimate.py --report-id <report_id> --start-step 4 --end-step 6
```

Direct calls to `skills/factor-forge-step*/scripts/run_step*.py` are reserved for wrapper/debug repair work. A formal run is complete only when the wrapper proof report exists and passes:

```text
objects/runtime_context/ultimate_run_report__<report_id>.json
```

Ad-hoc metric tables, hand-written handoffs, and legacy sample runners are not valid substitutes for wrapper proof.

## Why This Project Exists

Factor research often fails in predictable ways:

- high IC or long-short spread hides a weak long side;
- failed experiments are not preserved, so future agents repeat the same mistakes;
- reports, formulas, code, metrics, charts, and conclusions are scattered across local artifacts;
- automated search optimizes metrics before the researcher understands the return source.

FactorForge addresses this by enforcing a full evidence chain:

- every serious factor keeps source, thesis, spec, data contract, implementation, evaluation, archive, and reflection;
- every attempt enters the all-factor library;
- only promoted factors enter the official factor library;
- failed attempts write anti-patterns, kill criteria, and reusable lessons to the knowledge base;
- Step6 acts as the durable research brain of the system.

## Step1-Step6 Workflow

### Step1: Source Understanding

Step1 ingests a report, paper, formula source, or manually supplied idea. It extracts the author's thesis and produces:

- `alpha_idea_master__<report_id>.json`
- initial random object / target statistic / information-set hints
- initial return-source hypothesis
- related prior-case hints

The point is not merely to copy a formula. The point is to understand why the author believes the signal should work.

### Step2: Canonical Factor Specification

Step2 turns the idea into a machine-readable factor spec:

- `factor_spec_master__<report_id>.json`
- `handoff_to_step3__<report_id>.json`

It preserves the formula, fields, economic mechanism, target prediction, expected failure modes, and reusable idea seeds.

### Step3A: Data Entrance And Execution Contract

Step3A uses the shared clean data layer and report-level local inputs. It must not rebuild full history per factor.

Principles:

- data cleaning is infrastructure, not a per-factor ritual;
- Step3 has a fixed data entrance;
- shared clean data is refreshed only when explicitly requested or when the layer is missing/stale.

### Step3B: Factor Expression And Code

Step3B generates or revises the factor implementation. When possible, it produces first-run factor values and writes the handoff to Step4.

When Step6 decides to iterate, Step3B is where the factor expression and implementation are modified.

### Step4: Execution And Evaluation

Step4 executes the factor and emits standardized evidence:

- IC / Rank IC / IR;
- quantile/decile diagnostics;
- long-side NAV, return, Sharpe, drawdown, recovery;
- turnover;
- trading cost, defaulting to `turnover * 0.3%` when no better estimate exists;
- cost-adjusted long-side evidence;
- backend payloads and charts.

Deciles, long-short spreads, and short-leg evidence are diagnostics only. They are not adoption evidence.

### Step5: Case Closure

Step5 consumes Step4 evidence and writes:

- `factor_case_master__<report_id>.json`
- `factor_evaluation__<report_id>.json`
- `handoff_to_step6__<report_id>.json`
- archive bundles

A case cannot be marked validated if core long-side risk-adjusted evidence is missing.

### Step6: Research Reflection, Knowledge Writeback, And Loop Control

Step6 is the research brain. It does not generate raw metrics. It reads Step4/5 evidence, retrieves prior cases, forms a research judgment, writes durable lessons, and decides:

- `promote_official`
- `promote_candidate`
- `iterate`
- `reject`
- `needs_human_review`

Step6 is responsible for review, revision proposal, library writeback, knowledge writeback, and loop control.

## Long-Only Research Mandate

FactorForge currently follows a long-only adoption mandate:

- no short selling;
- no direct decile trading;
- no promotion based on long-short spread;
- no promotion based on short-side dominance;
- no revision by changing portfolio expressions, rebalance mechanics, or short-leg rules.

Formal adoption depends on whether high factor values produce explainable, repeatable, risk-adjusted long-side returns.

If the high-score long side does not work, Step6 must choose `iterate` or `reject`, not promotion.

## Factor-As-Business Evaluation

Step6 evaluates each factor like a small business:

- `revenue`: long-side return / risk premium;
- `COGS`: explicit trading cost, defaulting to `turnover * 0.3%`;
- `volatility`: operating instability / risk-capital pressure;
- `volatility_drag`: geometric growth drag, `-0.5 * sigma^2`;
- `max_drawdown`: capital impairment;
- `recovery_time`: payback period;
- `risk_budget`: a function of Sharpe, drawdown, recovery, capacity, and confidence in repeatability.

Default governance thresholds:

- candidate: long-side Sharpe >= `0.50`;
- official: long-side Sharpe >= `0.80`;
- drawdown soft limit: max drawdown no worse than `-35%`;
- recovery soft limit: no more than `252` trading days.

These are governance defaults, not immutable laws. They can be tightened by asset class, liquidity, frequency, turnover, or portfolio context.

## How Step6 Uses The Knowledge Base

Step6 and the knowledge base form the learning loop:

```text
Step4/5 evidence
    ↓
Step6 reads evidence + retrieves prior knowledge
    ↓
Step6 decides promote / iterate / reject
    ↓
Step6 writes factor-library, knowledge, and iteration records
    ↓
Future Step6 runs retrieve those lessons
```

### Two Knowledge Layers

Human-readable knowledge base:

```text
knowledge/因子工厂/
```

It contains:

- `正式因子库/`
- `普通因子库/`
- `知识库/`
- `研究迭代/`
- `Agent/`
- `仪表盘/`

Machine-readable object layer:

```text
factorforge/objects/research_knowledge_base/
factorforge/objects/factor_library_all/
factorforge/objects/factor_library_official/
factorforge/objects/research_iteration_master/
factorforge/objects/research_journal/
```

Markdown is for human review and research notes. JSON objects are for scripts, validators, retrieval, and agents.

### Retrieval Before Judgment

Before Step6 judges a factor, it should retrieve similar historical cases:

- similar formulas;
- similar return sources;
- similar failure modes;
- successful and failed revision operators;
- cases where long-short looked good but long-side failed;
- family-level regime and market-structure lessons.

This gives Step6 priors before it interprets current metrics.

### Knowledge Writeback

Every serious Step6 run should write back:

1. Factor case records:

```text
knowledge/因子工厂/普通因子库/<report_id>.md
knowledge/因子工厂/正式因子库/<report_id>.md
```

2. Research knowledge records:

```text
knowledge/因子工厂/知识库/<report_id>.md
factorforge/objects/research_knowledge_base/knowledge_record__<report_id>.json
```

3. Research iteration records:

```text
knowledge/因子工厂/研究迭代/<report_id>.md
factorforge/objects/research_iteration_master/research_iteration_master__<report_id>.json
```

The writeback must include transferable patterns, anti-patterns, failure regimes, revision insights, reuse instructions, and innovative idea seeds.

### Required Research Memo

Step6 should produce a substantive `research_memo` including:

- `formula_understanding`
- `return_source_hypothesis`
- `metric_interpretation`
- `evidence_quality`
- `failure_or_risk_analysis`
- `decision_rationale`
- `next_research_tests`
- `math_discipline_review`
- `learning_and_innovation`
- `experience_chain`
- `revision_taxonomy`
- `program_search_policy`

The goal is not to say “the factor ran.” The goal is to answer:

> What did this attempt teach us about factors, market structure, return sources, failure modes, and future innovation?

### Math Discipline Review

Step6 must answer:

- `step1_random_object`: what random object is being studied;
- `target_statistic`: what statistic the factor claims to predict;
- `information_set_legality`: whether future information is used;
- `spec_stability`: whether the formula is stable;
- `signal_vs_portfolio_gap`: whether signal quality translates into investable long-side return;
- `revision_operator`: what type of modification is being proposed;
- `generalization_argument`: why the change is not merely overfitting;
- `overfit_risk`: what can go wrong;
- `kill_criteria`: when the branch must stop.

If these cannot be answered, the factor cannot be promoted to official.

### Iteration Flow

When Step6 decides `iterate`, it must generate a revision proposal and stop for human approval:

```text
Step6 revision proposal
    ↓
Human approval
    ↓
Step3B modifies factor expression / code
    ↓
Step4 reruns evaluation
    ↓
Step5 closes the case
    ↓
Step6 reflects again
```

A revision proposal must state the target expression/code change, the return source being strengthened, the expected monotonic/economic improvement, success criteria, kill criteria, and whether program search is appropriate.

## Program Search Is Advisory

Step6 may use program-search tools as supplements:

- Bayesian parameter search;
- genetic formula mutation;
- reinforcement-learning advisory after many trajectories exist;
- multi-agent parallel exploration.

Search must start from research analysis, knowledge-base priors, success criteria, and falsification tests. Algorithms may propose candidates, but they cannot directly promote factors or overwrite canonical Step3B code without human approval.

## Data Rules

FactorForge reuses the shared clean data layer:

- do not reclean full history per factor;
- `build_clean_daily_layer.py` is not a required per-factor step;
- data refresh requires explicit authorization;
- Step3A uses clean layer plus report-level local inputs;
- Mac and EC2 should sync data and knowledge state intentionally.

## Repository Layout

```text
scripts/                              # ultimate wrapper, data tools, governance tools
skills/factor-forge-step1/             # Step1 skill
skills/factor-forge-step2/             # Step2 skill
skills/factor-forge-step3/             # Step3 skill
skills/factor-forge-step4/             # Step4 skill
skills/factor-forge-step5/             # Step5 skill
skills/factor-forge-step6/             # Step6 skill
skills/factor-forge-ultimate/          # top-level orchestration skill
skills/factor-forge-researcher/        # full-workflow researcher layer
skills/factor-forge-step6-researcher/  # deep Step6 researcher layer
skills/factor-forge-research-brain/    # investment logic and reflection framework
factor_factory/data_access/            # shared data access package
knowledge/因子工厂/                    # human-readable knowledge base
factorforge/objects/                   # local runtime objects, usually gitignored
factorforge/runs/                      # local run outputs, usually gitignored
factorforge/evaluations/               # local evaluation outputs, usually gitignored
```

## Common Commands

Install the package:

```bash
python3 -m pip install -e .
```

Install optional Step4 / qlib helpers:

```bash
python3 -m pip install -e ".[step4]"
python3 -m pip install -e ".[qlib]"
```

Build runtime context:

```bash
python3 scripts/build_factorforge_runtime_context.py --report-id <report_id> --write
```

Run the formal workflow:

```bash
python3 scripts/run_factorforge_ultimate.py --report-id <report_id> --start-step 3 --end-step 6
```

Build retrieval index:

```bash
python3 scripts/build_factorforge_retrieval_index.py
```

Export the Obsidian-style knowledge base:

```bash
python3 scripts/export_factorforge_obsidian.py
```

Query retrieval index:

```bash
python3 scripts/query_factorforge_retrieval_index.py --query "long-side monotonicity failure" --top-k 5
```

## Governance Rules

- Formal workflow must use `scripts/run_factorforge_ultimate.py`.
- Legacy/sample/debug writers must not write canonical artifacts.
- `objects/`, `runs/`, `evaluations/`, `generated_code/`, `archive/`, `factorforge/`, `data/clean/`, and `data/raw/` are local runtime state and are normally ignored.
- Step5 validation requires complete long-side risk-adjusted evidence.
- Step6 promotion requires knowledge retrieval, math discipline, long-only evidence, and risk-adjusted long-side thresholds.
- Any new canonical writer requires architecture review.

## Recommended Reading Path

1. `skills/factor-forge-ultimate/SKILL.md`
2. `skills/factor-forge-step6/SKILL.md`
3. `skills/factor-forge-research-brain/SKILL.md`
4. `docs/contracts/README.md`
5. `docs/contracts/step6-contract.md`
6. `docs/operations/factorforge-math-research-discipline.zh-CN.md`
7. `knowledge/因子工厂/Home.md`
8. `knowledge/因子工厂/知识库/因子迭代方法论.md`

