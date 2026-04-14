> [English Version](README.md)

# 可复现说明

本目录用于保存按步骤组织的可复现说明卡、差距卡，以及与 Bernard/Mac 直接复现有关的仓库结构说明。

## 本目录在仓库中的位置

如果你是从上往下阅读仓库，建议顺序如下：
1. `README.md` —— 先理解仓库顶层身份与阅读路径；
2. `docs/repo-layering-and-naming.md` —— 再理解分层边界与命名原则；
3. `docs/reproducibility/` —— 再看当前最小可复现边界；
4. `docs/contracts/` —— 然后看稳定契约；
5. `fixtures/step*/` + `scripts/run_step*_sample.*` —— 最后进入具体样本运行路径。

换句话说：
- `README.md` 说明 **这个仓库是什么**；
- `docs/repo-layering-and-naming.md` 说明 **该如何读这个仓库而不把层次搞混**；
- `docs/reproducibility/` 说明 **当前到底有什么能够被真实复现**。

## 这里应该放什么

本目录适合放：
- 各步骤可复现说明卡；
- gap cards；
- 最小可复现边界说明；
- 与可复现直接相关的仓库结构说明；
- 面向复现者的 reader-first 导航文档。

本目录**不适合**放：
- 低层 runtime artifact 倾倒；
- 临时本地执行残留；
- 本应进入 contracts 的未成文化架构假设。

## 读完本目录后，读者应能回答什么

一个新读者在看完本目录后，应当能够回答：
- 当前每一步能复现到什么程度；
- 验收边界在哪里；
- 微型 fixture 路径从哪里进入；
- 哪些步骤仍然有意保持 partial 或有限状态。
