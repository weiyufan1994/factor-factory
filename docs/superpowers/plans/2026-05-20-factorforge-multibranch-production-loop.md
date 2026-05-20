# Phase P4: Production Multibranch Loop Integration

## Goal
Make `scripts/run_factorforge_ultimate_loop.py` consume a completed Council plus `main_agent_multibranch_synthesis` as a production loop path, not only as manually callable bridge scripts.

## Contract
When a parent report reaches a Council-completed pause and `main_agent_multibranch_synthesis__<report_id>.json` exists, the loop must:

1. Approve the multibranch synthesis with `approve_main_agent_multibranch_synthesis.py`.
2. Materialize all selected branches with `materialize_step6_multibranch_children.py` under loop materialization guard.
3. Run each materialized child through the official wrapper from Step3B through Step6.
4. Build and validate `branch_comparison__<parent_report_id>__loopNN.json/md` from real parent/child evaluation artifacts.
5. Continue only from `main_agent_selection.selected_next_parent_child_report_id`.
6. Let non-selected siblings continue only as `sibling_branch_memory`, never as the next parent.
7. Keep existing no-clean-data, no-search-worker, no-official-promotion, and canonical no-pollution boundaries.

## TDD Plan
1. Add a `/tmp` production-loop smoke that seeds a completed Council plus valid multibranch synthesis and expects the loop to approve, materialize, execute children, build comparison, and continue from the selected child.
2. Run the smoke before implementation to confirm it fails against the current single-branch loop.
3. Implement minimal loop integration helpers in `run_factorforge_ultimate_loop.py`.
4. Re-run the new smoke and existing P1/P2/P3/regression smokes.
5. Sync installed `factor-forge-ultimate` / `factor-forge-step6` if docs or skill-facing behavior changes.
