# Alpha037 长期生产合同回归反馈

日期：2026-06-03

## 结论

Alpha037 已作为真实公式回归样本验证本轮长期 production contract 收口。结果：

- Step1 canonical formula intake：PASS
- Step2 validator：PASS
- Step3A run：PASS
- Step3A validator：PASS
- runtime_context：未写入
- worker_started：false
- Step3B/Step4：未执行

本轮测试暴露并修复了一个新增长期合同缺口：Data API blocked 时，Step3A 不能只清空可执行 snapshot，还必须写出公式算子派生字段合同，声明 unit/lookback/leakage。Alpha037 公式包含 `delay/correlation/rank`，适合作为该合同的真实回归样本。

## Alpha037 来源

EC2 只读检查的最新 Alpha037 root：

```text
/var/lib/factorforge/artifacts/20260602T160400853327Z_alpha037_step1-step3a_3fa3df0a450b
```

公式：

```text
rank(correlation(delay((open-close),1),close,200))+rank((open - close))
```

原 EC2 artifact 中：

- Step1 research discipline 已有三项结构化字段
- Step2 standard formula fields contract 存在
- Step3A `data_prep_master.feasibility=blocked`
- Step3A `derived_field_contract=null`

## 本地回归

最终 P1 closure 本地测试 root：

```text
/tmp/factorforge_alpha037_research_test_20260603_p1closure
```

执行范围只到 Step3A。未启动 worker，未跑 Step3B/Step4，未处理 clean data。

关键结果：

```text
validate_step1 rc=0
validate_step2 rc=0
run_step3 rc=0
validate_step3 rc=0
```

Step3A blocked 合同结果：

```json
{
  "feasibility": "blocked",
  "blocked_items": [
    {
      "code": "DATA_API_CLEAN_DAILY_BAR_UNAVAILABLE"
    }
  ],
  "handoff_to_step4": {
    "step3a_ready": false,
    "step3b_ready": false,
    "first_run_outputs.status": "blocked"
  },
  "runtime_context_exists": false,
  "worker_started": false
}
```

派生字段合同已写入：

```json
{
  "version": "factorforge_derived_field_contract_v1",
  "materialization_status": "planned_by_formula_contract",
  "validation_result": "PASS",
  "derived_field_count": 7,
  "output_units": {
    "formula_op_1_minus": "price",
    "formula_op_2_delay": "price",
    "formula_op_3_correlation": "dimensionless_correlation",
    "formula_op_4_rank": "rank_score",
    "formula_op_5_minus": "price",
    "formula_op_6_rank": "rank_score",
    "formula_op_7_plus": "composite_rank_score"
  }
}
```

## 修复点

1. `run_step3.py` 修复导入顺序，确保隔离 worktree 优先加载当前 repo 的 `factor_factory`，避免误加载 Mac 主 workspace 旧模块。
2. `run_step3.py` 新增公式算子派生字段合同：
   - source fields
   - source/output unit
   - lookback window
   - leakage policy
   - rank scope / rolling window policy
3. `validate_step3.py` 在 `feasibility=blocked` 时也校验 `derived_field_contract`，但不要求 snapshot 文件存在。
4. `run_factorforge_derived_field_contract_smoke.py` 新增 Alpha037 风格算子合同正负例：
   - missing correlation lookback BLOCK
   - missing rank scope BLOCK
   - missing expected Alpha037 operator nodes BLOCK
   - valid operator contract PASS
5. `returns` 标准字段修正为确定性 decimal return：
   - `pct_chg` 来源一律写入 `returns = pct_chg / 100`
   - `source_units.pct_chg=percent`
   - `percent_or_decimal_from_catalog` 模糊单位会被 validator BLOCK

## 后续边界

本报告只证明 repo-side 合同和 Alpha037 Step1/2/3A prepare 路径。它不证明：

- clean data catalog 已可用
- Step3B 样本执行可通过
- Step4 formal factor parquet 可产生
- worker runtime 已同步
- official promotion 可执行

这些需要单独授权真实 worker/Step3B/Step4 proof。
