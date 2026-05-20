# Factor Forge Ultimate 问题反馈：Alpha033 Agentic Council 到可执行 Revision Loop 的桥接缺口

Date: 2026-05-19

Audience: Factor Forge Architect / Factor Forge Programmer

Related report ids:

- `ALPHA033_CANONICAL_FORMULA_20160101_QA_COUNCIL_PROD_RETEST_CLEAN_20260519_105938`
- `ALPHA033_CANONICAL_FORMULA_20160101_QA_COUNCIL_PROD_RETEST_CLEAN_20260519_105938__LOOP01__MAIN_ITER_003`

Key proof paths:

- `objects/runtime_context/ultimate_loop_report__ALPHA033_CANONICAL_FORMULA_20160101_QA_COUNCIL_PROD_RETEST_CLEAN_20260519_105938.json`
- `objects/runtime_context/ultimate_run_report__ALPHA033_CANONICAL_FORMULA_20160101_QA_COUNCIL_PROD_RETEST_CLEAN_20260519_105938.json`
- `objects/research_iteration_master/main_agent_mechanism_memo__ALPHA033_CANONICAL_FORMULA_20160101_QA_COUNCIL_PROD_RETEST_CLEAN_20260519_105938.json`
- `objects/research_iteration_master/revision_council/ALPHA033_CANONICAL_FORMULA_20160101_QA_COUNCIL_PROD_RETEST_CLEAN_20260519_105938/agentic_result_collection__ALPHA033_CANONICAL_FORMULA_20160101_QA_COUNCIL_PROD_RETEST_CLEAN_20260519_105938.json`
- `objects/research_iteration_master/revision_council/ALPHA033_CANONICAL_FORMULA_20160101_QA_COUNCIL_PROD_RETEST_CLEAN_20260519_105938/revision_council_summary__ALPHA033_CANONICAL_FORMULA_20160101_QA_COUNCIL_PROD_RETEST_CLEAN_20260519_105938.json`
- `objects/research_iteration_master/revision_council/ALPHA033_CANONICAL_FORMULA_20160101_QA_COUNCIL_PROD_RETEST_CLEAN_20260519_105938/council_derivation_appendix__ALPHA033_CANONICAL_FORMULA_20160101_QA_COUNCIL_PROD_RETEST_CLEAN_20260519_105938.json`
- `objects/handoff/handoff_to_step3b__ALPHA033_CANONICAL_FORMULA_20160101_QA_COUNCIL_PROD_RETEST_CLEAN_20260519_105938.json`
- `objects/runtime_context/child_revision_materialization__ALPHA033_CANONICAL_FORMULA_20160101_QA_COUNCIL_PROD_RETEST_CLEAN_20260519_105938__ALPHA033_CANONICAL_FORMULA_20160101_QA_COUNCIL_PROD_RETEST_CLEAN_20260519_105938__LOOP01__MAIN_ITER_003.json`
- `objects/runtime_context/ultimate_run_report__ALPHA033_CANONICAL_FORMULA_20160101_QA_COUNCIL_PROD_RETEST_CLEAN_20260519_105938__LOOP01__MAIN_ITER_003.json`
- `objects/validation/factor_evaluation__ALPHA033_CANONICAL_FORMULA_20160101_QA_COUNCIL_PROD_RETEST_CLEAN_20260519_105938__LOOP01__MAIN_ITER_003.json`

## Summary

Alpha033 production-loop test shows that the Phase O2 main-agent memo and real agentic Council path now work through the advisory-research layer, but the full 10-loop production objective still cannot be completed correctly.

The blocker is not Council reasoning. The blocker is the missing bridge from:

```text
validated Council / Step6 revision law
-> executable factor expression or Step3B code mutation
-> child report materialization
-> fresh Step3B/Step4/Step5/Step6 evaluation
```

In this run, the Council produced real agentic results, the results were collected, finalized, attached to Step6, and validated. Step6 then produced an approved `handoff_to_step3b`. The loop orchestrator materialized a child report. However, the child Step3B regenerated the same canonical formula instead of applying the Council-approved revision direction. The child therefore reran the same Alpha033 factor and reproduced the same metrics.

Continuing to 10 loops in this state would create repeated artifacts, not valid research iterations. The correct outcome is `BLOCK` until the revision-bridge contract is implemented.

## User Requirement Being Tested

The requested production behavior was:

```text
Run Alpha033 through the full Factor Forge Ultimate Loop.
Use fresh / existing production artifacts as needed.
Default-approve every human approval checkpoint.
Continue through up to 10 loops.
Each loop must represent a real revision, not a copied parent formula.
All changes must remain guarded by wrapper proof and validators.
```

The important part is "real revision." A child loop is not valid if it merely copies the parent formula/spec and reruns the same factor.

## What Worked

### 1. Main-agent memo gate worked

Step6 first paused at:

```text
awaiting_main_agent_mechanism_memo
```

The current main agent wrote:

```text
objects/research_iteration_master/main_agent_mechanism_memo__ALPHA033_CANONICAL_FORMULA_20160101_QA_COUNCIL_PROD_RETEST_CLEAN_20260519_105938.json
objects/research_iteration_master/main_agent_mechanism_memo__ALPHA033_CANONICAL_FORMULA_20160101_QA_COUNCIL_PROD_RETEST_CLEAN_20260519_105938.md
```

`validate_main_agent_mechanism_memo.py` passed.

The memo correctly treated Alpha033 as an open-close price-only factor:

```text
rank(negate(signedpower(minus(1, divide(open, close)), 1)))
= rank(open / close - 1)
```

It did not use stale price-volume language.

### 2. Agentic Council dispatch and collection worked

The wrapper reached:

```text
final_outcome = awaiting_agent_results
revision_council.status = awaiting_agent_results
effective_mode = agentic_dispatch_manifest
deterministic_scaffold_used = false
```

Five real-agent council results were produced and validated:

- `symbolic_law_discovery`
- `dimensional_scaling_critic`
- `stochastic_process_modeler`
- `microstructure_cost_analyst`
- `statistical_falsification_agent`

Collection status:

```text
status = complete
required_result_count = 5
present_result_count = 5
valid_result_count = 5
invalid_result_count = 0
missing_result_count = 0
ready_for_finalize = true
```

Council summary:

```text
selection_source = agentic_results
deterministic_fallback_used = false
valid_agent_results = 5
blocked_agent_results = 0
recommended_branch_templates = 5
```

`finalize_agentic_council_dispatch.py` passed:

```text
result = PASS
side_effects_unchanged = true
```

### 3. Council attached to Step6 correctly

After finalization, Step6 contained:

```text
revision_council_ref.status = completed
revision_council_ref.producer_modes = ["real_agent"]
revision_council_ref.valid_proposal_count = 5
final_revision_strategy.selected_council_proposal_ids =
  [
    "agent_dimensional_scaling_critic",
    "agent_microstructure_cost_analyst",
    "agent_statistical_falsification_agent",
    "agent_stochastic_process_modeler",
    "agent_symbolic_law_discovery"
  ]
approval_required_before_step3b = true
```

This part satisfies the intended "Council critiques main-agent memo and produces revision laws" contract.

### 4. Parent Step6 could produce approved handoff through wrapper

After the user explicitly said all approval checkpoints can be considered approved, the parent was rerun through:

```bash
python3 scripts/run_factorforge_ultimate.py \
  --report-id ALPHA033_CANONICAL_FORMULA_20160101_QA_COUNCIL_PROD_RETEST_CLEAN_20260519_105938 \
  --start-step 6 \
  --end-step 6 \
  --council-mode off
```

This produced:

```text
objects/handoff/handoff_to_step3b__ALPHA033_CANONICAL_FORMULA_20160101_QA_COUNCIL_PROD_RETEST_CLEAN_20260519_105938.json
```

The loop state then became continuable:

```text
outcome = iterate
can_continue = true
stop_reason = approved_step3b_handoff_available
```

## What Failed

### Failure A: Child materialization with `start-step 3b` lacks daily snapshot

The loop orchestrator was run as:

```bash
python3 scripts/run_factorforge_ultimate_loop.py \
  --report-id ALPHA033_CANONICAL_FORMULA_20160101_QA_COUNCIL_PROD_RETEST_CLEAN_20260519_105938 \
  --start-step 6 \
  --max-loops 10 \
  --council-mode off
```

It materialized child:

```text
ALPHA033_CANONICAL_FORMULA_20160101_QA_COUNCIL_PROD_RETEST_CLEAN_20260519_105938__LOOP01__MAIN_ITER_003
```

Materialization wrote child Step1/2/3 objects and handoffs, and reported:

```text
generated_code_written = false
clean_data_touched = false
official_promotion_written = false
```

But the child loop then started at `3b`. Step4 failed because self-quant could not find a report-local Step3A daily snapshot:

```text
FileNotFoundError:
missing daily input:
runs/<child>/step3a_local_inputs/daily_input__<child>.parquet
or
runs/<child>/step3a_local_inputs/daily_input__<child>.csv
```

This indicates a loop/materialization contract mismatch:

```text
If child loop starts at 3b, materialization must either copy/link the parent report-local daily snapshot to the child path, or the loop must start child reports at Step3.
```

Manual recovery was possible by rerunning the child from Step3:

```bash
python3 scripts/run_factorforge_ultimate.py \
  --report-id ALPHA033_CANONICAL_FORMULA_20160101_QA_COUNCIL_PROD_RETEST_CLEAN_20260519_105938__LOOP01__MAIN_ITER_003 \
  --start-step 3 \
  --end-step 6 \
  --council-mode off
```

That fixed the daily snapshot problem, generated child local parquet input, and got to Step6.

### Failure B: Child Step3B did not apply a real revision

After child rerun from Step3, Step3B/Step4/Step5 succeeded, but the child was still the same formula.

Parent:

```text
report_id = ALPHA033_CANONICAL_FORMULA_20160101_QA_COUNCIL_PROD_RETEST_CLEAN_20260519_105938
formula_hash = 7a14e1e5b1078f873373de5f5bc6caf8eb1647c0105c0d62ef6fab5c6d67b5ec
branch_id = main
```

Child:

```text
report_id = ALPHA033_CANONICAL_FORMULA_20160101_QA_COUNCIL_PROD_RETEST_CLEAN_20260519_105938__LOOP01__MAIN_ITER_003
formula_hash = 7a14e1e5b1078f873373de5f5bc6caf8eb1647c0105c0d62ef6fab5c6d67b5ec
branch_id = main_iter_003
```

The implementation file path changed because Step3B regenerated a child stub, but the formula identity did not change. The child metrics were identical to the parent:

```text
rank_ic_mean = 0.04848802288596722
long_side_annual_return = -0.24921621821272769
cost_adjusted_annual_return = -0.9012891663509676
turnover_mean = 0.8628752288724066
```

This proves the child was not a real Council revision. It was a relabeled rerun of the parent canonical formula.

### Failure C: Existing advisory branch system cannot become executable Step3B input

The current repo has separate advisory branch scripts:

```text
build_program_search_plan.py
approve_program_search_branch.py
prepare_approved_search_branch.py
record_search_branch_result.py
merge_program_search_branches.py
```

These are deliberately advisory and isolated. They validate branch results and can produce a merge report, but the merge script explicitly says it must not update `handoff_to_step3b` or canonical code.

This is correct as a safety rule, but it leaves no implemented bridge for the production loop:

```text
Council advisory branch
-> approved executable formula/code mutation
-> validated child Step3B spec/code
```

The old `apply_step6_iteration.py` path is also not adequate for this case. It expects an approved revision proposal and existing Step3B handoff / Step4 handoff, then applies a generic wrapper transform. That does not encode the Council's formula-specific laws such as sign challenge, open-close persistence, amplitude gate, or state split. It risks becoming a generic smoothing wrapper rather than a research-grounded formula revision.

## Why This Must BLOCK

This is a correctness issue, not merely an automation inconvenience.

If we continue to 10 loops now:

1. the loop can keep generating child report ids;
2. Step3B can keep regenerating stubs;
3. Step4/5/6 can keep producing artifacts;
4. but the underlying formula can remain unchanged.

That would create false evidence of iterative research. It would pollute the knowledge base with duplicated Alpha033 runs and make the loop cap meaningless.

The research standard requires:

```text
Each child loop must have a verifiable revision identity:
parent formula/code hash != child formula/code/revision hash,
unless the loop is explicitly an audit/rerun branch.
```

For Alpha033, the revision target was not an audit rerun. It was:

```text
Revise factor expression and Step3B code so high factor values map to positive long-side expected returns.
Repair factor-expression monotonicity.
Test sign orientation / state split / persistence or amplitude gate.
```

Therefore an unchanged formula child is invalid.

## Required Architecture Fix

### 1. Add an executable revision spec artifact

Introduce a guarded artifact between Council/Step6 and Step3B, for example:

```text
objects/research_iteration_master/executable_revision_spec__<report_id>.json
```

It should be produced only after:

```text
main-agent memo PASS
Council agent results PASS
Council summary / derivation appendix PASS
human approval or explicit default approval flag
```

Minimum fields:

```json
{
  "contract_version": "factorforge_executable_revision_spec_v1",
  "parent_report_id": "...",
  "child_report_id": "...",
  "source_council_summary_path": "...",
  "selected_revision_law_ids": ["..."],
  "revision_type": "formula_mutation | direct_code_patch | hybrid_patch | audit_rerun",
  "parent_formula": "...",
  "child_formula": "...",
  "formula_mutation_description": "...",
  "expected_metric_signature": {...},
  "falsification_tests": [...],
  "kill_criteria": [...],
  "implementation_mode": "operator | direct_code | hybrid",
  "canonical_write_permission": false,
  "execution_allowed_by_default": false,
  "human_approval": {...}
}
```

For Alpha033, a valid revision spec might choose one of:

```text
sign challenge:
  rank(close / open - 1)

persistence confirmation:
  rank(ts_mean(open / close - 1, k))

amplitude robust state:
  rank(winsorize(log(open) - log(close)))

state split:
  separate exhaustion/rebound state from adverse continuation state
```

The exact formula should be selected by the main agent / Council, but it must be explicit before child Step3B runs.

### 2. Make Step3B consume the revision spec

Step3B should not silently regenerate the parent canonical formula when a child branch is marked as a revision.

Required behavior:

```text
If report_id is a child revision and executable_revision_spec exists:
  Step3B must build the child from child_formula / direct_code_patch / hybrid_patch.

If report_id is a child revision and executable_revision_spec is missing:
  BLOCK with a clear token.
```

Suggested token:

```text
BLOCK_FACTORFORGE_CHILD_REVISION_SPEC_MISSING
```

If the child revision spec resolves to the same formula/code as the parent and the branch is not an explicit audit rerun:

```text
BLOCK_FACTORFORGE_CHILD_REVISION_NO_EFFECT
```

### 3. Add revision identity and no-op checks

Every child Step3B/Step4 proof should record:

```text
parent_formula_hash
child_formula_hash
parent_code_hash
child_code_hash
revision_spec_hash
revision_noop = true/false
revision_identity_status = changed | audit_rerun | blocked_noop
```

Validation rule:

```text
If branch_role != audit and child_formula_hash == parent_formula_hash
and child_code_hash is semantically equivalent to parent:
  BLOCK
```

This would have caught Alpha033 immediately.

### 4. Fix child Step3A snapshot materialization

The loop orchestrator currently moves from parent to child with `current_start_step = "3b"`.

That is only safe if the child has a report-local Step3A snapshot:

```text
runs/<child>/step3a_local_inputs/daily_input__<child>.parquet
```

Fix options:

1. Materializer copies or hard-links parent daily parquet/csv into the child path and rewrites `data_prep_master.local_input_paths`.
2. Or loop runner starts child reports at Step3, not Step3B.

The first option is faster; the second is simpler and safer.

Suggested validation token if neither is true:

```text
BLOCK_FACTORFORGE_CHILD_DAILY_SNAPSHOT_MISSING
```

### 5. Make "default approved" explicit and auditable

The user can say "all approval checkpoints are approved." That should become a formal approval artifact, not an implicit assistant behavior.

Suggested artifact:

```text
objects/research_iteration_master/default_approval_scope__<root_report_id>.json
```

It should record:

```json
{
  "approval_scope": "all_current_alpha033_loop_revision_checkpoints",
  "approved_by": "user",
  "approval_text": "所有需要我同意的地方你都默认同意",
  "applies_to_report_id": "...",
  "does_not_allow": [
    "clean data mutation",
    "official promotion without gate",
    "search worker outside approved branch",
    "portfolio expression repair",
    "short-leg adoption",
    "manual generated_code edits outside wrapper"
  ]
}
```

Then Step6/loop can consume this artifact instead of requiring ad hoc reruns.

## Required Acceptance Test

Use Alpha033 or a synthetic price-only factor where the first Council recommendation is a sign/persistence revision.

Expected test flow:

```bash
python3 scripts/run_factorforge_ultimate_loop.py \
  --report-id <fresh_alpha033_report_id> \
  --start-step 2 \
  --max-loops 10 \
  --council-mode auto
```

After `awaiting_main_agent_mechanism_memo`, write memo and continue.

After `awaiting_agent_results`, provide five validated real-agent results and finalize.

After user/default approval, expected behavior:

1. executable revision spec is written and validated;
2. child report materialization includes revision spec and Step3A local snapshot;
3. child Step3B produces a changed formula/code identity;
4. child Step4 metrics are not bit-identical to parent unless branch is explicit audit rerun;
5. child Step6 gets its own main-agent memo gate;
6. loop either continues to a second true revision, promotes, rejects, exhausts, or reaches max loops;
7. no clean data mutation;
8. no official promotion unless official gate passes;
9. no direct decile / short / portfolio-expression repair;
10. `ultimate_loop_report` accurately reports child revision identity and stop reason.

Minimum assertion set:

```text
parent_formula_hash != child_formula_hash
or child_revision_identity_status == audit_rerun

child_daily_snapshot_exists = true
revision_spec_validation = PASS
child_step3b_revision_noop = false
child_step4_validation = PASS
clean_data_digest_unchanged = true
official_absent_unless_promoted = true
```

## Current Outcome

Current Alpha033 production-loop status:

```text
BLOCK
```

Reason:

```text
The system can produce and validate agentic Council research,
but it cannot yet convert approved Council revision laws into executable child Step3B formula/code changes.
The first child report reran the same formula and reproduced the same metrics.
```

This should be treated as a Phase O / Phase M bridge contract bug before running more formal 10-loop factor research.

