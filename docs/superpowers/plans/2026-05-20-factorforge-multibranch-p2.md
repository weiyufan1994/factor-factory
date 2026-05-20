# Factor Forge Multi-Branch P2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement guarded multi-branch child materialization for Factor Forge Step6 without changing default production loop behavior.

**Architecture:** P2 keeps the existing single-child materializer as the execution primitive. A new approval script validates `main_agent_multibranch_synthesis`, creates per-branch single-synthesis adapter artifacts, and records branch ids. A new multibranch materialization script calls the existing child materializer once per approved branch and aggregates proofs.

**Tech Stack:** Python 3, existing Factor Forge runtime context, existing Formula parser, existing Step6 materializer, `/tmp` smoke tests, JSON/Markdown proof artifacts.

---

### Task 1: Extend Single-Child Materializer With Optional Branch Context

**Files:**
- Modify: `skills/factor-forge-step6/scripts/materialize_step6_child_revision.py`

- [ ] **Step 1: Add CLI args without changing defaults**

Add these optional arguments in `parse_args()`:

```python
ap.add_argument("--synthesis-path", default=None)
ap.add_argument("--branch-group-id", default=None)
ap.add_argument("--branch-index", type=int, default=None)
ap.add_argument("--branch-role", default=None)
ap.add_argument("--source-multibranch-synthesis-path", default=None)
ap.add_argument("--source-multibranch-synthesis-sha256", default=None)
ap.add_argument("--sibling-branch-count", type=int, default=None)
```

Expected: running existing single-child materializer without these args preserves old behavior.

- [ ] **Step 2: Let `resolve_synthesis_path()` honor explicit path**

Change `resolve_synthesis_path(root, parent, parent_handoff)` to accept `explicit_synthesis_path: str | None` and prefer it when provided:

```python
if explicit_synthesis_path:
    path = Path(explicit_synthesis_path).expanduser()
    return path if path.is_absolute() else root / path
```

Expected: existing parent handoff path and default path logic remain fallback only.

- [ ] **Step 3: Add `branch_context` to executable spec**

In `build_executable_revision_spec()`, accept a `branch_context: dict[str, Any] | None`. If provided, add top-level fields:

```python
spec["branch_role"] = branch_context["branch_role"]
spec["branch_index"] = branch_context["branch_index"]
spec["branch_group_id"] = branch_context["branch_group_id"]
spec["source_multibranch_synthesis_path"] = branch_context["source_multibranch_synthesis_path"]
spec["source_multibranch_synthesis_sha256"] = branch_context["source_multibranch_synthesis_sha256"]
spec["sibling_branch_count"] = branch_context["sibling_branch_count"]
spec["branch_context"] = branch_context
```

Expected: single-child spec has no branch fields; multibranch spec has all branch fields.

- [ ] **Step 4: Compile**

Run:

```bash
python3 -m py_compile skills/factor-forge-step6/scripts/materialize_step6_child_revision.py
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add skills/factor-forge-step6/scripts/materialize_step6_child_revision.py
git commit -m "feat: add branch context to child materialization"
```

### Task 2: Add Multibranch Approval Script

**Files:**
- Create: `skills/factor-forge-step6/scripts/approve_main_agent_multibranch_synthesis.py`

- [ ] **Step 1: Implement constants and path helpers**

Use these contract constants:

```python
APPROVAL_VERSION = "factorforge_main_agent_multibranch_synthesis_approval_v1"
SINGLE_SYNTHESIS_VERSION = "factorforge_main_agent_council_synthesis_v1"
MULTIBRANCH_VERSION = "factorforge_main_agent_multibranch_synthesis_v1"
TOKEN_SOURCE_CHANGED = "BLOCK_FACTORFORGE_MULTIBRANCH_SOURCE_SYNTHESIS_CHANGED"
TOKEN_APPROVAL_INVALID = "BLOCK_FACTORFORGE_MULTIBRANCH_APPROVAL_INVALID"
TOKEN_CHILD_COLLISION = "BLOCK_FACTORFORGE_MULTIBRANCH_CHILD_ID_COLLISION"
TOKEN_DUP_HASH = "BLOCK_FACTORFORGE_MULTIBRANCH_CHILD_FORMULA_DUPLICATE"
```

- [ ] **Step 2: Validate synthesis before approval**

Call the existing validator with `importlib.util.spec_from_file_location()` because `factor-forge-step6` contains a hyphen:

```python
validator_path = REPO_ROOT / "skills" / "factor-forge-step6" / "scripts" / "validate_main_agent_multibranch_synthesis.py"
spec = importlib.util.spec_from_file_location("validate_main_agent_multibranch_synthesis", validator_path)
module = importlib.util.module_from_spec(spec)
assert spec and spec.loader
spec.loader.exec_module(module)
validation = module.validate(root, report_id, synthesis_path, markdown_path)
if validation.get("result") != "PASS":
    print(json.dumps(validation, ensure_ascii=False, indent=2, sort_keys=True))
    return 1
```

Expected: approval exits rc=1 if P1 validator returns BLOCK.

- [ ] **Step 3: Generate deterministic branch group id**

Use:

```python
branch_group_id = f"{report_id}__LOOP{loop_index:02d}__MULTIBRANCH"
```

`loop_index` defaults to `1` and is accepted as `--loop-index`.

- [ ] **Step 4: Generate child report ids**

Use existing helper:

```python
from factor_factory.ultimate_loop.state import next_child_report_id
child_report_id = next_child_report_id(report_id, loop_index, f"{branch_role}_{law_id}")
```

Expected: ids are unique and under the existing 120 character safety budget.

- [ ] **Step 5: Write per-branch single synthesis adapter**

For each selected branch, write:

```text
objects/research_iteration_master/revision_council/<parent>/multibranch_materialization/main_agent_council_synthesis__<parent>__branch<idx>__<safe_law_id>.json
```

Payload shape:

```json
{
  "contract_version": "factorforge_main_agent_council_synthesis_v1",
  "report_id": "<parent>",
  "canonical_write_permission": false,
  "execution_allowed_by_default": false,
  "human_approval_required": true,
  "selected_revision": {
    "law_id": "...",
    "child_formula": "...",
    "why_selected": "...",
    "economic_mechanism_link": "...",
    "math_model_link": "...",
    "expected_metric_signature": {...},
    "falsification_tests": [...],
    "kill_criteria": [...],
    "source_agent_roles": [...]
  },
  "source_multibranch_synthesis_path": "...",
  "source_multibranch_synthesis_sha256": "...",
  "branch_context": {...}
}
```

Expected: existing `materialize_step6_child_revision.py` can consume this through `--synthesis-path`.

- [ ] **Step 6: Write approval artifact**

Path:

```text
objects/research_iteration_master/revision_council/<parent>/main_agent_multibranch_synthesis_approval__<parent>.json
```

Include branch list with child ids, hashes, adapter synthesis paths, and source sha256.

- [ ] **Step 7: Compile**

Run:

```bash
python3 -m py_compile skills/factor-forge-step6/scripts/approve_main_agent_multibranch_synthesis.py
```

Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add skills/factor-forge-step6/scripts/approve_main_agent_multibranch_synthesis.py
git commit -m "feat: approve multibranch council synthesis"
```

### Task 3: Add Multibranch Materialization Script

**Files:**
- Create: `skills/factor-forge-step6/scripts/materialize_step6_multibranch_children.py`

- [ ] **Step 1: Implement root and safety checks**

Require:

```python
if os.environ.get("FACTORFORGE_ULTIMATE_LOOP_MATERIALIZE") != "1" and not args.allow_manual:
    print("BLOCK_FACTORFORGE_MULTIBRANCH_MATERIALIZATION_NOT_ENABLED")
    return 1
```

Also enforce source synthesis sha256 equals the approval artifact value before doing any child write.

- [ ] **Step 2: Load approval artifact**

Expected path:

```text
objects/research_iteration_master/revision_council/<parent>/main_agent_multibranch_synthesis_approval__<parent>.json
```

If missing, output `BLOCK_FACTORFORGE_MULTIBRANCH_APPROVAL_MISSING` and rc=1.

- [ ] **Step 3: Call single-child materializer for each branch**

Run subprocess command:

```python
[
  sys.executable,
  "skills/factor-forge-step6/scripts/materialize_step6_child_revision.py",
  "--parent-report-id", parent,
  "--child-report-id", child,
  "--factorforge-root", str(root),
  "--synthesis-path", adapter_synthesis_path,
  "--branch-group-id", branch_group_id,
  "--branch-index", str(branch_index),
  "--branch-role", branch_role,
  "--source-multibranch-synthesis-path", source_path,
  "--source-multibranch-synthesis-sha256", source_sha256,
  "--sibling-branch-count", str(branch_count),
]
```

Expected: any rc != 0 blocks the aggregate script and records stdout/stderr tail.

- [ ] **Step 4: Write aggregate materialization report**

Path:

```text
objects/runtime_context/multibranch_child_materialization__<parent>__loop<loop_index>.json
```

Include:

```json
{
  "contract_version": "factorforge_multibranch_child_materialization_v1",
  "parent_report_id": "...",
  "branch_group_id": "...",
  "status": "PASS",
  "children": [
    {
      "child_report_id": "...",
      "branch_role": "exploit",
      "law_id": "...",
      "materialization_rc": 0,
      "materialization_report_path": "...",
      "executable_revision_spec_path": "..."
    }
  ],
  "canonical_write_permission": false,
  "execution_allowed_by_default": false,
  "human_approval_required": true
}
```

- [ ] **Step 5: Compile**

Run:

```bash
python3 -m py_compile skills/factor-forge-step6/scripts/materialize_step6_multibranch_children.py
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add skills/factor-forge-step6/scripts/materialize_step6_multibranch_children.py
git commit -m "feat: materialize approved multibranch children"
```

### Task 4: Add P2 Smoke

**Files:**
- Create: `scripts/run_factorforge_multibranch_materialization_smoke.py`

- [ ] **Step 1: Build `/tmp` fixture root**

Create parent artifacts needed by existing materializer:

```text
objects/alpha_idea_master/alpha_idea_master__<parent>.json
objects/factor_spec_master/factor_spec_master__<parent>.json
objects/data_prep_master/data_prep_master__<parent>.json
objects/handoff/handoff_to_step3__<parent>.json
objects/handoff/handoff_to_step4__<parent>.json
objects/handoff/handoff_to_step3b__<parent>.json
runs/<parent>/step3a_local_inputs/daily_input__<parent>.parquet
runs/<parent>/step3a_local_inputs/daily_input__<parent>.csv
runs/<parent>/step3a_local_inputs/daily_input_meta__<parent>.json
```

Use a tiny deterministic pandas fixture with 2 codes x 5 dates.

- [ ] **Step 2: Write valid multibranch synthesis**

Use parent formula `rank(close)`, exploit formula `rank(delta(close, 1))`, exploration formula `rank(volume)`.

Expected: P1 validator PASS.

- [ ] **Step 3: Run approval + materialization**

Run:

```bash
python3 skills/factor-forge-step6/scripts/approve_main_agent_multibranch_synthesis.py --report-id <parent> --factorforge-root <tmp> --loop-index 1 --approval-source smoke
FACTORFORGE_ULTIMATE_LOOP_MATERIALIZE=1 python3 skills/factor-forge-step6/scripts/materialize_step6_multibranch_children.py --report-id <parent> --factorforge-root <tmp> --loop-index 1
```

Expected: both rc=0.

- [ ] **Step 4: Assert child artifacts**

For both children, assert these paths exist:

```text
objects/factor_spec_master/factor_spec_master__<child>.json
objects/data_prep_master/data_prep_master__<child>.json
objects/research_iteration_master/executable_revision_spec__<child>.json
runs/<child>/step3a_local_inputs/daily_input__<child>.parquet
runs/<child>/step3a_local_inputs/daily_input__<child>.csv
```

Assert executable specs contain branch context and unique formula hashes.

- [ ] **Step 5: Add negative cases**

Required cases:

```text
multibranch_source_mutation_blocks -> BLOCK_FACTORFORGE_MULTIBRANCH_SOURCE_SYNTHESIS_CHANGED
multibranch_duplicate_child_formula_blocks -> BLOCK_FACTORFORGE_MULTIBRANCH_CHILD_FORMULA_DUPLICATE
multibranch_missing_approval_blocks -> BLOCK_FACTORFORGE_MULTIBRANCH_APPROVAL_MISSING
multibranch_non_tmp_root_blocks -> BLOCK_NON_TMP_FACTORFORGE_ROOT
```

- [ ] **Step 6: Run smoke**

Run:

```bash
python3 scripts/run_factorforge_multibranch_materialization_smoke.py --fresh --root /tmp/factorforge_multibranch_materialization_phase_p2
```

Expected summary:

```json
{
  "verdict": "ACCEPT",
  "canonical_pollution": {"polluted": false}
}
```

- [ ] **Step 7: Commit**

```bash
git add scripts/run_factorforge_multibranch_materialization_smoke.py
git commit -m "test: cover multibranch child materialization"
```

### Task 5: Documentation and Regression

**Files:**
- Modify: `skills/factor-forge-step6/SKILL.md`
- Modify: `skills/factor-forge-ultimate/SKILL.md`

- [ ] **Step 1: Document P2 as guarded experimental execution bridge**

Add language:

```text
Phase P2 materializes approved multi-branch synthesis into independent child reports. It is not the default production loop path until P3 branch comparison and sibling memory are implemented.
```

- [ ] **Step 2: Run compile set**

Run:

```bash
python3 -m py_compile \
  skills/factor-forge-step6/scripts/validate_main_agent_multibranch_synthesis.py \
  skills/factor-forge-step6/scripts/approve_main_agent_multibranch_synthesis.py \
  skills/factor-forge-step6/scripts/materialize_step6_child_revision.py \
  skills/factor-forge-step6/scripts/materialize_step6_multibranch_children.py \
  scripts/run_factorforge_multibranch_synthesis_smoke.py \
  scripts/run_factorforge_multibranch_materialization_smoke.py \
  scripts/run_factorforge_ultimate_loop.py
```

Expected: PASS.

- [ ] **Step 3: Run P1/P2 smokes**

Run:

```bash
python3 scripts/run_factorforge_multibranch_synthesis_smoke.py --fresh --root /tmp/factorforge_multibranch_synthesis_phase_p2_regression
python3 scripts/run_factorforge_multibranch_materialization_smoke.py --fresh --root /tmp/factorforge_multibranch_materialization_phase_p2_final
```

Expected: both `verdict=ACCEPT` and canonical pollution false.

- [ ] **Step 4: Run existing regressions**

Run:

```bash
python3 scripts/run_agentic_council_dispatch_smoke.py --fresh --root /tmp/factorforge_agentic_council_dispatch_phase_p2_regression
python3 scripts/run_factorforge_ultimate_loop_smoke.py --fresh --root /tmp/factorforge_ultimate_loop_phase_p2_regression
python3 scripts/run_step6_intelligence_acceptance.py --fresh --root /tmp/factorforge_step6_intelligence_acceptance_phase_p2_regression
```

Expected:

```text
agentic dispatch: ACCEPT
ultimate loop: ACCEPT
Step6 intelligence acceptance: STEP6_INTELLIGENCE_ACCEPTED
```

- [ ] **Step 5: Commit docs and final verification notes**

```bash
git add skills/factor-forge-step6/SKILL.md skills/factor-forge-ultimate/SKILL.md docs/operations/factorforge-phase-p2-multibranch-materialization-architecture.zh-CN.md docs/superpowers/plans/2026-05-20-factorforge-multibranch-p2.md
git commit -m "docs: define multibranch materialization P2 contract"
```
