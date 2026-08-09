---
name: factor-forge-step1
description: Run Step 1 of the Factor Factory pipeline — PDF report ingestion, dual-route reading (primary + challenger), chief merge, and canonical alpha_idea_master generation. Triggers when user provides a research report PDF and asks to extract the alpha factor, run the full Step 1 pipeline, or produce an alpha_idea_master object. Requires OpenClaw with google/gemini-3.1-pro-preview available via the pdf tool.
---

# Factor Factory Step 1 Skill

## What This Skill Does

Runs the complete Step 1 pipeline on a single research report PDF:

1. **Primary intake** — read PDF with pdf skill, extract structured intake (subfactors, final_factor, formula_clues, etc.)
2. **Challenger intake** — same PDF re-read with adversarial prompt to surface gaps and missed details
3. **Report map + thesis** — both routes produce structured thesis objects
4. **Diff** — intake_diff and thesis_diff compare primary vs challenger
5. **Chief merge** — authoritative adjudication producing canonical alpha_idea_master
6. **Research discipline standardization** — attach the selected mathematical object, target statistic hint, information-set hint, return-source hypothesis, and similar-case lessons
7. **Writeback** — all objects written to workspace; handoff file ready for Step 2

## Research Discipline

Step 1 must not stop at report summary. It must identify:
- the mathematical object the paper/report is trying to value, estimate,
  identify, optimize, filter, compare, or otherwise measure,
- the target statistic: expected return, rank, volatility, tail, regime, or other object,
- the tradable information set and possible leakage risks,
- a two-layer economic hypothesis:
  - layer 1: whether the factor is expected to earn `risk_premium`, `information_advantage`, `market_structure_arbitrage`, or `mixed`,
  - layer 2: who plausibly pays the return and why: e.g. earnings/growth/discount-rate risk bearers, slower information processors, behavioral counterparties, liquidity demanders, forced rebalancers, or other constrained participants,
- an explicit alternative-return-source review: the route must state why the
  primary source is not better explained by at least one non-primary source
  such as risk premium, information advantage, market-structure arbitrage, or
  constraint-driven arbitrage, and must include a discriminating test plus the
  metric signature that would support the alternative,
- math hypothesis candidates that can plausibly model the author thesis. These are not fixed by asset class or input type; the reader must justify why tools such as DCF/FCF/PEG, stochastic processes, jumps, cointegration, copulas, wavelets/Fourier, projection, PDE/ODE, or dimensional/scaling analysis are appropriate for this specific report,
- the initial return-source hypothesis: `risk_premium`, `information_advantage`, `constraint_driven_arbitrage`, or `mixed` for backward compatibility,
- what must be true and what would break the thesis.

Step1 owns the pre-implementation half of the math-first authority chain:
economic hypothesis -> open mathematical-tool search -> competing model
families and selection -> primary math mechanism -> market-outcome projection
-> applicable audits -> candidate observation equation. It must not choose a
model because an operator or field is convenient. At least one
mechanism-distinct alternative and one null/alias model must be recorded with
discriminating predictions. DCF/residual-income/accounting models are valid for
fundamental hypotheses; stochastic, spectral, functional, causal, optimization
and other tools are selected only when the hypothesis warrants them.

These fields are later consumed by Step6; weak Step1 understanding makes later iteration look clever but shallow.

Step1 outputs must include:
- `research_discipline.step1_mathematical_object`
- `research_discipline.target_statistic_hint`
- `research_discipline.information_set_hint`
- `research_discipline.initial_return_source_hypothesis`
- `research_discipline.economic_hypothesis`
- `research_discipline.math_hypothesis_candidates`
- `research_discipline.similar_case_lessons_imported`
- `research_discipline.knowledge_reference_contract`
- `research_discipline.what_must_be_true`
- `research_discipline.what_would_break_it`

Step1 must treat prior factor knowledge as an auditable contract. It may cold
start when no retrieval index or similar case exists, but it must still write
`knowledge_reference_contract.contract_version=factorforge_knowledge_reference_contract_v1`
with checked index paths, query hash, hit count, retrieved case ids, and the
fallback reason. A bare `similar_case_lessons_imported` string without this
provenance is not sufficient for formal Step1 acceptance.

The deterministic standardizer/validator is a developer-debug fallback after an existing Step1 route. Formal agent-led research should let the Step1 route emit canonical artifacts, then continue from Step2 via `scripts/run_factorforge_ultimate.py --report-id <report_id> --start-step 2 --end-step 6`.

## Factor Knowledge Network

Step1 must treat the factor knowledge network as a prior/analogy source. During
standardization, retrieve graph context from `knowledge/因子工厂/graph` and carry
it forward under:

- `research_discipline.factor_knowledge_context`
- `research_discipline.knowledge_reference_contract`
- `learning_and_innovation.factor_knowledge_context`
- `learning_and_innovation.knowledge_reference_contract`
- top-level `knowledge_reference_contract`

The graph uses multi-label taxonomy for market and institutional conventions:
momentum, reversal, value, quality, low volatility, liquidity, microstructure,
Barra-style exposures, WorldQuant-style operator families, and China quant
practice such as index enhancement, market neutral, intraday reversal,
high-frequency microstructure, crowding monitor, and ML feature. These labels
are retrieval hints only. They must not replace report reading, economic
hypothesis formation, or Dirac-style mathematical mechanism extraction.

Graph context is not same-factor evidence unless identity/hash lineage proves
it. Use it to import reusable mechanisms, anti-patterns, and failed paths:
wrong mathematical object, size/liquidity exposure, after-cost failure, data
coverage block, or overfit gate.

Knowledge, history and current data are advisory priors, counterexamples and
tool candidates only. They may expand the model-family set but cannot select the
primary mechanism, override the estimand, or justify a convenient proxy without
an explicit observation-error contract.

## Prerequisites

- OpenClaw environment with `pdf` tool available
- `google/gemini-3.1-pro-preview` configured as the PDF model
- factorforge Python package accessible at `/home/ubuntu/.openclaw/workspace/factorforge`

## How to Run

### Step 1a: Run Primary Intake

Use the `pdf` tool with this prompt on the target PDF:

```
请阅读这篇研报，并严格按以下 JSON 结构输出，不要输出 JSON 以外的任何文字。
要求：
1. 把因子尽量拆到最小可拆分子因子；
2. 对每个子因子和最终合成因子，都分别给出 economic_logic、behavioral_logic、causal_chain；
3. 每条 logic 都要标明 source 是 native 还是 inferred；如果是根据表达式/公式推断，必须明确写 inferred；
4. 把报告中的公式、表达式、伪代码、实现线索尽量单列抽出；
5. 若报告未明确解释逻辑，可根据表达式做谨慎推断，但必须标注 inferred。
JSON 结构：
{
  "report_meta": {"title": "", "broker": "", "topic": ""},
  "section_map": [{"section_title": "", "summary": ""}],
  "variables": [""],
  "signals": [""],
  "subfactors": [{"name": "", "formula_or_expression": "", "implementation_clues": [""], "economic_logic": "", "economic_logic_source": "native|inferred", "behavioral_logic": "", "behavioral_logic_source": "native|inferred", "causal_chain": "", "causal_chain_source": "native|inferred", "ambiguities": [""]}],
  "final_factor": {"name": "", "assembly_steps": [""], "component_subfactors": [""], "economic_logic": "", "economic_logic_source": "native|inferred", "behavioral_logic": "", "behavioral_logic_source": "native|inferred", "causal_chain": "", "causal_chain_source": "native|inferred", "ambiguities": [""]},
  "formula_clues": [{"content": "", "location_hint": ""}],
  "code_clues": [{"content": "", "location_hint": ""}],
  "implementation_clues": [{"content": "", "location_hint": ""}],
  "alpha_candidates": [{"name": "", "logic": "", "direction": ""}],
  "evidence_clues": [{"clue": "", "location_hint": ""}],
  "ambiguities": [""]
}
```

Save the returned JSON as `primary_raw.txt`.

### Step 1b: Run Challenger Intake

Use the `pdf` tool with this prompt on the **same** PDF:

```
请作为 challenger reader 独立阅读这篇研报，并严格按与主路相同的 JSON 结构输出，不要输出 JSON 以外的任何文字。
要求：
1. 不要简单复述主路结论；
2. 优先识别主路可能遗漏的子因子、公式、实现线索和歧义；
3. 对每个子因子和最终合成因子，仍需分别给出 economic_logic、behavioral_logic、causal_chain，并标注 native 或 inferred；
4. 若你不同意主路可能的最终因子选择，请明确给出不同的 final_factor。
JSON 结构：[同上方]
```

Save the returned JSON as `challenger_raw.txt`.

### Step 1c: Execute Pipeline

Run the Python pipeline script:

```bash
cd /home/ubuntu/.openclaw/workspace/factorforge
python3 -c "
import sys; sys.path.insert(0, '.')
from skills.factor_forge_step1.modules.report_ingestion.orchestration.wiring import build_step1_pipeline
from skills.factor_forge_step1.modules.report_ingestion.registry.report_registry import ReportRegistry
from pathlib import Path

project_root = Path('/home/ubuntu/.openclaw/workspace/factorforge')
report_id = 'YOUR_REPORT_ID'

# Load primary and challenger JSON
primary_raw = open('/tmp/primary_raw.txt').read()
challenger_raw = open('/tmp/challenger_raw.txt').read()

# Build registry source (use existing or create minimal)
registry = ReportRegistry(project_root / 'data' / 'report_ingestion' / 'report_registry.json')
rec = registry.get(report_id)
from skills.factor_forge_step1.modules.report_ingestion.registry.report_source_contract import ReportSource
source = ReportSource(**{k: v for k, v in rec.items() if k in {'report_id','source_type','source_uri','title','broker','author','published_at','local_cache_path','metadata','tags','status'}})

pipe = build_step1_pipeline(project_root)
result = pipe.run_pdf_skill(source, primary_raw, challenger_raw)
print(result)
"
```

### Step 1d: Run Chief Merge

After pipeline completes, use the `pdf` tool to run chief merge (feed all context JSON):

Follow the prompt template in `references/chief_merge_prompt.md`.

### Step 1e: Write alpha_idea_master

```bash
python3 -c "
from pathlib import Path
# chief_merge_output.json 是 pdf tool 返回的 JSON
# Write to objects/alpha_idea_master/
"
```

## Output Locations

All objects are written under `/home/ubuntu/.openclaw/workspace/factorforge/objects/`:

| Object | Path pattern |
|--------|-------------|
| Primary intake | `validation/report_map_validation__${report_id}__intake.json` |
| Challenger intake | `validation/report_map_validation__${report_id}__challenger_intake.json` |
| Primary report_map | `report_maps/report_map__${report_id}__primary.json` |
| Challenger report_map | `report_maps/report_map__${report_id}__challenger.json` |
| Primary thesis | `validation/report_map_validation__${report_id}__alpha_thesis.json` |
| Challenger thesis | `validation/report_map_validation__${report_id}__challenger_alpha_thesis.json` |
| Alpha idea master | `alpha_idea_master/alpha_idea_master__${report_id}.json` |
| Handoff | `handoff/handoff__${report_id}.json` |

`alpha_idea_master` must carry Step1 research discipline fields either directly
or under `research_discipline`, plus
`math_discipline_review.mathematical_object` and
`learning_and_innovation.similar_case_lessons_imported` for downstream
consumers. Existing artifacts may still expose `step1_random_object`; treat it
as a read-only legacy alias, not a new-run requirement.

## Report ID Convention

Use the filename-safe ID derived from the PDF filename:
```
RPT_pdf_{8-char-hash}_{YYYY-MM-DD}_{broker}_{title}
```
Example: `RPT_pdf_fde3cba2_20200223-东吴证券-东吴证券_技术分析拥抱选股因子`

## Architecture Reference

See `references/architecture.md` for the full module map and data flow diagram.

## Prompt Templates

Core prompts are in `references/prompts.md`.
Before generating alpha_idea_master, use the Dirac-Style Step1 Mechanism Extraction Prompt in references/prompts.md.
When a report suggests a market structure relation, first identify the research
equation or quasi-equation, then derive one or more observable detector
candidates. A detector candidate is not an approved factor. It must state
`source_equation_id`, `observable_inputs`, `measurement_equation`,
`market_outcome_projection_terms`, `expected_metric_signature`,
`expected_cost_risk_profile`, `falsification_tests`, and
`branch_action=review_only|human_approval_required`.
No equation-derived candidate may launch Step2/Step3/Step4 automatically. Candidate packets are advisory until the existing run loop or a human-approved branch request starts a formal factor run.

## Data Schemas

Structured object schemas are in `references/schema.md`.
## Implementation and Factor Isolation Discipline

- Every formal factor artifact must carry `artifact_identity`.
- Every formal run must carry `manifest_identity`.
- `implementation_mode` is restricted to `operator`, `direct_code`, or `hybrid`.
- Artifacts must not be reused across mode, factor, report, branch, or run unless identity/hash lineage matches explicitly.
- Formal execution must consume manifest-specified paths only; do not pick files by `glob`, mtime, or "latest" guesses.
- If `report_id`, `factor_id`, `source_type`, `implementation_mode`, `branch_id`, `spec_hash`, or formula/code/hybrid hash does not match, BLOCK.
- Direct generated implementation files belong to one factor identity; shared helpers may be reused, factor-specific generated code may not be silently copied.

## Mechanism-Conditioned Math Authority

Read `docs/contracts/mechanism_conditioned_measurement_program_v1.zh-CN.md`
before formalizing a new idea. Read
`docs/contracts/mechanism_math_contract_v2.zh-CN.md` only when migrating or
validating an existing v2 artifact. Step1 must produce an auditable public
derivation seed:
definitions, assumptions, candidate model families, each candidate's
`mathematical_object`, independent `mechanism_equation_or_functional`,
`target_functional`, `market_outcome_projection`, and `observation_mapping`, selection rationale,
market-outcome projection, applicable specialized audits, observation equation,
discriminating predictions and open identification gaps. This public artifact
does not expose or claim to expose private chain-of-thought.

Factor Forge uses a Dirac-style research discipline: a factor must be tied to a
classified research equation, a primary mathematical model selected from the
economic hypothesis, a mechanism-specific map to a tradeable value/payoff/price
or return quantity, formula-implied information, expected metric signature,
anomaly classification, and falsification tests. A stochastic benchmark is used
only for a stochastic claim; a fundamental factor may instead derive the map
from cash flows, discount rates, terminal value and value-price convergence.

Step1 should add `market_process_thesis`,
`primary_mechanism_model_candidates`, `market_outcome_projection`, and the exact
`mechanism_conditioned_measurement_program` under `research_discipline`. These
are early public research contracts and must not be empty or generic. Step1 may
list multiple candidate primary models and must mark the preferred candidate,
a mechanism-distinct alternative, and a null/alias model. The core mechanism
equation or functional is not the market-outcome projection: first model the
economic object, then separately map it to a tradeable value/payoff/price/return.

Canonical formula intake is not exempt from this contract. If Step1 is built
from a formula-only source such as Alpha101/canonical formula intake,
`build_canonical_formula_step1` must still translate the formula-specific
economic hypothesis and math hypothesis candidates into
`research_discipline.market_process_thesis`,
`research_discipline.primary_mechanism_model_candidates`, and
`research_discipline.market_outcome_projection`. Missing these fields or the
exact measurement program
is a Step1 BLOCK, not a reason to continue to Step3 or worker execution.

Step1 economic hypothesis is a candidate model contract, not a formula
description or a narrative. It should produce `economic_hypothesis_candidates`,
`preferred_economic_hypothesis`, `alternative_return_source_tests`,
`primary_mathematical_model`, and `formula_as_observable_estimator`. Candidate
lenses include risk premium, delayed information diffusion, liquidity/price
pressure, institutional constraints, time option, behavioral/organizational
bias, market microstructure, fundamental repricing, statistical artifact, and
report-specific mixed/other mechanisms. Do not default every factor to a
stochastic process or a dimensional-analysis exercise. Select the primary
mathematical model from the economic hypothesis and use DCF, residual income,
accounting identities, stochastic processes, Ito calculus, linear algebra,
optimization, information theory, causal tests, spectral or functional methods,
or a newly composed object only when justified.

`market_process_thesis` must include `alternative_return_source_tests`, with
at least one non-primary source and fields `why_not_primary`,
`discriminating_test`, and `expected_signature_if_alternative_true`.
This is the hard boundary between a real economic hypothesis and a narrative
label such as "not risk premium".

The preferred mechanism model must explain what mathematical object, state,
value, constraint, functional, relation, or parameter the formula is trying to
recover. It is not enough to restate inputs such as `close`,
`volume`, or the factor expression. Step2 will turn this into
`formula_implied_information` and block if the result is just raw-field or
formula-call restatement.

Step1 also seeds the universal `research_quality_gate` for the idea. The seed
may be incomplete, but it must explicitly state `allowed_next_step` and must
not pretend an idea is ready for Step3 when the economic mechanism or
mathematical object is still missing. Include:

- `economic_mechanism_contract`: payer/receiver hypothesis, persistence
  reason, expected sign, and observable proxy;
- `mathematical_object_contract`: selected mathematical object, target
  functional/statistic, information set, horizon, and formula-to-object mapping;
- `alias_elimination_matrix`: plausible lookalike explanations and the test
  that would separate each one from the preferred mechanism;
- `falsification_plan`: at least one kill criterion and one component or
  regime diagnostic;
- `claim_level_assessment`: normally `narrative_only`, `math_framed`, or
  `metric_candidate` at Step1;
- `reviewer_attack_memo`: the strongest skeptical interpretation of the idea.

If the source is oral, formula-only, or a mined candidate rather than a report,
Step1 is still responsible for this seed. Missing payer, mathematical object,
information set, alias tests, or falsification design should set
`research_quality_blocked` or `allowed_next_step=miner_only`, not a formal
Step3 handoff.

## Research Conjecture Protocol v1

Step1 must also draft the semantic content for
`factorforge_research_conjecture_protocol_v1`. This is not another prose
summary. Freeze:

- `claim_class`, before any metric is seen;
- preferred, null and at least one alternative hypothesis;
- economic-game participants, binding constraints, observable proxies and
  falsifiers;
- mathematical object, mechanism equation or functional, market-outcome
  projection, observation/estimation map and legal information set;
- terminal success, reject and block conditions;
- IS/OOS windows, sealed-OOS policy, purge/embargo, trial budget,
  multiplicity, cost, impact and capacity policies;
- at least three mechanism-distinct research-route questions, including a
  null/alias attack.

The default Step1 claim level is `narrative_only` or `math_framed`. Do not
pretend that Step1 has validated metrics. A deterministic builder may preserve
the current agent's authored packet, but it may not generate a payer, equation
or route from a fixed family template and call that research.

Knowledge retrieval occurs before this draft. Record matched cases, rejected
analogies and cold-start status in the knowledge-reference contract; prior
cases are priors and counterexample sources, never proof of the current factor.
