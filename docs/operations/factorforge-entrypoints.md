# Factor Forge Entrypoints

This repository separates production research entrypoints from smoke, fixture,
and deprecated developer entrypoints. Agents should prefer the production
entrypoints below unless the user explicitly asks for a smoke or historical
reproducibility check.

Every file under `scripts/` must be classified in
`docs/operations/factorforge-entrypoint-registry.json`. Run
`scripts/run_factorforge_entrypoint_hygiene_smoke.py` after adding, moving, or
renaming an entrypoint.

Adjacent topic-monitoring, AI-interest, and intraday source-layer utilities do
not belong in this repository. They live in separate workspaces under
`/Users/humphrey/projects/topic-liquidity`, `/Users/humphrey/projects/ai-interests`,
and `/Users/humphrey/projects/data-yichu`.

## Production Entrypoints

- `scripts/prepare_factorforge_formal_artifacts.py`
  - Humphrey/control-plane formal preparation.
  - Consumes source PDF plus Step1/Step2 formal LLM raw outputs, or runs the
    explicit formal LLM bridges when requested.
  - Produces Step1, Step2, and Step3A artifacts under the active
    `FACTORFORGE_ROOT`.
  - May write `objects/runtime_context/runtime_context__<report_id>.json`.
  - Must not start Step3B, Step4, or the research worker.

- `scripts/build_factorforge_runtime_context.py`
  - Builds the runtime manifest that freezes all artifact, run, evaluation, and
    handoff paths for worker-side execution.
  - This manifest is the handoff contract between Humphrey and the research
    worker.

- `scripts/run_factorforge_ultimate.py`
  - Worker-side formal execution wrapper for Step3B through Step6.
  - Formal Step3B/Step4/Step5/Step6 work should enter through this wrapper with
    a runtime manifest, not through direct step scripts.

## Formal LLM Boundary

- `scripts/run_factorforge_step1_llm_bridge.py`
  - Step1 formal LLM bridge.
  - Produces Step1 raw extraction artifacts.

- `scripts/run_factorforge_step2_llm_bridge.py`
  - Step2 formal LLM bridge.
  - Produces Step2 raw extraction and audit artifacts.

- `scripts/run_factorforge_humphrey_llm_provider.py`
  - Humphrey/OpenClaw provider adapter used by the formal bridges.
  - It is an IO adapter, not a research entrypoint.

Alternative Step12 intake helpers are classified as research scaffolds, not the
PDF formal path. They must write through explicit `FACTORFORGE_ROOT` outside the
repo worktree and may not create repo-root `objects/`.

Provider/model selection must be explicit and auditable. OpenClaw display names
are not formal API model names unless a contract maps them explicitly. In formal
mode the Humphrey provider adapter must receive
`formal_llm_provider_request.contract_version`, `provider`, and `model` from the
Step1/Step2 bridge request; wrapper defaults and environment fallback are not a
valid production provider contract.

## Smoke And Developer Entrypoints

Files named `*_smoke.py`, `*_benchmark.py`, or under `scripts/deprecated/` are
not production entrypoints. They may be used for local verification only and must
not be cited as fresh factor-research proof.

The deprecated Step1 sample entrypoints live under:

- `scripts/deprecated/run_alpha014_step3b.py`
- `scripts/deprecated/run_step1_sample.py`
- `scripts/deprecated/run_step1_sample.sh`

They are retained for historical fixture reproducibility only. Deprecated files
must stay under `scripts/deprecated/` and must not be used as formal research
entrypoints.

## Workspace Hygiene

Runtime artifacts should not live in the repo worktree during normal
development. Keep these roots outside the repo or under an explicit temporary
root:

- `objects/`
- `runs/`
- `evaluations/`
- `generated_code/`
- `archive/`
- `factorforge/`
- `output/`
- `tmp/`

For local smoke tests, prefer `/tmp/factorforge_*` roots. For production, use the
environment-specific `FACTORFORGE_ROOT`.

`scripts/prepare_factorforge_formal_artifacts.py` blocks formal writes to the
repository root with `BLOCK_FORMAL_ROOT_UNSPECIFIED`; pass an explicit temporary
or production root instead.
