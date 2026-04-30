# Humphrey Skill Alignment

## 结论

Humphrey 的 `factor-forge-step3/4/5` 应保持 agent-oriented skill 入口定位，
但数据预处理、共享数据访问、Step4 评估与 qlib native 基础设施应统一复用 repo 层。

## 分层建议

- repo-oriented layer
  - `scripts/preprocess_daily_data.py`
  - `factor_factory.data_access`
  - repo-side Step3/4/5 scripts
- agent-oriented layer
  - `/home/ubuntu/.openclaw/workspace/skills/factor-forge-step3`
  - `/home/ubuntu/.openclaw/workspace/skills/factor-forge-step4`
  - `/home/ubuntu/.openclaw/workspace/skills/factor-forge-step5`

## 执行原则

1. skill 是公共 EC2 入口。
2. repo 是共享实现与数据真相层。
3. skill scripts 默认委托 repo scripts。
4. 不允许 skill scripts 再单独维护一套数据清洗和回测口径。

## Agent Prompt 对齐

1. 先区分“共享基础设施问题”和“研究判断问题”。
   - 共享基础设施问题：数据预处理、数据源发现、qlib provider 构建、Step4 backend 执行顺序。
   - 研究判断问题：proxy 是否可接受、benchmark 是否合理、因子是否继续迭代。

2. Step 3 先准备数据，再写因子。
   - 日频输入优先调用 repo 侧 `scripts/preprocess_daily_data.py`。
   - 不再在 skill 内重复实现 raw 路径发现、PIT 清洗、OHLC 复权。

3. 数据源优先级固定。
   - Mac 本地 cache 优先。
   - EC2 上可用时优先 Tailscale 共享目录。
   - EC2 持久 raw cache 默认放在 `/home/ubuntu/.openclaw/workspace/factorforge/data/raw_tushare`。
   - 本地/Tailscale 不完整时再回退到 S3 拉 raw 数据，并写入这个持久目录。

4. 共享清洗策略不是 agent 的自由裁量项。
   - `BJ` / `ST` / 停牌 / 上市不足 / 涨跌停封板 / 异常 `pct_chg` 过滤遵循共享 policy。
   - `open/high/low/close/pre_close` 统一按共享 policy 复权。

5. Step 4 执行顺序固定。
   - 先 `self_quant_analyzer`
   - 再 small native qlib smoke test
   - 最后才 full native qlib

6. skill 负责解释和判断，repo 负责执行真相。
   - skill 可以解释 tradeoff、提醒风险、要求用户确认参数。
   - skill 不应自己发明另一套数据清洗、收益构造或回测口径。
