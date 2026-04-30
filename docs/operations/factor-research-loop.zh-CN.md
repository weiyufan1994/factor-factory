# 因子研究闭环

## 一句话目标

让因子工厂从“会跑脚本”升级成“会积累经验、会决定是否继续、会把经验沉淀下来”的研究闭环。

## 职责分层

### Step 3B
- 因子实现层
- 根据上游 spec / 下游反馈改公式与代码
- 输出新的实现与 first-run 产物

### Step 4
- 证据生产层
- 负责执行因子与分发评估 backend
- 输出 metric、图表、回测结果、诊断信息

### Step 5
- 收口与案例归档层
- 汇总 Step 4 结果
- 形成 factor_case_master、evaluation、archive
- 写 lessons / next_actions

### Step 6
- 研究反思与 loop 控制层
- 解释 Step 4 metric 的含义
- 结合历史因子库与知识库做判断
- 执行数学研究纪律检查：随机对象、目标统计量、信息集合法性、spec 稳定性、signal-vs-portfolio gap、overfit 风险
- 抽象可迁移经验：pattern、anti-pattern、similar-case lesson、innovative idea seed
- 决定 promote / iterate / reject
- 如需迭代，明确送回 Step 3B 修改什么

## 标准闭环

1. Step 3B 写出或修改因子实现
2. Step 4 执行并产出证据
3. Step 5 对当前结果做归档和 case 收口
4. Step 5 同时写 `handoff_to_step6`
5. Step 6 做反思、决策、知识写回
6. 若决策为 `iterate`，回到 Step 3B 再改一轮
7. 重复直到：
   - 正式入库
   - 放弃
   - 或需要人工复核

## 当前自动化落地

当前第一版自动 loop 已拆成两段：

1. `run_step6_controller.py`
   - 顺序执行 `Step5 -> validate_step5 -> Step6 -> validate_step6`
2. `run_step6_autoloop.py`
   - 顺序执行 `Step4 -> Step5 -> Step6`
   - 若决策为 `iterate`，默认先生成 `revision_proposal__{report_id}.json` 并暂停，等待人工审批
   - 审批通过后，再调用 `apply_step6_iteration.py`
   - 该脚本会生成一个新的 `factor_impl__...__iterN.py` 包装层，并把 `handoff_to_step4.factor_impl_ref` 指向新实现
   - 然后继续下一轮 Step4/5/6

注意：
- 当前自动修改策略是“保守鲁棒化包装层”，不是论文级重写。
- 它会保留原 Step3B 实现文件，并在外层增加平滑、截尾、再标准化等保守变换。
- 当前默认要求人工先确认“修订方向、思路、逻辑”，再真的落代码。

## 三类长期资产

### 全部因子库
- 保存所有尝试
- 目的是保留完整实验历史，而不是只留赢家

### 正式因子库
- 只保存表现足够好、边界足够清晰的因子
- 供后续信号合成、组合优化使用

### 统一知识库
- 记录成功和失败经验
- 记录哪些修改方向有效、哪些无效
- 记录可迁移 pattern、anti-pattern 与 innovative idea seed
- 目标是培养“有经验的量化基金经理”，而不是每轮都从零开始

## 谁负责什么

- 反思：`Step 6`
- 收口归档：`Step 5`
- 生成 metric / 图表 / backtest：`Step 4`
- 真正改因子代码：`Step 3B`
- 学习与举一反三：`Step 6 + 统一知识库 + retrieval`

## Loop 停机条件

### promote_official
- 进入正式因子库
- 当前实现不再继续 loop

### iterate
- 继续修改 Step 3B
- 必须写明修改目标

### reject
- 进入全部因子库与知识库
- 不再继续 loop

### needs_human_review
- 当前证据不足或存在重大边界问题
- 暂停 loop，等待人工判断
