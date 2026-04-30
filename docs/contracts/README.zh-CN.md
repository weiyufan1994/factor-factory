> [English Version](README.md)

# 契约文档

本目录保存稳定的输入 / 输出 / 运行时契约文档。目标是让读者**不需要翻 runtime artifact**，也能理解每一步当前到底如何定义。

## 本目录在仓库中的位置

推荐的 reader-first 阅读顺序是：
1. `README.md`
2. `docs/repo-layering-and-naming.md`
3. `docs/reproducibility/`
4. `docs/contracts/`
5. `fixtures/step*/` 与 `scripts/run_step*_sample.*`

这个顺序是有意设计的：
- 先理解**仓库身份**；
- 再理解**层次边界**；
- 再理解**当前可复现边界**；
- 最后再进入**各步骤契约**与样本运行路径。

## 契约文档应该完成什么任务

每一步契约文档至少应让读者清楚：
- 当前输入类别是什么；
- 当前输出类别是什么；
- 已提交的微型可复现输入有哪些；
- 对应 sample runner 是什么；
- 工程实现层依赖面在哪里；
- 是否存在特别的可复现边界或警告。

一个合格的契约文档，应当稳定到足以让读者**无需通过以下方式反推步骤定义**：
- 隐藏 object 路径；
- runtime 目录；
- commit 考古；
- 或聊天历史。

## 当前范围

当前这些契约文档对应的是 **Step1–Step5 第一版最小可复现链路**，以及 **Step6 研究闭环控制层的第一版职责定义**。
它们并不宣称已经达到最终架构纯化，也不宣称已经完成生产级打包。

## 运行时路径契约

Step 间路径和 artifact locator 不再应由各脚本自行猜测。新增统一契约：

- `factorforge-runtime-context-contract.zh-CN.md`
- `factorforge-runtime-context-contract.md`

新增统一 Python 接口：

```python
from factor_factory.runtime_context import resolve_factorforge_context
```

新增 manifest 入口：

```bash
python3 scripts/build_factorforge_runtime_context.py --report-id <report_id> --write
```

以后新增 skill / worker 时，优先接入 runtime context，不要复制新的 `LEGACY_WORKSPACE` / `FACTORFORGE_ROOT` / path candidates 逻辑。
