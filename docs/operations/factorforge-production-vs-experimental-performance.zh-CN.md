# Factor Forge 生产级 Skill 与实验性能轨道边界

## 目的

本文件把当前 Factor Forge Ultimate 的可生产使用能力，与尚未完成或尚未推广的性能实验明确分开。

结论：

- `factor-forge-ultimate` 当前可用于新因子生产级闭环测试。
- 生产级默认路径不得启用 experimental Polars、experimental `ts_rank`、或 Phase N.5 operator kernel rewrite 候选。
- 性能实验可以继续，但必须走独立 opt-in、parity、runtime guard、review、benchmark 流程，不能污染生产默认路径。

## 生产级 Skill 范围

生产级 Factor Forge Ultimate 包含：

- Step1：报告/idea intake，生成两层 `economic_hypothesis` 与 report-specific `math_hypothesis_candidates`。
- Step2：生成 canonical `factor_spec_master`，并保持 Step1 经济/数学假设源字段。
- Step3A：生成数据准备合同和 report-local parquet/CSV snapshot。
- Step3B：用默认 pandas Formula-IR / direct / hybrid path 生成 factor values。
- Step4：用 T 日因子值对齐 T+1 adjusted return，执行 self quant。
- Step5：归档 case 与经验。
- Step6：机制数学、研究反思、Council-primary revision 判断。
- Ultimate loop：最多 10 次 Council revision loop，直到 promote/reject/exhausted/awaiting-agent-results/block。

生产级新因子推荐入口：

```bash
FACTORFORGE_CSV_OUTPUT_POLICY=sample_csv \
python3 scripts/run_factorforge_ultimate_loop.py \
  --report-id <NEW_REPORT_ID> \
  --start-step 1 \
  --max-loops 10 \
  --council-mode auto
```

如果 Step1/2 已经完成，可从对应步骤开始，但仍必须使用 wrapper / loop wrapper。

## 生产级默认性能设置

生产级允许：

- Parquet IO path。
- `FACTORFORGE_CSV_OUTPUT_POLICY=sample_csv`，用于避免大 full CSV 写出成本。
- Operator profile 作为 observation-only profiling，但不能改变语义。

生产级默认不得启用：

```bash
FACTORFORGE_ENABLE_EXPERIMENTAL_POLARS=1
FACTORFORGE_ENABLE_EXPERIMENTAL_TS_RANK_ENGINE=1
FACTORFORGE_TS_RANK_ENGINE=numpy_sliding_window_experimental
FACTORFORGE_ENABLE_EXPERIMENTAL_FORMULA_KERNEL=1
FACTORFORGE_FORMULA_KERNEL_ENGINE=<experimental_engine>
```

## 实验性能轨道

以下属于实验轨道，不是生产级默认能力：

- Polars experimental backend。
- `numpy_sliding_window_experimental` `ts_rank` engine。
- Phase N.5 operator kernel rewrite。
- optional numba / numpy rolling kernel candidates。
- 任何尚未通过 Alpha017 full benchmark、runtime guard、reviewer acceptance 的 optimized kernel。

实验轨道必须满足：

1. 显式 opt-in。
2. pandas reference oracle parity。
3. NaN mask、key order、row count、max abs diff、rank corr 检查。
4. runtime guard。
5. `/tmp` smoke 先通过。
6. 用户批准后才跑 Alpha017 full benchmark。
7. reviewer acceptance 后才允许进入更高一级实验状态。
8. 即使实验通过，也不得自动成为默认路径；默认切换必须另开 Phase。

## 当前实验结论

截至 Phase N.4B：

- `numpy_sliding_window_experimental` 在 synthetic benchmark 上快，但 Alpha017 全量 benchmark 明显变慢，不能推广。
- Polars experimental path 在 Alpha017 上因 `unsupported_operator:mean` fallback 到 pandas，`compute_factor` 变慢，不能推广。
- Phase N.5 仍是任务说明书，尚未实现，不能作为生产能力使用。

## 给 Bernard / Humphrey / Codex 的使用规则

所有主 agent 使用 `factor-forge-ultimate` 时：

- 默认按生产级路径跑新因子。
- 不要自行设置 experimental env。
- 如果用户明确说“性能实验 / benchmark / N.5 / Polars / ts_rank experimental”，才进入实验轨道。
- 实验轨道不能写 official promotion，不能改变 Step6/Council/promotion gate。
- 实验轨道 benchmark 必须报告 wrapper proof、performance profile、metric parity、clean data unchanged、no search worker、no official promotion。

## GitHub / Runtime 同步规则

- GitHub 保存生产级 skill、contracts、SOP、以及实验性能任务说明书。
- Mac/Codex/Bernard 的本地 skill 目录应同步生产级 skill 文档。
- EC2/Humphrey 应通过 GitHub pull 获取同一套 repo/skill 文档；如使用本地 OpenClaw skill cache，也应从 repo `skills/` 同步。
- 任何 runtime 如果只拉到了实验文档但没有生产 skill 更新，不能声称已更新 Factor Forge Ultimate。
