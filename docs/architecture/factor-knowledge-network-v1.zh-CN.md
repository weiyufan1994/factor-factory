# Factor Knowledge Network v1

日期：2026-06-17

## 目标

因子知识库不只是保存单个研究报告。它要让后续研究员能够按经济机制、数学机制、数据来源、失败模式和市场共识分类检索旧经验，从而在新因子研究时复用、反用或绕开已有路径。

现有 `knowledge/因子工厂/` 是人读的 vault。v1 在其上增加一个轻量机器层：

```text
knowledge/因子工厂/
  普通因子库/        # 所有尝试，包括 candidate、feature_candidate、reject
  正式因子库/        # 只保存严肃通过的正式因子
  知识库/            # 机制、失败经验、可迁移范式
  研究迭代/          # 版本轨迹和 evidence
  taxonomy/          # 统一多标签 taxonomy
  graph/
    nodes/           # 手写或自动生成的知识节点
    templates/       # 节点写回模板
    factor_knowledge_nodes.jsonl
    factor_knowledge_edges.jsonl
    factor_knowledge_graph_manifest.json
```

## 为什么不是单一分类树

市场共识会把因子分为动量、反转、价值、质量、低波、流动性等；更细的研究口径还会拆成 price momentum、earnings momentum、short-term reversal、residual momentum、relative value、profitability quality、turnover / liquidity、capital flow、crowding 等。私募/量化大厂也会并行使用 Barra 风险暴露、WorldQuant/operator 表达式风格、国内指增/市场中性/高频微观结构口径、以及内部买方研究桶，例如 stat-arb signal、microstructure alpha、flow alpha、risk premia、execution-aware alpha、crowding detector、alpha-combination feature、universe selector 等。

但一个因子通常同时属于多个维度：

```text
Moneyflow V18b
  market_consensus: microstructure, reversal
  economic_mechanism: profit_payer_supply, smart_absorption
  math_mechanism: hidden_state, first_passage
  data_source: minute_bar_derived_state, moneyflow
  tradability: long_side, cost_sensitive, high_turnover_risk
  research_status: feature_candidate, standalone_rejected
```

因此 v1 采用多标签 taxonomy，而不是单一树。

分类维度包括：

- `market_consensus`：动量、反转、价值、质量、低波、流动性、微观结构等市场共识，并允许更细的 price momentum、earnings momentum、short-term reversal、residual momentum、relative value、profitability quality、capital flow、crowding 等标签；
- `barra_style`：Size、Value、Momentum、Volatility、Liquidity 等风险模型/指增常见暴露；
- `worldquant_style`：价量、rank、ts/cs operator、neutralization 等表达式风格；
- `cn_quant_practice`：指增、市场中性、日内反转、高频微观结构、moneyflow alpha、小中盘 alpha、龙头跟随、涨跌停微观结构、拥挤监控、ML feature 等国内实盘研究分类；
- `buyside_style`：私募/买方内部更常见的研究桶，例如 stat-arb signal、short-horizon stat-arb、medium-horizon alpha、pure alpha、risk premia、behavioral alpha、microstructure alpha、flow alpha、execution-aware alpha、capacity/crowding、alpha-combination feature、ensemble feature、universe selector、regime conditioner；
- `economic_mechanism` 和 `math_mechanism`：因子真正的经济来源和数学对象。

这些标签用于检索和联想，不是研究约束。一个节点可以只填写有把握的维度，但必须保留经济机制、数学机制、研究状态和失败边界。

`taxonomy/factor_taxonomy_v1.json` 同时维护常用中文/市场口语别名，例如 `动量类`、`反转类`、`资金流`、`私募资金流`、`龙头战法`、`占用测度`。别名只用于检索入口，会解析成标准 tag，例如 `动量类 -> market_consensus:momentum`、`资金流 -> buyside_style:flow_alpha`，不会改变节点里的 canonical taxonomy。

## 节点

一个节点表示一个可复用研究对象，可以是：

- `factor`: 单个因子或因子族；
- `mechanism`: 经济/数学机制；
- `anti_pattern`: 失败范式；
- `feature_candidate`: 可进入模型组合但不适合 standalone promotion 的特征；
- `methodology`: 研究方法；
- `data_state`: 可复用 Data API/datamart 状态。

节点必须包含：

- `id`: 全局稳定 ID；
- `node_type`;
- `title`;
- `summary`;
- `taxonomy`;
- `evidence`;
- `source_paths`;
- `relations`;
- `reuse_guidance`。

写回模板：

```text
knowledge/因子工厂/graph/templates/factor_knowledge_node_template.json
knowledge/因子工厂/graph/templates/factor_knowledge_node_writeback_guide.md
```

## 边

边用于表达知识网络关系：

| edge_type | 含义 |
| --- | --- |
| `belongs_to` | 属于某类机制或风格 |
| `uses_math` | 使用某个数学对象或推导范式 |
| `shares_failure_with` | 共享失败模式 |
| `inspired_by` | 由旧因子/机制启发 |
| `inspires` | 可启发后续方向 |
| `contradicts` | 证伪或反驳某个 naive 机制 |
| `refines` | 是旧版本的机制修正 |
| `requires_data_state` | 依赖某个 datamart/state |
| `reusable_as` | 可作为模型特征、反例或方法论复用 |

## 和现有 Factor Forge artifact 的关系

这个知识网络不是替代正式 artifacts：

- `objects/factor_library_all` / `objects/research_knowledge_base` 仍是 formal artifact 层；
- `knowledge/因子工厂` 仍是人读 vault；
- `knowledge/因子工厂/graph` 是跨研究的结构化索引层。

正式 promotion 仍由 Step6/Ultimate 的 evidence gate 决定。Graph 节点只说明知识状态，不自动批准因子。

## Researcher 写回要求

每轮研究完成后，研究员至少应写回：

1. 普通因子库记录：是否 official/candidate/feature_candidate/reject；
2. 知识库记录：经济机制、数学机制、失败经验；
3. Graph node：统一 taxonomy、证据、关系边；
4. 如果有正式批准，再写正式因子库。

失败同样必须写入 graph，尤其是：

- 高 IC 但 long-side after-cost 失败；
- 因子被 size/liquidity 暴露解释；
- 数学对象选错；
- 数据层 BLOCK；
- 复杂 gate 破坏 payer 机制。

## v1 验证

构建索引：

```bash
python3 scripts/build_factor_knowledge_graph.py
```

检索示例：

```bash
python3 scripts/query_factor_knowledge_graph.py --tag first_passage
python3 scripts/query_factor_knowledge_graph.py --tag feature_candidate --text moneyflow
python3 scripts/query_factor_knowledge_graph.py --edge-type shares_failure_with
python3 scripts/run_factor_knowledge_graph_smoke.py
```

为 Step1/Step2/Step6 或研究员生成完整上下文：

```bash
python3 scripts/retrieve_factor_knowledge_context.py \
  --tag market_consensus:reversal \
  --text moneyflow \
  --top-k 5
```

输出 schema 为 `factor_knowledge_context_v1`，会展开节点的 `mechanism`、`evidence`、`relations`、`reuse_guidance` 和 `source_paths`。它适合写入 formal artifact 的 knowledge provenance；`query_factor_knowledge_graph.py` 只适合人工快速查看。
retrieval CLI 只向 stdout 输出；正式 artifact 必须由具备 workspace path guard 和
provenance 的 Host writer 接管，不能使用 retrieval CLI 直接写文件。

## Step1/Step2/Step6 接入

Step1 在 standardize 阶段会根据 report thesis / factor concept 自动检索 graph：

```text
research_discipline.factor_knowledge_context
research_discipline.knowledge_reference_contract
learning_and_innovation.factor_knowledge_context
learning_and_innovation.knowledge_reference_contract
knowledge_reference_contract
```

Step1 的 graph context 用途是早期启发：帮助 reader 看到旧研究里的经济机制、数学对象、失败经验和市场共识分类，例如动量、反转、微观结构、Barra liquidity、WorldQuant rank/ts operator、国内指增/高频微观结构等。它不能把旧节点当作同因子证明，也不能跳过 PDF/报告本身的 primary/challenger/chief merge 判断。

Step2 在构建 `research_contract` 时会根据 Step1/primary spec 文本自动检索 graph：

```text
research_contract.factor_knowledge_context
research_contract.knowledge_reference_contract
learning_and_innovation.factor_knowledge_context_imported
learning_and_innovation.knowledge_reference_contract
```

Step6 在 `build_retrieval_context` 中读取同一 graph context，并把 graph nodes 追加进 `similar_cases`，`doc_type=factor_knowledge_graph_node`。这些记录默认是 analogy / anti-pattern，不是 same-factor proof。

验证：

```bash
python3 scripts/run_factor_knowledge_step1_context_smoke.py
python3 scripts/run_factor_knowledge_step2_context_smoke.py
python3 scripts/run_factor_knowledge_step6_context_smoke.py
python3 scripts/run_factor_knowledge_graph_smoke.py
python3 scripts/run_factor_knowledge_network_readiness.py
python3 scripts/report_factor_knowledge_graph_coverage.py \
  --json-output knowledge/因子工厂/graph/factor_knowledge_coverage.json \
  --markdown-output knowledge/因子工厂/仪表盘/知识网络覆盖率.md
```

`run_factor_knowledge_network_readiness.py` 是总验收入口。它会检查 taxonomy 关键分类、买方分类、graph build、节点质量、Step1/Step2/Step6 自动接入、installed skill parity，以及需要精确 `git add -f` 的知识网络文件。节点质量检查会验证 repo 内 `source_paths` 真实存在；`/tmp` 这类临时路径不能作为知识节点来源，S3/worker 外部路径只能作为外部证据引用，不能替代本地 durable source。

`report_factor_knowledge_graph_coverage.py` 是覆盖率盘点入口。它对比人读 vault 中的普通因子库、正式因子库、研究知识库和研究迭代记录，输出哪些记录已经被 graph node 的 `source_paths` 覆盖，哪些高优先级记录还缺 graph node。覆盖率是迁移进度，不是 readiness blocker；历史 vault 很大，应优先迁移有强机制、正式/候选状态、或重复失败模式的记录。

## 版本管理注意

当前 `knowledge/因子工厂/` 在本地 ignore 规则中被整体忽略。新增 taxonomy、graph node、template 或 dashboard 文件需要精确 `git add -f`，不要直接解除整个目录 ignore，以免把无关 vault 文件混入提交。`run_factor_knowledge_network_readiness.py` 会按当前 graph/taxonomy/dashboard 文件动态输出需要 force-add 的路径清单，提交前以该清单为准。
