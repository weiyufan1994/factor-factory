# 因子工厂知识检索架构（第一版）

## 目标
我们希望 `factor factory` 不只是“会跑流程”，而是能逐步沉淀成一个可迁移、可检索、可复盘的研究系统。知识层要同时服务两类主体：

1. 人：像量化 PM 一样回顾因子、对比试验、写洞察。
2. Agent：在进入 `Step6` 反思前，先检索历史相似因子、失败模式和有效改法。

## 设计原则
1. 结构化对象是唯一真相源。
2. Obsidian 是人类阅读和专题整理界面，不是唯一数据库。
3. 检索层要同时支持：
   - 精确过滤：按因子家族、决策、指标门槛筛选。
   - 文本召回：按失败模式、修改方向、市场风格搜索。
   - 语义召回：按“相似问题/相似因子”找历史案例。
4. 会话 memory 只能做辅助，不应替代可迁移知识库。

## 三层架构
### 第一层：Canonical Structured Store
当前已有并应继续扩展的结构化对象：
- `objects/factor_library_all/`
- `objects/factor_library_official/`
- `objects/research_knowledge_base/`
- `objects/research_iteration_master/`
- `objects/research_journal/`

它们是所有人和 agent 的唯一真相源。

### 第二层：Obsidian Vault
推荐把结构化对象自动导出到 `knowledge/因子工厂/`，用于：
- Dashboard 浏览
- 因子家族专题整理
- 手工评论和洞察补充
- 建立人类可读链接网络

默认 vault 名称为 `因子工厂`，其中必须包含：
- `普通因子库/`
- `正式因子库/`
- `知识库/`
- `研究迭代/`
- `Agent/FactorForge Researcher Agent.md`

注意：Obsidian 笔记可以丰富，但不应该反向覆盖 canonical JSON。

### 第三层：Retrieval Index
推荐把结构化对象压成 JSONL 检索语料，用于：
- SQLite FTS / ripgrep 关键字检索
- 向量化 embedding 检索
- Step6 在反思前自动召回相似因子

当前第一版建议输出：
- `knowledge/retrieval/factorforge_retrieval_index.jsonl`
- `knowledge/retrieval/factorforge_retrieval_manifest.json`

## 与文献的对照
### FactorMiner
参考：[FactorMiner paper](https://arxiv.org/pdf/2602.14670) 和 [repo](https://github.com/minihellboy/factorminer)

它最值得借鉴的是：
- 把技能和记忆分开。
- 记忆里存“成功模式”和“禁区/失败模式”。
- 用 retrieve → generate → evaluate → distill 的循环减少重复探索。
- 强调从“全局因子库视角”决定下一步，而不是只看单个候选因子的分数。

这非常接近我们现在的 `Step4 -> Step5 -> Step6`。

### FactorEngine
参考：[FactorEngine paper](https://arxiv.org/abs/2603.16365)

它对 Factor Forge 的最大启发不是“用 Bayesian 替代研究员”，而是明确拆开：
- 逻辑修改：由 LLM / researcher agent 根据收益来源、市场结构、历史经验决定；
- 参数优化：由 Bayesian 等算法在有边界的 search space 内做 micro tuning；
- 轨迹记忆：把每次 revise / evaluate / fail / promote 写成可复用经验。

因此我们采用的原则是：
`Step6 researcher first, algorithm second`。Bayesian worker 只能执行 Step6 已批准的局部参数分支。

### CogAlpha / QuantaAlpha
参考：[CogAlpha](https://arxiv.org/abs/2511.18850) 和 [QuantaAlpha](https://github.com/QuantaAlpha/QuantaAlpha)

它们说明 evolution search 的价值不在蛮力穷举，而在：
- mutation：对公式结构做有解释的变异；
- recombination：把同机制或相邻机制的有效片段重组；
- LLM reasoning：让变异围绕经济/市场结构逻辑展开。

这对应我们后续的 `genetic_algorithm` branch，但必须先由 Step6 写清 thesis 和 falsification test。

### AlphaSAGE / Quality-Diversity
参考：[AlphaSAGE OpenReview](https://openreview.net/forum?id=zRKF4ln2VE)、[AutoAlpha](https://arxiv.org/abs/2002.08245)

它们强调：因子挖掘不是只找一个最高分候选，而是建设一个低相关、机制多样、不过度拥挤的因子库。

对我们的要求是：
- Step6 必须记录 candidate 与已有普通因子库/正式因子库的冗余关系；
- 后续加入 novelty / redundancy gate；
- 失败区域也要入库，防止 future agent 重复挖同一片“红海”。

### AlphaAgent
参考：[AlphaAgent paper](https://arxiv.org/pdf/2502.16789)

它的重点不在长期 memory，而在“约束探索”以降低 alpha decay：
- complexity control
- hypothesis alignment
- novelty enforcement

对我们很有启发的一点是：
知识库不仅要存“以前什么成功/失败”，还要给下一轮探索加约束，避免生成越来越拥挤、越来越相似、越来越复杂的因子。

### AlphaAgentEvo
参考：[AlphaAgentEvo paper](https://openreview.net/pdf?id=lNmZrawUMu)

它解决 explore/exploit 的方式更像：
- 分层 reward
- 允许多轮自我探索
- 奖励持续改进，同时惩罚无效工具调用和低质量偏移

对我们的意义是：
`Step6` 不应该只写结论，还应该逐步学会区分：
- 哪些修改属于稳健 exploitation
- 哪些属于值得尝试的 exploration
- 何时应该停止

## 我们当前推荐方案
### 近期
1. 继续使用 JSON 对象作为 canonical source。
2. 自动导出 Obsidian vault。
3. 自动生成 retrieval index JSONL。
4. 让 Step6 在反思前先做 metadata + full-text 检索。

### 中期
1. 给 retrieval index 加 embedding。
2. 构建“相似因子召回”和“失败模式召回”。
3. 在 revision proposal 里显式引用历史成功/失败案例。

### 远期
1. 把知识库变成真正的“研究记忆层”。
2. 让 Step6 的 iterate/reject/promote 判断部分基于历史统计和相似案例，而不是只看本轮指标。
3. 再把这层扩展到信号合成、组合优化和策略风格管理。

## 不推荐的单点方案
### 只用 Obsidian
问题：适合人读，不适合 agent 稳定检索和自动过滤。

### 只用 agent memory
问题：不可迁移、不可审计、不可重建，容易把经验锁死在单一 agent 会话里。

## 当前仓库里的两个入口
### 导出 Obsidian Vault
```bash
cd /Users/humphrey/projects/factor-factory
python3 scripts/export_factorforge_obsidian.py
```

默认会写到：

```text
knowledge/因子工厂/
```

### 构建检索索引
```bash
cd /Users/humphrey/projects/factor-factory
python3 scripts/build_factorforge_retrieval_index.py
```

## 结论
最稳妥的路线不是在 `Obsidian`、`memory`、`Hermes 风格经验积累` 里三选一，而是：

- 结构化对象做真相源
- Obsidian 做人类工作台
- retrieval index 做 agent 检索层

这三者叠起来，才更像一个可成长的量化研究系统。
