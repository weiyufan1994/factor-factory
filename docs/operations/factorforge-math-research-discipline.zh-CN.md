# Factor Forge 数学研究纪律

## 定位

本文是 `factorforge-step1-step6-math-map-2026-04-23.md` 的执行版。

它不是数学课程表，也不是让 agent 在报告里堆高等数学术语。它的用途是给 Step1-Step6 加一层研究纪律：

- 每个因子必须先被定义成可验证的随机对象；
- 每个实现必须说明信息时点、变换边界和数据代理；
- 每次评价必须区分信号质量、组合可交易性和收益来源；
- 每次迭代必须证明自己是在提高泛化能力，而不是美化指标。

## 全局原则

### 1. 先定义随机对象，再谈公式

Step1/2 必须回答：

- 这个因子作用于什么随机对象？
- 它预测均值、排序、尾部、波动、状态切换，还是 hitting probability？
- 它使用的信息在交易时点是否真实可得？
- 它的收益来源是假设为 `risk_premium`、`information_advantage`、`constraint_driven_arbitrage`，还是 `mixed`？

### 2. 先判断收益来源，再解释 metric

Step4/5/6 不得从 IC、Sharpe、回测净值直接跳到结论。

正确顺序：

1. 收益来源假说；
2. 对手盘或客观约束；
3. Step4 metric 是否支持该收益来源；
4. 组合实现是否能把信号变成可交易收益；
5. 再决定 promote / iterate / reject。

### 3. revision 必须有泛化理由

任何 Step6 -> Step3B 的修改都必须写清：

- 本次修改强化哪一种收益来源；
- 使用什么数学操作：fold、rank、neutralize、winsorize、smooth、regime weight、combo、cost-aware rebalance 等；
- 为什么它应当提高泛化能力；
- 它的 overfit 风险是什么；
- 什么结果会 kill 掉这次假说。

## Step 纪律

### Step1：Thesis 数学化

必须形成：

- `random_object`：收益、成交量、价差、财务状态、订单流、市场状态等；
- `target_statistic`：条件期望、条件排序、方差、偏度、峰度、状态概率、尾部风险等；
- `information_set`：t 时点可得信息与不可得信息；
- `return_source_hint`：初步收益来源判断；
- `what_must_be_true` 与 `what_would_break_it`。

### Step2：Canonical Spec 守门

必须检查：

- 公式是否保留作者原始 thesis；
- 滞后、窗口、排序、标准化、中性化是否有无二义性；
- 是否存在前视泄漏；
- rank / bucket / truncation / winsorize 是否改变了原始经济含义；
- 是否需要人工复核关键歧义。

### Step3：实现与数据纪律

必须检查：

- 使用共享 clean layer，不把全量清洗误当作每个因子的工作；
- 数据代理与原论文观测对象的差异；
- 字段映射、缺失值、停牌、复权、流通市值等关键定义；
- 代码是否保持 Step2 invariants；
- 变换是否数值稳定，对极端值和边界条件是否明确。

### Step4：证据生产纪律

必须区分：

- signal evidence：IC、rank IC、decile monotonicity、spread；
- portfolio evidence：净值、turnover、成本、回撤、benchmark relation；
- robustness evidence：窗口、年份、regime、universe、成本敏感性；
- evidence gap：IC 好但组合差、group spread 好但多头无收益、后端成功但 payload 不完整。

### Step5：案例压缩纪律

Step5 的 lessons 不得只是“跑通/失败”。必须压缩成：

- 哪些证据值得保留；
- 哪些证据只是弱证据或不可传播；
- 因子在哪些 regime / universe / 成本假设下有效或失效；
- 本 case 对未来 agent 有什么可迁移经验。

### Step6：研究控制纪律

Step6 必须写出 `math_discipline_review`，至少覆盖：

- `step1_random_object`；
- `target_statistic`；
- `information_set_legality`；
- `spec_stability`；
- `signal_vs_portfolio_gap`；
- `revision_operator`；
- `generalization_argument`；
- `overfit_risk`；
- `kill_criteria`。

若这些字段无法回答，Step6 应优先选择 `needs_human_review` 或 `iterate`，不得正式入库。

## 因子迭代方法论治理

知识库中已有 Fold、Regime 加权、TsRank+rank、combo、市值中性化、Decile 修复等手法。使用这些手法时必须加三道闸：

1. **收益来源闸**：修改是否强化了真实收益来源？
2. **稳健性闸**：修改是否降低样本、窗口、极值、regime 依赖？
3. **反证闸**：若下轮哪个指标不改善，就应停止该修改方向？

不允许：

- 因为某个 metric 变好就直接接受修改；
- 连续尝试多个 wrapper 后只保留最好结果而不记录失败；
- 把中性化、fold、regime、combo 当作万能修复器；
- 把局部 feature experiment 伪装成稳定因子。

## 研究员学习纪律

Factor Forge 的知识库不是案例墓地，而是 researcher agent 的经验库。

每次 Step6 必须把单个 case 抽象成四类可迁移知识：

1. **Pattern**：这类因子的成功模式是什么，适用于什么数据结构和市场状态？
2. **Anti-pattern**：这类想法为什么会失败，哪些看似合理的修补其实无效？
3. **Transfer**：这条经验能迁移到哪些相邻因子家族、变量组合或市场结构？
4. **Idea seed**：基于本次发现，下一代可尝试的新 idea 是什么？

一条优秀知识记录应让未来的我、Bernard 或 Humphrey 更像“有经验的量化研究员”，而不是重新从零开始读公式、跑回测、看 IC。

Step6 写回知识库时，必须避免只写状态总结。它要回答：

- 未来遇到相似公式时，应该先联想到哪个旧案例？
- 哪个修改方向值得复用，哪个方向应该少试或不试？
- 这次失败是否暗示了一个反向因子、组合因子或 regime 因子？
- 有没有新的 innovative idea seed，值得在下一轮研究中独立立项？

## 最小验收

一个严肃因子研究 case 至少应能回答：

- 这条因子在数学上预测什么？
- 它在投资上赚谁的钱？
- Step4 的证据支持收益来源，还是只支持当前实现？
- 如果 iteration，修改的数学操作是什么，为什么不是过拟合？
- 如果 reject，失败经验如何进入知识库，避免未来 agent 重复踩坑？
