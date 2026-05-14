# A股量价因子市场结构先验

> 本文记录 Humphrey 对 A 股量价因子收益来源和市场 regime 的研究先验。它是研究假说，不是任何因子的 promotion 证据。正式因子结论仍以 `scripts/run_factorforge_ultimate.py` 的 Step4/5/6 证据为准。

## 1. 市场分期先验

### 2016 年以前：草莽时代

A 股机构化程度较低，Alpha101 尚未公开，简单价量结构更容易赚钱。这个阶段的收益不能直接外推到今天。

研究含义：
- 若一个量价因子主要靠 2010-2015 赚钱，之后长期水下，应视为老市场红利，而不是可推广 alpha。
- 回测展示必须拆分 pre-2016 和 post-2016，不允许用全样本平均掩盖失效。

### 2016-2020：白马和公募主导

市场主线转向白马、消费、医药、光伏、新能源等机构审美，公募基金和基本面叙事影响增强，同时量化私募开始大范围起步。

研究含义：
- 短周期价量因子可能被白马/大市值主线压制。
- 如果因子在这一阶段退化，需要区分是因子本身失效，还是只适用于非机构主导的小票/流动性环境。

### 2020-2024-09-24：疫情后混乱阶段

疫情、风格切换、流动性冲击、政策预期和风险偏好反复，使短周期价量结构更不稳定。

研究含义：
- 这个阶段应作为 drawdown/recovery 的核心压力测试。
- 如果 NAV 从 2020 高点长时间水下，不能只归因于交易成本，也可能是 regime mismatch。

### 2024-09-24 之后：新概念主线重新活跃

政策转向、AI、CPO 等主题成为市场主线后，概念炒作和行为偏差重新增强。

研究含义：
- 后续若样本足够，应单独观察 post-2024-09-24 表现。
- 若价量因子只在概念活跃期恢复，需要标注其依赖市场风险偏好和散户/主题博弈结构。

## 2. 量价因子的三类收益来源

### Risk Premium

尤其是流动性风险、拥挤风险、小票冲击风险、短期价格压力补偿。

判定线索：
- 高分组承担更高流动性/拥挤/冲击风险；
- 收益来自承担不受欢迎的短期风险，而不是提前知道信息；
- 成本、容量、回撤是核心约束。

### Information Advantage

某些形态可能表明聪明钱提前知道了什么，或更早解释了未公开反映的信息。

判定线索：
- 成交量、开盘价、价量相关性在消息公开前变化；
- 信号在主题切换、事件前后、产业链主线形成前更有效；
- 需要防止把纯流动性冲击误判为信息优势。

### 博傻 / Market Structure Harvesting

市场结构允许系统化策略收割不理性的散户行为、主题追涨、流动性错配和概念炒作。

判定线索：
- 因子在概念活跃、散户参与强、主题切换频繁时更强；
- 收益来自他人非理性交易和约束行为，而不是传统风险补偿；
- 拥挤后容易失效，容量和交易成本约束强。

## 3. 对 Alpha014 / Smooth5 的当前理解

Alpha014 原式：

```text
((-1 * rank(delta(returns, 3))) * correlation(open, volume, 10))
```

Smooth5 修订：

```text
mean(((-1 * rank(delta(returns, 3))) * correlation(open, volume, 10)), 5)
```

当前理解：
- 原式是短周期收益变化和开盘价/成交量关系的交互项。
- Smooth5 说明 persistence/smoothing 方向有效，但 2016+ 后单独 Smooth5 仍有深回撤和成本后亏损。
- 进一步测试 `smooth5_lowturn` 后，最佳版本也只是 G10 Sharpe `0.475`、最大回撤 `-34.94%`、recovery `1823` 天、成本后年化 `-7.19%`。
- `smooth10_lowturn`、`smooth5_lowamount`、`smooth5_lowvol20` 均未改善到可采用：要么信号变钝，要么低流动性风险过粗，要么收益被风险过滤削弱。
- 这更像弱流动性/低关注风险补偿，而不是稳定 information advantage 或纯粹博傻因子。
- Alpha014 当前结论为 `reject_archive_as_lesson`：保留经验，不继续作为主线烧研究预算。

专项沉淀：
- [[知识库/ALPHA014_20160101_RESEARCH_ARCHIVE|ALPHA014 2016+ Research Archive]]

## 4. 对 Alpha015 / High Amount Active Structure 的当前理解

Alpha015 原式：

```text
(-1 * sum(rank(correlation(rank(high), rank(volume), 3)), 3))
```

当前最佳 2016+ 修订：

```text
(((-1 * sum(rank(correlation(rank(high), rank(volume), 7)), 7)) * rank(amount)) * (0.40 + (0.60 * (1 - rank(turnover)))))
```

当前理解：
- Alpha015 的有效部分不是低流动性风险溢价，也不是低波动质量因子。
- `rank(amount)` 是机制门控：它把信号集中到高成交、高关注、可交易容量较强的活跃股票里。
- 高分组收益更像来自 active-liquidity / behavioral microstructure：在高关注股票中识别价量共振没有进入过热确认状态的部分。
- 温和 `turnover` penalty 可以小幅改善成本后收益，但硬低换手会破坏信号。
- 低波动、低 kurtosis、低 amount 慢窗口等通用风险过滤都削弱了 alpha body。

关键证据：
- `ALPHA015_REGIME_R03_CORR7_HIGHAMOUNT_20160101`：G10 年化 `22.26%`、Sharpe `0.969`、maxDD `-37.96%`、recovery `498`、成本后年化 `3.06%`。
- `ALPHA015_SWEEP_TURNPEN_A040_20160101`：G10 年化 `22.65%`、Sharpe `0.966`、maxDD `-39.54%`、recovery `704`、成本后年化 `4.34%`。

结论：
- Alpha015 有真实、可解释的 post-2016 信号体，但成本后 Sharpe、最大回撤和 recovery 仍不合格。
- 参数 sweep 的边际收益已经很低。后续不应继续堆 scalar filters；若重开，应转向真正的市场 regime gate 或新的机制变量。
- 当前结论为 `iterate_archive_as_lesson`，不 promotion。

专项沉淀：
- [[知识库/ALPHA015_20160101_RESEARCH_ARCHIVE|Alpha015 2016+ Research Archive]]

## 5. 后续研究要求

每个 Alpha101 或量价因子，至少要回答：

1. 它主要挣 risk premium、information advantage，还是博傻/market-structure harvesting 的钱？
2. 2010-2015 的收益是否显著高于 post-2016？如果是，是否只是老市场红利？
3. 2016-2020 白马/公募主导期是否退化？
4. 2020-2024-09-24 是否贡献主要回撤或最长恢复期？
5. post-2024-09-24 是否重新有效，且这种有效是否依赖主题炒作？
6. long-only 高分组是否在成本后仍能赚钱？不允许用 short leg 或 long-short spread 替代 adoption evidence。

## 6. 修订原则

允许的修订：
- 表达式级 smoothing / persistence confirmation；
- 价量结构的流动性确认项；
- regime-aware 的表达式过滤或权重；
- 分窗口/分市场结构验证。

禁止的修订：
- 通过 short leg 赚钱来解释 promotion；
- 直接把 decile portfolio 当交易规则；
- 用 portfolio expression、rebalance、成本模型或 clean-data mutation 修复因子；
- 只优化全样本指标而不解释收益来源。
