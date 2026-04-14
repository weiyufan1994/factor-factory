> [中文版本](repo-layering-and-naming.zh-CN.md)

# Repo layering and naming doctrine

## Purpose

This note explains how to read the repository without confusing:
- historical Step 1-first construction,
- current Step1–Step5 reproducibility scope,
- engineering implementation layers,
- runtime artifact layers.

## Layering doctrine

### A. Reader-first governance layer
This is the layer a fresh reader should use first.

- `README.md`
- `docs/contracts/`
- `docs/reproducibility/`
- `docs/closeouts/`

This layer defines what the repository *claims* and what can currently be reproduced.

### B. Tiny reproducibility layer
This is the minimal runnable substrate retained in git.

- `fixtures/step1/` through `fixtures/step5/`
- `scripts/run_step1_sample.sh` through `scripts/run_step5_sample.sh`
- `scripts/run_step1_sample.py` through `scripts/run_step5_sample.py`

This layer exists so the repo does not depend purely on hidden local state or chat memory.

### C. Engineering implementation layer
This is the real implementation substrate.

- `skills/factor_forge_step1/modules/`
- `skills/factor_forge_step1/prompts/`
- `skills/factor_forge_step1/schemas/`
- `skills/`

This layer is allowed to reflect historical build order.
That means it may still look more Step 1-heavy than the reader-first layer.

### D. Runtime artifact layer
This is where locally produced outputs accumulate.

- `objects/`
- `runs/`
- `archive/`
- `evaluations/`
- `generated_code/`

These paths are useful operationally, but they should not define the human-facing repo identity.

## Naming doctrine

### 1. Docs naming
- contracts: `docs/contracts/stepN-contract.md`
- reproducibility notes: `docs/reproducibility/*`
- acceptance / closeout notes: `docs/closeouts/*`

### 2. Fixture naming
- keep tiny committed sample files under `fixtures/stepN/`
- use `__sample` suffix for canonical tiny committed objects where practical

Examples:
- `alpha_idea_master__sample.json`
- `factor_spec_master__sample.json`
- `data_prep_master__sample.json`
- `handoff_to_step4__sample.json`

### 3. Runtime object naming
Use explicit object-class prefixes and preserve handoff direction.

Examples:
- `alpha_idea_master__{report_id}.json`
- `factor_spec_master__{report_id}.json`
- `data_prep_master__{report_id}.json`
- `qlib_adapter_config__{report_id}.json`
- `implementation_plan_master__{report_id}.json`
- `factor_run_master__{report_id}.json`
- `factor_case_master__{report_id}.json`
- `handoff_to_step3__{report_id}.json`
- `handoff_to_step4__{report_id}.json`
- `handoff_to_step5__{report_id}.json`

### 4. Script naming
Keep runnable tiny sample entry points explicit and step-indexed.

- `run_step1_sample.py|sh`
- `run_step2_sample.py|sh`
- `run_step3_sample.py|sh`
- `run_step4_sample.py|sh`
- `run_step5_sample.py|sh`

### 5. Scope wording doctrine
Use these terms consistently:

- **minimal reproducibility chain** — committed tiny-fixture path across Step1–Step5
- **engineering layer** — implementation substrate such as step-specific modules/prompts/schemas under `skills/` plus skill wrappers
- **runtime layer** — produced objects, runs, archives, evaluations
- **truthful partial sample** — a sample that intentionally shows partial status instead of fake success

Avoid presenting:
- a fixture sample as full production proof,
- a runtime artifact path as the repository architecture,
- the old Step 1-first build order as the current whole-repo identity.

## Current governance rule

Until a future deliberate migration is approved, prefer:
- improving root readability,
- improving layer boundaries,
- improving naming clarity,

over large-scale directory relocation.

That is the current cleanup policy for this repository.
