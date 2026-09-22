> [中文版本](README.zh-CN.md)

# Contracts

This directory holds stable input/output/runtime contracts that should be readable without digging through runtime artifacts.

## How this directory fits the repo

The intended reader-first path is:
1. `README.md`
2. `docs/repo-layering-and-naming.md`
3. `docs/reproducibility/`
4. `docs/contracts/`
5. `fixtures/step*/` and `scripts/run_step*_sample.*`

That ordering is deliberate:
- first understand the **repo identity**,
- then the **layer boundaries**,
- then the **current reproducibility boundary**,
- and only then the **step contracts** used by the implementation and sample runners.

## What contracts should do

Each step contract should let a reader understand, at minimum:
- the current input class,
- the current output class,
- the committed tiny reproducibility inputs,
- the committed sample runner,
- the engineering layer dependency surface,
- any reproducibility warning or boundary condition.

A contract should be stable enough that a reader does not need to reconstruct the step definition from:
- hidden object paths,
- runtime directories,
- commit archaeology,
- or chat history.

## Current scope

These contracts document the current first-version Step1–Step5 minimal reproducibility chain.
They do not claim final architecture purity or full production packaging.

## Runtime Context

Step workers should not independently guess artifact paths. Use the shared runtime context contract:

- `factorforge-runtime-context-contract.md`
- `factorforge-runtime-context-contract.zh-CN.md`

Python entrypoint:

```python
from factor_factory.runtime_context import resolve_factorforge_context
```

Manifest entrypoint:

```bash
python3 scripts/build_factorforge_runtime_context.py --report-id <report_id> --write
```
