# Ultimate intake hotfix — 2026-09-28

本补丁解决 Amihud 原始非流动性研究实际暴露的两个框架缺陷，并澄清
direct-code 的输入顺序。它不改变 Amihud 定义、数据、IS/OOS 范围或评价方法。

## 修复

- Source-First public bridge 和 validator 使用本地入口明确提供的共享工作根，
  不再假设代码仓库就是研究工作根。`factorforge-local-runtime/workspaces`
  这样的容器名称不会因为含 `runtime` 一词被误判；字面保护目录、根不匹配、
  alias、非本地环境和实际代码保护目录的重叠仍拒绝。
- Step2 将原有 compatibility profile 和两个空列表理由完整转交到
  `learning_and_innovation` 及 Step3 handoff。校验规则未放宽，也不生成虚构经验。
- Step2/3 Skill 明确：先提供来源与数学对应的算法代码契约，再进行初始
  Step2 验证；Step3B 的实际代码仍须独立 Step2 review 后才能进入验收测试和 Step4。

## 作者验证

- 实际 public CLI → package validator、原路径保护与实际 Step1→Step2 producer/
  validator→消费者：109 passed。
- 公共离线套件：1,505 passed，2 个原有 deselected，6 个原有 pandas FutureWarning。
- Step2、Step3、Ultimate Skill 静态检查通过。
- 测试覆盖空理由、错误类型、缺失理由和 hosted 路径的拒绝；空列表只有在
  ordinary local IS 且确有已写明理由时才合法。

这些是工程回归，不是非流动性因子的实证结果。真实研究仍需补完来源绑定的
direct-code 输入并通过正式 Ultimate 复跑。旧的失败记录和旧版本不得擦除；
已有研究需显式选择修复版本，不能静默修改原 pin。
