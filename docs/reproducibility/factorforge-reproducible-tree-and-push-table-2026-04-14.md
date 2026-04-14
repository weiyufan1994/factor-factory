# 2026-04-14 — FactorFactory reproducible tree + Step1–5 push table

- Workstream: `FactorFactory 仓库结构化整理 + Bernard/Mac 可复现边界`
- Status: `drafted`
- Purpose: define the repository tree that should be pushed when the goal is **Mac/Bernard directly reproducible**, not merely skill-readable

## 1. Final conclusion
The current repository already contains useful material for Step1–5, but it is **not yet organized as a clean reproducible engineering repository**.

The main problem is not “missing all code”; it is **layer mixing**:
- engineering implementation layer
- runtime/generated artifacts layer
- skill packaging layer
- documentation / contracts layer
are currently mixed in a way that is understandable to us, but not yet ideal for Bernard-on-Mac direct reproduction.

So the correct next standard is:

> Push a repository tree where Bernard can clearly distinguish:
> 1. what is source code,
> 2. what is skill packaging,
> 3. what is reproducible fixture input,
> 4. what is runtime output,
> 5. what should never be committed.

## 2. Recommended structured repository tree

```text
factorforge/
├── README.md
├── pyproject.toml / requirements.txt                # runtime environment declaration (to be added)
├── docs/
│   ├── architecture/
│   ├── contracts/
│   ├── reproducibility/
│   └── closeouts/
├── src/
│   └── factorforge/
│       ├── step1/
│       ├── step2/
│       ├── step3/
│       ├── step4/
│       ├── step5/
│       ├── common/
│       └── report_ingestion/
├── prompts/
├── schemas/
├── skills/
│   ├── factor-forge-step1.skill
│   ├── factor-forge-step1/
│   ├── factor-forge-step2.skill
│   ├── factor-forge-step2/
│   ├── factor-forge-step3.skill
│   ├── factor-forge-step3/
│   ├── factor-forge-step4.skill
│   ├── factor-forge-step4/
│   ├── factor-forge-step5/
│   └── factor_forge_step5/
├── fixtures/
│   ├── step1/
│   ├── step2/
│   ├── step3/
│   ├── step4/
│   └── step5/
├── scripts/
│   ├── run_step1_sample.sh
│   ├── run_step2_sample.sh
│   ├── run_step3_sample.sh
│   ├── run_step4_sample.sh
│   └── run_step5_sample.sh
├── outputs/                                         # optional local-only; usually gitignored
├── archive/                                         # gitignored unless tiny curated proof bundles
├── runs/                                            # gitignored unless tiny curated fixtures
├── evaluations/                                     # gitignored unless tiny curated fixtures
├── objects/                                         # gitignored unless curated reproducibility fixtures
└── .gitignore
```

## 3. What should be considered each layer

### A. Engineering implementation layer
This is the actual source of truth for reproduction.
It should include:
- reusable Python modules
- orchestration logic
- validators
- adapters
- prompt loaders
- schema helpers
- step-specific source code

**Current state**
- Step 1 has this layer most clearly, currently under `modules/report_ingestion/**`
- Step 2–5 mostly have code embedded under `skills/factor-forge-step*/scripts` and `skills/factor-forge-step5/modules`

**Recommended direction**
- Step 1 engineering code can remain, but should eventually move under `src/factorforge/step1/` (or `src/factorforge/report_ingestion/` for the shared intake stack)
- Step 2–5 engineering code should be promoted out of skill-only placement into `src/factorforge/step2..step5/`
- skill directories should become packaging / invocation wrappers, not the only home of core logic

### B. Skill layer
This layer is for OpenClaw discovery and invocation.
It should include:
- `SKILL.md`
- references/
- thin scripts/ wrappers
- bundled helper modules only when strictly needed

**Rule**
The skill layer should not be the sole place where critical engineering logic lives, if Bernard/Mac direct reproduction is required.

### C. Fixture layer
This is the minimum reproducibility substrate.
It should include:
- tiny synthetic or tiny real sample inputs
- stable, small enough to commit
- enough for Bernard to run each step without huge data dependencies

**Current state**
- This layer is not yet formalized.
- This is one of the biggest current gaps.

### D. Runtime output layer
This includes:
- `runs/`
- `archive/`
- `evaluations/`
- `objects/`

**Rule**
These should normally be gitignored, except for tiny curated fixtures or proof bundles explicitly selected for reproducibility.

## 4. Immediate tree cleanup recommendation
Without doing a huge refactor first, the repository can already become much more structured by adopting this near-term layout policy:

### Keep now
- `skills/`
- `prompts/`
- `schemas/`
- `modules/report_ingestion/**` (Step 1 engineering layer)

### Add soon
- `docs/reproducibility/`
- `docs/contracts/`
- `fixtures/`
- `scripts/` for sample runs

### Avoid pushing by default
- `runs/**`
- `evaluations/**`
- `archive/**`
- `objects/**`
- large parquet / csv artifacts

## 5. Step1–5 reproducible push table

### Legend
- `Y` = should be pushed for Bernard/Mac reproducibility
- `N` = should not be pushed by default
- `P` = partial / currently insufficient / push exists but not enough for full reproducibility

| Step | Skill layer | Engineering code layer | Fixture / sample input | Runtime output needed in git? | Current reproducibility judgment |
|------|-------------|------------------------|------------------------|-------------------------------|----------------------------------|
| Step 1 | Y | Y | P | N | **Closest to reproducible**, but still needs explicit fixture + run docs |
| Step 2 | Y | P | N | N | **Not yet reproducible-level**; engineering logic mainly lives in skill scripts |
| Step 3 | Y | P | N | N | **Not yet reproducible-level**; needs fixture and clearer engine/source split |
| Step 4 | Y | P | N | N | **Not yet reproducible-level**; code exists, but depends on upstream local objects/data |
| Step 5 | Y | P | N | N | **Not yet reproducible-level**; good code exists, but reproduction depends on upstream handoff fixture |

## 6. Step-by-step interpretation

### Step 1
#### What should be pushed
- skill package
- `modules/report_ingestion/**`
- prompts
- schemas
- a tiny reproducibility fixture
- a clear run command

#### Why
Step 1 already has a meaningful engineering layer in repo.
It is the template for what later steps should approach.

#### Current verdict
**Almost reproducible-level, but not yet fully so** because fixture + environment/run instructions are not yet formalized.

### Step 2
#### What should be pushed
- skill package
- core source code promoted into engineering layer
- one tiny input fixture representing `alpha_idea_master` / Step 1 handoff shape
- one deterministic run path

#### Current verdict
**Current push is insufficient for Bernard direct reproduction.**

### Step 3
#### What should be pushed
- skill package
- source code promoted out of skill-only scripts into engineering layer
- tiny fixture for `factor_spec_master` / `data_prep_master` expected shapes
- run instructions

#### Current verdict
**Current push is insufficient for Bernard direct reproduction.**

### Step 4
#### What should be pushed
- skill package
- engineering implementation of run/validate/adapters
- tiny controlled local input fixture instead of huge minute parquet
- sample command that can generate a tiny run artifact on Mac

#### Current verdict
**Current push is insufficient for Bernard direct reproduction.**
The main gap is fixture/input strategy.

### Step 5
#### What should be pushed
- skill package
- engineering code for run/validate/evaluator/case_builder/archiver/rules/io
- tiny handoff fixture from Step 4
- deterministic sample command

#### Current verdict
**Current push is insufficient for Bernard direct reproduction.**
The main gap is fixture and upstream object closure.

## 7. Minimal reproducibility standard by step
Each step should eventually satisfy all five of these:

1. source code exists in a stable engineering layer
2. skill package exists as invocation wrapper
3. tiny fixture exists and is committed
4. one sample run command is documented
5. one success criterion is documented

If any of these is missing, the step should not be called “Bernard/Mac directly reproducible”.

## 8. Concrete next repository actions

### Action 1 — tree regularization
Create these directories in repo:
- `docs/reproducibility/`
- `docs/contracts/`
- `fixtures/`
- `scripts/`

### Action 2 — Step 1 formal reproducibility card
Write one file:
- `docs/reproducibility/step1-repro-card.md`

Include:
- required files
- fixture path
- run command
- output expectation

### Action 3 — Step 2–5 gap cards
Write one file per step:
- `docs/reproducibility/step2-gap-card.md`
- `docs/reproducibility/step3-gap-card.md`
- `docs/reproducibility/step4-gap-card.md`
- `docs/reproducibility/step5-gap-card.md`

Each should explicitly say:
- what is already in repo
- what still lives only in skill scripts
- what fixture is missing
- what blocks Bernard direct reproduction

### Action 4 — do not push runtime data as reproducibility substitute
Do not confuse:
- giant minute parquet
- generated runs
- archived outputs
with
- formal reproducibility fixtures

Large runtime artifacts are evidence, not the right default reproducibility substrate.

## 9. Final judgment
If the standard is merely “OpenClaw can discover the skills”, the recent push was enough.
If the standard is “Bernard on Mac can directly reproduce Step1–5”, the repository still needs:
- clearer tree layering
- promoted engineering code for Step2–5
- tiny committed fixtures
- explicit reproducibility docs

So the current state should be judged as:

> **Step 1 = near reproducible-level**
> **Step 2–5 = code-visible and skill-visible, but not yet Bernard/Mac reproducible-level**

## 10. One-sentence summary
The right push target is not “more files”, but a repository where source code, skill wrappers, tiny fixtures, and reproducibility docs are separated cleanly enough that Bernard can run each step without depending on our private runtime outputs.
