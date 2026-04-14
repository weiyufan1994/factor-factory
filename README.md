> [中文版本](README.zh-CN.md)

# FactorForge

FactorForge is a **Step1–Step5 factor research pipeline repository** with a committed **minimal reproducibility chain**.

The repository should now be read in this order:
1. **root README** — what the repo is and how to orient yourself,
2. **`docs/reproducibility/`** — what is minimally reproducible today,
3. **`docs/contracts/`** — step-level input/output/runtime contracts,
4. **`fixtures/step*/` + `scripts/run_step*_sample.*`** — the tiny runnable sample path,
5. **`skills/` / runtime object paths** — step-specific engineering implementation layers and outputs.

## Current repo judgment

As of 2026-04-14, the repository is no longer just a Step 1 build artifact.
It should be understood as:

> **a Step1–Step5 repository with committed minimal reproducibility, where Step 1 is the earliest engineering layer, not the whole repository identity.**

That distinction matters because some older root files and early commits still reflect the original Step 1-first construction history.
The current repository intent is broader than that origin point.

## What is in scope today

The current accepted in-repo baseline is:
- Step 1 through Step 5 all have committed fixture directories,
- Step 1 through Step 5 all have committed sample runners,
- step-level contracts are documented under `docs/contracts/`,
- reproducibility notes and gap/acceptance cards are under `docs/reproducibility/` and `docs/closeouts/`.

This means the repository now supports a **tiny-fixture / Bernard-Mac-ready first-version reproducibility path** across the full chain.

## What is *not* claimed

This repository does **not** yet claim:
- full production-grade one-command reproducibility,
- final clean-room cross-machine packaging,
- final architecture purity across all historical layers,
- that Step 4 / Step 5 samples are full-window success cases.

Some samples are intentionally **truthful partial** samples rather than fake success samples.

## Repo layering

### 1) Contracts and reproducibility layer
Use this layer first if you are trying to understand or reproduce the repo.

- `docs/contracts/` — stable step contracts
- `docs/reproducibility/` — reproducibility cards and gap cards
- `docs/closeouts/` — acceptance and closeout notes
- `fixtures/step1/` … `fixtures/step5/` — tiny committed fixtures
- `scripts/run_step1_sample.*` … `scripts/run_step5_sample.*` — sample entry points

### 2) Engineering implementation layer
Use this layer when you need to inspect how the pipeline is actually implemented.

- `skills/factor_forge_step1/modules/` — current Step 1 engineering substrate
- `skills/factor_forge_step1/prompts/` — prompt assets, currently Step 1-heavy
- `skills/factor_forge_step1/schemas/` — schema assets used by the engineering layer
- `skills/` — skill wrappers and step packages

### 3) Runtime/output layer
Use this layer for local runs, artifacts, and handoff objects.

- `objects/` — object/handoff artifacts
- `runs/` — local run outputs
- `archive/` — closure bundles
- `evaluations/` — evaluation outputs
- `generated_code/` — generated implementation artifacts

## Current naming doctrine

- **Step contracts** live under `docs/contracts/stepN-contract.md`
- **Reproducibility notes** live under `docs/reproducibility/`
- **Acceptance / closeout notes** live under `docs/closeouts/`
- **Tiny committed sample inputs** live under `fixtures/stepN/`
- **Tiny sample entry scripts** live under `scripts/run_stepN_sample.py|sh`
- **Handoff objects** use `handoff_to_stepN__{report_id}.json`
- **Master objects** keep explicit suffixes such as `alpha_idea_master__{report_id}.json`, `factor_spec_master__{report_id}.json`, `data_prep_master__{report_id}.json`, `factor_run_master__{report_id}.json`, `factor_case_master__{report_id}.json`

The intent is that a reader can distinguish:
- **docs layer**,
- **fixtures layer**,
- **engineering code layer**,
- **runtime artifact layer**,
without having to infer repo structure from chat history or commit archaeology.

## Where Step 1 fits now

Step 1 remains important, but it should be read as:
- the **earliest implemented engineering layer**, and
- one contributor to the full Step1–Step5 pipeline,
not as the complete definition of the repository.

Historically, several root-level files still came from the Step 1-first phase.
That historical fact should not be mistaken for the current architectural intent.

## Recommended reading path

1. `docs/closeouts/step1-step5-minimal-reproducibility-acceptance-2026-04-14.md`
2. `docs/reproducibility/README.md`
3. `docs/contracts/README.md`
4. `docs/contracts/step1-contract.md` through `step5-contract.md`
5. `docs/plans/private-fund-grade-factor-factory-gap-roadmap-2026-04-14.md`
6. `fixtures/step*/README.md`
7. `scripts/run_step*_sample.sh`

## Runtime note

Older Step 1 engineering notes referenced a dedicated local runtime for extraction work.
That remains an implementation detail, not the top-level repository identity.

## Practical command map

Typical minimal sample runs:

```bash
./scripts/run_step1_sample.sh
./scripts/run_step2_sample.sh
./scripts/run_step3_sample.sh
./scripts/run_step4_sample.sh
./scripts/run_step5_sample.sh
```

## Roadmap documents

For the next-stage build path from the current CPV-backed minimal chain to a private-fund-grade factor factory, see:
- `docs/plans/private-fund-grade-factor-factory-gap-roadmap-2026-04-14.md`

## Current cleanup stance

The current cleanup goal is **governance clarity, layering clarity, and naming clarity first**.
Large-scale relocations or architectural migrations should only happen after the repository story is readable from the root.
