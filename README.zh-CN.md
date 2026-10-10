# Factor Forge Ultimate — 研究框架与 SDK

研究主线：理解原文或假设 → 经济机制与数学推导 → 因子类实现及评审 → 标准因子值与评估 → 解释、修订或停止。

## 从这里开始

- [安装、手算例子和研究入口](docs/quickstart-publish.zh-CN.md)
- [Ultimate Skill](skills/factor-forge-ultimate/SKILL.md)
- [数据、因子和回测接口](docs/research-interface.zh-CN.md)
- [本轮改动、实际测试与未完成项](docs/publish-verification.zh-CN.md)

本分支为本地清理候选，尚未完成 M2 验收。普通本地 IS 不需要 Host/SoD 服务；真实研究仍需使用者提供有权使用的原文和数据。离线例子不是新因子实证。

交付由 `scripts/build_factorforge_publish_bundle.py` 从指定 Git 提交生成源码、Skill 和 wheel，安装说明只有上面的一个维护位置。旧 integration-patch 资料仅供历史复现，不是当前安装流程。现有研究保持原固定版本，本分支不会自动切换全局 Skill、发布知识库或推送 GitHub。
