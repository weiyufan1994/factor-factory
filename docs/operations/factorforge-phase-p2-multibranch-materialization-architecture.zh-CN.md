# Factor Forge Phase P2 Multi-Branch Materialization Architecture

## Goal

Phase P2 把 Phase P1 的 `main_agent_multibranch_synthesis` 从“合格研究意图”推进到“可审计的多 child materialization”。P2 不做 branch comparison，也不选择下一轮 winner；那是 P3 的职责。

## Current Baseline

当前单分支链路是：

```text
real-agent Council
  -> main_agent_council_synthesis__<parent>.json
  -> approve_main_agent_council_synthesis.py
  -> handoff_to_step3b__<parent>.json
  -> materialize_step6_child_revision.py
  -> one child report
```

Phase P1 新增了：

```text
main_agent_multibranch_synthesis__<parent>.json/md
validate_main_agent_multibranch_synthesis.py
```

但 P1 只验证 branch 合同，没有 materialize 多个 child。

## P2 Boundary

P2 只解决：

1. 读取已验证的 `main_agent_multibranch_synthesis`。
2. 为每个 selected branch 生成独立 child report id。
3. 为每个 branch 复用现有 single-child materializer 生成 child artifacts。
4. 在每个 child executable revision spec 中记录 branch lineage。
5. 写入 multibranch approval/materialization report。
6. smoke 证明多 child materialization 可执行、去重、no-clobber、无 canonical pollution。

P2 不解决：

- 不跑真实 Alpha production benchmark。
- 不默认接入 production loop 的自动并行执行。
- 不做 branch comparison。
- 不写 sibling branch memory 到下一轮 Council packet。
- 不写 official promotion。
- 不处理 clean data。
- 不执行 search worker。

## Artifacts

### Input

```text
objects/research_iteration_master/revision_council/<parent_report_id>/
  main_agent_multibranch_synthesis__<parent_report_id>.json
  main_agent_multibranch_synthesis__<parent_report_id>.md
```

### Approval Report

```text
objects/research_iteration_master/revision_council/<parent_report_id>/
  main_agent_multibranch_synthesis_approval__<parent_report_id>.json
```

Required fields:

```json
{
  "contract_version": "factorforge_main_agent_multibranch_synthesis_approval_v1",
  "parent_report_id": "...",
  "source_multibranch_synthesis_path": "...",
  "source_multibranch_synthesis_sha256": "...",
  "branch_group_id": "<parent_report_id>__LOOP<n>__MULTIBRANCH",
  "approval_source": "ultimate_loop_auto_bridge|manual_main_agent",
  "canonical_write_permission": false,
  "execution_allowed_by_default": false,
  "human_approval_required": true,
  "selected_branch_count": 2,
  "selected_branches": [
    {
      "branch_index": 0,
      "branch_role": "exploit",
      "law_id": "...",
      "child_report_id": "...",
      "child_formula_hash": "..."
    }
  ]
}
```

### Per-Branch Single Synthesis Adapter

To avoid duplicating materializer semantics, P2 should create an internal single-branch adapter artifact for each selected branch:

```text
objects/research_iteration_master/revision_council/<parent_report_id>/multibranch_materialization/
  main_agent_council_synthesis__<parent_report_id>__branch<idx>__<law_id>.json
```

This artifact uses existing contract:

```text
factorforge_main_agent_council_synthesis_v1
```

and maps `selected_branches[idx]` into `selected_revision`.

### Per-Child Executable Revision Spec

Each child keeps existing executable revision spec path:

```text
objects/research_iteration_master/executable_revision_spec__<child_report_id>.json
```

P2 adds branch metadata both as top-level convenience fields and under `branch_context`:

```json
{
  "branch_role": "exploit|exploration",
  "branch_index": 0,
  "branch_group_id": "...",
  "source_multibranch_synthesis_path": "...",
  "source_multibranch_synthesis_sha256": "...",
  "sibling_branch_count": 2,
  "branch_context": {
    "parent_report_id": "...",
    "child_report_id": "...",
    "law_id": "...",
    "branch_role": "...",
    "branch_index": 0,
    "branch_group_id": "...",
    "source_multibranch_synthesis_path": "...",
    "source_multibranch_synthesis_sha256": "..."
  }
}
```

## New Scripts

### `approve_main_agent_multibranch_synthesis.py`

Responsibility:

- Enforce `/tmp` smoke root behavior via `resolve_factorforge_context`.
- Call/consume `validate_main_agent_multibranch_synthesis.py` logic.
- Compute branch formula hashes.
- Generate deterministic child report ids.
- Write approval artifact.
- Write per-branch single synthesis adapter artifacts.
- Does not materialize children.

### `materialize_step6_multibranch_children.py`

Responsibility:

- Require `FACTORFORGE_ULTIMATE_LOOP_MATERIALIZE=1` unless `--allow-manual` is passed for smoke/manual validation.
- Load approval artifact.
- For each approved branch, call existing materializer with:
  - `--parent-report-id <parent>`
  - `--child-report-id <branch child>`
  - `--synthesis-path <per-branch adapter synthesis>`
  - branch metadata arguments.
- Aggregate child materialization reports.
- BLOCK if any child fails.
- Write multibranch materialization report.

### `materialize_step6_child_revision.py` extension

Add optional args:

```text
--synthesis-path
--branch-group-id
--branch-index
--branch-role
--source-multibranch-synthesis-path
--source-multibranch-synthesis-sha256
--sibling-branch-count
```

No existing single-child behavior changes when these args are absent.

## BLOCK Tokens

New P2 tokens:

```text
BLOCK_FACTORFORGE_MULTIBRANCH_APPROVAL_MISSING
BLOCK_FACTORFORGE_MULTIBRANCH_APPROVAL_INVALID
BLOCK_FACTORFORGE_MULTIBRANCH_MATERIALIZATION_FAILED
BLOCK_FACTORFORGE_MULTIBRANCH_CHILD_ID_COLLISION
BLOCK_FACTORFORGE_MULTIBRANCH_CHILD_FORMULA_DUPLICATE
BLOCK_FACTORFORGE_MULTIBRANCH_CHILD_NO_CLOBBER
BLOCK_FACTORFORGE_MULTIBRANCH_SOURCE_SYNTHESIS_CHANGED
```

Existing P1 tokens remain authoritative for synthesis validation.

## No-Clobber Rules

P2 must preserve existing single-child no-clobber behavior and add group-level checks:

- No child report id may equal parent report id.
- Child report ids must be unique in the group.
- Child formula hashes must be unique in the group.
- If a child target already exists and is not a matching idempotent materialization, BLOCK.
- If the source multibranch synthesis sha256 changes after approval, BLOCK before materialization.

## Production Loop Integration

P2 should not make multi-branch the default production path yet. It may add a guarded CLI flag to the ultimate loop such as:

```text
--enable-multibranch-materialization
```

Default remains single-child behavior. P3 will decide how branch comparison feeds the next loop.

## Acceptance Criteria

P2 is accepted when:

1. Synthetic `/tmp` smoke materializes 1 exploit + 1 exploration child.
2. Both child executable specs contain branch context and different formula hashes.
3. Both child data snapshots are child-local and no-clobber protected.
4. Duplicate branch child id/formula hash BLOCKs.
5. Source synthesis mutation after approval BLOCKs.
6. Non-`/tmp` smoke root BLOCKs.
7. Existing single-child loop smoke remains ACCEPT.
8. Step6 intelligence acceptance remains `STEP6_INTELLIGENCE_ACCEPTED`.
9. No canonical pollution.
