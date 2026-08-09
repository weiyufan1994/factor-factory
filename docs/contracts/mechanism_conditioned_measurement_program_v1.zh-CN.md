# Mechanism-Conditioned Measurement Program v1

`factorforge_mechanism_conditioned_measurement_program_v1` 是当前数学权威链，规定如何从经济假设选择数学机制，再把机制变成可观测、可实现、可证伪的因子。`mechanism_math_contract_v2` 只用于已存在历史 artifact 的兼容校验，新研究不生成它。任何路线都不得用实现便利反向修改上游 estimand。

## Authority Chain

```text
frozen economic claim and estimand
-> open mathematical tool search
-> selected mathematical model against mechanism alternative and null/alias
-> primary mechanism equation or functional
-> market-outcome projection
-> applicable specialized audits
-> observation equation
-> component measurement bindings
-> operator | direct code | hybrid
-> deterministic checks
-> empirical falsification
```

当上游机制、适用审计或 observation equation 未冻结时，本合同状态只能是 `under_specified`，不能通过拼接算子制造一个可运行因子。

## Required Record

Measurement program 至少包含：

- `contract_version=factorforge_mechanism_conditioned_measurement_program_v1`；
- `authority_order`：固定的经济假设、数学机制、测量、实现、证伪顺序；
- `knowledge_role`：知识只能是 prior、counterexample 或 tool candidate，并声明冲突处理；
- `math_tool_selection`：开放候选工具、实际选择、组合/新数学对象许可、拒绝理由；工具名不受固定枚举限制；
- `model_selection`：estimand/selection target、首选、机制不同替代、null/alias 三类候选，唯一首选及区分性检验；每个候选必须分别声明 `mathematical_object`、`mechanism_equation_or_functional`、`target_functional`、`market_outcome_projection` 与 `observation_mapping`，核心机制方程不得复用市场结果投影；
- `market_outcome_projection`：从数学对象到价值、支付、价格差或收益的通用映射；随机过程不是必选项；
- `applicable_audits`：开放的专项审计列表，可以为空；选择量纲、随机过程、
  频谱、因果、估值或其他审计后才要求记录理由、结果和 falsifier；
- `observation_and_estimation`：estimand、observation map、estimator、识别假设、噪声和合法时点；
- `public_derivation_record`：定义、假设、关键推导步骤、识别缺口、近似和 overclaim guard；
- `implementation`：`operator | direct_code | hybrid` 及逐组件绑定；
- `deterministic_validation_plan`：schema/测量语义、future mutation、极限 oracle、ablation/alias 和 parity；单位只在适用时检查；
- `search_policy`：不变 estimand、允许的模型/估计器变化、禁用捷径、目标向量与停止规则。

## Component Binding

每个 `component_binding` 必须同时回答：

| Field | Requirement |
|---|---|
| `component_id` | 稳定且可追踪的组件标识 |
| `math_term_or_functional` | 对应方程、状态、泛函或参数，而非泛泛的“动量/波动” |
| `economic_claim` / `mechanism_role` | 对应经济主张，以及该项为何是主机制所必需 |
| `observable_or_input` | Data API 字段或上游状态 |
| `input_measurement_semantics` / `output_measurement_semantics` | 记录数据和输出的经济/统计测量语义；只在单位确实有意义时记录单位或 `dimensionless` |
| `information_time` | 在 `F_t` 中何时合法可知 |
| `transformation_or_estimator` | 从 observation equation 到该项的统计/数值映射 |
| `implementation_binding` | operator id、direct-code block 或 hybrid boundary |
| `preserved_information` | 变换保留的幅度、顺序、相位、尺度、尾部或状态信息 |
| `discarded_information` | 变换主动删除的信息及理由 |
| `expected_metric_signature` | 若机制为真，该组件对 IC、分位形状、状态切片等的独有预测 |
| `ablation_test` | 删除/替代该项后应发生什么 |
| `falsifier` | 哪个观测会否定该组件的机制角色 |

组件缺少任一数学项、输入输出语义、信息集、预期签名或 falsifier 时，
不得声称 measurement complete。单位只在其对数学对象或实现语义有意义时
记录；这不等于要求每个因子执行量纲分析。

## Implementation Routes

### Operator

仅当已有算子的精确定义、边界、缺失值规则、窗口语义和单位与 `estimation_map` 相同才可复用。名字相似不等于语义一致。不得先选算子再编写机制。

### Direct Code

适用于滤波、状态估计、路径泛函、优化、PDE/ODE、图结构、事件状态机或其他难以表达为现有算子的测量。代码必须绑定输入/输出 schema、数值方法、误差容限、时间复杂度、随机种子、信息集、单元测试和 code-law hash。Direct code 不是绕过数学合同的自由文本入口。

### Hybrid

适用于标准变换与自定义状态估计的组合。必须声明 operator subgraph、custom block、边界 schema、单位转换、所有权和 parity/接口测试。边界不得隐式改变 estimand。

路线由数学与数值需求决定，不由“哪个最容易跑通”决定；三种路线具有相同的研究证据义务。

## Data And Transformation Discipline

数据处理不是中性的。每个 winsorization、rank、z-score、neutralization、resample、filter、FFT/wavelet、缺失填充、复权和聚合都必须说明：

- 它估计哪一个数学量；
- 改变了哪种单位、信息或不变性；
- 对 payer/market-state 主张的必要性；
- 若删除或替换，预期指标签名如何改变。

若数据无法支持 observation equation，应请求新 datamart/字段、缩小可识别主张或 BLOCK。禁止用容易获得的 proxy 静默替换目标；显式 proxy 必须记录测量误差和区分性检验。

## Deterministic Validation

进入正式回测前至少检查：

- type/schema、测量语义，以及适用时的单位和数值范围；
- 时间合法性、lag、calendar、窗口端点及 future-mutation invariance；
- 缩放/平移不变性、极限情形和手算 oracle；
- constant、missing、停牌、涨跌停、极端值和小样本行为；
- operator/direct-code/hybrid 的实现一致性或明确的不适用声明；
- full-versus-ablated 组件身份和输出 hash。

确定性 PASS 只证明实现符合 measurement program，不证明经济机制或因子收益成立。

## Knowledge And Search

知识库可返回 DCF/剩余收益、随机过程、泛函、信号、信息论、因果、图、控制等模型族，以及已知反例、算子、代码块、datamart 和失败路径，且必须记录 provenance。它们只能标记为 `advisory_prior`、`counterexample` 或 `tool_candidate`。Agent 必须重新验证其数学定义、适用审计、信息集和适用域；历史成功不能替代当前推导，历史失败也只能在身份/假设相同时直接排除。

探索允许在 measurement program 定义的邻域内改变模型、估计器或实现，但每个 branch 必须先声明修改的数学项、保留的不变量、预期签名和停止规则。超出邻域或改变 estimand 的候选是新研究，不是参数 mutation。

## Public Record And Falsification

公开 artifact 展示可复现的定义、关键推导、模型选择理由、组件映射、测量语义、适用时的单位、近似、预期签名和 falsifier；不展示也不声称展示私有 chain-of-thought。

Formal evidence 必须区分：

- mechanism-consistent signature；
- implementation correctness；
- predictive diagnostics；
- promotion-gate evidence。

当结果失败时，按 mechanism-math contract 定位失败层。只有 measurement/implementation 层失败时才允许在不改 estimand 的前提下修正数据处理、算子或代码；上游机制失败必须新建模型 branch 并重新推导。
