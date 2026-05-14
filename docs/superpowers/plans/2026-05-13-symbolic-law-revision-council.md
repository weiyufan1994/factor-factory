# Symbolic Law Revision Council Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a Step6 Revision Council layer that can reason from formula symbols, units, dimensions, scaling laws, stochastic-process structure, spectral/statistical structure, and prior evidence to propose better revision directions without bypassing Factor Forge gates.

**Architecture:** This is an incremental Step6 Intelligence layer. It adds a proposal-only `revision_council` subsystem between Step6 mechanism/revision analysis and program-search branch generation. Council agents may write isolated proposal artifacts only; Step6 arbiter remains the only component allowed to convert accepted proposals into approval-gated `branch_templates`.

**Tech Stack:** Python 3, existing Factor Forge JSON artifacts, `factor_factory` package modules, Step6 scripts, `/tmp` smoke harnesses, existing wrapper/validator discipline.

---

## Non-Negotiable Boundaries

- Do not rewrite existing Step2 source contract, Step5 provenance gates, Step6 prewrite gates, or program-search approval gates.
- Do not let any council agent write `handoff_to_step3b`, `generated_code`, `factor_library_official`, shared `data/clean`, or canonical Step3B implementation artifacts.
- Do not restore branch guessing fallback. Program search branches must still come from explicit Step6-approved `branch_templates`.
- Mathematical plausibility, dimensional elegance, or symbolic derivation is never promotion evidence by itself. Step4/5 evidence and Step6 validators remain decisive.
- All new smoke/acceptance tests must use `/tmp` roots and prove no canonical pollution.
- Official factor runs remain wrapper-only through `scripts/run_factorforge_ultimate.py`.

## Conceptual Model

The new layer implements a mathematical discovery loop:

```text
market phenomenon
  -> mathematical object
  -> symbolic representation
  -> structural constraints
  -> derived hypothesis
  -> revision proposal
  -> Step6 arbiter
  -> program-search plan
  -> human approval
  -> branch execution
  -> evidence feedback
  -> knowledge update
```

The core new agent is `symbolic_law_discovery`. It is an upper-level mathematical reasoning agent, not a narrow dimensional-analysis checklist. It dynamically chooses tools such as:

- dimensional analysis
- scaling-law analysis
- invariance and symmetry analysis
- limiting-case analysis
- perturbation analysis
- stochastic-process modeling
- stochastic calculus
- jump-diffusion reasoning
- natural-time / market-clock analysis
- Fourier or spectral analysis
- robust statistics and tail-distribution analysis
- linear projection / residualization
- functional analysis
- dynamical systems
- stopping-time reasoning
- information-theoretic reasoning

Dimensional analysis is a core tool inside this agent, not a separate rigid endpoint. It should help detect unit pollution, scale pollution, frequency mismatch, and structurally incoherent formula terms.

## New Artifact Shape

Council output should live under:

```text
objects/research_iteration_master/revision_council/{report_id}/
```

Required files:

```text
revision_council_packet__{report_id}.json
proposal__{report_id}__symbolic_law_discovery.json
proposal__{report_id}__evidence_auditor.json
proposal__{report_id}__economic_mechanism.json
proposal__{report_id}__formula_engineer.json
proposal__{report_id}__cost_turnover.json
proposal__{report_id}__regime_robustness.json
proposal__{report_id}__knowledge_retrieval_critic.json
revision_council_summary__{report_id}.json
```

Each proposal must use this minimum schema:

```json
{
  "contract_version": "factorforge_revision_council_proposal_v1",
  "report_id": "<report_id>",
  "agent_role": "symbolic_law_discovery",
  "proposal_id": "symbolic_law_001",
  "proposal_status": "proposed",
  "revision_type": "expression_revision | mechanism_challenge | audit | reject_advisory | no_action",
  "target_failure_signature": "cost_too_high | long_side_negative | non_monotonic | mechanism_unclear | implementation_suspect | same_factor_identity_mismatch | none",
  "selected_math_tools": ["dimensional_analysis", "stochastic_process_modeling"],
  "market_phenomenon": "short text",
  "symbolic_model": {
    "state_or_object": "short text",
    "state_process": "short text or empty",
    "latent_state": "short text or empty",
    "target_functional": "short text"
  },
  "dimensional_scaling_review": {
    "raw_field_units": {},
    "formula_output_dimension": "dimensionless | price | money | shares | return | volatility | unknown",
    "dimension_erasing_transforms": [],
    "scale_invariance_claims": [],
    "natural_time_scale": "calendar_time | trading_time | volume_time | volatility_time | event_time | unknown",
    "dimension_risks": [],
    "limiting_cases": []
  },
  "structural_findings": [],
  "candidate_revision_laws": [
    {
      "law_statement": "short text",
      "formula_direction": "short text",
      "expected_metric_change": ["item 1", "item 2"],
      "falsification_tests": ["item 1", "item 2"],
      "kill_criteria": ["item 1", "item 2"]
    }
  ],
  "return_source_hypothesis": "risk_premium | information_advantage | constraint_driven_arbitrage | market_structure_harvesting | mixed | unknown",
  "expression_change": "short text or empty",
  "why_not_portfolio_fix": "required text",
  "forbidden_changes_ack": [
    "no_portfolio_expression_repair",
    "no_short_leg_adoption",
    "no_decile_trading",
    "no_shared_clean_data_mutation"
  ],
  "confidence": "low | medium | high",
  "risk_notes": "short text"
}
```

## Task 1: Create Revision Council Package

**Files:**
- Create: `/Users/humphrey/projects/factor-factory/factor_factory/revision_council/__init__.py`
- Create: `/Users/humphrey/projects/factor-factory/factor_factory/revision_council/schema.py`
- Create: `/Users/humphrey/projects/factor-factory/factor_factory/revision_council/validator.py`
- Create: `/Users/humphrey/projects/factor-factory/factor_factory/revision_council/guards.py`

- [ ] **Step 1: Define schema constants**

Implement `schema.py` with role names, enum values, forbidden guard tokens, and required top-level fields.

Required roles:

```python
COUNCIL_AGENT_ROLES = {
    "symbolic_law_discovery",
    "evidence_auditor",
    "economic_mechanism",
    "formula_engineer",
    "cost_turnover",
    "regime_robustness",
    "knowledge_retrieval_critic",
}
```

Required math toolkit values for `symbolic_law_discovery`:

```python
SYMBOLIC_MATH_TOOLS = {
    "dimensional_analysis",
    "scaling_law_analysis",
    "invariance_analysis",
    "limiting_case_analysis",
    "perturbation_analysis",
    "stochastic_process_modeling",
    "stochastic_calculus",
    "jump_diffusion_reasoning",
    "natural_time_clock_analysis",
    "fourier_or_spectral_analysis",
    "robust_statistics",
    "tail_distribution_analysis",
    "linear_projection",
    "functional_analysis",
    "dynamical_systems",
    "stopping_time_reasoning",
    "information_theoretic_reasoning",
}
```

- [ ] **Step 2: Implement forbidden text guards**

Implement `guards.py` with recursive scanning for portfolio repair, rebalance repair, short-leg adoption, decile trading, and shared clean-data mutation. Reuse the spirit of `validate_program_search_plan.py`: scan all free-text proposal fields but skip explicit guard-token containers.

Required block token:

```text
BLOCK_REVISION_COUNCIL_FORBIDDEN_CHANGE
```

- [ ] **Step 3: Implement proposal validator**

Implement `validator.py` with:

```python
def validate_revision_council_proposal(proposal: dict) -> list[str]:
    """Return list of block reasons. Empty means valid."""
```

Validation must block when:

- contract version is wrong or missing.
- role is not in `COUNCIL_AGENT_ROLES`.
- forbidden guard tokens are missing.
- `why_not_portfolio_fix` is empty.
- `symbolic_law_discovery` has no `selected_math_tools`.
- `symbolic_law_discovery` includes unknown math tools.
- `dimensional_scaling_review` is absent for `symbolic_law_discovery`.
- revision type is expression-level but no falsification tests or kill criteria exist.
- text contains forbidden portfolio/short/decile/clean-data mutation language.

- [ ] **Step 4: Add py_compile check**

Run:

```bash
cd /Users/humphrey/projects/factor-factory
python3 -m py_compile factor_factory/revision_council/schema.py factor_factory/revision_council/validator.py factor_factory/revision_council/guards.py
```

Expected: rc `0`.

## Task 2: Build Council Packet Script

**Files:**
- Create: `/Users/humphrey/projects/factor-factory/skills/factor-forge-step6/scripts/build_revision_council_packet.py`

- [ ] **Step 1: Implement packet builder**

The script must read existing Step6/Step5/Step4 artifacts for a report and write:

```text
objects/research_iteration_master/revision_council/{report_id}/revision_council_packet__{report_id}.json
```

The packet must include:

- `report_id`
- `artifact_identity`
- `factor_formula` if available
- `implementation_mode`
- `mechanism_math_contract`
- `research_memo.evidence_audit`
- `research_memo.mechanism_analysis`
- `research_memo.case_comparison`
- `research_memo.revision_strategy`
- `loop_research_brief` reference and summary
- Step4/5 core metrics
- chart evidence references
- existing program-search policy if present

- [ ] **Step 2: Enforce read-only scope**

The script may only write the packet under `revision_council/{report_id}/`. It must not write handoff, generated_code, official library, clean data, runs, or evaluations.

Required block token if required upstream artifacts are missing:

```text
BLOCK_REVISION_COUNCIL_PACKET_MISSING_INPUT
```

- [ ] **Step 3: Add command smoke**

Command:

```bash
cd /Users/humphrey/projects/factor-factory
FACTORFORGE_ROOT=/tmp/factorforge_revision_council_packet_smoke python3 skills/factor-forge-step6/scripts/build_revision_council_packet.py --report-id REVISION_COUNCIL_SMOKE
```

Expected for missing fixture: rc `1`, token `BLOCK_REVISION_COUNCIL_PACKET_MISSING_INPUT`, no canonical writes.

## Task 3: Implement Proposal Generators

**Files:**
- Create: `/Users/humphrey/projects/factor-factory/skills/factor-forge-step6/scripts/run_revision_council.py`

- [ ] **Step 1: Implement deterministic local generators first**

This script should not call external LLMs in v1. It should generate deterministic proposal artifacts from packet contents. Later Bernard/Humphrey/Codex can replace individual proposal generation, but schema/guards must be stable first.

Required output directory:

```text
objects/research_iteration_master/revision_council/{report_id}/
```

Required proposal files:

```text
proposal__{report_id}__symbolic_law_discovery.json
proposal__{report_id}__evidence_auditor.json
proposal__{report_id}__economic_mechanism.json
proposal__{report_id}__formula_engineer.json
proposal__{report_id}__cost_turnover.json
proposal__{report_id}__regime_robustness.json
proposal__{report_id}__knowledge_retrieval_critic.json
```

- [ ] **Step 2: Implement symbolic law proposal logic**

For price-volume formulas, the symbolic proposal should at minimum inspect formula text/operator metadata and generate findings like:

- raw volume should be normalized by float shares, ADV, or free-float market value if the formula claims cross-sectional comparability.
- rank/zscore/corr erase dimensions but may also erase scale information.
- short windows on price-volume coupling may estimate transient shock state rather than persistent drift.
- high turnover/cost failure suggests a natural-time or liquidity-pressure mismatch.

It should select tools such as:

```json
[
  "dimensional_analysis",
  "scaling_law_analysis",
  "stochastic_process_modeling",
  "natural_time_clock_analysis"
]
```

- [ ] **Step 3: Implement role-specific proposal rules**

Minimum v1 behavior:

- `evidence_auditor`: propose `audit` if evidence is blocked, all backend skipped, identity drift exists, or implementation suspect.
- `economic_mechanism`: propose `mechanism_challenge` if mechanism fit is weak/contradicted.
- `formula_engineer`: propose expression-level operator/hybrid/direct-code direction but never canonical code.
- `cost_turnover`: propose Bayesian/local bounded branch if failure signature is `cost_too_high`.
- `regime_robustness`: propose regime/frequency split checks if evidence is unstable.
- `knowledge_retrieval_critic`: summarize same-factor/similar-case lessons; same-factor mismatch must be block-grade.

- [ ] **Step 4: Validate every proposal before writing summary**

Use `validate_revision_council_proposal()` before accepting each proposal. Invalid proposals should be written with `proposal_status=blocked` and block reasons, but must not become candidate branch input.

## Task 4: Merge Council Proposals

**Files:**
- Create: `/Users/humphrey/projects/factor-factory/skills/factor-forge-step6/scripts/merge_revision_council.py`

- [ ] **Step 1: Load and validate proposal artifacts**

Load only files under:

```text
objects/research_iteration_master/revision_council/{report_id}/
```

Do not glob by latest or mtime. Use exact report id and expected role names.

- [ ] **Step 2: Generate council summary**

Write:

```text
objects/research_iteration_master/revision_council/{report_id}/revision_council_summary__{report_id}.json
```

Summary schema:

```json
{
  "contract_version": "factorforge_revision_council_summary_v1",
  "report_id": "<report_id>",
  "candidate_proposals": [],
  "blocked_proposals": [],
  "recommended_branch_templates": [],
  "arbiter_notes": [],
  "human_approval_required": true,
  "execution_allowed_by_default": false
}
```

- [ ] **Step 3: Arbiter branch selection rules**

Map proposals to branch templates only when valid:

- evidence failure -> `audit`
- cost too high with viable expression hypothesis -> `bayesian_exploit`
- non-monotonic or formula structure issue -> `genetic_explore`
- mechanism contradiction or unclear source -> `mechanism_challenge`
- long-side negative without approved loop -> `kill` or advisory only

All branch templates must include:

- `status=proposed`
- `human_approval_required=true`
- `execution_allowed_by_default=false`
- full hard guards
- no forbidden text

- [ ] **Step 4: Prewrite forbidden side-effect scan**

Before writing summary, block if any council process has created forbidden artifacts for current report:

```text
objects/handoff/handoff_to_step3b__{report_id}.json
generated_code/{report_id}/
objects/factor_library_official/factor_record__{report_id}.json
data/clean modified under test root
```

Required block token:

```text
BLOCK_REVISION_COUNCIL_FORBIDDEN_WRITEBACK_PRESENT
```

## Task 5: Integrate with Step6 Search Policy

**Files:**
- Modify: `/Users/humphrey/projects/factor-factory/skills/factor-forge-step6/scripts/run_step6.py`
- Modify: `/Users/humphrey/projects/factor-factory/skills/factor-forge-step6/scripts/validate_step6.py`
- Modify: `/Users/humphrey/projects/factor-factory/skills/factor-forge-step6/scripts/build_program_search_plan.py` only if needed to read council-derived templates already stored in Step6 output.

- [ ] **Step 1: Add optional council summary consumption**

If `revision_council_summary__{report_id}.json` exists and validates, Step6 may include it under:

```json
research_memo.revision_council
```

- [ ] **Step 2: Do not make council mandatory in v1**

Existing Step6 runs must still pass without council artifacts. The council is an enhancement path, not a new required dependency for all factors.

- [ ] **Step 3: Feed selected branch templates into search policy**

When council summary exists, Step6 may use `recommended_branch_templates` to enrich `search_policy_decision.branch_templates`, subject to existing guards:

- human approval required
- execution disabled by default
- no branch guessing
- no direct handoff unless existing Step6 loop authorization explicitly approves it

- [ ] **Step 4: Extend loop brief**

Loop brief should include a concise `symbolic_law_discovery` / `dimensional_scaling_review` section when council summary exists. It must be clear that this is hypothesis-generation, not evidence.

## Task 6: Smoke Harness

**Files:**
- Create: `/Users/humphrey/projects/factor-factory/scripts/run_revision_council_smoke.py`
- Modify: `/Users/humphrey/projects/factor-factory/scripts/run_step6_intelligence_acceptance.py` to include council smoke as optional Phase H status, if stable.

- [ ] **Step 1: Enforce `/tmp` root policy**

`run_revision_council_smoke.py` must reject non-`/tmp` roots with:

```text
BLOCK_NON_TMP_FACTORFORGE_ROOT
```

- [ ] **Step 2: Positive smoke cases**

Create synthetic `/tmp` fixtures for:

1. `price_volume_cost_contradiction`
- Expected symbolic tools: dimensional analysis, stochastic process, natural-time clock.
- Expected branch: advisory `mechanism_challenge` or cost-focused Bayesian branch depending on loop authorization.

2. `high_turnover_parameter_revision`
- Expected branch: `bayesian_exploit`.
- No Step3B handoff unless approved by existing loop authorization.

3. `mechanism_unclear_symbolic_challenge`
- Expected branch: `mechanism_challenge`.

- [ ] **Step 3: Negative smoke cases**

Must block and prove no forbidden writes:

1. proposal contains portfolio repair language.
2. proposal contains short-leg adoption language.
3. proposal contains decile trading language.
4. symbolic proposal lacks dimensional review.
5. branch template has execution enabled by default.
6. council process creates forbidden `handoff_to_step3b` before merge.
7. generated_code appears before human approval.

- [ ] **Step 4: Canonical pollution check**

Smoke summary must include:

```json
{
  "canonical_pollution": {
    "polluted": false,
    "new_files": []
  }
}
```

## Task 7: Documentation and Skill Updates

**Files:**
- Modify: `/Users/humphrey/projects/factor-factory/skills/factor-forge-step6/SKILL.md`
- Modify: `/Users/humphrey/projects/factor-factory/skills/factor-forge-research-brain/SKILL.md`
- Modify: `/Users/humphrey/projects/factor-factory/skills/factor-forge-ultimate/SKILL.md`
- Modify: `/Users/humphrey/projects/factor-factory/docs/contracts/step6-contract.md`
- Modify: `/Users/humphrey/projects/factor-factory/docs/contracts/step6-contract.zh-CN.md`

- [ ] **Step 1: Document Revision Council role**

Explain that council outputs are proposal-only and never canonical code/writeback.

- [ ] **Step 2: Document symbolic law discovery**

Include this exact principle:

```text
The symbolic law discovery agent treats a factor formula as a mathematical object. It may use dimensional analysis, scaling laws, stochastic-process reasoning, spectral analysis, robust statistics, projection, functional analysis, dynamical systems, and stopping-time reasoning to propose testable hypotheses. It must not treat mathematical plausibility as evidence of tradability or promotion readiness.
```

- [ ] **Step 3: Document dimensional/scaling discipline**

Cover:

- units and dimensions
- dimension-erasing transforms
- scale invariance
- natural market time
- drift/diffusion/jump scale
- limit cases
- frequency consistency

- [ ] **Step 4: Sync installed skills**

After repo docs/scripts are stable, sync installed skills:

```bash
rsync -a --delete --exclude __pycache__ /Users/humphrey/projects/factor-factory/skills/factor-forge-step6/ /Users/humphrey/.codex/skills/factor-forge-step6/
rsync -a --delete --exclude __pycache__ /Users/humphrey/projects/factor-factory/skills/factor-forge-research-brain/ /Users/humphrey/.codex/skills/factor-forge-research-brain/
rsync -a --delete --exclude __pycache__ /Users/humphrey/projects/factor-factory/skills/factor-forge-ultimate/ /Users/humphrey/.codex/skills/factor-forge-ultimate/
```

Verify:

```bash
diff -qr -x __pycache__ /Users/humphrey/projects/factor-factory/skills/factor-forge-step6 /Users/humphrey/.codex/skills/factor-forge-step6
diff -qr -x __pycache__ /Users/humphrey/projects/factor-factory/skills/factor-forge-research-brain /Users/humphrey/.codex/skills/factor-forge-research-brain
diff -qr -x __pycache__ /Users/humphrey/projects/factor-factory/skills/factor-forge-ultimate /Users/humphrey/.codex/skills/factor-forge-ultimate
```

Expected: rc `0`, no diff output.

## Reviewer Acceptance Checklist

Reviewer should not re-review old Step2/5/6 architecture. Review only Phase H changes.

Required checks:

1. Council agents are proposal-only.
2. No council script writes Step3B handoff, generated code, clean data, official library, runs, evaluations, or archive.
3. `symbolic_law_discovery` includes real mathematical reasoning fields, not only hard-coded labels.
4. Dimensional/scaling review includes units, dimension-erasing transforms, scale invariance, natural time, and limiting cases.
5. Forbidden portfolio/short/decile/clean-data mutation text is recursively scanned.
6. Branch templates from council remain `proposed`, human approval required, execution disabled.
7. Missing council artifacts do not break existing Step6 path.
8. Existing Step6 intelligence acceptance still passes.
9. New council smoke passes in `/tmp` and blocks non-`/tmp` roots.
10. Negative smokes fail for the intended reason, not unrelated missing-provenance reasons.
11. Canonical pollution is false.
12. Installed skill diff is clean if skills were changed.

## Minimum Verification Commands

```bash
cd /Users/humphrey/projects/factor-factory
python3 -m py_compile \
  factor_factory/revision_council/schema.py \
  factor_factory/revision_council/validator.py \
  factor_factory/revision_council/guards.py \
  skills/factor-forge-step6/scripts/build_revision_council_packet.py \
  skills/factor-forge-step6/scripts/run_revision_council.py \
  skills/factor-forge-step6/scripts/merge_revision_council.py \
  scripts/run_revision_council_smoke.py

python3 scripts/run_revision_council_smoke.py --fresh --root /tmp/factorforge_revision_council_phase_h
python3 scripts/run_revision_council_smoke.py --fresh --root /Users/humphrey/tmp_factorforge_bad
python3 scripts/run_step6_intelligence_acceptance.py --fresh --root /tmp/factorforge_step6_intelligence_acceptance_phase_h_regression
```

Expected:

- py_compile rc `0`.
- `/tmp` council smoke verdict `ACCEPT`.
- non-`/tmp` smoke rc `1`, token `BLOCK_NON_TMP_FACTORFORGE_ROOT`.
- Step6 intelligence acceptance token `STEP6_INTELLIGENCE_ACCEPTED`.
- no canonical pollution.

## Suggested Commit Sequence

1. `feat: add revision council schema and guards`
2. `feat: build revision council packet`
3. `feat: generate symbolic revision council proposals`
4. `feat: merge revision council proposals into branch templates`
5. `feat: integrate revision council with step6 search policy`
6. `test: add revision council smoke harness`
7. `docs: document symbolic law discovery in factor forge skills`
