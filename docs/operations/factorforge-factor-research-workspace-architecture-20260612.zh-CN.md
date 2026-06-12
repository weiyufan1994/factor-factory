# Factor Forge 因子研究工作区隔离架构书

日期：2026-06-12

状态：待实现

对象：Factor Forge Ultimate 架构师 / coder / reviewer

依据：

- 用户目标：每个因子的研究代码、运行结果、Step3 runtime copy、知识沉淀必须分开；新因子研究先建文件夹；baseline Step3 不得混入具体因子逻辑；检查并修正知识库落库路径；明确当前 worktree 清理策略。
- 研究员反馈：`docs/operations/factorforge-factor-research-workspace-isolation-feedback-20260612.zh-CN.md`
- 现有合同：Factor Forge Ultimate、Step3 template runtime、Step6 knowledge writeback、Mac/EC2/S3 knowledge sync。

## 1. 结论

Factor Forge 需要新增 P0 级 `factor research workspace` 合同。

当前系统已经具备 Step3 模板副本机制，能避免直接修改 baseline Step3 runner；但它只按 `report_id` 写入 `runs/<report_id>/step3_runtime/`，没有把一个因子的多轮研究、分支、Step4/5/6 产物、Council 结果、知识沉淀绑定到同一个因子工作区。

同时，当前多个知识脚本默认写 repo 根目录：

```text
knowledge/因子工厂/
data/alpha101_*
```

这会把生产研究产物、人类可读 vault、批量评测输出、临时研究数据混进源码 worktree。这个问题必须由框架收口，不能靠每个研究员手工记路径。

## 2. 目标

### 2.1 必须实现

1. 每个正式因子研究必须先创建一个独立工作区。
2. 每个工作区必须显式登记 `factor_id`、`research_id`、`report_id`、`branch_id`、`implementation_mode`、`law_id`、`source hashes`。
3. Step3 runtime copy 必须写入该工作区，不能只写全局 `runs/<report_id>/step3_runtime/`。
4. Step4/5/6、Council、branch comparison、paused note、knowledge records 都必须由 runtime manifest 指向工作区内路径。
5. 生产知识写入默认只允许落入工作区内 canonical/human-readable 路径。
6. repo 根目录 `knowledge/因子工厂` 只能作为显式 export/vault/sync 目标，不能作为 production loop 的默认 primary write path。
7. 如果没有 active factor workspace，Ultimate/Step3/Step6 必须 BLOCK，而不是回退到 repo 根目录或共享目录。
8. 当前 dirty worktree 必须按事项分组清理，禁止 `git add .`。

### 2.2 不在本次范围

1. 不重新设计 clean daily layer。
2. 不启动新的 Step3B/Step4 生产研究。
3. 不迁移所有历史 artifact。
4. 不改 official promotion 研究标准。
5. 不把 Obsidian vault 删除；只改变默认生产写入路径和显式 export 语义。

## 3. 当前问题证据

### 3.1 Step3 模板隔离已存在但粒度不足

当前 Step3 runtime copy 路径由 `factor_factory/step3/template_runtime.py` 生成：

```text
factorforge_root / "runs" / report_id / "step3_runtime" / ...
```

这说明 baseline runner 可以作为模板，不需要每次直接修改模板文件。但是这个路径仍然是全局 report-local，不是 factor workspace-local。

缺口：

- 无法自然表达同一因子的 parent / child / sibling branch。
- 无法把 Step4/5/6 结果与该因子的研究代码、知识沉淀放在同一边界。
- 多个因子或批量 Alpha101 研究会共享 repo-root `runs/objects/knowledge/data` 风险面。

### 3.2 知识库落库路径存在边界问题

当前以下脚本默认写 repo-root：

```text
scripts/run_alpha101_qlib_batch_judge.py
  KNOWLEDGE_ROOT = REPO_ROOT / "knowledge" / "因子工厂"
  DEFAULT_OUTPUT_ROOT = REPO_ROOT / "data" / "alpha101_qlib_judge"

scripts/build_alpha101_research_queue.py
  DEFAULT_KNOWLEDGE_ROOT = REPO_ROOT / "knowledge" / "因子工厂"
  DEFAULT_OUTPUT = REPO_ROOT / "data" / "alpha101_registry" / ...

scripts/export_factorforge_obsidian.py
  FACTORFORGE_ROOT defaults to REPO_ROOT
  DEFAULT_OUTPUT = RUNTIME_ROOT / "knowledge" / "因子工厂"
```

同时，Ultimate skill / knowledge sync SOP 仍把 repo-root `knowledge/因子工厂` 描述为 active human-readable vault。这与“生产研究默认写入 factor workspace，repo-root vault 只显式 export”的新要求冲突。

### 3.3 当前 worktree 已被多类事项污染

当前 dirty worktree 混有：

- framework tracked modified；
- SSM worker execution contract；
- clean daily / qlib provider infra；
- VP / value-occupation 研究；
- Alpha101 batch judge 与 knowledge markdown；
- `data/` 产物。

这证明路径边界不是抽象问题，已经影响 review 和提交安全。

## 4. 目标目录模型

新增正式 factor workspace 根目录：

```text
factor_research/
  <factor_id>/
    <research_id>/
      manifest.json
      identity/
      step1/
      step2/
      step3_runtime/
        <report_id>/
          run_step3__<report_id>.py
          run_step3__<report_id>.meta.json
          run_step3b__<report_id>.py
          run_step3b__<report_id>.meta.json
      runs/
        <report_id>/
          step3a_local_inputs/
          factor_values__<report_id>.parquet
          run_metadata__<report_id>.json
      objects/
        alpha_idea_master/
        factor_spec_master/
        data_prep_master/
        implementation_plan_master/
        factor_run_master/
        factor_case_master/
        research_iteration_master/
        research_knowledge_base/
        research_journal/
        handoff/
        validation/
        factor_library_all/
        factor_library_official/
        runtime_context/
      evaluations/
        <report_id>/
      council/
        <report_id>/
      branch_comparison/
      knowledge/
        canonical/
        human_readable/
        export_manifest/
      reports/
      logs/
      tmp/
```

说明：

- `factor_research/<factor_id>/<research_id>/` 是一个研究批次的强边界。
- `objects/` 在工作区内保留现有 Factor Forge object naming，减少现有代码迁移成本。
- `knowledge/canonical/` 存结构化 JSON 或 canonical records。
- `knowledge/human_readable/` 存该工作区的人类可读 markdown。
- repo-root `knowledge/因子工厂` 不再是 production write path，只是显式 export target。
- shared clean layer 仍可在 repo/runtime 共享，不要求 per-factor 复制全量 clean data。

## 5. Workspace Manifest 合同

每个 workspace 必须有：

```text
factor_research/<factor_id>/<research_id>/manifest.json
```

Schema 版本：

```text
factorforge_factor_research_workspace_v1
```

建议字段：

```json
{
  "contract_version": "factorforge_factor_research_workspace_v1",
  "factor_id": "...",
  "research_id": "...",
  "root_report_id": "...",
  "active_report_id": "...",
  "created_at_utc": "...",
  "created_by": "factor_forge_ultimate",
  "repo_root": "/Users/humphrey/projects/factor-factory",
  "factorforge_root": "/Users/humphrey/projects/factor-factory",
  "workspace_root": "/Users/humphrey/projects/factor-factory/factor_research/<factor_id>/<research_id>",
  "implementation_mode": "operator | direct_code | hybrid | unknown",
  "status": "active | paused | closed | archived",
  "identity": {
    "source_type": "...",
    "report_ids": [],
    "branch_ids": [],
    "law_ids": [],
    "formula_hashes": [],
    "code_law_hashes": []
  },
  "paths": {
    "objects_root": ".../objects",
    "runs_root": ".../runs",
    "evaluations_root": ".../evaluations",
    "step3_runtime_root": ".../step3_runtime",
    "knowledge_canonical_root": ".../knowledge/canonical",
    "knowledge_human_root": ".../knowledge/human_readable",
    "logs_root": ".../logs"
  },
  "shared_inputs": {
    "clean_data_root": "/Users/humphrey/projects/factor-factory/data/clean",
    "provider_root": null
  },
  "write_policy": {
    "production_writes_must_stay_under_workspace": true,
    "repo_root_knowledge_write_allowed": false,
    "repo_root_data_write_allowed": false,
    "vault_export_requires_explicit_flag": true
  },
  "provenance": {
    "repo_commit": "...",
    "runtime_context_path": null,
    "source_feedback_doc": "docs/operations/factorforge-factor-research-workspace-isolation-feedback-20260612.zh-CN.md"
  }
}
```

## 6. Runtime Context 集成

`factor_factory.runtime_context.FactorForgeContext` 当前只有 `factorforge_root` 级别路径。需要新增 workspace-aware context：

```text
factorforge_root      repo/runtime 根
workspace_root        当前因子研究工作区
objects_root          workspace_root/objects
runs_root             workspace_root/runs
evaluations_root      workspace_root/evaluations
step3_runtime_root    workspace_root/step3_runtime
knowledge_root        workspace_root/knowledge
```

正式 Step3-6 manifest 必须包含：

```json
{
  "contract_version": "factorforge_runtime_context_v2",
  "report_id": "...",
  "factor_id": "...",
  "research_id": "...",
  "factor_workspace": "...",
  "factor_workspace_manifest": ".../manifest.json",
  "objects": {},
  "runs": {},
  "evaluations": {},
  "knowledge": {},
  "write_policy": {}
}
```

兼容策略：

- `factorforge_runtime_context_v1` 可保留给历史 artifact 读取。
- 正式新研究必须使用 v2。
- wrapper 如果未收到 `factor_id/research_id/factor_workspace`，必须 BLOCK。
- 只有 smoke/debug 且显式 `--allow-legacy-global-runtime` 时才允许 v1 路径。

## 7. Step3 Runtime Copy 合同

目标路径：

```text
<factor_workspace>/step3_runtime/<report_id>/run_step3__<report_id>.py
<factor_workspace>/step3_runtime/<report_id>/run_step3b__<report_id>.py
```

meta 必须包含：

```json
{
  "version": "factorforge_step3_runtime_copy_v2",
  "factor_id": "...",
  "research_id": "...",
  "report_id": "...",
  "factor_workspace": "...",
  "source_template_path": ".../skills/factor-forge-step3/scripts/run_step3b.py",
  "runtime_copy_path": ".../factor_research/.../step3_runtime/<report_id>/run_step3b__<report_id>.py",
  "baseline_template_hash": "...",
  "runtime_copy_hash": "...",
  "created_at_utc": "...",
  "policy": "formal_step3_runs_must_execute_workspace_copy"
}
```

Step3B direct-code law 仍应通过 law registry / executable spec 管理，不应把具体因子逻辑写回 baseline runner。

## 8. Knowledge 写入模型

### 8.1 Canonical write

生产研究默认写：

```text
<factor_workspace>/objects/research_knowledge_base/knowledge_record__<report_id>.json
<factor_workspace>/objects/research_iteration_master/research_iteration_master__<report_id>.json
<factor_workspace>/knowledge/canonical/*.json
<factor_workspace>/knowledge/human_readable/*.md
```

每条 knowledge record 必须含：

```json
{
  "factor_id": "...",
  "research_id": "...",
  "report_id": "...",
  "source_artifacts": [],
  "source_hashes": {},
  "workspace_manifest": ".../manifest.json",
  "producer": "...",
  "created_at_utc": "..."
}
```

### 8.2 Vault export

repo-root vault：

```text
/Users/humphrey/projects/factor-factory/knowledge/因子工厂
```

只能由显式 export 写入：

```bash
python3 scripts/export_factorforge_obsidian.py \
  --workspace-root <factor_workspace> \
  --output-root /Users/humphrey/projects/factor-factory/knowledge/因子工厂 \
  --export-knowledge-vault \
  --write-export-manifest
```

export manifest 必须写：

```text
<factor_workspace>/knowledge/export_manifest/export__<timestamp>.json
```

manifest 必须记录：

- source workspace；
- exported files；
- source sha256；
- destination sha256；
- factor_id / research_id / report_id；
- whether repo-root vault was touched；
- git status summary before/after export。

### 8.3 S3 knowledge sync

S3 bundle 仍可以包含：

```text
objects/
knowledge/因子工厂/
knowledge/retrieval/
```

但 bundle source 应来自显式 export 后的 curated vault，而不是 production loop 默认直接写 repo-root vault。

## 9. Guard / Blocker 合同

新增 blocker tokens：

```text
BLOCK_FACTORFORGE_FACTOR_RESEARCH_WORKSPACE_MISSING
BLOCK_FACTORFORGE_FACTOR_RESEARCH_WORKSPACE_IDENTITY_INVALID
BLOCK_FACTORFORGE_FACTOR_RESEARCH_WORKSPACE_MANIFEST_INVALID
BLOCK_FACTORFORGE_FACTOR_RESEARCH_OUTPUT_OUTSIDE_WORKSPACE
BLOCK_FACTORFORGE_STEP3_RUNTIME_COPY_OUTSIDE_WORKSPACE
BLOCK_FACTORFORGE_KNOWLEDGE_WRITE_PATH_INVALID
BLOCK_FACTORFORGE_KNOWLEDGE_PROVENANCE_MISSING
BLOCK_FACTORFORGE_KNOWLEDGE_VAULT_EXPORT_NOT_EXPLICIT
BLOCK_FACTORFORGE_REPO_ROOT_GENERATED_DATA_WRITE_FORBIDDEN
```

Validator 必须检查：

1. workspace manifest 存在且 schema version 正确。
2. `factor_id/research_id/report_id` 与 runtime manifest、artifact identity 匹配。
3. Step3 runtime copy path 在 workspace 下。
4. Step3/4/5/6 outputs 在 workspace 下，shared clean layer 例外。
5. knowledge generated outputs 在 workspace 下。
6. repo-root `knowledge/` 写入只允许在显式 export 模式。
7. repo-root `data/` 写入只允许在显式 cache/build 模式，并写 provenance。

## 10. Worktree 清理策略

当前 worktree 不应直接清理或批量提交。必须按事项拆分：

1. Workspace 架构/任务文档：独立文档提交。
2. SSM worker execution contract：独立 framework 提交。
3. Clean daily / qlib provider infra：独立数据基础设施提交。
4. VP / value-occupation research：独立研究归档。
5. Alpha101 batch output / knowledge：先冻结，不提交；等 workspace/knowledge guard 完成后迁移或显式 export。
6. `data/`：默认视为 local/generated/cache，不纳入源码提交，除非有明确小型 contract fixture。

禁止：

```bash
git add .
```

推荐 coder 在新 worktree 或干净分支做本架构实现。

## 11. 迁移阶段

### Phase 1：合同与 guard

- 新增 workspace initializer。
- 新增 workspace validator。
- Runtime context v2 支持 workspace。
- Ultimate wrapper 对正式 Step3-6 强制 workspace。
- Step3 runtime copy 改到 workspace。

### Phase 2：Knowledge 写入收口

- Step6/Ultimate knowledge output 写 workspace。
- Alpha101 batch scripts 禁止默认写 repo-root vault/data。
- Obsidian export 改成显式 export。
- knowledge sync SOP / Ultimate skill 文案同步更新。

### Phase 3：历史产物迁移

- 为现有 Alpha101 / moneyflow / VP 产物生成迁移 manifest。
- 只迁移 curated records。
- 大批量 markdown/data 先作为 generated output 隔离，不直接提交。

## 12. 验收标准

必须提供以下证据：

1. 新 workspace 初始化 smoke PASS。
2. Runtime context v2 manifest 包含 `factor_id/research_id/factor_workspace`。
3. Step3 runtime copy 实际写入 `<factor_workspace>/step3_runtime/<report_id>/`。
4. 无 workspace 的 formal Ultimate run BLOCK，token 为 `BLOCK_FACTORFORGE_FACTOR_RESEARCH_WORKSPACE_MISSING`。
5. 人为构造 repo-root knowledge write 时 BLOCK，token 为 `BLOCK_FACTORFORGE_KNOWLEDGE_VAULT_EXPORT_NOT_EXPLICIT` 或 `BLOCK_FACTORFORGE_KNOWLEDGE_WRITE_PATH_INVALID`。
6. 显式 export 能写 repo-root vault，并生成 export manifest。
7. `git status --short` 证明 smoke 没有新增 repo-root `knowledge/因子工厂/*.md` 或 `data/alpha101_*` 污染。
8. 所有新增/修改 Python 通过 `py_compile` 或对应 smoke。
9. `git diff --check` 通过。

## 13. 对 coder 的边界提醒

本架构是 Factor Forge 框架改造，不是某个因子研究任务。实现时不要启动新的正式 Step3B/Step4/Step6 研究，不要清理当前用户 dirty files，不要移动或删除 `knowledge/因子工厂` 现有内容。先实现 guard 和新路径，再由研究侧决定历史产物怎么迁移。
