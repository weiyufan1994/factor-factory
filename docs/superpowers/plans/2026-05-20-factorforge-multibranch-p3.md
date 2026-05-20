# Factor Forge Multibranch P3 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add the P3 branch-comparison and sibling-branch-memory contract for approved multibranch child runs.

**Architecture:** P2 can materialize multiple children, but P3 must make their results comparable before any selected child enters its next Council. Add a `/tmp`-safe branch comparison builder/validator, then make `build_revision_council_packet.py` BLOCK multibranch children that lack comparison and include sibling outcomes when comparison exists.

**Tech Stack:** Python stdlib, existing Factor Forge JSON artifact conventions, existing Step6 scripts and smoke harnesses.

---

## File Structure

- Create `skills/factor-forge-step6/scripts/build_branch_comparison.py`
  - Build `branch_comparison__<parent_report_id>__loopNN.json/md` from a P2 aggregate materialization report plus parent/child metric artifacts.
  - Enforce `/tmp`-only in smoke/selftest mode through `--factorforge-root`.
- Create `skills/factor-forge-step6/scripts/validate_branch_comparison.py`
  - Validate schema, safe flags, branch coverage, selected child, metric deltas, and no duplicate child formulas.
- Create `scripts/run_factorforge_multibranch_comparison_smoke.py`
  - Synthetic `/tmp` smoke covering missing comparison BLOCK and sibling memory propagation.
- Modify `skills/factor-forge-step6/scripts/build_revision_council_packet.py`
  - Detect child executable specs with `branch_context.branch_group_id`.
  - BLOCK with `BLOCK_FACTORFORGE_BRANCH_COMPARISON_MISSING` when a multibranch child has siblings but no validated branch comparison.
  - Add `sibling_branch_memory` to the Council packet when comparison exists.
- Modify `skills/factor-forge-step6/SKILL.md`
  - Document P3 branch comparison and sibling branch memory.
- Modify `skills/factor-forge-ultimate/SKILL.md`
  - Document that multibranch execution is still guarded until comparison exists.

---

### Task 1: Branch Comparison Builder And Validator

**Files:**
- Create: `skills/factor-forge-step6/scripts/build_branch_comparison.py`
- Create: `skills/factor-forge-step6/scripts/validate_branch_comparison.py`

- [ ] **Step 1: Write validator first**

Create a validator that loads a comparison JSON and blocks:
- unsafe top-level permissions,
- missing parent id / branch group id,
- selected child not in children,
- duplicate child report ids or formula hashes,
- missing required metrics/deltas,
- missing branch outcome.

Expected BLOCK tokens:
- `BLOCK_FACTORFORGE_BRANCH_COMPARISON_MISSING`
- `BLOCK_FACTORFORGE_BRANCH_COMPARISON_PERMISSION_UNSAFE`
- `BLOCK_FACTORFORGE_BRANCH_COMPARISON_SELECTED_CHILD_INVALID`
- `BLOCK_FACTORFORGE_BRANCH_COMPARISON_CHILD_DUPLICATE`
- `BLOCK_FACTORFORGE_BRANCH_COMPARISON_CHILD_METRICS_MISSING`

- [ ] **Step 2: Implement builder**

Builder arguments:

```bash
python3 skills/factor-forge-step6/scripts/build_branch_comparison.py \
  --parent-report-id <parent> \
  --loop-index 1 \
  --selected-next-parent-child-report-id <child> \
  --factorforge-root /tmp/<root>
```

Builder reads:
- `objects/runtime_context/multibranch_child_materialization__<parent>__loopNN.json`
- parent metrics from `objects/validation/factor_evaluation__<parent>.json`
- child metrics from `objects/validation/factor_evaluation__<child>.json`

Builder writes:
- `objects/research_iteration_master/branch_comparison__<parent>__loopNN.json`
- `objects/research_iteration_master/branch_comparison__<parent>__loopNN.md`

- [ ] **Step 3: Run py_compile**

```bash
python3 -m py_compile \
  skills/factor-forge-step6/scripts/build_branch_comparison.py \
  skills/factor-forge-step6/scripts/validate_branch_comparison.py
```

Expected: exit `0`.

- [ ] **Step 4: Commit**

```bash
git add skills/factor-forge-step6/scripts/build_branch_comparison.py \
  skills/factor-forge-step6/scripts/validate_branch_comparison.py \
  docs/superpowers/plans/2026-05-20-factorforge-multibranch-p3.md
git commit -m "feat: add multibranch branch comparison contract"
```

### Task 2: Council Packet Sibling Memory Gate

**Files:**
- Modify: `skills/factor-forge-step6/scripts/build_revision_council_packet.py`

- [ ] **Step 1: Add branch comparison lookup**

In `build_revision_council_packet.py`, when `prior_revision_memory.is_child_revision=true` and the executable revision spec has `branch_context.branch_group_id`, find the matching branch comparison under:

```text
objects/research_iteration_master/branch_comparison__<parent_report_id>__loop*.json
```

The comparison must match the same `branch_group_id`.

- [ ] **Step 2: Add missing-comparison BLOCK**

If the comparison is missing or invalid, print:

```text
BLOCK_FACTORFORGE_BRANCH_COMPARISON_MISSING
```

and exit `1`.

- [ ] **Step 3: Add `sibling_branch_memory`**

When comparison exists, include:

```json
{
  "contract_version": "factorforge_sibling_branch_memory_v1",
  "branch_group_id": "...",
  "selected_current_child_report_id": "...",
  "selected_next_parent_child_report_id": "...",
  "siblings": [
    {
      "child_report_id": "...",
      "branch_role": "exploration",
      "law_id": "...",
      "formula_hash": "...",
      "branch_outcome": "falsified|improved|inconclusive",
      "metric_delta_vs_parent": {}
    }
  ],
  "council_requirements": [
    "Compare the current selected branch against sibling branch outcomes before proposing another revision.",
    "Do not re-create a sibling formula hash or rejected sibling derivation law unless explicitly justified by new evidence."
  ]
}
```

- [ ] **Step 4: Run py_compile**

```bash
python3 -m py_compile skills/factor-forge-step6/scripts/build_revision_council_packet.py
```

Expected: exit `0`.

- [ ] **Step 5: Commit**

```bash
git add skills/factor-forge-step6/scripts/build_revision_council_packet.py
git commit -m "feat: add sibling branch memory to council packets"
```

### Task 3: P3 Smoke Coverage

**Files:**
- Create: `scripts/run_factorforge_multibranch_comparison_smoke.py`

- [ ] **Step 1: Add synthetic fixture**

Reuse P2 smoke setup helpers to create:
- one parent report,
- two approved/materialized children,
- parent and child factor evaluation artifacts,
- child factor specs with executable revision refs.

- [ ] **Step 2: Add missing comparison case**

Run:

```bash
python3 skills/factor-forge-step6/scripts/build_revision_council_packet.py --report-id <childA>
```

Expected:
- `rc=1`
- output contains `BLOCK_FACTORFORGE_BRANCH_COMPARISON_MISSING`

- [ ] **Step 3: Add sibling memory case**

Build branch comparison selecting childA, then build childA packet.

Expected:
- `rc=0`
- packet contains `prior_revision_memory`
- packet contains `sibling_branch_memory`
- sibling memory includes childB and does not include childA
- sibling memory includes metric deltas and branch outcome

- [ ] **Step 4: Add validator negative cases**

Mutate comparison to:
- selected child not in group,
- duplicate child formula hash,
- child missing metrics.

Expected:
- validator `rc=1`
- corresponding BLOCK token present.

- [ ] **Step 5: Add non-`/tmp` block and canonical pollution check**

Smoke must reject non-`/tmp` root and report `canonical_pollution.polluted=false`.

- [ ] **Step 6: Run smoke**

```bash
python3 scripts/run_factorforge_multibranch_comparison_smoke.py \
  --fresh \
  --root /tmp/factorforge_multibranch_comparison_phase_p3
```

Expected:
- `verdict=ACCEPT`
- all cases `ok=true`
- `canonical_pollution=false`

- [ ] **Step 7: Commit**

```bash
git add scripts/run_factorforge_multibranch_comparison_smoke.py
git commit -m "test: cover multibranch branch comparison memory"
```

### Task 4: Docs, Installed Sync, And Regression

**Files:**
- Modify: `skills/factor-forge-step6/SKILL.md`
- Modify: `skills/factor-forge-ultimate/SKILL.md`

- [ ] **Step 1: Update skill docs**

Document:
- P3 comparison is required before selected multibranch child enters next Council.
- Sibling branch memory must be passed into next packet.
- This remains guarded and does not write official records or clean data.

- [ ] **Step 2: Run focused verification**

```bash
python3 -m py_compile \
  skills/factor-forge-step6/scripts/build_branch_comparison.py \
  skills/factor-forge-step6/scripts/validate_branch_comparison.py \
  skills/factor-forge-step6/scripts/build_revision_council_packet.py \
  scripts/run_factorforge_multibranch_comparison_smoke.py

python3 scripts/run_factorforge_multibranch_comparison_smoke.py --fresh --root /tmp/factorforge_multibranch_comparison_phase_p3_final
python3 scripts/run_factorforge_multibranch_synthesis_smoke.py --fresh --root /tmp/factorforge_multibranch_synthesis_p3_regression
python3 scripts/run_factorforge_multibranch_materialization_smoke.py --fresh --root /tmp/factorforge_multibranch_materialization_p3_regression
python3 scripts/run_step6_intelligence_acceptance.py --fresh --root /tmp/factorforge_step6_intelligence_acceptance_p3_regression
python3 scripts/run_factorforge_ultimate_loop_smoke.py --fresh --root /tmp/factorforge_ultimate_loop_p3_regression
```

Expected:
- all smoke summaries `ACCEPT`
- acceptance token `STEP6_INTELLIGENCE_ACCEPTED`
- no canonical pollution.

- [ ] **Step 3: Sync installed skills**

```bash
rsync -a --delete --exclude '__pycache__' skills/factor-forge-step6/ /Users/humphrey/.codex/skills/factor-forge-step6/
rsync -a --delete --exclude '__pycache__' skills/factor-forge-ultimate/ /Users/humphrey/.codex/skills/factor-forge-ultimate/
diff -qr -x __pycache__ skills/factor-forge-step6 /Users/humphrey/.codex/skills/factor-forge-step6
diff -qr -x __pycache__ skills/factor-forge-ultimate /Users/humphrey/.codex/skills/factor-forge-ultimate
```

Expected: both diffs clean.

- [ ] **Step 4: Commit**

```bash
git add skills/factor-forge-step6/SKILL.md skills/factor-forge-ultimate/SKILL.md
git commit -m "docs: document multibranch P3 comparison gate"
```

## Self-Review

- Spec coverage: Branch comparison artifact, sibling memory, missing comparison BLOCK, validation of selected child and duplicate/missing metrics, smoke, docs, and installed sync are covered.
- Placeholder scan: no TBD/TODO/later placeholders remain.
- Boundary check: P3 does not make multibranch execution the production default; it only hardens the post-P2 comparison/memory contract.
