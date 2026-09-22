# Factor Forge 能力台账

更新日期：2026-04-26

本文记录 Factor Forge Ultimate 当前尚未完全工程化的能力缺口，以及给 Bernard / Humphrey / Codex 的后续施工方向。它不是单次因子研究结论，而是系统能力建设台账。

## 总原则

Factor Forge Ultimate 当前已经可以作为 researcher-led 因子研究闭环使用，但还需要继续把若干“研究方法”从原则升级成可执行、可验收、可复盘的工程模块。

所有新增能力必须满足：

- 不绕过 Step1-6 主流程；
- 不允许 agent 私自改 shared clean data；
- 不允许临时图表或临时 notebook 冒充正式 Step4 evidence；
- 因子代码修改必须先有 Step6 revision proposal，并经用户批准；
- 每条分支都必须留下失败记录，不能只保留最好结果。

## 0. Runtime Context / 标准路径接口

当前实现状态：`V1 已启动`。

已新增：

- `factor_factory/runtime_context.py`
- `scripts/build_factorforge_runtime_context.py`
- `docs/contracts/factorforge-runtime-context-contract.zh-CN.md`
- `docs/contracts/factorforge-runtime-context-contract.md`

目标：所有 Step / Skill / Worker 使用同一个 runtime context 获取路径，避免每个脚本自己搜索 `FACTORFORGE_ROOT`、EC2 legacy path、objects、runs、evaluations、handoff、factor_values。

标准用法：

```python
from factor_factory.runtime_context import resolve_factorforge_context

ctx = resolve_factorforge_context()
handoff4 = ctx.object_path('handoff_to_step4', report_id)
factor_values = ctx.factor_values_path(report_id, 'parquet')
daily_input = ctx.step3a_daily_input_path(report_id)
```

manifest 用法：

```bash
python3 scripts/build_factorforge_runtime_context.py --report-id <report_id> --write
```

首批已接入：

- `run_program_search_bayesian_worker.py`

后续要求：

- 新增 worker 不得复制 `LEGACY_WORKSPACE` / `FACTORFORGE_ROOT` / path candidates 逻辑；
- 共享 ledger 更新必须使用 `update_json_locked`；
- 普通 JSON 写入使用 `write_json_atomic`；
- handoff 中旧 EC2 绝对路径由 `ctx.remap_legacy_path()` 统一处理。

## 1. Program Search 能力升级

当前实现状态：`V1 scaffold 已启动`。

已新增：

- `skills/factor-forge-step6/scripts/build_program_search_plan.py`
- `skills/factor-forge-step6/scripts/validate_program_search_plan.py`
- `skills/factor-forge-step6/scripts/approve_program_search_branch.py`
- `skills/factor-forge-step6/scripts/prepare_approved_search_branch.py`
- `skills/factor-forge-step6/scripts/run_program_search_audit_worker.py`
- `skills/factor-forge-step6/scripts/run_program_search_bayesian_worker.py`
- `skills/factor-forge-step6/scripts/validate_bayesian_search_trials.py`
- `skills/factor-forge-step6/scripts/record_search_branch_result.py`
- `skills/factor-forge-step6/scripts/validate_search_branch_result.py`
- `skills/factor-forge-step6/scripts/merge_program_search_branches.py`

V1 定位：先把 Step6 的研究判断转成可审批、可派发、可追踪的搜索分支计划；当前已具备 audit worker 与 bayesian parameter worker 两类内置 worker。所有 worker 均不得自动改 Step3B，不得触碰 shared clean data。

对应问题：Step6 现在已经写入 genetic algorithm、Bayesian search、reinforcement learning、multi-agent parallel exploration 等方法名，但它们还不是完整自动优化引擎。

目标：把 Step6 的“建议搜索方法”升级为“可派发、可预算、可验收、可回滚”的分支搜索系统。

### 1.0 外部方法启发登记

以下外部工作进入 Factor Forge 方法台账，但不能被机械照搬：

- `FactorMiner`：最有价值的是 skill / experience memory 分离，以及 retrieve -> generate -> evaluate -> distill 循环。Factor Forge 应把成功模式、失败约束、冗余教训写入结构化知识库。
- `FactorEngine`：最有价值的是 logic revision 与 parameter optimization 分离。Step6 researcher 负责收益来源、市场结构、公式逻辑；Bayesian 只做 micro-level 参数优化。
- `CogAlpha` / `QuantaAlpha`：最有价值的是 LLM reasoning + evolutionary mutation / recombination。后续遗传分支应由 Step6 先定义机制，再做有边界的公式变异。
- `AlphaSAGE` / GFlowNet：最有价值的是多样性和低相关因子库目标，而不是单一最优公式。后续要加入 factor-library redundancy / novelty gate。
- `AutoAlpha` / Quality-Diversity：最有价值的是远离已探索拥挤区域。知识库必须记录失败区域和重复区域，避免反复挖同一类因子。

当前优先级：

1. Bayesian parameter worker：已启动 V1，负责窗口、delay、winsorize、方向、横截面变换等 bounded 参数搜索。
2. Evolution / GA worker：下一步，负责公式结构 mutation / recombination，但必须先有 Step6 revision proposal。
3. Quality-Diversity / novelty gate：下一步，把候选与普通因子库、正式因子库做相关性和 family redundancy 检查。
4. RL / GFlowNet：中长期，等 revision trajectories 足够多后再作为 advisory policy，不直接接管 Step6 判断。

### 1.1 分支对象标准化

每个搜索分支都必须生成统一对象：

```yaml
branch_id: string
parent_report_id: string
parent_factor_version: string
search_mode: genetic_algorithm|bayesian_search|reinforcement_learning_advisory|multi_agent_parallel_exploration|manual_research_revision
hypothesis: string
return_source_target: risk_premium|information_advantage|constraint_driven_arbitrage|mixed
modification_targets:
  - formula
  - parameters
  - preprocessing_assumption
  - neutralization
  - portfolio_expression
  - turnover_cost_control
budget:
  max_trials: integer
  max_runtime_minutes: integer
  max_compute_cost_note: string
approval:
  requires_human_approval: true
  approved_by: string|null
lineage:
  generated_from_step6_proposal: string
  compared_against_baseline: string
status: proposed|approved|running|completed|failed|killed
kill_criteria:
  - string
expected_outputs:
  - factor_values
  - step4_payloads
  - step5_case
  - step6_branch_judgment
```

### 1.2 遗传算法分支

适用场景：公式结构可能有问题，或者需要探索算子组合、符号、窗口、rank/ts_rank/fold/neutralization 等结构性变化。

必须包含：

- genome：公式 AST、窗口、符号、transform、neutralization、missing handling；
- mutation：窗口变动、符号翻转、rank/ts_rank 替换、fold、winsorize、smooth、industry/size neutralization；
- crossover：只允许在同 family 或机制相近的因子之间做，避免无意义拼接；
- diversity constraint：不能一轮只围着同一个 wrapper 调参；
- objective：不能只最大化 IC，必须同时看 OOS、decile NAV、long-short spread、turnover/cost、coverage、drawdown；
- anti-cherry-pick：失败个体也要记录到 branch ledger。

### 1.3 贝叶斯搜索分支

适用场景：公式逻辑基本可信，但窗口、阈值、decay、bucket、neutralization strength 等参数需要系统搜索。

当前实现状态：`run_program_search_bayesian_worker.py` 已提供 V1。

必须包含：

- search space：参数上下界、离散/连续类型、合法组合；
- objective：多目标评分，不允许单一 IC 作为晋级标准；
- split：train / validation / OOS 或 rolling validation；
- stop：若 validation 改善但 OOS 不改善，禁止 promote；
- output：每次 trial 的参数、metric、失败原因、是否进入下一轮。

V1 边界：

- 只读取 `handoff_to_step4` 里的 first-run factor values 和 Step3A daily snapshot；
- 只在 `factorforge/research_branches/{report_id}/{branch_id}/` 下写 trial 和候选产物；
- 默认搜索 `direction`、`delay`、`smooth_window`、`winsorize_q`、`cross_section_transform`；
- 若本机有 `sklearn`，使用 Gaussian Process acquisition 排序后续候选；否则退化为 bounded randomized coverage；
- 输出 `search_branch_result`，但不得直接更新 canonical Step3B 或 `handoff_to_step3b`。

### 1.4 强化学习分支

当前定位：advisory only。

原因：Factor Forge 目前还没有足够多的 revision trajectories，无法可靠训练一个真正的 revise/promote/reject policy。

短期用法：

- 把 RL 当作“未来 policy learner 的数据结构准备”；
- 每次 Step6 记录 state/action/reward；
- state 包括因子 family、return source、IC、decile、turnover、portfolio gap、失败模式；
- action 包括 formula mutation、parameter search、portfolio repair、kill、promote；
- reward 使用 OOS 稳定性、净收益、成本后收益、知识可迁移性，不用单次回测胜负。

正式启用条件：

- 至少积累一批不同 family 的成功和失败 revision trajectories；
- 有固定 benchmark task；
- policy 输出只作为候选建议，不得绕过 Step6 人类审批。

### 1.5 多 agent 并行探索

适用场景：Step6 判断一个因子值得 iterate，但不确定是公式问题、参数问题、组合表达问题，还是样本/机制问题。

建议固定四类分支：

- exploit branch：小范围参数/窗口/阈值搜索；
- explore branch：结构性公式突变或 family-level 迁移；
- portfolio branch：只修 portfolio expression、成本、换手、rank-only / quantile portfolio；
- audit branch：检查 thesis、信息集、数据字段、lookahead、Step4 artifact 是否有 bug。

治理要求：

- 每个分支写入独立 branch_id；
- 分支之间不得覆盖同一代码文件，除非进入最终 merge；
- Step6 合并时必须比较 baseline 和所有失败分支；
- 不能只报告胜出分支。

## 2. Golden Case 回归测试

对应问题：workflow、skill、repo 实现有时会出现细微口径差异。需要用固定样本把流程钉住。

目标：建立一组 Factor Forge golden cases，用来验证每次修改后 Step1-6 的流程、产物、validator、skill 文档和 repo 脚本是否一致。

### 2.1 Golden case 的意义

它不是为了“增加样本做研究”，而是为了固定系统行为：

- 同一个输入应走同一个入口；
- skill 写的流程必须和 repo 脚本真实行为一致；
- Step4 必须产出同一套标准 artifact；
- Step5/6 必须按同一套 promote / iterate / reject 规则判断；
- 数据层不应被因子任务意外重建。

### 2.2 建议样本池

首批建议固定：

- `ALPHA001_PAPER_20100104_CURRENT`：已知公式、可快速验证 Step3-6；
- `ALPHA002_PAPER_20160101_20250711`：已有 iterate 案例，适合测 Step6 revision；
- `ALPHA010_PAPER_20160101_20250711`：凸型/非线性分位结构，适合测 Step6 研究判断；
- `ALPHA012_PAPER_20160101_20250711`：用于复现近期 bug，测 Step4/clean data/contract 稳定性；
- `DONGWU_TECH_ANALYSIS_20200619_02` 或 UBL/CPV：研报型案例，适合测 Step1-6 端到端。

### 2.3 每个 golden case 要固定什么

每个 case 应包含：

- input object：原始报告、公式、report_id、回测区间；
- expected path：应从 Step1、Step3 或 Step4 哪个入口开始；
- expected artifacts：每步必须存在的对象；
- expected validators：哪些 validator 必须 PASS，哪些允许 WARN；
- metric tolerance：关键指标允许浮动范围，不要求逐 bit 相同；
- data mutation assertion：本 case 不得触发 shared clean data mutation；
- skill/repo parity assertion：skill.md 的流程描述必须能映射到真实脚本调用。

### 2.4 最小验收

每次大改 workflow 后，至少跑：

```bash
python3 scripts/run_factorforge_golden_cases.py --case-set smoke
python3 scripts/check_skill_repo_parity.py
```

如果脚本尚未存在，Humphrey 应先把它们作为任务建账，不得用口头“看起来能跑”代替。

## 3. Portfolio / Signal Synthesis 下一层系统

对应问题：Factor Forge 当前核心是单因子发现、评估、迭代和入库；组合构建、信号合成、portfolio optimization 仍然是下一层系统。

目标：把它记为正式路线，但不要混进当前 Step1-6 主闭环里。

边界：

- 当前 Step4 的 portfolio evidence 用来判断单因子是否可交易；
- Step6 的 portfolio expression branch 用来修复“信号好但组合变现差”的问题；
- 真正的 multi-factor signal synthesis、risk model、portfolio optimizer、capital allocation 是 Factor Forge 之后的 Portfolio Forge / Signal Forge 层。

后续建设方向：

- 因子相关性和冗余检测；
- 正式因子库的组合选择；
- 多因子信号合成；
- 风格/行业/市值/流动性风险约束；
- 交易成本和容量模型；
- PM 级 portfolio decision report。

## 4. 常驻调度与 Agent Orchestration

对应问题：现在 Bernard / Humphrey / Codex 仍主要靠用户 prompt 和 skill 调用驱动，还没有一个常驻 manager process 自动排任务、监控、重试、归档。

目标：建立从轻到重的三阶段 agent orchestration。

当前实现状态：`Phase A lightweight ledger 已启动`。

已新增：

- `scripts/factorforge_task_ledger.py`

Phase A 定位：只记录任务状态，不自动调度、不启动任务、不改数据、不绕过审批。

### 4.1 Phase A：轻量任务台账

短期先做：

- 每个任务写 task record；
- 每个 Step 写 status、start/end time、exit code、artifact list；
- 每次失败写 failure signature；
- 每次需要人类批准时生成 approval checkpoint；
- Humphrey / Bernard 必须先查台账再继续任务。

推荐对象：

```yaml
task_id: string
report_id: string
owner: Bernard|Humphrey|Codex|EC2
current_step: Step1|Step2|Step3A|Step3B|Step4|Step5|Step6
status: queued|running|blocked|waiting_for_approval|completed|failed
last_evidence: string
next_action: string
approval_required: boolean
artifact_paths:
  - string
failure_signature: string|null
```

最小用法：

```bash
python3 scripts/factorforge_task_ledger.py create \
  --goal "研究 Alpha002 并生成 Step6 search plan" \
  --report-id ALPHA002_PAPER_20160101_20250711 \
  --owner Humphrey \
  --current-step Step6 \
  --status queued \
  --data-policy "read shared clean only; no data mutation" \
  --boundary "code changes require Step6 proposal and human approval" \
  --expected-output "program_search_plan + branch ledger"

python3 scripts/factorforge_task_ledger.py update \
  --task-id <task_id> \
  --status waiting_for_approval \
  --current-step ProgramSearch \
  --approval-required true \
  --approval-checkpoint "approve exploit/explore/portfolio branch" \
  --next-action "wait for user approval"

python3 scripts/factorforge_task_ledger.py list --status waiting_for_approval
python3 scripts/factorforge_task_ledger.py validate
```

### 4.2 Phase B：Manager script

中期做一个本地 manager：

- 读取 task queue；
- 调用对应 skill/script；
- tail log；
- 检查 validator；
- 失败重试有限次数；
- 遇到 data mutation、factor code revision、promotion 决策时停止等人类批准；
- 可把 heavy compute 派给 EC2，把 knowledge/retrieval 派给 Bernard。

### 4.3 Phase C：常驻调度器 / Dashboard

长期做：

- 一个常驻 scheduler；
- Web/Obsidian dashboard；
- 多 agent 状态监控；
- branch search 并行调度；
- 自动同步 EC2 产物回 Mac；
- 定期重建 retrieval index；
- 定期复盘 official factor library。

### 4.4 推荐顺序

当前不要直接跳到 Phase C。先做 Phase A 和 Golden Case，等流程稳定后再做 Manager script。

## 给 Humphrey 的当前台账任务

Humphrey 后续应把下面四项登记为系统能力建设任务：

1. `PROGRAM_SEARCH_ENGINE_V1`：把 Step6 的 GA / Bayesian / RL advisory / multi-agent branch 从文字策略升级为 branch schema、branch ledger、budget、validator 和 merge protocol。
2. `GOLDEN_CASE_REGRESSION_V1`：建立 Alpha001/002/010/012/UBL-or-CPV 的 golden case 固定流程，验证 skill/repo parity。
3. `PORTFOLIO_SIGNAL_SYNTHESIS_BACKLOG`：记录为 Factor Forge 之后的下一层系统，不混入当前单因子 Step1-6 主闭环。
4. `AGENT_ORCHESTRATION_V1`：先做轻量任务台账，再做 manager script，最后才考虑常驻 scheduler/dashboard。
