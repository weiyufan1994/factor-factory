> [English Version](step2-gap-card.md)

# Step 2 缺口卡

## 当前判断
Step 2 已超越纯文档阶段：已有第一套极简提交的 fixture 束设计。
但仍不如 Step 1 整洁，因为当前 runner 期望多个上游对象文件存在于固定的运行时路径。

## 仓库中已有的内容
- skill wrapper，位于 `skills/factor-forge-step2*`
- 可执行入口脚本 `skills/factor-forge-step2/scripts/run_step2.py`
- 合约 / 可复现性文档 / sample 命令卡
- `fixtures/step2/` 下的第一套极简 fixture 束

## 剩余可复现性缺口
- 当前 sample 路径仍需将 fixture 文件安装到 runner 期望的对象位置，而非直接消费 fixture 命名空间
- 工程层仍主要为 skill 打包方式
- 环境/运行时声明仍需正式化

## 下一步强化方向
重构 Step 2 runner 或添加薄的仓库原生封装，使 fixture 路径可被直接消费，无需对象路径拷贝。