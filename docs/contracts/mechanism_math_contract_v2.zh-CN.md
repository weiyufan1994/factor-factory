# Mechanism Math Contract v2: Legacy Compatibility

`mechanism_math_contract_v2` 是历史兼容 artifact，不再是新研究的通用数学
权威合同。它的可执行 validator 包含 `t0_t1_stochastic_benchmark` 等旧字段，
因此只用于读取、校验和保真传递已经存在的 v2 artifact。

新研究和新 revision 的数学权威是：

- `docs/contracts/mechanism_conditioned_measurement_program_v1.zh-CN.md`；
- artifact 字段 `mechanism_conditioned_measurement_program`；
- 合同版本 `factorforge_mechanism_conditioned_measurement_program_v1`。

## Compatibility Rules

1. 若上游 artifact 已包含合法 `mechanism_math_contract_v2`，Step2、Step3、
   Step6 可保真传递并继续执行旧 validator。
2. 若新研究没有 v2 artifact，不得自动合成一个随机过程合同，也不得因为
   缺少 `t0_t1_stochastic_benchmark` 而 BLOCK。
3. 不得把旧 v2 的随机过程字段复制到新的 measurement program，除非首选
   数学机制本身就是随机过程，并且该诊断确实适用。
4. 旧 v2 artifact 的存在不能覆盖 measurement program 中冻结的 estimand、
   数学机制、信息集、观测方程或 falsifier。两者冲突时必须 BLOCK 并迁移，
   不能静默选择旧合同。

## Current Authority Chain

```text
economic hypothesis
-> open mathematical-tool search
-> primary / mechanism-alternative / null-alias model selection
-> mechanism-specific derivation
-> market-outcome projection
-> applicable audits
-> observation and estimation
-> operator | direct code | hybrid
-> empirical falsification
```

数学工具由经济假设选择。DCF、剩余收益、会计恒等式、随机过程、微观结构、
优化、信息论、泛函、谱/信号、因果、图、PDE/ODE 或新组合对象都可以成为
首选机制，但没有任何一家族是通用默认。量纲分析、随机过程诊断及其他专项
审计只有在已选机制需要时才启用；不适用时不要求伪造空洞的 `N/A` 推导。

知识库、历史因子和已有算子只能提供 prior、counterexample 与 tool
candidate，不能决定数学机制，也不能替代推导或正式证据。

## Migration Boundary

遇到旧 v2 artifact 时：

- 保留原始 hash、身份和内容；
- 另外生成完整的 `mechanism_conditioned_measurement_program`；
- 明确旧字段与新 `market_outcome_projection`、`applicable_audits`、
  `observation_and_estimation` 的对应关系；
- 不得把迁移后的 program 回写成一个伪造的旧随机过程合同。

缺失当前 measurement program、模型选择由算子便利决定、知识库被当作证明、
或 market-outcome/observation/falsification 链断裂，才是新研究的数学合同
BLOCK。单纯没有随机过程或量纲分析不是 BLOCK。
