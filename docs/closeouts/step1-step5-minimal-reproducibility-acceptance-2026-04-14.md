# 2026-04-14 — Step1–Step5 minimal reproducibility acceptance note

- Repository: `factorforge`
- Scope: `FactorForge Step1–Step5 Bernard/Mac minimal reproducibility chain`
- Acceptance time: 2026-04-14 07:26 UTC
- Acceptance status: `pass` (minimal reproducibility level)

## Final conclusion
As of this acceptance note, the repository has been upgraded from:
- skill-visible / code-visible only

to:
- **Step1–Step5 minimal reproducibility chain present in-repo**

This does **not** mean full production-scale reproduction is complete.
It **does** mean the repository now contains, for each step from 1 through 5:
1. committed fixture layer,
2. committed sample runner,
3. local runnable sample evidence,
4. GitHub-pushed retention.

Therefore the correct acceptance wording is:

> **FactorForge Step1–Step5 minimal reproducibility chain is now accepted at the tiny-fixture / Bernard-Mac-ready-first-version level.**

## What was completed

### Repository structure and governance layer
The repository now contains explicit reproducibility structure:
- `docs/reproducibility/`
- `docs/contracts/`
- `docs/closeouts/`
- `fixtures/step1/` through `fixtures/step5/`
- `scripts/run_step1_sample.sh` through `scripts/run_step5_sample.sh`
- `scripts/run_step1_sample.py` through `scripts/run_step5_sample.py`

This means source/skill/reproducibility/fixture layers are now visibly separated enough for Bernard/Mac-oriented use.

### Step 1
#### Fixture layer present
- `fixtures/step1/sample_factor_report.html`
- `fixtures/step1/sample_intake_response.json`

#### Sample runner present
- `scripts/run_step1_sample.sh`
- `scripts/run_step1_sample.py`

#### Evidence
The local sample run produced Step 1 artifact classes equivalent to:
- intake validation artifact
- report_map artifact
- alpha_thesis artifact
- ambiguity_review artifact

#### GitHub retention commit
- `e8d72d4` — `fixtures: add runnable step1 tiny reproducibility sample`

### Step 2
#### Fixture layer present
- `fixtures/step2/alpha_idea_master__sample.json`
- `fixtures/step2/report_map_validation__sample__alpha_thesis.json`
- `fixtures/step2/report_map_validation__sample__challenger_alpha_thesis.json`
- `fixtures/step2/report_map__sample__primary.json`
- `fixtures/step2/sample_report_stub.pdf`

#### Sample runner present
- `scripts/run_step2_sample.sh`
- `scripts/run_step2_sample.py`

#### Evidence
The local sample run completed and wrote Step 2 artifact classes:
- primary raw spec artifact
- challenger raw spec artifact
- consistency audit artifact
- `factor_spec_master`
- `handoff_to_step3`

#### GitHub retention commit
- `408a23e` — `fixtures: add runnable step2 tiny reproducibility sample`

### Step 3
#### Fixture layer present
- `fixtures/step3/factor_spec_master__sample.json`
- `fixtures/step3/alpha_idea_master__sample.json`
- `fixtures/step3/minute_input__sample.csv`
- `fixtures/step3/daily_input__sample.csv`
- `fixtures/step3/factor_impl__sample.py`

#### Sample runner present
- `scripts/run_step3_sample.sh`
- `scripts/run_step3_sample.py`

#### Evidence
Step 3 local sample run produced:
- `data_prep_master`
- `qlib_adapter_config`
- `implementation_plan_master`
- generated code artifacts
- `handoff_to_step4`
- first-run factor-value outputs

Validator evidence:
- `validate_step3.py --report-id STEP3_SAMPLE_CPV` → `RESULT: PASS`
- `validate_step3b.py --report-id STEP3_SAMPLE_CPV` → `RESULT: PASS`

#### GitHub retention commit
- `1b3c514` — `fixtures: add runnable step3 tiny reproducibility sample`

### Step 4
#### Fixture layer present
- `fixtures/step4/factor_spec_master__sample.json`
- `fixtures/step4/data_prep_master__sample.json`
- `fixtures/step4/handoff_to_step4__sample.json`
- `fixtures/step4/minute_input__sample.csv`
- `fixtures/step4/daily_input__sample.csv`
- `fixtures/step4/factor_impl__sample.py`

#### Sample runner present
- `scripts/run_step4_sample.sh`
- `scripts/run_step4_sample.py`

#### Evidence
Step 4 local sample run produced:
- `factor_run_master`
- `factor_run_diagnostics`
- evaluation payload
- run metadata
- `handoff_to_step5`
- validation revision artifact

Validator evidence:
- `validate_step4.py --report-id STEP4_SAMPLE_CPV` → `RESULT: PASS`
- `VALIDATED_RUN_STATUS: partial`

This is an intentionally truthful partial sample, not a fake success sample.

#### GitHub retention commit
- `35c1ea2` — `fixtures: add runnable step4 tiny partial sample`

### Step 5
#### Fixture layer present
- `fixtures/step5/factor_run_master__sample.json`
- `fixtures/step5/factor_spec_master__sample.json`
- `fixtures/step5/data_prep_master__sample.json`
- `fixtures/step5/handoff_to_step5__sample.json`
- `fixtures/step5/factor_run_diagnostics__sample.json`
- `fixtures/step5/evaluation_payload__sample.json`
- `fixtures/step5/factor_values__sample.csv`
- `fixtures/step5/run_metadata__sample.json`

#### Sample runner present
- `scripts/run_step5_sample.sh`
- `scripts/run_step5_sample.py`

#### Evidence
Step 5 local sample run produced:
- `factor_evaluation`
- `factor_case_master`
- nonempty archive bundle

Validator evidence:
- `validate_step5.py --report-id STEP5_SAMPLE_CPV` → `result: PASS`
- all listed checks returned `ok: true`

This is an intentionally truthful partial-status closure sample.

#### GitHub retention commit
- `4ad7c40` — `fixtures: add runnable step5 tiny partial closure sample`

## Repository milestone commits
The current minimal reproducibility chain sits on top of these repository milestones:
- `fed0d29` — `step1-complete: dual-route + chief merge + alpha_idea_master`
- `e90a1b4` — `skills: add factor forge step1-step5 packages`
- `960b9af` — `repo: add reproducibility tree skeleton and step1-5 push cards`
- `3051023` — `docs: strengthen step1 reproducibility card and contract`
- `153bab0` — `docs: add step2-step5 contracts and sample command cards`
- `6f7a6cd` — `skills: align step2-step5 docs with current repo contracts`
- `893e70b` — `docs: add step2-step5 fixture specs`
- `e8d72d4` — Step 1 runnable tiny sample
- `408a23e` — Step 2 runnable tiny sample
- `1b3c514` — Step 3 runnable tiny sample
- `35c1ea2` — Step 4 runnable tiny partial sample
- `4ad7c40` — Step 5 runnable tiny partial closure sample

## Acceptance boundary
This acceptance means:
- Bernard/Mac has a committed tiny sample path for each of Step1–Step5
- each step now has in-repo contracts + reproducibility notes + fixture layer + sample runner
- the repository no longer depends only on chat history or hidden runtime state to explain how Step1–Step5 should be exercised at minimal scale

This acceptance does **not** mean:
- full production-scale data reproduction on Mac is solved
- all environment/runtime dependencies are one-command turnkey
- current sample runners are the final clean-room architecture

## Known limits
1. Some sample runners still install fixture files into runner-expected object/runtime paths rather than consuming a clean fixture namespace directly.
2. Step 4 sample is intentionally `partial`, not `success`, because that is the truthful status under the tiny-window design.
3. Step 5 sample is intentionally `partial` closure, not `validated/full-window` closure.
4. Environment/runtime packaging still needs further hardening for a cleaner cross-machine experience.
5. Step 4 backend path emits pandas `FutureWarning`; this does not break acceptance, but should be cleaned up later.

## Final verdict
The repository now satisfies the correct first-version acceptance statement:

> **Step1–Step5 minimal reproducibility chain accepted.**
> **Bernard/Mac now has a real in-repo tiny-fixture path for each step, with runnable sample entries and retained GitHub commits.**
