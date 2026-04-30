---
name: factor-forge-step2
description: Step 2 of the Factor Factory pipeline — Factor Spec Extraction and Validation. Consumes alpha_idea_master from Step 1, extracts factor construction specs via dual-model extraction (primary + challenger), audits consistency, and produces factor_spec_master for Step 3. Triggers when user provides a report_id with alpha_idea_master ready and asks to run Step 2 or produce factor_spec_master.
---

# Factor Factory Step 2 Skill

## What This Skill Does

Step 2 converts an `alpha_idea_master` into a machine-readable `factor_spec_master` — the authoritative construction blueprint for implementing the factor in Step 3.

## Research Discipline

Step 2 is the canonical-spec guardrail. It must verify:
- the spec preserves the author's original thesis rather than rewriting it into a convenient local formula,
- every lag/window/rank/normalization/neutralization choice is explicit,
- information used at time `t` is legally available at time `t`,
- boundary-sensitive transforms such as rank, bucket, winsorize, truncate, argmax, and argmin are called out,
- critical ambiguities trigger `human_review_required` instead of being silently guessed.
- the Step1 random object and similar-case lessons are preserved instead of lost at spec extraction time,
- the canonical spec states the target statistic, economic mechanism, expected failure modes, innovative idea seeds, and reuse instructions for future agents.

The output should be precise enough that two independent implementers would build the same kind of factor.

## Model Assignment

| Role | Model | When to use |
|------|-------|-------------|
| Primary spec extraction | `minimax/MiniMax-M2.7` | Always — first pass |
| Challenger spec extraction | `openai-codex/gpt-5.4` | Always — adversarial second pass |
| Consistency auditor | `deepseek/deepseek-reasoner` | Always — judge alignment |
| Chief finalizer | `openrouter/anthropic/claude-opus-4.6` | **Only on material disagreement** |

> **Opus 4.6 policy**: Do NOT use in the normal flow. Use only when primary and challenger specs have substantive disagreement on core operators, required inputs, or reconstruction logic. Track usage.

## Inputs

- Step 1 artifact: `alpha_idea_master` JSON file
  - Path: `factorforge/objects/alpha_idea_master/alpha_idea_master__{report_id}.json`
  - Key fields needed: `report_id`, `final_factor`, `assembly_path`, `unresolved_ambiguities`
- Report PDF (for visual spec extraction)
  - Source: `factorforge/data/report_ingestion/report_registry.json` → `local_cache_path`
  - Or: original PDF path from `alpha_idea_master.source_uri`

## Schema: factor_spec_raw

Both primary and challenger produce this schema:

```json
{
  "factor_id": "string",
  "report_id": "string",
  "route": "primary|challenger",
  "raw_formula_text": "string",
  "operators": ["string"],
  "required_inputs": ["string"],
  "time_series_steps": ["string"],
  "cross_sectional_steps": ["string"],
  "preprocessing": ["string"],
  "normalization": ["string"],
  "neutralization": ["string"],
  "rebalance_frequency": "string",
  "explicit_items": ["string"],
  "inferred_items": ["string"],
  "ambiguities": ["string"]
}
```

## Schema: factor_consistency

```json
{
  "factor_id": "string",
  "report_id": "string",
  "consistency_score": 0.0,
  "matches_core_driver": true,
  "mismatch_points": ["string"],
  "missing_steps": ["string"],
  "distortion_risks": ["string"],
  "recommendation": "proceed|revise|stop"
}
```

## Schema: factor_spec_master

```json
{
  "factor_id": "string",
  "linked_idea_id": "string",
  "report_id": "string",
  "canonical_spec": {
    "formula_text": "string",
    "required_inputs": ["string"],
    "operators": ["string"],
    "time_series_steps": ["string"],
    "cross_sectional_steps": ["string"],
    "preprocessing": ["string"],
    "normalization": ["string"],
    "neutralization": ["string"],
    "rebalance_frequency": "string"
  },
  "thesis": {
    "alpha_thesis": "string",
    "target_prediction": "string",
    "economic_mechanism": "string"
  },
  "math_discipline_review": {
    "step1_random_object": "string",
    "target_statistic": "string",
    "information_set_legality": "string",
    "expected_failure_modes": ["string"]
  },
  "learning_and_innovation": {
    "similar_case_lessons_imported": ["string"],
    "innovative_idea_seeds": ["string"],
    "reuse_instruction_for_future_agents": ["string"]
  },
  "research_contract": {
    "target_statistic": "string",
    "economic_mechanism": "string",
    "expected_failure_modes": ["string"],
    "innovative_idea_seeds": ["string"],
    "reuse_instruction_for_future_agents": ["string"]
  },
  "ambiguities": ["string"],
  "human_review_required": false,
  "chief_decision": "string|null",
  "opus_invoked": false
}
```

## Execution Flow

### Step 2a: Load alpha_idea_master

Read `factorforge/objects/alpha_idea_master/alpha_idea_master__{report_id}.json`.
Extract: `report_id`, `final_factor.name`, `final_factor.assembly_steps`, `final_factor.direction`, `unresolved_ambiguities`.

### Step 2b: Primary Spec Extraction (MiniMax M2.7)

Use `pdf` tool on the report PDF with this prompt:

```
You are the Spec Extraction Agent (Primary Route).

Inputs:
- alpha_idea_master: {alpha_idea_master_json}
- The research report PDF you are reading

Task:
Extract the factor specification as faithfully as possible from this report.

Requirements:
1. Recover formulas, operators, transformations, rolling windows, ranking rules, winsorization, neutralization, and rebalance frequency.
2. Separate what is EXPLICIT (stated in the report) from what is INFERRED (you deduced from the formula/expression).
3. Flag ambiguities that require human review.
4. Do NOT rewrite into local implementation code yet.
5. Focus especially on: the assembly_steps from alpha_idea_master — verify if the report text supports those steps.

Output ONLY valid JSON matching this schema:
{factor_spec_raw_schema}
```

Save output as `/tmp/step2_primary_raw_{report_id}.json`.

### Step 2c: Challenger Spec Extraction (GPT-5.4 via Codex)

Use Codex session with the same PDF + this prompt:

```
You are the Spec Extraction Agent (Challenger Route) — adversarial reader.

Inputs:
- alpha_idea_master: {alpha_idea_master_json}
- The research report PDF you are reading

Task:
Independently extract the factor specification. Your job is to FIND WHAT THE PRIMARY ROUTE LIKELY MISSED.

Requirements:
1. Do NOT simply agree with the alpha_idea_master or primary route.
2. Focus on: alternative formula interpretations, missed operator steps, ambiguities the primary route may have papered over.
3. Recover formulas, operators, rolling windows, winsorization, neutralization, rebalance frequency.
4. Label explicit vs inferred items honestly.
5. If you disagree with the assembly_steps proposed in alpha_idea_master, say so explicitly.

Output ONLY valid JSON matching this schema:
{factor_spec_raw_schema}
```

Save output as `/tmp/step2_challenger_raw_{report_id}.json`.

### Step 2d: Consistency Audit (DeepSeek Reasoner)

Use `deepseek/deepseek-reasoner` with this prompt:

```
You are the Consistency Auditor.

Inputs:
1. alpha_idea_master: {alpha_idea_master_json}
2. Primary factor_spec_raw: {primary_spec}
3. Challenger factor_spec_raw: {challenger_spec}

Task:
Judge whether the extracted factor specifications are truly consistent with the alpha thesis in alpha_idea_master.

Requirements:
1. Score consistency 0.0–1.0. Score < 0.7 means material mismatch.
2. Identify: which formula steps distort or weaken the core alpha thesis.
3. Identify: mismatches between the report narrative and the formula specification.
4. Recommend: proceed (no material issues), revise (fix needed), or stop (factor not recoverable).

Output ONLY valid JSON matching this schema:
{factor_consistency_schema}
```

### Step 2e: Chief Finalization (Opus 4.6 — on-demand only)

Trigger condition: `consistency_score < 0.7` OR primary vs challenger have > 2 material disagreements on operators/inputs.

If triggered, use `openrouter/anthropic/claude-opus-4.6`:

```
You are the Chief Research Agent.

Inputs:
1. alpha_idea_master
2. Primary factor_spec_raw
3. Challenger factor_spec_raw
4. factor_consistency audit

Task:
Create the canonical factor specification for implementation. Resolve disagreements between primary and challenger.

Requirements:
1. Keep EXPLICIT AMBIGUITY fields — do not hallucinate certainty.
2. If primary and challenger disagree materially, pick the more faithful interpretation and note the disagreement.
3. Mark human_review_required = true if critical ambiguities cannot be resolved.
4. Set opus_invoked = true in output.

Output ONLY valid JSON matching this schema:
{factor_spec_master_schema}
```

If NOT triggered: use DeepSeek's consistency audit result + primary spec as canonical, set `opus_invoked = false`.

### Step 2f: Write Outputs

Write `factor_spec_master` to:
```
factorforge/objects/factor_spec_master/factor_spec_master__{report_id}.json
```

Also write side artifacts:
```
factorforge/objects/validation/factor_spec_raw__primary__{report_id}.json
factorforge/objects/validation/factor_spec_raw__challenger__{report_id}.json
factorforge/objects/validation/factor_consistency__{report_id}.json
```

## Output Locations

| Object | Path |
|--------|------|
| factor_spec_master | `factorforge/objects/factor_spec_master/factor_spec_master__{report_id}.json` |
| Primary spec | `factorforge/objects/validation/factor_spec_raw__primary__{report_id}.json` |
| Challenger spec | `factorforge/objects/validation/factor_spec_raw__challenger__{report_id}.json` |
| Consistency audit | `factorforge/objects/validation/factor_consistency__{report_id}.json` |
| Step 3 handoff | `factorforge/objects/handoff/handoff_to_step3__{report_id}.json` |

## Automatic PDF Resolution

The runner must resolve the original PDF in this order:
1. `factorforge/data/report_ingestion/report_registry.json`
2. `factorforge/objects/handoff/handoff__{report_id}.json`
3. any usable path fields inside `alpha_idea_master`

If no local PDF path can be found, the run must fail explicitly instead of pretending completion.

## Handoff to Step 3

After factor_spec_master is written, generate handoff file:
```
factorforge/objects/handoff/handoff_to_step3__{report_id}.json
```
Content: `factor_spec_master` ref + `alpha_idea_master` ref + `report_id`.

## Acceptance Criteria

- [ ] `factor_spec_master` file exists at correct path
- [ ] `canonical_spec` has all required fields (formula_text, operators, time_series_steps, cross_sectional_steps, preprocessing, normalization, neutralization, rebalance_frequency)
- [ ] `thesis.alpha_thesis`, `thesis.target_prediction`, and `thesis.economic_mechanism` exist
- [ ] `math_discipline_review.target_statistic` and `math_discipline_review.expected_failure_modes` exist
- [ ] `learning_and_innovation.innovative_idea_seeds` and `reuse_instruction_for_future_agents` exist
- [ ] `ambiguities` array is non-empty if human review is needed
- [ ] `opus_invoked` field is present and correctly set (true only if chief was called)
- [ ] All three validation artifacts exist
- [ ] No `TODO` / `TO_BE_FILLED` / placeholder residues
- [ ] `human_review_required` is false OR true with documented ambiguities

## Repository alignment note

Current repository reproducibility docs for Step 2 live at:
- `docs/contracts/step2-contract.md`
- `docs/reproducibility/step2-gap-card.md`
- `scripts/run_step2_sample.sh`

Treat those files as the authoritative current repo-level reproducibility notes when they differ from older path assumptions in chat history.

## Run Command

```bash
# Current skill-side runner path in repo:
cd /home/ubuntu/.openclaw/workspace/factorforge
python3 repos/factor-factory/scripts/run_factorforge_ultimate.py --report-id <report_id> --start-step 2 --end-step 2

# Or via skill:
# Give Humphrey: report_id of a completed Step 1 run
# Humphrey will execute the full Step 2 pipeline automatically
```

Direct `run_step2.py` / `validate_step2.py` commands are developer-debug only. Formal agent runs must use `scripts/run_factorforge_ultimate.py` so Step2 writes through the same runtime proof path consumed by Step3-6.

## Report ID

Use the same report_id as Step 1:
```
RPT_pdf_{8-char-hash}_{YYYY-MM-DD}_{broker}_{title}
```
Example: `RPT_pdf_fde3cba2_20200223-东吴证券-东吴证券_技术分析拥抱选股因子_系列研究_一_高频价量相关性_意想不到的选股因子`
