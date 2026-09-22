# Step4 回测协作备忘（Mac / EC2）

## 这份备忘解决什么问题

这份说明只回答一个实际问题：

> Bernard 在 Mac 上、Humphrey 在 EC2 上，怎么用同一套口径跑 Step4，避免“图是有了，但到底是不是可信结果”这种反复 debug。

这份备忘不讨论因子经济含义，只记录工程层面的稳定经验。

## 当前推荐顺序

以后跑 Step4，推荐固定按下面顺序：

1. 先跑 `self_quant_analyzer`
2. 看 `IC + 分组净值 + 分组人数`
3. 再跑 `qlib native`
4. 先用小窗口 / 小股票池做 smoke test
5. 最后再放大全样本 / 全时间窗口

原因：

- `self_quant` 更快，适合先判断因子有没有排序能力。
- `qlib native` 更接近真实组合交易，但更容易被环境、provider、instrument 编码、交易约束影响。

## 现在各条回测线分别负责什么

### self_quant_analyzer

现在 `self_quant_adapter.py` 已经不只是算 `rank_ic / pearson_ic`，还会输出：

- `quantile_returns_10groups.csv`
- `quantile_nav_10groups.csv`
- `quantile_counts_10groups.csv`
- `quantile_nav_10groups.png`
- `quantile_counts_10groups.png`

适合作为：

- 第一层诊断
- 看分组单调性
- 看组内人数是否合理

### qlib_backtest_adapter

这条线目前有两层职责：

1. grouped diagnostics
- 快速看 10 分组收益 / 净值 / 分组人数

2. native qlib bridge
- 调真正的 `TopkDropoutStrategy + SimulatorExecutor + backtest(...)`

注意：

- 如果环境里 `redis_lock` / `qlib.backtest` 不完整，adapter 会退回 grouped diagnostics only。
- 所以它的 `sample_stub / partial` 不等于因子有问题，很多时候只是运行环境没对齐。

### run_qlib_native_report.py

这是现在最稳的 native qlib 入口。

推荐用它做：

- 小样本 smoke test
- 全样本正式回测

它现在支持：

- `--start-date`
- `--end-date`
- `--universe-limit`
- `--topk`
- `--n-drop`

## Mac / EC2 最重要的环境约定

### 1. Mac 上不要默认信任裸 `python3`

这次排查里，裸 `python3` 指到了 Homebrew 的 Python，不带完整 qlib 依赖。

在 Mac 上跑 native qlib，推荐直接固定：

```bash
/Users/humphrey/miniforge3/bin/python3
```

如果 Bernard 机器上也有单独环境，同理固定到那套解释器，不要模糊依赖 shell 默认值。

### 2. native qlib 先看 provider 和 signal 的 instrument 编码是否一致

这是这次最关键的坑。

之前 grouped diagnostics 能跑，但 native qlib 一直空仓，根因不是复权，而是：

- provider 里的 instrument 是 `000001.SZ`
- signal frame 里之前是 `SH600000`

现在共享访问层已经支持 instrument 双风格：

- `legacy_qlib`
- `ts_code`

约定：

- grouped diagnostics 可以继续用 `legacy_qlib`
- native provider/backtest 必须用 `ts_code`

### 3. provider 要从 Step3A 清洗后日线快照构建

不要直接拿一份来源不明的原始 `daily.csv` 去临时拼 provider。

当前推荐是：

1. Step3A 先物化清洗后的本地日线快照
2. 用 `scripts/build_report_qlib_provider.py` 生成 report-scoped provider
3. 再用 native qlib runner 跑回测

这样可以确保：

- 复权口径一致
- `BJ / ST / 新股 / 停牌 / 涨跌停` 过滤一致
- provider 和 Step4 的研究层数据来自同一份 snapshot

## Step3 侧现在已经稳定下来的约定

### 1. Step3A / Step3B 可以安全重跑

现在 3A、3B 都改成“合并写回”，不再互相覆盖。

这意味着：

- 可以先跑 3A
- 再跑 3B
- 再回头重跑 3A

而不会把下面这些字段冲掉：

- `factor_impl_stub_ref`
- `qlib_expression_draft_ref`
- `hybrid_execution_scaffold_ref`
- `evaluation_plan`
- `first_run_outputs`

### 2. daily-only 因子已经是正式一等公民

像 `UBL` 这种日频因子：

- Step3A 可以直接产出 `daily_only` 本地输入
- Step4 不再强制要求 minute snapshot

所以以后 Bernard / Humphrey 不需要再为日频因子硬补分钟数据链。

## 如何判断一条回测“像真的”

建议看 4 个信号：

1. `group_member_count`
- 如果分组人数长期极小，先不要解读净值。

2. `nonzero_turnover_rows`
- 如果 native qlib 全是 `0`，优先怀疑 instrument / provider / tradable 约束。

3. `nonzero_value_rows`
- 如果长期是 `0`，说明根本没持仓。

4. `turnover` 而不是 `total_turnover`
- `total_turnover` 是累计曲线，一定单调上升。
- 评估交易是否过度频繁，要看单日 `turnover`。

## 这次已经证明有效的回测流程

### 小样本 smoke test

```bash
/Users/humphrey/miniforge3/bin/python3 scripts/run_qlib_native_report.py \
  --report-id DONGWU_TECH_ANALYSIS_20200619_02 \
  --output evaluations/DONGWU_TECH_ANALYSIS_20200619_02/qlib_native_small/evaluation_payload.json \
  --start-date 20100104 \
  --end-date 20100210 \
  --universe-limit 200 \
  --topk 20 \
  --n-drop 5
```

这个配置已经验证过会产生真实持仓和真实换手。

### 全样本正式跑法

```bash
/Users/humphrey/miniforge3/bin/python3 scripts/run_qlib_native_report.py \
  --report-id DONGWU_TECH_ANALYSIS_20200619_02 \
  --output evaluations/DONGWU_TECH_ANALYSIS_20200619_02/qlib_native_full/evaluation_payload.json
```

## Bernard / Humphrey 的推荐协作分工

### Bernard（Mac）

更适合负责：

- Step2 / Step3 公式和实现迭代
- `self_quant` 分组图和 IC 快速诊断
- native qlib 小样本 smoke test

### Humphrey（EC2）

更适合负责：

- 数据更新和 provider 构建
- 全样本 / 长窗口 native qlib 跑批
- 大规模结果归档

### 两边共用的约定

两边都应该优先复用：

- `factor_factory.data_access`
- `scripts/build_report_qlib_provider.py`
- `scripts/run_qlib_native_report.py`

不要再各自维护一套数据读取和 instrument 转换逻辑。

## 最值得记住的一句话

一句话总结给 Bernard 和 Humphrey：

> 先用 `self_quant` 看 IC、分组净值和分组人数；native qlib 一定先小样本 smoke test，再全样本放大；如果 native 全程空仓，先查 instrument 编码和 provider，不要先怪因子本身。
