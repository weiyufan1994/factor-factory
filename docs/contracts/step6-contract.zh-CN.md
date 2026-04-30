> [English Version](step6-contract.md)

# Step 6 合约

## 当前判断

Step 6 是 **研究闭环控制层**。
它不是另一个 execution backend，而是消费 Step 4 / Step 5 的证据，决定一个因子应当：
- 进入正式库，
- 继续迭代，
- 放弃，
- 或进入人工复核。

它的职责是把单次因子实验，沉淀成可累积的因子库与知识库，并在需要时把流程送回 Step 3B 继续改公式。

## 目标

Step 6 的存在意义，是让因子工厂具备“记忆”和“进化”能力，而不是每次都像新人一样重新研究。

它应把单次实验转化为：
- 全部因子库
- 正式因子库
- 统一知识库
- 明确的 loop 决策

## 输入

- `factorforge/objects/factor_run_master/factor_run_master__{report_id}.json`
- `factorforge/objects/factor_case_master/factor_case_master__{report_id}.json`
- `factorforge/objects/validation/factor_evaluation__{report_id}.json`
- 优先：
  - `factorforge/objects/handoff/handoff_to_step6__{report_id}.json`
- 向后兼容：
  - `factorforge/objects/handoff/handoff_to_step5__{report_id}.json`
- 可选 backend payload：
  - `factorforge/evaluations/{report_id}/{backend}/`
- 可选历史迭代对象：
  - `factorforge/objects/research_iteration_master/research_iteration_master__{report_id}.json`

## 输出

- `factorforge/objects/research_iteration_master/research_iteration_master__{report_id}.json`
- `factorforge/objects/factor_library_all/factor_record__{report_id}.json`
- 可选正式库记录：
  - `factorforge/objects/factor_library_official/factor_record__{report_id}.json`
- 一条或多条知识写回：
  - `factorforge/objects/research_knowledge_base/`
- 如需继续改因子，可写回 Step 3B handoff：
  - `factorforge/objects/handoff/handoff_to_step3b__{report_id}.json`
- 如需搜索分支，可生成：
  - `factorforge/objects/research_iteration_master/program_search_plan__{report_id}.json`
  - `factorforge/objects/research_iteration_master/search_branch_ledger__{report_id}.json`
  - `factorforge/objects/research_iteration_master/search_branch_result__{report_id}__{branch_id}.json`
  - `factorforge/objects/research_iteration_master/program_search_merge__{report_id}.json`
  - `factorforge/objects/research_iteration_master/search_branch_taskbook__{report_id}__{branch_id}.json`
  - `factorforge/research_branches/{report_id}/{branch_id}/TASKBOOK.md`

## 核心决策状态

Step 6 必须把每条因子尝试归入以下状态之一：
- `promote_official`
- `iterate`
- `reject`
- `needs_human_review`

注意：
这些状态不同于 Step 4 的 `run_status` 和 Step 5 的 `final_status`。

## research_iteration_master 结构

```json
{
  "report_id": "string",
  "factor_id": "string",
  "iteration_no": 0,
  "source_case_status": "validated|partial|failed",
  "evidence_summary": {
    "run_status": "success|partial|failed",
    "backend_statuses": {
      "self_quant_analyzer": "success",
      "qlib_backtest": "success"
    },
    "headline_metrics": {}
  },
  "research_judgment": {
    "decision": "promote_official|iterate|reject|needs_human_review",
    "thesis": "string",
    "strengths": ["string"],
    "weaknesses": ["string"],
    "risks": ["string"],
    "why_now": "string|null",
    "research_memo": {
      "formula_understanding": {
        "factor_type": "string",
        "plain_language": "string",
        "economic_story": ["string"],
        "what_must_be_true": ["string"],
        "what_would_break_it": ["string"]
      },
      "return_source_analysis": {
        "primary_hypothesis": "risk_premium|information_advantage|constraint_driven_arbitrage|mixed",
        "factor_family": "string",
        "bias_type": "string",
        "explanation": "string",
        "constraint_sources": ["string"],
        "objective_constraint_dependency": "string"
      },
      "metric_interpretation": {
        "verdict": "supportive|mixed|negative|inconclusive",
        "positive_evidence": ["string"],
        "negative_evidence": ["string"],
        "ambiguities": ["string"],
        "raw_metrics_used": {}
      },
      "math_discipline_review": {
        "math_axis": ["string"],
        "step1_random_object": "string",
        "target_statistic": "string",
        "information_set_legality": "string",
        "spec_stability": {},
        "signal_vs_portfolio_gap": "string",
        "revision_operator": "string",
        "generalization_argument": "string",
        "overfit_risk": ["string"],
        "kill_criteria": ["string"]
      },
      "learning_and_innovation": {
        "learning_goal": "string",
        "transferable_patterns": ["string"],
        "anti_patterns": ["string"],
        "similar_case_lessons_imported": ["string"],
        "innovative_idea_seeds": ["string"],
        "reuse_instruction_for_future_agents": ["string"]
      },
      "experience_chain": {
        "purpose": "string",
        "current_attempt": {},
        "prior_iteration_no": 0,
        "similar_experience_imported": [],
        "writeback_rule": ["string"]
      },
      "revision_taxonomy": {
        "macro_revision": {},
        "micro_revision": {},
        "portfolio_revision": {},
        "stop_or_kill": {}
      },
      "program_search_policy": {
        "search_budget_branches": 0,
        "method_library": {
          "genetic_algorithm": {},
          "bayesian_search": {},
          "reinforcement_learning": {},
          "multi_agent_parallel_exploration": {}
        },
        "recommended_next_search": {
          "branches": [],
          "requires_human_approval_before_code_change": true
        }
      },
      "diversity_position": {
        "factor_family": "string",
        "library_overlap_signals": [],
        "novelty_assessment": "string",
        "diversity_value": "string"
      },
      "evidence_quality": {
        "notes": ["string"],
        "backend_statuses": {},
        "run_status": "string",
        "row_count": 0,
        "date_count": 0,
        "ticker_count": 0
      },
      "failure_and_risk_analysis": {
        "expected_failure_regimes": ["string"],
        "crowding_risk": "string",
        "capacity_constraints": "string",
        "implementation_risk": "string"
      },
      "decision_rationale": ["string"],
      "next_research_tests": ["string"]
    },
    "factor_investing_framework": {
      "factor_family": "style_risk_factor|fundamental_information_factor|behavioral_price_pattern_factor|market_structure_microstructure_factor|mixed_or_unclear",
      "monetization_model": "risk_premium|information_advantage|constraint_driven_arbitrage|mixed",
      "bias_type": "risk_compensation|information_diffusion|behavioral_bias|constraint_plus_behavior|mixed_or_unclear",
      "return_source_hypothesis": "string",
      "expected_failure_regimes": ["string"],
      "objective_constraint_dependency": "low|medium|high|low_to_medium|medium_to_high",
      "constraint_sources": ["string"],
      "crowding_risk": "low|medium|high|medium_to_high",
      "capacity_constraints": "string",
      "implementation_risk": "string",
      "improvement_frontier": ["string"],
      "program_search_axes": {},
      "review_checklist": ["string"],
      "revision_principles": ["string"]
    }
  },
  "knowledge_writeback": {
    "success_patterns": ["string"],
    "failure_patterns": ["string"],
    "modification_hypotheses": ["string"],
    "factor_family": "string",
    "monetization_model": "string",
    "bias_type": "string",
    "return_source_hypothesis": "string",
    "expected_failure_regimes": ["string"],
    "objective_constraint_dependency": "string",
    "constraint_sources": ["string"],
    "crowding_risk": "string",
    "capacity_constraints": "string",
    "implementation_risk": "string",
    "improvement_frontier": ["string"],
    "program_search_axes": {},
    "review_checklist": ["string"],
    "revision_principles": ["string"],
    "research_commentary": ["string"],
    "learning_and_innovation": {},
    "experience_chain": {},
    "revision_taxonomy": {},
    "program_search_policy": {},
    "diversity_position": {}
  },
  "loop_action": {
    "should_modify_step3b": true,
    "modification_targets": ["string"],
    "next_runner": "step3b|stop",
    "stop_reason": "string|null"
  }
}
```

## 核心规则

1. Step 6 不得把缺失的 Step 4 证据解释成成功。
2. 不管最终决定是继续还是放弃，Step 6 都必须写出可复用的判断对象。
3. 每一次尝试都必须进入“全部因子库”。
4. 只有明确判定 `promote_official` 的因子，才能进入“正式因子库”。
5. 知识库必须同时记录成功模式和失败模式。
6. 如果判断是 `iterate`，Step 6 必须明确指出应如何回到 Step 3B 改代码。
7. 当因子已经足够正式入库，或已经没有改进空间时，Step 6 应停止 loop。
8. Step 6 负责反思与决策，不负责原始 metric 生成。
9. Step 6 可以要求 Step 3B 修改，但真正改公式/改实现的动作仍属于 Step 3B。
10. Step 6 不应把“风险补偿”和“信息优势”机械二分；它应允许收益来源是混合的，并明确记录主导来源假说与失效条件。
11. Step 6 应把“市场结构”推广理解为“约束驱动套利”，即由制度规则、资金属性、考核约束、流动性或执行约束等客观原因所形成的可重复行为。
12. Step 6 的 review 必须先判断收益来源与约束来源，再解释 metric。
13. Step 6 的 revision proposal 必须说明：本次修改在强化哪一种收益来源，以及为什么比上一版更合理。
14. Step 6 不得只输出简单判词；必须写出 `research_memo`，至少覆盖公式理解、收益来源、metric 解读、证据质量、失败机制、决策理由和下一轮测试。
15. Step 6 不得把“backend 成功”直接等同于“正式入库”；若原始 IC 支持但组合净值/账户表现不支持，应优先判为 `iterate`，并解释差异来自方向、交易成本、换手、组合构造还是样本稳定性。
16. Step 6 是因子工厂的独立研究员 agent，而不是日志汇总器。它必须形成 thesis、反驳 thesis、对比历史案例、写回经验，并在需要迭代时给 Step 3B 一份具体、可执行、有研究理由的修订 brief。
17. `validate_step6.py` 必须作为严格闸门：即使文件齐全，只要 `research_memo` 缺少公式理解、收益来源、metric 证据、失败机制、决策理由或下一轮测试，也必须 FAIL。
18. `validate_step6.py` 的结果必须使用 `PASS|WARN|BLOCK`：`BLOCK` 代表不能进入 promote / archive final / closed-loop complete；`WARN` 代表可以保留实验记录，但必须在正式入库前解决。
19. 缺少 `kill_criteria` 时，不允许 `promote_official` 或 archive final；缺少 `learning_and_innovation.reuse_instruction_for_future_agents` 时，不允许 archive final。
20. `information_set_legality=illegal*` 必须 BLOCK；`information_set_legality=requires_researcher_confirmation_no_forward_leakage` 不得进入 `promote_official`。
21. `overfit_risk=unknown|not assessed` 不得进入 `promote_official`。
18. 正常因子研究不得使用纯脚本式 Step6。`validate_step6.py` 必须要求外部研究员上下文：至少存在全流程 `research_journal` 或 Step6 专项 `researcher_memo`，并被 Step6 保存在 `research_memo` 里。
19. 全流程研究员必须从 Step1/Step2 开始记录作者思路，而不是等回测结束才解释结果。Step6 的判断必须能回溯到原始 thesis、Step2 canonical spec、Step3 implementation、Step4 evidence 和历史知识。
20. Step 6 必须写出 `math_discipline_review`，把因子映射到随机对象、目标统计量、信息集合法性、spec 稳定性、signal-vs-portfolio gap、revision operator、泛化理由、overfit 风险和 kill criteria。
21. Step 6 必须写出 `learning_and_innovation`，从当前 case 中抽象 transferable pattern、anti-pattern、similar-case lesson、innovative idea seed 和 future-agent reuse instruction。
22. 知识库写回不得只是状态总结；它必须让未来的 Bernard、Humphrey 或 Codex 更会挖因子。
23. Step 6 不得写入 `dd_view_edge_trade`；DD-view-edge-trade 属于个股基本面投研框架，不属于因子工厂的 Step6 合约。
24. Step 6 必须写出 `experience_chain`，把当前尝试、历史相似案例、失败签名和写回规则作为搜索轨迹保存。
25. Step 6 必须写出 `revision_taxonomy`，明确区分 macro revision、micro revision、portfolio revision 和 stop/kill。
26. Step 6 必须写出 `program_search_policy`，其中至少包含 `genetic_algorithm`、`bayesian_search`、`reinforcement_learning`、`multi_agent_parallel_exploration` 四类方法库。
27. `reinforcement_learning` 默认是未来策略学习器，只有当知识库积累了足够 revision trajectory 后才应自动决策；当前单因子迭代优先使用遗传式公式突变、贝叶斯参数搜索和多分支并行探索。
28. 若决策为 `iterate`，`program_search_policy.recommended_next_search.branches` 不得为空，并且任何代码改动前必须保留人工确认闸门。
29. Program search 是 Step6 研究判断的补充，不是替代。任何搜索分支都必须先写清收益来源、市场结构/客观约束、知识库先验、成功标准和反证标准，才能进入算法搜索或子代理执行。

## Program Search Plan 合约

当 Step6 判断需要 `iterate` 或需要人工复核搜索方向时，可生成 `program_search_plan__{report_id}.json`。

核心结构：

```json
{
  "report_id": "string",
  "factor_id": "string",
  "producer": "program_search_engine_v1",
  "status": "pending_human_approval",
  "purpose": "string",
  "step6_decision": "iterate|needs_human_review|reject|promote_official",
  "research_context": {
    "metric_verdict": "supportive|mixed|negative|inconclusive",
    "signal_vs_portfolio_gap": "string",
    "return_source": "risk_premium|information_advantage|constraint_driven_arbitrage|mixed",
    "market_structure": {
      "hypothesis": "string",
      "constraint_sources": ["string"],
      "objective_constraint_dependency": "string",
      "expected_failure_regimes": ["string"],
      "capacity_constraints": "string",
      "implementation_risk": "string"
    },
    "knowledge_priors": {
      "similar_cases": [],
      "transferable_patterns": ["string"],
      "anti_patterns": ["string"],
      "innovative_idea_seeds": ["string"],
      "reuse_instruction_for_future_agents": ["string"]
    }
  },
  "branches": [
    {
      "branch_id": "string",
      "branch_role": "audit|exploit|explore|portfolio|macro",
      "search_mode": "research_audit|bayesian_search|genetic_algorithm|reinforcement_learning_advisory|multi_agent_parallel_exploration",
      "status": "proposed",
      "requires_human_approval_before_execution": true,
      "research_question": "string",
      "hypothesis": "string",
      "return_source_target": "string",
      "market_structure_hypothesis": {},
      "knowledge_priors": {},
      "modification_scope": ["string"],
      "budget": {},
      "success_criteria": ["string"],
      "falsification_tests": ["string"],
      "hard_guards": ["string"],
      "expected_outputs": ["string"]
    }
  ],
  "selection_protocol": {}
}
```

硬规则：

1. `status` 必须从 `pending_human_approval` 开始。
2. 每个 branch 必须有 `research_question`、`hypothesis`、`return_source_target`、`market_structure_hypothesis`、`knowledge_priors`。
3. 每个 branch 必须有 `success_criteria` 与 `falsification_tests`，否则视为 data mining 风险。
4. `audit` branch 用于先排除证据、数据、contract 或实现错误；若 audit 发现 BLOCK，不能继续公式搜索。
5. `exploit` branch 只能做保守参数/窗口/归一化搜索，不能伪装成新机制发现。
6. `explore` branch 可以做遗传式公式突变，但必须说明如何保留或挑战原收益来源。
7. `portfolio` branch 只修 portfolio expression、成本、换手、rebalance、bucket construction，不应改写因子 thesis。
8. `macro` branch 负责挑战收益来源和市场结构，不应直接调参。
9. 所有 branch 结果都必须进入 ledger，失败分支也必须保留。
10. 分支执行前必须先经人工批准，并生成独立 taskbook。分支工作目录必须隔离在 `factorforge/research_branches/{report_id}/{branch_id}/`，不得直接覆盖 canonical Step3B 代码或 handoff。

## Search Branch Result 合约

每个搜索分支完成、失败、阻断或被 kill 后，必须写出 `search_branch_result__{report_id}__{branch_id}.json`。

核心结构：

```json
{
  "report_id": "string",
  "branch_id": "string",
  "branch_role": "audit|exploit|explore|portfolio|macro",
  "search_mode": "string",
  "status": "completed|failed|killed|blocked|inconclusive",
  "outcome": "improved|not_improved|bug_found|thesis_rejected|needs_more_evidence|inconclusive",
  "recommendation": "use_branch_for_next_step3b|keep_exploring|kill_branch|repair_workflow_first|needs_human_review",
  "research_question": "string",
  "branch_hypothesis": "string",
  "return_source_target": "string",
  "market_structure_hypothesis": {},
  "knowledge_priors": {},
  "researcher_summary": "string",
  "research_assessment": {
    "return_source_preserved_or_challenged": "string",
    "market_structure_lesson": "string",
    "knowledge_lesson": "string",
    "anti_pattern_observed": "string|null",
    "overfit_assessment": "string",
    "falsification_result": "string"
  },
  "evidence": {
    "metric_delta": {},
    "step4_artifacts": ["string"],
    "validator_results": {},
    "failure_signatures": ["string"],
    "notes": ["string"]
  },
  "human_approval_required_before_canonicalization": true
}
```

硬规则：

1. 分支结果必须回答 `falsification_result` 和 `overfit_assessment`，否则不能进入合并比较。
2. 若 recommendation 是 `use_branch_for_next_step3b`，必须有真实 Step4 artifact 或等价证据。
3. `program_search_merge__{report_id}.json` 只做 advisory 合并报告，不得直接改 `handoff_to_step3b` 或 canonical 代码。
4. 若 audit 分支发现 `bug_found` 或 `repair_workflow_first`，必须先修 workflow / data / contract / evidence，不能继续公式搜索。

## Audit Worker

`run_program_search_audit_worker.py` 是 Program Search Engine 的第一类内置 worker。

职责：

1. 检查 Step4/5/6 关键对象是否存在；
2. 检查 `factor_evaluation`、backend status、payload 路径、artifact 路径；
3. 检查 `handoff_to_step4` 中的 first-run factor values 和 run metadata；
4. 检查 data_prep、qlib adapter、implementation plan、factor spec、factor implementation ref；
5. 检查 Step6 `information_set_legality`；
6. 检查是否仍有 `dd_view_edge_trade` 等 Factor Forge 合约外字段；
7. 生成标准 `search_branch_result` 并更新 `search_branch_ledger`。

边界：

- 不上网；
- 不跑优化；
- 不改数据；
- 不改 Step3B；
- 不把远端 EC2 绝对路径在 Mac 上缺失误判为必然失败，而是记录为本机不可核验 warning。

## Bayesian Parameter Worker

`run_program_search_bayesian_worker.py` 是 Program Search Engine 的第二类内置 worker。

职责：

1. 只在已批准并 prepared 的 `bayesian_search` / `exploit` 分支运行；
2. 读取 `handoff_to_step4` 中的 first-run factor values 和 Step3A daily snapshot；
3. 在不改变原始 thesis 的前提下搜索局部参数；
4. 默认参数包括 `direction`、`delay`、`smooth_window`、`winsorize_q`、`cross_section_transform`；
5. 对每个 trial 记录参数、score、Rank IC、Pearson IC、long-short spread、coverage、失败签名；
6. 写出标准 `search_branch_result`，并由 `validate_bayesian_search_trials.py` 验收。

边界：

- 不改 shared clean data；
- 不改 canonical Step3B；
- 不改 `handoff_to_step3b` 或 `handoff_to_step4`；
- 不允许用单一 IC 宣布胜利；
- 不允许绕过 Step6 merge 和用户批准；
- 若本机缺少 `sklearn`，可以退化为 bounded randomized coverage，但必须如实写入 `selection_mode`。

## 独立研究员验收标准

一份合格的 Step 6 研究输出，至少必须回答：

- 这条因子到底想赚什么钱：风险溢价、信息优势、约束驱动套利，还是混合来源？
- 原研报/论文作者原本想表达什么，Step2 和 Step3 有没有保留这个想法？
- 为什么对手盘或市场结构会反复给出这个机会？背后的客观约束是什么？
- 当前 Step4 指标支持的是收益来源本身，还是只支持某个脆弱实现？
- 这条因子已经是可复用因子，还是仍然只是局部有效的 feature experiment？
- 本次实验应该沉淀什么知识，未来 agent 如何复用这条经验？
- 如果继续迭代，Step3B 具体该改什么，为什么这不是指标美化，而是在强化真实收益来源？
- 这条因子的数学对象、目标统计量、信息集边界和 overfit 风险是什么？
- 这次研究给未来 agent 留下了什么可迁移 pattern、anti-pattern 或 innovative idea seed？
- 下一轮搜索应该采用遗传式公式突变、贝叶斯参数搜索、组合表达修复、还是多子代理并行探索？
- 当前迭代是在 exploit 已有思路，还是 explore 邻近家族/新机制？两类分支是否都有被记录？

## 推荐执行顺序

1. Step 4 产出 metric / backtest 证据。
2. Step 5 写出 `factor_case_master`、`factor_evaluation`、`handoff_to_step6`。
3. Step 6 读取 Step 5 handoff，生成研究判断与知识写回。
4. 若决策为 `iterate`，Step 6 继续写 `handoff_to_step3b`，把流程送回 Step 3B。

## 当前自动化实现边界

当前第一版 `Step6` 已具备：
- 写 `research_iteration_master`
- 写全部因子库 / 正式因子库 / 统一知识库
- 写 `handoff_to_step3b`
- 通过 `run_step6_autoloop.py` 自动触发下一轮 Step4/5/6

当前第一版 `Step6` 的自动修改动作采用**保守包装层**：
- 保留原 Step3B 实现
- 新建 `factor_impl__...__iterN.py`
- 通过外层平滑、winsorize、re-zscore 等保守变换做自动迭代

它仍不等同于“论文级语义重写器”。

此外，当前默认增加了**人工审批闸门**：
- Step 6 先写 `revision_proposal__{report_id}.json`
- 明确修订方向、思路、逻辑与 planned actions
- 只有人工明确批准后，`apply_step6_iteration.py` 才允许真正改写下一轮执行入口

## 三类库的职责

### 全部因子库
作用：保存 **所有尝试**，包括失败、partial、废案、试错版本。

### 正式因子库
作用：保存明确被认为值得长期复用、可进入更高层信号合成/组合优化的因子。

### 统一知识库
作用：沉淀可迁移经验，例如：
- 哪类因子成功
- 哪类因子失败
- 为什么成功 / 失败
- 什么修改方向有效
- 哪些家族应当停止继续挖

## 推荐闭环

`Step3B -> Step4 -> Step5 -> Step6 -> Step3B ...`

在以下条件之一满足时停止：
- 达到正式入库门槛
- 已经没有明确改进空间
- 需要人工复核后再继续
