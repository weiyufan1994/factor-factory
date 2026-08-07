# Factor Knowledge Node Writeback Guide

每轮因子研究结束后，除了人读 Markdown，还要写一个机器可读节点：

```text
knowledge/因子工厂/graph/nodes/<STABLE_ID>_<YYYYMMDD>.json
```

从模板复制：

```text
knowledge/因子工厂/graph/templates/factor_knowledge_node_template.json
```

## 分类原则

不要把因子塞进单一类别。每个节点至少从这些维度选择标签：

- `market_consensus`：市场共识分类，例如 `momentum`、`price_momentum`、`earnings_momentum`、`residual_momentum`、`reversal`、`short_term_reversal`、`medium_term_reversal`、`value`、`quality`、`size`、`low_volatility`、`liquidity`、`microstructure`、`capital_flow`、`crowding`。
- `barra_style`：Barra/风险模型风格，例如 `size`、`value`、`momentum`、`volatility`、`liquidity`、`growth`。
- `worldquant_style`：表达式/算子风格，例如 `price_volume`、`rank_transform`、`ts_operator`、`cs_operator`、`neutralized_expression`。
- `cn_quant_practice`：国内私募/实盘研究常见工作流，例如 `index_enhancement`、`market_neutral`、`intraday_reversal`、`high_frequency_microstructure`、`moneyflow_alpha`、`small_mid_cap_alpha`、`leader_following`、`limit_up_down_microstructure`、`industry_rotation`、`crowding_monitor`、`feature_for_ml`。
- `buyside_style`：买方/私募内部常见研究桶，例如 `stat_arb_signal`、`short_horizon_stat_arb`、`medium_horizon_alpha`、`pure_alpha_signal`、`risk_premia_signal`、`behavioral_alpha`、`risk_factor`、`microstructure_alpha`、`flow_alpha`、`liquidity_provider_signal`、`execution_aware_alpha`、`crowded_trade_detector`、`alpha_combination_feature`、`ensemble_feature`、`universe_selector`、`regime_conditioner`。
- `economic_mechanism`：收益来自谁的错误、约束或风险承接。
- `math_mechanism`：推导用到的数学对象，例如 `first_passage`、`occupation_measure`、`residualization`、`distribution_moment`、`stochastic_process`。
- `data_source`：原始数据或 Data API/datamart 状态。
- `tradability`：long-side、成本、容量、暴露和组合用途。
- `research_status`：`official`、`candidate`、`feature_candidate`、`standalone_rejected`、`anti_pattern`、`data_blocked` 等。
- `failure_mode`：失败也要写，例如 `turnover_cost_exceeds_gross_edge`、`wrong_math_object`、`data_coverage_gap`。

## 必写内容

节点不应只记录流程元数据。至少写清楚：

1. 经济假设：谁是 payer，谁是 receiver，为什么这个错误定价能存在。
2. 数学机制：随机对象、目标统计量、关键方程、推导逼出的方向。
3. 信息变化：变换保留了什么、删除了什么、混淆了什么、是否变得不可交易。
4. 可执行表达：公式、law id、direct-code state 或 feature definition。
5. 证据：窗口、universe、cost、portfolio policy、核心 metric、artifact 路径。
6. 失败边界：什么结果已经证伪，什么结果未来会 kill 这个机制。
7. 关系边：它使用了什么数学对象、受谁启发、反驳了什么 naive 机制、和谁共享失败。

## 分类写法示例

一个节点可以同时属于多个市场和买方分类，不要为了“主类”牺牲检索能力：

```json
{
  "market_consensus": ["microstructure", "reversal", "capital_flow"],
  "barra_style": ["liquidity", "momentum"],
  "worldquant_style": ["price_volume", "rank_transform", "ts_operator"],
  "cn_quant_practice": ["index_enhancement", "moneyflow_alpha", "feature_for_ml"],
  "buyside_style": ["microstructure_alpha", "flow_alpha", "execution_aware_alpha", "alpha_combination_feature"]
}
```

标签是 retrieval / analogy 工具，不是死板 checklist。比如一个资金流因子可以同时是 `market_consensus:microstructure`、`market_consensus:reversal`、`buyside_style:flow_alpha` 和 `cn_quant_practice:moneyflow_alpha`；一个 Alpha101 价量公式可以同时是 `worldquant_style:rank_transform`、`barra_style:liquidity` 和 `buyside_style:stat_arb_signal`。

## 验证

写完节点后运行：

```bash
python3 scripts/validate_factor_knowledge_node.py knowledge/因子工厂/graph/nodes/<STABLE_ID>_<YYYYMMDD>.json
python3 scripts/build_factor_knowledge_graph.py
python3 scripts/query_factor_knowledge_graph.py --tag <your_tag> --text <keyword>
python3 scripts/run_factor_knowledge_graph_smoke.py
python3 scripts/run_factor_knowledge_network_readiness.py
```

`validate_factor_knowledge_node.py` 是单节点快速验收入口。它会检查 schema、taxonomy 标签合法性、payer/receiver、与机制匹配的 mathematical object、公式/方程、Dirac-style insight、证据窗口、核心指标、失败边界、source_paths 和 relation edges。旧节点的 `random_object` 只作兼容别名。新增节点先跑这个，再 rebuild 全图。

Graph 节点不等于正式入库。`feature_candidate`、`standalone_rejected`、`anti_pattern`、`data_blocked` 都是合法且重要的知识状态。

分类是为了检索，不是为了限制研究。没有把握的维度可以留空，但经济机制、数学机制、研究状态和失败边界不能省略。

## 别名检索

`factor_taxonomy_v1.json` 维护了常用中文/市场口语别名。研究员可以直接用别名查询，脚本会解析为标准 tag：

```bash
python3 scripts/query_factor_knowledge_graph.py --tag 动量类 --top-k 10
python3 scripts/query_factor_knowledge_graph.py --tag 反转类 --top-k 10
python3 scripts/query_factor_knowledge_graph.py --tag 资金流 --top-k 10
python3 scripts/retrieve_factor_knowledge_context.py --tag 占用测度 --text CPV --top-k 5
```

常用别名包括：`动量类`、`反转类`、`价值类`、`质量类`、`资金流`、`私募资金流`、`龙头战法`、`小中盘`、`统计套利`、`风险溢价`、`执行流`、`占用测度`、`首达时间`、`随机过程`。

`run_factor_knowledge_network_readiness.py` 会检查节点质量。每个节点至少要能回答：

1. 谁付钱、谁接收收益；
2. 随机对象或数学对象是什么；
3. 哪个方程、公式、law 或 state 表达了这个机制；
4. 数学对象逼出了什么新 insight，或者某个变换保留/删除了什么信息；
5. 证据窗口、核心指标、失败边界在哪里；
6. 后续研究应该复用、反用还是避免什么。
