# Factor Forge 因子研究目录隔离与知识库落库反馈

日期：2026-06-12

对象：架构师 / coder

结论：现在最需要收口的是“每个因子的研究工作区”合同。Step3 模板隔离已经有 smoke 证明，但当前运行产物、知识库导出、临时研究脚本仍可能落在 repo 根目录或共享目录里，导致 baseline、单因子研究、批量知识沉淀混在一起。建议把它作为框架问题处理，不让研究员在每个因子里手工维护路径纪律。

## 1. 每个因子应有独立研究文件夹

用户希望的目标是合理的：每个因子一个独立文件夹，新开因子研究必须先创建研究工作区，所有代码副本、运行结果、Step3 runtime copy、Step4/5/6 artifacts、Council synthesis、知识沉淀都落在这个文件夹下。

建议建立类似以下结构，具体命名可由架构师定：

```text
factor_research/
  <factor_id>/
    <research_id>/
      manifest.json
      step1/
      step2/
      step3_runtime/
        run_step3__<report_id>.py
        run_step3b__<report_id>.py
      step4/
      step5/
      step6/
      council/
      branch_comparison/
      knowledge/
      reports/
      logs/
```

关键要求：

1. `factor_id`、`research_id`、`report_id`、`branch_id`、`law_id` 必须在 `manifest.json` 里显式登记。
2. baseline runner 只能作为模板，不允许直接承载某个因子的研究逻辑。
3. 每个版本的 direct-code law / Formula-IR law 都要写到该因子的工作区，再由 registry 或 runtime manifest 引用。
4. sibling branch、child branch、rejected branch 都留在同一个因子工作区下，避免跨因子污染。
5. 如果没有 active factor research workspace，Step3/Ultimate 应直接 BLOCK，而不是回退到 repo 根目录或共享目录。

建议 blocker token：

```text
BLOCK_FACTORFORGE_FACTOR_RESEARCH_WORKSPACE_MISSING
BLOCK_FACTORFORGE_FACTOR_RESEARCH_WORKSPACE_IDENTITY_INVALID
BLOCK_FACTORFORGE_FACTOR_RESEARCH_OUTPUT_OUTSIDE_WORKSPACE
```

## 2. Step3 副本应落入因子工作区

当前已有证据表明 Step3 模板隔离方向是对的：`run_factorforge_step3_template_isolation_smoke.py` 已经证明 `run_step3.py` / `run_step3b.py` 会复制到 report-local runtime path 后再执行。

但这还不够。report-local 只能保证不直接污染 baseline Step3 文件，不能保证同一个因子的多轮 revision、multibranch、knowledge、Step4/5/6 结果都归档在同一个因子目录。

建议把 Step3 runtime copy 从“仅 report-local”升级为“factor workspace 内的 report-local”：

```text
<factor_workspace>/step3_runtime/<report_id>/run_step3b__<report_id>.py
```

并要求 Step3B metadata 写入：

```json
{
  "factor_workspace": "...",
  "source_template_path": ".../scripts/run_step3b.py",
  "runtime_copy_path": ".../step3_runtime/<report_id>/run_step3b__<report_id>.py",
  "baseline_template_hash": "...",
  "runtime_copy_hash": "..."
}
```

这样以后判断污染问题时，不需要靠人工翻 worktree。

## 3. 因子知识库落库路径存在边界问题

本次检查到知识库路径确实有混乱风险。

### 直接证据

`scripts/run_alpha101_qlib_batch_judge.py` 直接写 repo 根目录下的人类可读知识库：

```text
KNOWLEDGE_ROOT = REPO_ROOT / "knowledge" / "因子工厂"
FACTOR_DIR = KNOWLEDGE_ROOT / "普通因子库"
KB_DIR = KNOWLEDGE_ROOT / "知识库"
ITER_DIR = KNOWLEDGE_ROOT / "研究迭代"
```

同时，当前 worktree 里已经出现大量 untracked 文件：

```text
knowledge/因子工厂/普通因子库/ALPHA001_QLIB_ONLY_20160101_20250711.md
...
knowledge/因子工厂/普通因子库/ALPHA101_QLIB_ONLY_20160101_20250711.md
knowledge/因子工厂/知识库/...
knowledge/因子工厂/研究迭代/...
```

`docs/operations/agent-calling-convention.zh-CN.md` 还把 Obsidian vault 固定为：

```text
/Users/humphrey/projects/factor-factory/knowledge/因子工厂
```

而 Step6 skill/同步脚本又同时存在 canonical object 路径和 vault 路径：

```text
objects/research_knowledge_base
objects/research_iteration_master
objects/research_journal
knowledge/因子工厂
knowledge/retrieval
```

### 问题判断

这不是单个 moneyflow 因子的错误，而是生产落库边界不清：

1. canonical knowledge 应该先落到结构化 objects，并带完整 provenance。
2. `knowledge/因子工厂` 更像人类可读 vault/export，不应作为批量研究的 primary write path。
3. 如果直接把所有 Alpha101 批量结果写进 repo 根目录 `knowledge/`，worktree 会被生成文件淹没，后续 commit/review 极易误纳入无关内容。
4. 当前路径也没有按 `factor_id/research_id/report_id` 做强隔离，无法自然表达“某个因子的某一轮研究沉淀”。

### 建议改法

1. Step6/Ultimate 生产写入只允许写：

```text
<factor_workspace>/knowledge/canonical/*.json
<factor_workspace>/knowledge/human_readable/*.md
```

2. repo 根目录 `knowledge/因子工厂` 只作为显式 export/sync 目标，不能由 production loop 默认写。
3. export 时必须生成 manifest，说明源 artifact、factor_id、research_id、report_id、hash。
4. 增加 validator：如果生产 run 将 generated knowledge 写到 repo root `knowledge/`，除非显式 `--export-knowledge-vault`，否则 BLOCK。

建议 blocker token：

```text
BLOCK_FACTORFORGE_KNOWLEDGE_WRITE_PATH_INVALID
BLOCK_FACTORFORGE_KNOWLEDGE_PROVENANCE_MISSING
BLOCK_FACTORFORGE_KNOWLEDGE_VAULT_EXPORT_NOT_EXPLICIT
```

## 4. 当前 worktree 脏文件分类

本次没有清理，也不建议 `git add .`。当前 worktree 是多类事项混在一起。

### 4.1 tracked modified

```text
M docs/operations/factorforge-entrypoint-registry.json
M scripts/append_clean_daily_layer.py
M scripts/publish_qlib_daily_provider.py
M scripts/update_clean_daily_bar_after_daily_update.py
M skills/factor-forge-step4/scripts/qlib_backtest_adapter.py
```

其中 `factorforge-entrypoint-registry.json` 来自 SSM worker execution contract 工作；其余 clean daily / qlib provider / Step4 adapter 需要分别确认归属，不能混进因子研究提交。

### 4.2 untracked SSM / worker execution contract

```text
docs/operations/ec2-ssm-worker-execution-contract-feedback-20260611.zh-CN.md
docs/operations/factorforge-v18-orchestration-step3-feedback-20260611.zh-CN.md
factor_factory/worker_execution.py
scripts/run_worker_execution_contract_smoke.py
scripts/run_worker_task_spec.py
scripts/run_worker_task_via_ssm.py
scripts/validate_worker_command_report.py
```

这批应作为独立 framework commit/review，不应混入 moneyflow/V17/V18 因子研究。

### 4.3 untracked value-occupation / VP proof

```text
docs/operations/intraday-value-occupation-state-p0-acceptance-20260612.zh-CN.md
scripts/research_vp_p0_baseline_eval.py
scripts/research_vp_p0_baseline_eval_fast.py
scripts/run_vp_p0_baseline_worker.sh
```

这批属于 value-domain / Lebesgue / VP 方向，不应和 moneyflow V18 命名或产物混淆。

### 4.4 untracked Alpha101 knowledge batch

```text
scripts/build_alpha101_registry.py
scripts/build_alpha101_research_queue.py
scripts/run_alpha101_qlib_batch_judge.py
knowledge/因子工厂/...
```

这批是知识库批量沉淀/Alpha101 qlib-only 结果。当前最大问题是大量生成 `.md` 文件直接进入 repo worktree。建议先不要纳入主提交，等知识库路径合同改好后再决定迁移、忽略或 curated commit。

### 4.5 untracked data

```text
data/
```

需要确认是否是本地 catalog/cache/runtime 数据。生产 repo 通常不应直接跟踪大数据或缓存目录。

## 5. 给架构师的优先级建议

P0：增加 factor research workspace 合同和 initializer。新因子研究没有 workspace 时直接 BLOCK。

P0：所有 Step3 runtime copy、direct-code child、branch artifacts、Step4/5/6 outputs 必须落在 factor workspace 内。

P1：知识库生产写入改为 factor workspace 内 canonical objects；repo root `knowledge/因子工厂` 只作为显式 export。

P1：增加 generated-output guard。任何 production loop 写 repo root `knowledge/`、`data/`、临时脚本或非 workspace 目录时，必须有显式开关和 manifest，否则 BLOCK。

P1：把 SSM worker execution contract 作为独立 framework commit/review，避免继续用临时 SSM 命令污染研究流程。

P2：清理 `.gitignore` / artifact summary / export manifest，让一个路人 clone repo 后能清楚分辨：

```text
source code
installed skills
runtime artifacts
factor research workspace
knowledge export
local cache/data
```

## 6. 当前研究侧建议

研究员可以继续专注因子挖掘，但在架构师修好前，应避免继续新增 repo-root 生成文件。新因子/新分支如果必须跑，至少要在报告里显式记录：

```text
factor_id
research_id
report_id
runtime root
knowledge output root
step3 runtime copy path
whether repo-root generated files were written
```

否则后续很难判断某个结果属于哪个因子、哪一轮 revision、哪个 worker/runtime。
