> [English Version](step4-gap-card.md)

# Step 4 缺口卡

## 当前判断
Step 4 已超越纯文档阶段：已有第一套极简提交的 fixture 束设计，以真实的部分样本为核心。

## 仓库中已有的内容
- skill wrapper，位于 `skills/factor-forge-step4*`
- 运行/验证脚本及后端适配器
- 合约 / 可复现性文档 / sample 命令卡
- `fixtures/step4/` 下的第一套极简 fixture 束

## 剩余可复现性缺口
- 当前 sample 路径仍需将 fixture 文件安装到 runner 期望的对象位置，而非直接消费 fixture 命名空间
- 后端多样性尚未在极简 sample 路径中经受锻炼（当前极简 sample 使用 self_quant 快速路径）
- 环境/运行时声明仍需正式化

## 下一步强化方向
重构 Step 4 runner 或添加更整洁的仓库原生封装，使提交的 fixture 路径可直接消费，无需对象路径拷贝。