# Factor Forge Workspace Migration / Quarantine Audit

日期：2026-06-23

## 结论

当前不能直接声称 Factor Forge Ultimate 工作树和工作区已经完全干净。

- `/tmp/factorforge-state-reuse-contract`：干净，PR 分支已和远端一致。
- `/Users/humphrey/projects/factor-factory`：不干净，当前在 `codex/factor-knowledge-network-v1`，存在大量 modified / untracked。
- `/Users/humphrey/projects/factorforge`：不是 git worktree，不能用 git clean 判断；仍有 legacy global runtime objects/runs。
- 新规矩“每个因子单独 folder”只在部分 workspace 中满足；repo 内 `factor_research/` 仍混有 legacy 一层目录。

本文件是非破坏性审计记录，不移动、不删除、不归档任何研究产物。

## 当前 Dirty Worktree

主 repo：

```text
/Users/humphrey/projects/factor-factory
branch: codex/factor-knowledge-network-v1
status: dirty
```

dirty 类别：

- framework code：`factor_factory/...`
- orchestration scripts：`scripts/run_factorforge_ultimate.py`、`scripts/run_factorforge_ultimate_loop.py`
- Step3 / Step4 / Step6 skill scripts
- repo-root `knowledge/因子工厂/...`
- repo-root `factor_research/...`
- tests / docs / generated research dirs

清理约束：

- 不允许 `git add .`。
- 不允许在未分类前移动或删除 research artifacts。
- 不允许把 repo-root `knowledge/因子工厂` 当作默认写入目标；只能作为显式 export/vault。

## Runtime Workspace 状态

### `/Users/humphrey/projects/factorforge/factor_research`

该目录目前符合两层隔离形态：

```text
neg_cs_resid_vol20/formal_ultimate_20260618/manifest.json
raw_price_resid_stability/formal_ultimate_20260618/manifest.json
```

审计结果：

```text
manifest_count=2
two_level=2
one_level_or_legacy=0
```

### `/Users/humphrey/projects/factorforge`

该 runtime root 仍保留 legacy global runtime：

```text
objects: 1325 files
runs:    45931 files
knowledge: missing
```

这些 global `objects/` 和 `runs/` 是历史产物，不应在本轮直接迁移。需要单独读 manifest / lineage / archive 引用后再决定只读保留、索引、迁移或归档。

## Repo 内 `factor_research/` 状态

路径：

```text
/Users/humphrey/projects/factor-factory/factor_research
```

审计结果：

```text
manifest_count=21
two_level=11
one_level_or_legacy=10
bad_json=0
```

### 已符合两层隔离

```text
Alpha007/alpha007_folded_reversal_ultimate_20260622
Alpha013/alpha013_abvol_norm_ultimate_20260622
Alpha040/alpha040_lowvol_pv_state_ultimate_20260623
TURNRATE_VOL_TREND_PENALTY_14_30/turnrate_vol_trend_penalty_20260623
dongwu_20241229_cpv_intraday_version/research_20260615
dongwu_20241229_cpv_price_path_occupation_v3/research_20260616
dongwu_20241229_cpv_retvol_v2/research_20260616
huaxi_20250529_lcr_retained_chip_ratio/research_20260618
kaiyuan_20200209_smart_money_v2/research_20260622
post_decline_quiet_base_volume_contraction_v2/research_20260622
value_occupation_v18/oos_incremental_20260615
```

注意：`dongwu_20241229_cpv_price_path_occupation_v3/research_20260616` 的 manifest 中 `factor_id=None`，迁移或正式复用前需要补 identity。

### Legacy 一层目录

这些目录有 `manifest.json` 但位于 `factor_research/<workspace>/manifest.json`，不是 `factor_research/<factor_id>/<research_id>/manifest.json`：

```text
alpha015_ultimate_promising_20260622
alpha036_production_acceptance_20260602
alpha101_batch_qlib_20260611
moneyflow_v18_long_edge_20260611
moneyflow_v19_payoff_calibration_20260615
moneyflow_v20_slow_state_event_triggered_20260615
moneyflow_v21_hysteresis_feature_policy_20260617
vp_p0_baseline_20260610
vp_v18_value_occupation_20260614
vp_v19_return_volume_20260612
```

建议迁移目标：

```text
factor_research/<manifest.factor_id>/<manifest.research_id>/
```

示例：

```text
factor_research/Alpha015/alpha015_ultimate_promising_20260622/
factor_research/alpha036/alpha036_production_acceptance_20260602/
factor_research/alpha101_batch/alpha101_batch_qlib_20260611/
factor_research/moneyflow_v18_long_edge/moneyflow_v18_long_edge_20260611/
```

### 无 manifest 的 research/support 目录

这些目录没有顶层 manifest，也没有 child manifest，应先 quarantine，不应合并进正式 factor workspace：

```text
.cache
cpv_lineage_20260615
cs_resid_vol_20260616
```

建议目标：

```text
factor_research/_quarantine/<original_dir>/
```

其中 `.cache` 应优先视为 generated cache，不应进入 git staging。

## 迁移原则

1. 先 audit，后迁移；不直接删除。
2. 迁移只处理 repo 内 `factor_research/`，暂不处理 `/Users/humphrey/projects/factorforge/objects` 或 `/Users/humphrey/projects/factorforge/runs`。
3. 每个迁移必须保留原目录名和 manifest identity，可写 `migration_manifest.json` 记录：
   - source path
   - target path
   - factor_id
   - research_id
   - moved_at
   - file count
4. 如 target 已存在，必须 BLOCK，不能覆盖。
5. 如 manifest 缺 `factor_id` 或 `research_id`，必须先修 manifest 或进入 quarantine。
6. 不修改 clean data，不启动 worker，不跑 production research。
7. 迁移后只允许显式 `git add <path>`，不允许 `git add .`。

## 建议执行批次

### Batch 0：只读确认

目标：确认当前审计结果仍成立。

命令类型：

```text
git status --short --branch
find factor_research -maxdepth 3 -name manifest.json
```

### Batch 1：迁移 legacy 一层目录

候选：

```text
alpha015_ultimate_promising_20260622
alpha036_production_acceptance_20260602
alpha101_batch_qlib_20260611
moneyflow_v18_long_edge_20260611
moneyflow_v19_payoff_calibration_20260615
moneyflow_v20_slow_state_event_triggered_20260615
moneyflow_v21_hysteresis_feature_policy_20260617
vp_p0_baseline_20260610
vp_v18_value_occupation_20260614
vp_v19_return_volume_20260612
```

执行前必须生成 dry-run mapping，并人工确认 target 不存在。

### Batch 2：quarantine 无 manifest 目录

候选：

```text
.cache
cpv_lineage_20260615
cs_resid_vol_20260616
```

`.cache` 可优先加入 `.gitignore` 或移入 `_quarantine/generated_cache/`，但不能直接删除。

### Batch 3：global runtime legacy index

对象：

```text
/Users/humphrey/projects/factorforge/objects
/Users/humphrey/projects/factorforge/runs
```

本批只建索引，不迁移。需要按 `report_id` / `factor_id` / `archive` 关系生成 read-only map。

## 当前建议

下一步先实现一个 dry-run migration planner，输出 mapping JSON，不移动文件：

```text
scripts/plan_factor_research_workspace_migration.py
```

输出：

```text
docs/operations/factorforge-workspace-migration-plan-20260623.json
```

只有 mapping 被复审后，才写实际迁移脚本。

## 2026-06-23 执行记录

已执行 Batch 1 / Batch 2，均未删除文件。

Batch 1：

- 已将 10 个 legacy 一层研究目录迁移到 `factor_research/<factor_id>/<research_id>/`。
- 每个迁移后的研究目录均写入 `migration_manifest.json`。

Batch 2：

- 已将 `factor_research/.cache` 迁入 `factor_research/_quarantine/generated_cache/.cache`。
- 已将 `factor_research/cpv_lineage_20260615` 迁入 `factor_research/_quarantine/legacy_unmanifested/cpv_lineage_20260615`。
- 已将 `factor_research/cs_resid_vol_20260616` 迁入 `factor_research/_quarantine/legacy_unmanifested/cs_resid_vol_20260616`。
- 每个 quarantine 目标目录均写入 `migration_manifest.json`。

迁移后重新生成计划：

- `legacy_one_level = []`
- `quarantine = []`
- `proposed_moves = []`
- `invalid = []`
- 保留 1 个 manifest identity warning：`dongwu_20241229_cpv_price_path_occupation_v3/research_20260616` 的 `factor_id` 为空。

边界：

- 未触碰 `/Users/humphrey/projects/factorforge/objects`。
- 未触碰 `/Users/humphrey/projects/factorforge/runs`。
- 未启动 production research / worker / formal Step3B / Step4 / Step6。
- 未修改 clean data。
- 未执行 `git add .`。
