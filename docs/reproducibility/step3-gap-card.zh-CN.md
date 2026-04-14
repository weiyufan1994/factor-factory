> [English Version](step3-gap-card.md)

# Step 3 缺口卡

## 当前判断
Step 3 已超越纯文档阶段：已有第一套极简提交的 fixture 束设计。
仍不如 Step 1/2 整洁，因为当前 Step 3 脚本期望对象路径安装加上本地输入快照。

## 仓库中已有的内容
- skill wrapper，位于 `skills/factor-forge-step3*`
- 脚本：`run_step3.py`、`run_step3b.py`、`validate_step3.py`、`validate_step3b.py`
- 合约 / 可复现性文档 / sample 命令卡
- `fixtures/step3/` 下的第一套极简 fixture 束

## 剩余可复现性缺口
- 当前 sample 路径仍需将 fixture 文件安装到 runner 期望的对象位置，而非直接消费 fixture 命名空间
- Step 3 验证与本地输入快照的存在紧密耦合
- 环境/运行时声明仍需正式化

## 下一步强化方向
重构 Step 3 脚本或添加更整洁的仓库原生封装，使提交的 fixture 路径可直接消费，无需对象路径拷贝和 monkeypatch。