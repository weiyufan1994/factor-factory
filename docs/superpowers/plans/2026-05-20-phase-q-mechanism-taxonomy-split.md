# Phase Q Mechanism Taxonomy Split Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Allow a factor's economic/mechanism family and mathematical tool family to differ without triggering stale mechanism-token validation.

**Architecture:** Keep legacy `model_family` for backward compatibility, but add explicit taxonomy fields to the Step6 loop brief and validator: `economic_mechanism_family`, `math_tool_family`, and `model_equation_family`. Markdown consistency should treat the math-tool token as allowed mechanism math text, not stale family pollution.

**Tech Stack:** Python Step6 scripts, existing `/tmp` smoke framework, JSON/Markdown loop brief artifacts.

---

### Task 1: Add a Failing Smoke for Price-Volume Mechanism With Stochastic-Process Math Tool

**Files:**
- Modify: `scripts/run_step6_intelligence_smoke.py`

- [ ] **Step 1: Write failing mutation/case**

Add a smoke mutation that builds a current iteration where:
- `mechanism_analysis.factor_family = price_volume_correlation`
- `mechanism_math_summary.model_family = price_volume_microstructure`
- `mechanism_math_summary.math_tool_family = stochastic_process`
- loop brief markdown contains both `price_volume_microstructure` and `stochastic_process`

Expected before implementation: `validate_step6.py` blocks with `loop_research_brief_mechanism_markdown_consistency` because `stochastic_process` is treated as stale.

- [ ] **Step 2: Run RED**

Run:
`python3 scripts/run_step6_intelligence_smoke.py --fresh --root /tmp/factorforge_step6_intelligence_phase_q_taxonomy_red`

Expected: smoke BLOCKs or the targeted case fails.

### Task 2: Add Taxonomy Fields to Loop Brief Generation

**Files:**
- Modify: `skills/factor-forge-step6/scripts/run_step6.py`

- [ ] **Step 1: Implement taxonomy enrichment**

Update `mechanism_math_summary_from_contract()` to carry:
- `economic_mechanism_family`: from contract `economic_mechanism_family`, else contract `model_family`
- `math_tool_family`: from contract `math_tool_family`, else first model-like toolkit such as `stochastic_process`, else contract `model_family`
- `model_equation_family`: from contract `model_equation_family`, else contract `process_hypothesis` family fallback

Do not implicitly copy `formula_specific_derivation.selected_model_family` into `math_tool_family`: in older artifacts that field may describe an economic mechanism or model-selection label rather than the mathematical tool. Only explicit `math_tool_family` contract/memo fields should override the backward-compatible fallback.

- [ ] **Step 2: Render taxonomy in Markdown**

In `render_loop_research_brief_markdown()`, print `Economic mechanism family`, `Math tool family`, and `Model equation family` in section 9.

### Task 3: Teach Validator That Math Tool Tokens Are Not Stale Mechanism Pollution

**Files:**
- Modify: `skills/factor-forge-step6/scripts/validate_step6.py`

- [ ] **Step 1: Read taxonomy fields**

Read current/brief `math_tool_family`, `economic_mechanism_family`, and `model_equation_family` from `mechanism_math_summary` / contract / formula derivation.

- [ ] **Step 2: Validate if present, preserve backward compatibility if absent**

If the brief includes taxonomy fields, require equality to current fields. If absent, do not fail old artifacts.

- [ ] **Step 3: Exclude math tool tokens from stale-term detection**

Build `allowed_tokens` from `factor_family`, `model_family`, `math_tool_family`, `economic_mechanism_family`, and formula derivation `selected_model_family`. Stale terms should exclude all allowed tokens.

### Task 4: Verify and Sync

**Files:**
- Modify: installed skills under `/Users/humphrey/.codex/skills/factor-forge-step6/`

- [ ] **Step 1: Run verification**

Run:
- `python3 -m py_compile skills/factor-forge-step6/scripts/run_step6.py skills/factor-forge-step6/scripts/validate_step6.py scripts/run_step6_intelligence_smoke.py`
- `python3 scripts/run_step6_intelligence_smoke.py --fresh --root /tmp/factorforge_step6_intelligence_phase_q_taxonomy_final`
- `python3 scripts/run_step6_intelligence_acceptance.py --fresh --root /tmp/factorforge_step6_intelligence_acceptance_phase_q_taxonomy_final`

Expected: all ACCEPT / `STEP6_INTELLIGENCE_ACCEPTED`.

- [ ] **Step 2: Sync installed skill**

Run:
`rsync -a --delete --exclude '__pycache__' skills/factor-forge-step6/ /Users/humphrey/.codex/skills/factor-forge-step6/`

Then verify diff clean:
`diff -qr -x __pycache__ skills/factor-forge-step6 /Users/humphrey/.codex/skills/factor-forge-step6`
