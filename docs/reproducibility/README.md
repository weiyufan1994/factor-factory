> [中文版本](README.zh-CN.md)

# Reproducibility

This directory holds step-level reproducibility cards, gap cards, and repo-structure doctrine for Bernard/Mac direct reproduction.

## How this directory fits the repo

If you are reading the repository from the top down, the intended order is:
1. `README.md` — root repo identity and current architectural reading path
2. `docs/repo-layering-and-naming.md` — layer boundaries and naming doctrine
3. `docs/reproducibility/` — what is minimally reproducible today
4. `docs/contracts/` — stable input/output/runtime contracts
5. `fixtures/step*/` + `scripts/run_step*_sample.*` — tiny runnable sample paths

In other words:
- `README.md` tells you **what the repo is**,
- `docs/repo-layering-and-naming.md` tells you **how to read the repo without confusing layers**,
- `docs/reproducibility/` tells you **what can currently be reproduced truthfully**.

## What belongs here

This directory is the right place for:
- step-level reproducibility cards,
- gap cards,
- notes about minimal reproducibility boundaries,
- repo-structure doctrine tied to reproducibility,
- reader-first navigation notes for reproduction.

This directory is **not** the place for:
- low-level runtime artifact dumps,
- ad hoc local execution residue,
- undocumented architecture assumptions that belong in contracts.

## Reading goal

A new reader should be able to inspect this directory and answer:
- what each step can reproduce today,
- what the acceptance boundary is,
- where the tiny fixture path begins,
- what remains intentionally partial or limited.
