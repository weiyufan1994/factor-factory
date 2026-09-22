# Factor Knowledge Network v1 提交范围与验收清单

日期：2026-06-18

## 目的

本文件只定义因子知识网络 v1 的提交边界和验收方式。当前 repo 可能同时存在其他因子研究、Data API 反馈、worker proof 或历史 vault 文件的脏状态；这些不应混入知识网络 v1 的提交。

知识网络 v1 的目标是让后续研究员可以按以下维度检索和复用因子经验：

- 市场共识分类：动量、反转、价值、质量、低波、流动性、微观结构、资金流、拥挤等；
- Barra / 风险模型风格；
- WorldQuant / operator 表达式风格；
- 国内量化实践分类：指增、市场中性、日内反转、高频微观结构、资金流、龙头战法等；
- 私募/买方内部研究桶：stat-arb、risk premia、microstructure alpha、flow alpha、execution-aware、crowding、ensemble feature 等；
- 经济机制、数学机制、数据来源、交易性、研究状态和失败模式。

分类用于检索和类比，不是研究 checklist。研究结论仍以经济假设、数学对象、信息集合法性、IS/OOS 证据和复杂度代价为准。

## 应纳入提交的文件

### 架构与公共代码

```text
docs/architecture/factor-knowledge-network-v1.zh-CN.md
docs/operations/factor-knowledge-network-v1-commit-scope-20260618.zh-CN.md
factor_factory/knowledge_context.py
scripts/build_factor_knowledge_graph.py
scripts/query_factor_knowledge_graph.py
scripts/report_factor_knowledge_graph_coverage.py
scripts/retrieve_factor_knowledge_context.py
scripts/run_factor_knowledge_graph_smoke.py
scripts/run_factor_knowledge_network_readiness.py
scripts/run_factor_knowledge_step1_context_smoke.py
scripts/run_factor_knowledge_step2_context_smoke.py
scripts/run_factor_knowledge_step6_context_smoke.py
scripts/validate_factor_knowledge_commit_scope.py
scripts/validate_factor_knowledge_node.py
```

### Skill / Step 接入

```text
skills/factor-forge-researcher/SKILL.md
skills/factor-forge-step1/SKILL.md
skills/factor-forge-step1/scripts/standardize_step1_research_fields.py
skills/factor-forge-step1/scripts/validate_step1.py
skills/factor-forge-step2/SKILL.md
skills/factor-forge-step2/scripts/run_step2.py
skills/factor-forge-step2/scripts/validate_step2.py
skills/factor-forge-step6/SKILL.md
skills/factor-forge-step6/scripts/run_step6.py
```

### 被 ignore 但必须强制纳入的知识网络文件

`knowledge/因子工厂/` 在本地 ignore 规则中被整体忽略。以下文件必须用 `git add -f` 精确加入，不要解除整个目录 ignore，也不要 `git add knowledge/因子工厂`：

```text
knowledge/因子工厂/taxonomy/factor_taxonomy_v1.json
knowledge/因子工厂/graph/nodes/*.json
knowledge/因子工厂/graph/templates/factor_knowledge_node_template.json
knowledge/因子工厂/graph/templates/factor_knowledge_node_writeback_guide.md
knowledge/因子工厂/graph/factor_knowledge_nodes.jsonl
knowledge/因子工厂/graph/factor_knowledge_edges.jsonl
knowledge/因子工厂/graph/factor_knowledge_graph_manifest.json
knowledge/因子工厂/graph/factor_knowledge_coverage.json
knowledge/因子工厂/export_manifest/*.json
knowledge/因子工厂/仪表盘/知识网络.md
knowledge/因子工厂/仪表盘/知识网络覆盖率.md
```

提交前以总验收脚本输出的 `version_control.paths` 为准。如果该列表变化，应采用脚本输出的精确列表。

## 不应纳入本提交的文件

以下文件或目录可能在当前工作树中存在，但不属于知识网络 v1 的核心提交：

```text
factor_research/
objects/
output/
data/
tmp/
knowledge/因子工厂/普通因子库/
knowledge/因子工厂/知识库/
knowledge/因子工厂/研究迭代/
knowledge/因子工厂/正式因子库/
docs/operations/*datamart*
docs/operations/*data-api*
tests/test_ultimate_data_request_autogen.py
scripts/run_factorforge_ultimate.py
skills/factor-forge-ultimate/SKILL.md
```

除非另有明确授权，不要在知识网络提交中整理、删除、迁移或提交这些文件。

## 验收命令

提交前至少运行：

```bash
python3 -m py_compile \
  factor_factory/knowledge_context.py \
  scripts/build_factor_knowledge_graph.py \
  scripts/query_factor_knowledge_graph.py \
  scripts/report_factor_knowledge_graph_coverage.py \
  scripts/retrieve_factor_knowledge_context.py \
  scripts/run_factor_knowledge_graph_smoke.py \
  scripts/run_factor_knowledge_network_readiness.py \
  scripts/run_factor_knowledge_step1_context_smoke.py \
  scripts/run_factor_knowledge_step2_context_smoke.py \
  scripts/run_factor_knowledge_step6_context_smoke.py \
  scripts/validate_factor_knowledge_commit_scope.py \
  scripts/validate_factor_knowledge_node.py

python3 scripts/run_factor_knowledge_graph_smoke.py
python3 scripts/run_factor_knowledge_network_readiness.py
python3 scripts/validate_factor_knowledge_node.py \
  knowledge/因子工厂/graph/nodes/CPV_OCC_LOC_STABILITY_V3_20260616.json
python3 scripts/validate_factor_knowledge_commit_scope.py
git diff --check -- \
  docs/architecture/factor-knowledge-network-v1.zh-CN.md \
  docs/operations/factor-knowledge-network-v1-commit-scope-20260618.zh-CN.md \
  factor_factory/knowledge_context.py \
  scripts/build_factor_knowledge_graph.py \
  scripts/query_factor_knowledge_graph.py \
  scripts/report_factor_knowledge_graph_coverage.py \
  scripts/retrieve_factor_knowledge_context.py \
  scripts/run_factor_knowledge_graph_smoke.py \
  scripts/run_factor_knowledge_network_readiness.py \
  scripts/run_factor_knowledge_step1_context_smoke.py \
  scripts/run_factor_knowledge_step2_context_smoke.py \
  scripts/run_factor_knowledge_step6_context_smoke.py \
  scripts/validate_factor_knowledge_commit_scope.py \
  scripts/validate_factor_knowledge_node.py \
  skills/factor-forge-researcher/SKILL.md \
  skills/factor-forge-step1/SKILL.md \
  skills/factor-forge-step1/scripts/standardize_step1_research_fields.py \
  skills/factor-forge-step1/scripts/validate_step1.py \
  skills/factor-forge-step2/SKILL.md \
  skills/factor-forge-step2/scripts/run_step2.py \
  skills/factor-forge-step2/scripts/validate_step2.py \
  skills/factor-forge-step6/SKILL.md \
  skills/factor-forge-step6/scripts/run_step6.py \
  knowledge/因子工厂/taxonomy/factor_taxonomy_v1.json \
  knowledge/因子工厂/graph \
  knowledge/因子工厂/仪表盘/知识网络.md \
  knowledge/因子工厂/仪表盘/知识网络覆盖率.md
```

预期：

```text
run_factor_knowledge_graph_smoke.py -> verdict=ACCEPT
run_factor_knowledge_network_readiness.py -> verdict=ACCEPT
validate_factor_knowledge_node.py -> verdict=ACCEPT
validate_factor_knowledge_commit_scope.py -> verdict=ACCEPT
git diff --check -> PASS
```

## 推荐 staging 方式

先加入非 ignored 文件：

```bash
git add \
  docs/architecture/factor-knowledge-network-v1.zh-CN.md \
  docs/operations/factor-knowledge-network-v1-commit-scope-20260618.zh-CN.md \
  factor_factory/knowledge_context.py \
  scripts/build_factor_knowledge_graph.py \
  scripts/query_factor_knowledge_graph.py \
  scripts/report_factor_knowledge_graph_coverage.py \
  scripts/retrieve_factor_knowledge_context.py \
  scripts/run_factor_knowledge_graph_smoke.py \
  scripts/run_factor_knowledge_network_readiness.py \
  scripts/run_factor_knowledge_step1_context_smoke.py \
  scripts/run_factor_knowledge_step2_context_smoke.py \
  scripts/run_factor_knowledge_step6_context_smoke.py \
  scripts/validate_factor_knowledge_commit_scope.py \
  scripts/validate_factor_knowledge_node.py \
  skills/factor-forge-researcher/SKILL.md \
  skills/factor-forge-step1/SKILL.md \
  skills/factor-forge-step1/scripts/standardize_step1_research_fields.py \
  skills/factor-forge-step1/scripts/validate_step1.py \
  skills/factor-forge-step2/SKILL.md \
  skills/factor-forge-step2/scripts/run_step2.py \
  skills/factor-forge-step2/scripts/validate_step2.py \
  skills/factor-forge-step6/SKILL.md \
  skills/factor-forge-step6/scripts/run_step6.py
```

再用 `run_factor_knowledge_network_readiness.py` 输出的 `version_control.paths` 精确 `git add -f`。
也可以直接生成 ignored 知识网络文件的 force-add 命令：

```bash
python3 scripts/validate_factor_knowledge_commit_scope.py --print-force-add
```

提交前检查 staged scope：

```bash
python3 scripts/validate_factor_knowledge_commit_scope.py
git diff --cached --name-only
```

如果出现不属于上面范围的研究目录、worker scratch、Data API 反馈、clean data、`objects/` 或 `output/`，应取消 staging 后重新精确加入。

如果需要在不污染 git index 的情况下测试某个路径是否会被接受，可以使用：

```bash
python3 scripts/validate_factor_knowledge_commit_scope.py --paths scripts/validate_factor_knowledge_commit_scope.py
python3 scripts/validate_factor_knowledge_commit_scope.py --paths factor_research/example_bad_scope/result.json
```

第一个应 `ACCEPT`；第二个应 `BLOCK` 并报告 `unexpected_staged_paths`。

如果准备做完整知识网络 v1 提交，可在 staging 后运行：

```bash
python3 scripts/validate_factor_knowledge_commit_scope.py --require-complete
```

该模式会要求当前存在的所有知识网络 v1 核心文件都已 staged，适合 commit 前最后检查；日常开发中不建议默认开启。
