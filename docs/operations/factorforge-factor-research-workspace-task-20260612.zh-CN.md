# Factor Forge 因子研究工作区隔离改造任务说明书

日期：2026-06-12

执行对象：Factor Factory coder thread

审查对象：Factor Forge reviewer thread

架构依据：

- `/Users/humphrey/projects/factor-factory/docs/operations/factorforge-factor-research-workspace-architecture-20260612.zh-CN.md`
- `/Users/humphrey/projects/factor-factory/docs/operations/factorforge-factor-research-workspace-isolation-feedback-20260612.zh-CN.md`

目标：实现 P0 `factor research workspace` 合同，使每个因子的代码副本、运行结果、Step3 runtime copy、Step4/5/6 artifacts、Council、knowledge 都按因子隔离；修正 repo-root `knowledge/因子工厂` 默认落库问题；给当前 dirty worktree 提供可执行清理边界。

## 0. 执行边界

请在干净分支或新 git worktree 中实现。当前主 worktree 已混有多类未提交文件，不能直接 `git add .`。

不要做：

```text
不要启动新的正式 Step3B / Step4 / Step6 生产研究
不要清理或删除现有 knowledge/因子工厂
不要清理或删除现有 data/
不要把 Alpha101 批量 markdown/data 纳入本提交
不要改 official promotion 研究标准
不要把 shared clean layer 复制到每个 factor workspace
```

允许做：

```text
新增/修改 framework code
新增 smoke/validator
新增/修改 docs/skill/SOP
使用 /tmp 或临时 factor_research smoke workspace 验证路径合同
```

## 1. 修改文件清单

### 新增

```text
/Users/humphrey/projects/factor-factory/factor_factory/research_workspace.py
/Users/humphrey/projects/factor-factory/scripts/init_factor_research_workspace.py
/Users/humphrey/projects/factor-factory/scripts/validate_factor_research_workspace.py
/Users/humphrey/projects/factor-factory/scripts/run_factor_research_workspace_smoke.py
/Users/humphrey/projects/factor-factory/scripts/run_factorforge_knowledge_write_guard_smoke.py
```

### 修改

```text
/Users/humphrey/projects/factor-factory/factor_factory/runtime_context.py
/Users/humphrey/projects/factor-factory/factor_factory/step3/template_runtime.py
/Users/humphrey/projects/factor-factory/scripts/build_factorforge_runtime_context.py
/Users/humphrey/projects/factor-factory/scripts/run_factorforge_ultimate.py
/Users/humphrey/projects/factor-factory/scripts/export_factorforge_obsidian.py
/Users/humphrey/projects/factor-factory/scripts/build_factorforge_embedding_index.py
/Users/humphrey/projects/factor-factory/scripts/sync_factorforge_knowledge_bundle.py
/Users/humphrey/projects/factor-factory/scripts/run_alpha101_qlib_batch_judge.py
/Users/humphrey/projects/factor-factory/scripts/build_alpha101_research_queue.py
/Users/humphrey/projects/factor-factory/skills/factor-forge-step3/SKILL.md
/Users/humphrey/projects/factor-factory/skills/factor-forge-step6/SKILL.md
/Users/humphrey/projects/factor-factory/skills/factor-forge-ultimate/SKILL.md
/Users/humphrey/projects/factor-factory/docs/operations/factorforge-knowledge-sync-sop.zh-CN.md
/Users/humphrey/projects/factor-factory/docs/operations/agent-calling-convention.zh-CN.md
```

如发现 Step4/5/6 脚本直接拼接 `factorforge_root / objects|runs|evaluations|knowledge`，也需要改为 runtime manifest path，不要继续本地猜路径。

## 2. Task A：新增 research workspace 模块

文件：

```text
factor_factory/research_workspace.py
```

实现：

```python
def safe_identity(value: str) -> str:
    ...

def default_workspace_root(
    *,
    factorforge_root: Path,
    factor_id: str,
    research_id: str,
) -> Path:
    ...

def build_workspace_manifest(
    *,
    repo_root: Path,
    factorforge_root: Path,
    factor_id: str,
    research_id: str,
    root_report_id: str,
    active_report_id: str | None = None,
    implementation_mode: str = "unknown",
    shared_clean_data_root: Path | None = None,
) -> dict[str, Any]:
    ...

def write_workspace_manifest(path: Path, manifest: dict[str, Any]) -> Path:
    ...

def load_workspace_manifest(path: Path) -> dict[str, Any]:
    ...

def validate_workspace_manifest(manifest: dict[str, Any]) -> list[str]:
    ...

def assert_path_under_workspace(path: Path, workspace_root: Path, *, label: str) -> None:
    ...
```

Manifest contract version：

```text
factorforge_factor_research_workspace_v1
```

必须创建目录：

```text
identity/
step1/
step2/
step3_runtime/
runs/
objects/
evaluations/
council/
branch_comparison/
knowledge/canonical/
knowledge/human_readable/
knowledge/export_manifest/
reports/
logs/
tmp/
```

验收：

```bash
python3 -m py_compile factor_factory/research_workspace.py
python3 scripts/init_factor_research_workspace.py --factor-id TEST_ALPHA001 --research-id smoke_20260612 --report-id TEST_ALPHA001_20160101 --factorforge-root /tmp/factorforge-workspace-smoke
python3 scripts/validate_factor_research_workspace.py --workspace-root /tmp/factorforge-workspace-smoke/factor_research/TEST_ALPHA001/smoke_20260612
```

## 3. Task B：初始化 CLI

文件：

```text
scripts/init_factor_research_workspace.py
```

CLI：

```bash
python3 scripts/init_factor_research_workspace.py \
  --factor-id <factor_id> \
  --research-id <research_id> \
  --report-id <root_report_id> \
  --factorforge-root <runtime_root> \
  --implementation-mode operator|direct_code|hybrid|unknown
```

行为：

1. 创建 workspace。
2. 写 `manifest.json`。
3. 打印 manifest path。
4. 如果 workspace 已存在，默认不覆盖；需要 `--reuse-existing` 才允许复用。
5. 如果 identity 不匹配，BLOCK。

Block tokens：

```text
BLOCK_FACTORFORGE_FACTOR_RESEARCH_WORKSPACE_IDENTITY_INVALID
BLOCK_FACTORFORGE_FACTOR_RESEARCH_WORKSPACE_MANIFEST_INVALID
```

## 4. Task C：Runtime context v2

文件：

```text
factor_factory/runtime_context.py
scripts/build_factorforge_runtime_context.py
```

新增支持：

```bash
python3 scripts/build_factorforge_runtime_context.py \
  --report-id <report_id> \
  --factor-id <factor_id> \
  --research-id <research_id> \
  --factor-workspace <workspace_root> \
  --write
```

Runtime manifest v2 必须包含：

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

路径规则：

```text
objects_root       = <factor_workspace>/objects
runs_root          = <factor_workspace>/runs
evaluations_root   = <factor_workspace>/evaluations
step3_runtime_root = <factor_workspace>/step3_runtime
knowledge_root     = <factor_workspace>/knowledge
clean_data_root    = shared input, may remain outside workspace
```

兼容要求：

- `load_runtime_manifest()` 必须能读 v1 和 v2。
- 正式 wrapper 默认要求 v2。
- 只有显式 `--allow-legacy-global-runtime` 才允许新 run 使用 v1。

Block tokens：

```text
BLOCK_FACTORFORGE_FACTOR_RESEARCH_WORKSPACE_MISSING
BLOCK_FACTORFORGE_FACTOR_RESEARCH_WORKSPACE_MANIFEST_INVALID
```

## 5. Task D：Ultimate wrapper 强制 workspace

文件：

```text
scripts/run_factorforge_ultimate.py
```

新增 CLI：

```text
--factor-id
--research-id
--factor-workspace
--init-factor-workspace
--allow-legacy-global-runtime
```

正式 Step3-6 行为：

1. 如果 `--factor-workspace` 存在，读取并校验 manifest。
2. 如果不存在但 `--init-factor-workspace` 且有 `--factor-id/--research-id`，自动创建 workspace。
3. 如果 start/end 涉及 Step3/3B/4/5/6 且无 workspace，BLOCK。
4. 写 runtime context v2。
5. 所有 step command 通过 manifest path 传递 workspace-aware paths。
6. wrapper side-effect snapshot 增加 repo-root generated output guard：

```text
knowledge/因子工厂
data/alpha101_*
runs/<report_id>
objects/<formal output>
evaluations/<report_id>
generated_code/<report_id>
```

其中正式 run 不应新增 repo-root generated outputs；shared clean layer 明确例外。

## 6. Task E：Step3 runtime copy 改到 workspace

文件：

```text
factor_factory/step3/template_runtime.py
```

改造：

1. `runtime_copy_path()` 支持 `workspace_root` 或 manifest `step3_runtime_root`。
2. v2 manifest 下路径必须是：

```text
<factor_workspace>/step3_runtime/<report_id>/run_step3__<report_id>.py
<factor_workspace>/step3_runtime/<report_id>/run_step3b__<report_id>.py
```

3. meta 从 v1 升级到 v2：

```json
{
  "version": "factorforge_step3_runtime_copy_v2",
  "factor_id": "...",
  "research_id": "...",
  "report_id": "...",
  "factor_workspace": "...",
  "source_template_path": "...",
  "runtime_copy_path": "...",
  "baseline_template_hash": "...",
  "runtime_copy_hash": "...",
  "created_at_utc": "...",
  "policy": "formal_step3_runs_must_execute_workspace_copy"
}
```

4. 如果 v2 manifest 存在但 copy path 不在 workspace 下，BLOCK：

```text
BLOCK_FACTORFORGE_STEP3_RUNTIME_COPY_OUTSIDE_WORKSPACE
```

## 7. Task F：Knowledge write guard

文件：

```text
scripts/export_factorforge_obsidian.py
scripts/build_factorforge_embedding_index.py
scripts/sync_factorforge_knowledge_bundle.py
scripts/run_alpha101_qlib_batch_judge.py
scripts/build_alpha101_research_queue.py
```

### F1. `export_factorforge_obsidian.py`

新增参数：

```text
--workspace-root
--export-knowledge-vault
--write-export-manifest
```

默认行为：

- 若输出路径是 repo-root `knowledge/因子工厂`，但未传 `--export-knowledge-vault`，BLOCK。
- 若传 `--workspace-root`，优先从 workspace `objects/` 读取，默认输出到 workspace `knowledge/human_readable/`。
- 显式 export 到 repo-root vault 时必须写 export manifest。

Block tokens：

```text
BLOCK_FACTORFORGE_KNOWLEDGE_VAULT_EXPORT_NOT_EXPLICIT
BLOCK_FACTORFORGE_KNOWLEDGE_PROVENANCE_MISSING
```

### F2. `build_factorforge_embedding_index.py`

默认 index 输出应改为 workspace：

```text
<factor_workspace>/knowledge/retrieval/
```

只有显式 `--runtime-root` 或 `--knowledge-root` 指向 curated vault 时，才允许 repo-root index。

### F3. `sync_factorforge_knowledge_bundle.py`

保留 bundle/apply 能力，但更新语义：

- bundle source 是 runtime/workspace/export 后的 curated layout。
- `knowledge_vault` 是 display/read/export material，不是 production primary write。
- manifest 里记录 source workspace 或 export manifest。

### F4. Alpha101 scripts

`run_alpha101_qlib_batch_judge.py`：

- 不再默认写 `REPO_ROOT/data/alpha101_qlib_judge` 和 `REPO_ROOT/knowledge/因子工厂`。
- 必须要求 `--workspace-root` 或显式 `--output-root`。
- 如果要写 repo-root knowledge，必须传 `--export-knowledge-vault`，并写 manifest。

`build_alpha101_research_queue.py`：

- `--knowledge-root` 必填，或从 `--workspace-root` 推导。
- 默认输出到 workspace `knowledge/canonical` 或 workspace `data/alpha101_registry`。
- 不再默认写 repo-root `data/alpha101_registry`。

## 8. Task G：Validator 和 smoke

### G1. `validate_factor_research_workspace.py`

CLI：

```bash
python3 scripts/validate_factor_research_workspace.py --workspace-root <workspace_root>
python3 scripts/validate_factor_research_workspace.py --runtime-manifest <manifest_path>
```

检查：

- manifest exists；
- schema version；
- identity fields；
- required dirs；
- all formal output paths under workspace；
- Step3 runtime copy meta under workspace；
- knowledge provenance；
- repo-root export manifest if vault export happened。

### G2. `run_factor_research_workspace_smoke.py`

必须覆盖：

1. 初始化 `/tmp/factorforge-workspace-smoke`。
2. build runtime context v2。
3. 验证 Step3 runtime copy path 函数返回 workspace 内路径。
4. 构造一个 outside path，validator BLOCK。
5. 构造 repo-root knowledge export 未授权，guard BLOCK。
6. 显式 export 模式允许写到临时 vault 并生成 manifest。

输出最后必须有：

```text
FACTOR_RESEARCH_WORKSPACE_SMOKE PASS
```

### G3. `run_factorforge_knowledge_write_guard_smoke.py`

必须覆盖：

- `export_factorforge_obsidian.py` 未带 `--export-knowledge-vault` 写 repo-root vault时 BLOCK。
- 带显式 export flag 时 PASS 并写 export manifest。
- Alpha101 batch script 没有 workspace/output-root 时 BLOCK。

输出最后必须有：

```text
FACTORFORGE_KNOWLEDGE_WRITE_GUARD_SMOKE PASS
```

## 9. Task H：文档和 skill 同步

必须更新：

```text
skills/factor-forge-step3/SKILL.md
skills/factor-forge-step6/SKILL.md
skills/factor-forge-ultimate/SKILL.md
docs/operations/factorforge-knowledge-sync-sop.zh-CN.md
docs/operations/agent-calling-convention.zh-CN.md
```

关键文案：

1. 正式新因子研究必须先有 factor workspace。
2. Step3 baseline runner 只能作为模板。
3. Step3 runtime copy 进入 workspace。
4. Step6 production knowledge 写 workspace canonical/human-readable。
5. repo-root `knowledge/因子工厂` 是显式 export/vault，不是 production primary write path。
6. S3 bundle 可包含 vault，但 bundle 应来自 curated export。
7. no workspace / unsafe write 必须 BLOCK。

## 10. 验收命令

在实现分支执行：

```bash
python3 -m py_compile \
  factor_factory/research_workspace.py \
  factor_factory/runtime_context.py \
  factor_factory/step3/template_runtime.py \
  scripts/init_factor_research_workspace.py \
  scripts/validate_factor_research_workspace.py \
  scripts/run_factor_research_workspace_smoke.py \
  scripts/run_factorforge_knowledge_write_guard_smoke.py \
  scripts/run_factorforge_ultimate.py \
  scripts/export_factorforge_obsidian.py \
  scripts/build_factorforge_embedding_index.py \
  scripts/sync_factorforge_knowledge_bundle.py \
  scripts/run_alpha101_qlib_batch_judge.py \
  scripts/build_alpha101_research_queue.py
```

```bash
python3 scripts/run_factor_research_workspace_smoke.py
```

```bash
python3 scripts/run_factorforge_knowledge_write_guard_smoke.py
```

```bash
git diff --check
```

```bash
git status --short
```

验收时请在回复中贴出：

- smoke PASS token；
- runtime manifest v2 path；
- workspace manifest path；
- Step3 runtime copy target path；
- knowledge export manifest path；
- `git status --short` 中是否出现 repo-root `knowledge/因子工厂` 或 `data/alpha101_*` 新污染。

## 11. Reviewer 检查清单

Reviewer 应重点看：

1. 是否仍有 production path 默认写 repo-root `knowledge/因子工厂`。
2. 是否仍有 Alpha101 脚本默认写 repo-root `data/`。
3. Ultimate wrapper 是否在 formal Step3-6 无 workspace 时 BLOCK。
4. Step3 runtime copy 是否真正落入 workspace。
5. v1 legacy path 是否只能显式启用，不能成为新研究默认。
6. export manifest 是否包含 factor_id / research_id / report_id / source hash / destination hash。
7. smoke 是否只用 `/tmp` 或临时 workspace，没有污染当前 repo-root generated outputs。
8. 文档和 skill 是否同步，不再把 repo-root vault 表述为 production primary write path。

## 12. 交付物

最终 PR / reviewer packet 至少包含：

```text
1. 改造摘要
2. 新增 block tokens
3. 新增/修改文件列表
4. smoke 输出
5. git diff --check 结果
6. git status --short 摘要
7. 未做事项：未启动生产 Step3B/Step4/Step6、未清理历史 knowledge/data、未迁移历史 Alpha101 产物
```
