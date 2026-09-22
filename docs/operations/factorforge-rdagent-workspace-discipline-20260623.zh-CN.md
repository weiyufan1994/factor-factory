# Factor Forge / RD-Agent 研究工作区纪律

日期：2026-06-23

## 背景

当前有多个 Factor Forge Ultimate 研究员 thread 同时研究因子，也有 Qlib
研究员通过 RD-Agent fin_factor_lite 研究因子。两类流程都会产生大量运行
产物。如果不先区分代码、知识导出、研究 workspace、clean data 和运行
cache，主 repo 会持续变脏，并且不同因子的代码、结果、Step3 runtime copy
会互相污染。

## 当前脏文件来源

1. 框架 / skill / tests 混线改动：
   - Data API / daily_basic cache
   - formula parser / operator / reference evaluator
   - Step3 / Step4 state and data contract
   - Ultimate data_request 自动生成
   - Step6 researcher / window evidence / knowledge context
2. repo-root `knowledge/因子工厂` 被导出脚本直接写入。
3. `factor_research` 里有多个正式研究 workspace 和运行产物，包括
   `results/`、`step3_runtime/`、cache、PDF、CSV、Parquet/HDF 等。
4. 部分历史一层目录已迁移为 `factor_research/<factor_id>/<research_id>/`，
   无 manifest 历史目录已进入 `_quarantine/`。

## 文件处理规则

### 代码 repo

- 每次开工先看 `git status --short --branch`。
- 不干净时先分类，不直接跑新研究。
- 永远不要 `git add .`。
- 框架、skill、tests 必须按功能线拆 commit / PR。
- 不要把 framework PR、knowledge export、生产研究产物混成一个提交。

### Factor Forge research workspace

- 新因子必须先创建或选择一个 workspace：
  `factor_research/<factor_id>/<research_id>/`。
- Step3 runtime copy、Step3B code、objects、results、knowledge、retrieval
  默认都写入该 workspace。
- baseline Step3 只能作为模板，不能写入具体因子逻辑。
- `factor_research/**` 是 runtime/artifact space，默认被 git 忽略。
- 只有经过复审的小型 provenance 文件才允许显式入库，例如：
  `manifest.json`、final report、canonical knowledge、migration manifest。
- 因为 `factor_research/**` 默认忽略，正式入库时必须使用显式路径和
  `git add -f <path>`。

### Knowledge

- repo-root `knowledge/因子工厂` 只能作为显式 export/vault target。
- 默认 knowledge 写入 factor workspace。
- repo-root export 必须显式批准，并写 export manifest / provenance。
- 未经批准的 repo-root knowledge diff 不应随 framework commit 提交。

### RD-Agent fin_factor_lite

- RD-Agent runtime 在 `/Users/humphrey/projects/rdagent_repo`。
- RD-Agent 运行产物写入：
  - `/Users/humphrey/projects/rdagent_repo/log/`
  - `/Users/humphrey/projects/rdagent_repo/git_ignore_folder/`
- RD-Agent 结果不得默认复制到 Factor Forge workspace、repo-root
  `knowledge/因子工厂` 或 clean data。
- Cross-system writeback 必须显式批准，标注 `source=rdagent`，并保留
  RD-Agent run id、log dir、provider audit、controlled Qlib judge provenance。

## 清理顺序

1. 先提交或记录 workspace 迁移治理。
2. 加 ignore 规则，阻断后续研究产物污染 git status。
3. 对剩余 tracked modified 文件按功能线拆分：
   - Data API / daily_basic cache
   - formula engine
   - Step3 / Step4 data contract
   - Ultimate data_request
   - Step6 researcher / knowledge context
4. repo-root knowledge diff 单独处理：
   - 正式 export：补 manifest 后提交；
   - 非正式误写：不要提交，后续按 guard 重新导出或清理。
5. 未跟踪研究 workspace 不整包提交，只在明确需要时 force-add 小型证明文件。

## 新 thread 必须遵守

任何新 Codex thread 使用 Factor Forge Ultimate 或 RD-Agent fin_factor_lite 前：

1. 先确认当前 repo / runtime 边界。
2. 先分类 dirty worktree。
3. 先创建或选择独立 workspace。
4. 运行产物只进 workspace 或 runtime log。
5. 代码、knowledge、研究结果分开提交。
6. 不清理、不 stage、不提交其他 thread 的文件。
7. 不使用 `git add .`。

## 本轮已落地

- `.gitignore` 已将 `factor_research/**` 设为默认忽略。
- `factor-forge-ultimate` skill 已加入 workspace / git hygiene discipline。
- `rdagent-fin-factor-lite` skill 已加入 workspace / git hygiene discipline。
- 已安装 skill 也已同步，供新 Codex thread 加载。
