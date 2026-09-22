# Factor Forge 算子、回测系统与 QuantZone 手册对照

日期：2026-09-20。代码基线：`factor-factory-knowledge-reuse-20260907` 当前工作树；分支 `codex/knowledge-reuse-20260907`，HEAD `525d4656`。工作树包含既有未提交改动，不能仅用 HEAD 复现当前代码。

本文保留算子补充前的盘点快照。用户随后授权借鉴补充，新增能力及当前状态见 [通用算子补充 v1](factorforge-operator-extensions-v1.zh-CN.md)。

外部来源：`/Users/humphrey/Downloads/quantzone-因子计算引擎手册.md`，描述 `quantzone>=0.10.0`。本次完整阅读手册、核对本地实现，并执行小型合成输入探针。QuantZone 一侧是手册声明及按其定义计算的预期，没有运行其 SDK，因此不构成两套软件的逐算子一致性验收。

## 1. 我们已有的算子与实现语言

统一表达式注册表为 `factor_factory/formula/registry.py`：35 个规范条目，34 个声明支持 pandas，18 个声明支持 qlib。别名不重复计数；`where` 虽已登记但声明不支持执行，本次实际调用也失败。这里统计的是统一表达式接口，不包括所有研究实例里的 Python 函数。

| 类别 | 数量 | 规范名称 |
| --- | ---: | --- |
| 截面 | 4 | `rank`、`scale`、`cs_zscore`、`cs_regression` |
| 基础时序 | 12 | `ts_rank`、`correlation`、`covariance`、`sum`、`mean`、`stddev`、`delta`、`delay`、`min`、`max`、`argmin`、`argmax` |
| 分布及嵌套窗口 | 8 | `rolling_excess_kurtosis`、`rolling_pearson_kurtosis`、`rolling_topk_skew`、`rolling_bottomk_skew`、`rolling_max_inner_skew`、`rolling_min_inner_skew`、`rolling_max_subwindow_sum`、`rolling_topk_sum` |
| 元素运算 | 10 | `abs`、`log`、`sign`、`signedpower`、`signed_log1p`、`plus`、`minus`、`multiply`、`divide`、`negate` |
| 已登记但不可执行 | 1 | `where` |

项目自写部分是 Python，参考计算与默认执行依赖 pandas / NumPy。已有部分 NumPy 时序加速内核；Polars、Numba 等扩展路径属于显式选择或实验能力，不能概括为已经全部替代 pandas。该算子目录没有项目自写的 C++/Rust 源文件；底层依赖库可以包含编译实现。

主要实现位置：`operators.py`、`fast_rolling.py`、`kernels.py`；公式编译和求值在 `parser.py`、`evaluator.py`；生成代码、一致性检查和 Qlib 转换在 `pandas_codegen.py`、`parity.py`、`qlib_codegen.py`。

## 2. 现在的回测系统

正式研究入口是 `scripts/run_factorforge_ultimate.py`，Step4 的 `run_step4.py` 负责因子正式计算和后端调度。代码默认评估计划列出 `self_quant_analyzer:quick` 与 `qlib_backtest:default`，研究可以显式指定自己的评估计划。

| 路径 | 实际实现 | 当前作用与边界 |
| --- | --- | --- |
| 自研快速因子评估 | `skills/factor-forge-step4/scripts/self_quant_adapter.py`；Python / pandas / NumPy | IC、Rank IC、分组收益/净值、长端、换手估计、成本、回撤等。长端采用组内平均收益和成员变动推算换手；默认成本系数 0.003。它没有逐笔现金/持仓撮合账本 |
| Microsoft Qlib 适配 | `qlib_backtest_adapter.py` 调用 `TopkDropoutStrategy`、`SimulatorExecutor`、`backtest(...)` | 现有原生路线明确是 `native_minimal`；代码设置 topk=50、n_drop=5、日频、close 成交价。需要正确的 Microsoft Qlib 环境和 provider；资源跳过或原生失败可能只剩诊断 payload，不能称为原生回测成功 |
| 研究专用现金/持仓执行 | `pfvv_monthly_step4_backend_v1.py` → `pfvv_monthly_evaluation_v1.py` → 显式加载的 `mszq_step4_portfolio_evaluator_candidate_v1` | 月度适配器调用自研账户模拟，处理现金、持仓、交易约束和成本；该接入限定 local IS，不是所有研究默认使用的全局统一引擎 |

实际运行记录核实：

- PF/VV：`factor_research/mszq_pfvv_source_baseline/mszq_pfvv_source_first_is_20260908/objects/factor_run_master/factor_run_master__RPT_pdf_11d72_pfvv_20250508_mszq.json` 声明主后端 `pfvv_monthly_cash_v1`，对应 payload 标为 `success`。其合同为月末形成、下个交易日 09:45–10:00 VWAP 入场、下月调仓窗口退出、单边 30bp。
- Signed-A：`factor_research/mszq_signed_a_response/mszq_signed_a_ultimate_loop01_is_20260909/objects/factor_run_master/factor_run_master__RPT_pdf_11d72_pfvv_20250508_mszq__LOOP01__SIGNED_A_RESPONSE.json` 同样声明该主后端，通过账户证据回放适配器接入。
- 上述是具体运行的后端来源核对，不把 payload 的 success 等同于整个 Ultimate 或正式 OOS 通过。

本次默认 Python 的模块搜索未发现 `qlib`；适配器还支持其他环境/源码位置。这不能用于断言研究机未安装 Qlib。本次没有启动或更改研究机。

## 3. 与 QuantZone 对应的现有框架

双方都有“表达式 → 受限解析 → 算子执行 → 因子值”的能力。Factor Forge 对应的是 Formula-IR 引擎，并已有代码生成、参考一致性、数据字段映射与研究身份绑定。

| 方面 | QuantZone 手册 | Factor Forge 当前代码 |
| --- | --- | --- |
| 输入结构 | 每个特征一张日期×股票宽表，叶子可以有独立网格 | 同一个 `ts_code`、`trade_date` 长表中的字段 |
| 对齐 | 单叶子原网格滚动，二元操作才做指定 union | 统一长表上按证券/日期计算；迁移时必须核对缺口日历和字段对齐 |
| 表达式语法 | 算术、比较、布尔、条件选择 | 算术及已登记函数；当前不支持比较/布尔 AST，`where` 不可执行 |
| 重复子表达式 | 单表达式 CSE；批量不自动跨表达式 CSE | optimized evaluator 有表达式内缓存；不是证明跨因子共享计算已经实现 |
| 批量入口 | 有 `compute_daily_factors(exprs, features)` | 当前直接对应接口是单公式 `parse_formula` / `evaluate_formula_frame`；Step3–4 再编排执行 |
| 文档组织 | 使用者手册集中描述签名、NaN、并列值、预热、异常 | 注册表、语义模块、实现、技能与性能文档分布在不同位置 |

## 4. 手册函数逐项对应

手册第 7 节列出 49 个函数名，包含 `minimum` / `maximum` 等别名；这与我们的 35 个规范条目不是同一计数口径。按名字或现有别名机械匹配有 19 项，其中 `where` 不可执行，`min/max` 意义冲突，其余也可能有默认参数或统计定义差异。因此 19 不是“已兼容数量”。

下表“接近”仅表示所述输入条件下的功能接近；“缺少”指未接入统一表达式注册表，不代表无法用 direct_code 开发。

| QuantZone 名称 | 我们的对应 | 对照结果 |
| --- | --- | --- |
| `delay` | `delay`，别名 `lag/ref` | n≥1 时功能接近；我们要求显式 n，拒绝 n=0；对方默认 n=1，允许 n=0 |
| `delta` | `delta` | 同上；默认参数和 n=0 不兼容 |
| `ts_mean` | `mean` / `ts_mean` | 对方半窗起算；我们需完整窗口有效值 |
| `ts_sum` | `sum` / `ts_sum` | 同类求和，但预热及缺失门槛不同 |
| `ts_max` | `max` | 我们没有 `ts_max` 别名；预热及缺失门槛也不同 |
| `ts_min` | `min` | 我们没有 `ts_min` 别名；预热及缺失门槛也不同 |
| `ts_std` | `stddev` / `ts_std` | 都是样本标准差；预热及缺失门槛不同 |
| `ts_ffill` | 无 | 缺少受限前向填充算子 |
| `ts_mean_wq` | `mean` | 都需 n 行预热，但对方可接受窗口内部分缺失，不能直接等同 |
| `ts_sum_wq` | `sum` | 同上 |
| `ts_min_wq` | `min` | 对方完整时间窗内有至少一个有限值即可；我们需完整有效窗口 |
| `ts_max_wq` | `max` | 同上 |
| `stddev` | `stddev` | 对方总体标准差 ddof=0；我们样本标准差 ddof=1；缺失规则也不同 |
| `ts_rank` | `ts_rank` | 对方平均秩/(m+1)，允许部分缺失；我们完整窗口平均秩/n |
| `ts_argmax` | `argmax` | 对方位置 0..n-1；我们位置 1..n；缺失规则不同，别名也未接入 |
| `ts_argmin` | `argmin` | 同上 |
| `decay_linear` | 无 | 缺少标准线性加权衰减算子 |
| `ts_product` | 无 | 缺少标准滚动连乘算子 |
| `correlation` | `correlation` / `corr` | 完整有效窗口的 Pearson 功能接近；对方允许部分有效配对且网格对齐不同 |
| `covariance` | `covariance` / `cov` | 对方总体协方差；我们样本协方差；缺失/对齐也不同 |
| `rank` | `rank` | 相同截面上均为 average 百分位；NaN 排除、Inf 参加 |
| `cs_rank` | 无同名入口 | 对方仅有限值、秩/(n+1)、不足 8 只全缺失；不能替换成我们的 `rank` |
| `cs_demean` | 无专门入口 | 单变量回归提供相关基础，但不是这一标准调用 |
| `cs_zscore` | `cs_zscore(x, ddof)` | 我们需显式 ddof；对方固定 ddof=1，调用形式不同 |
| `cs_winsor` | 无 | 缺少截面分位裁剪注册算子 |
| `cs_madwinsor` | 无 | 缺少截面 MAD 裁剪注册算子 |
| `cs_stdwinsor` | 无 | 缺少截面标准差裁剪注册算子 |
| `cs_fillmean` | 无 | 缺少截面均值填充注册算子 |
| `cs_rank_group` | 无 | 缺少按行业/组排名注册算子 |
| `scale` | `scale` | 行/截面按绝对值和缩放功能接近，零分母为缺失 |
| `indneutralize` | 无 | 缺少行业去均值标准接口 |
| `ind_fillmean` | 无 | 缺少行业均值填充标准接口 |
| `ind_winsor` | 无 | 缺少行业分位裁剪标准接口 |
| `ind_madwinsor` | 无 | 缺少行业 MAD 裁剪标准接口 |
| `ind_stdwinsor` | 无 | 缺少行业标准差裁剪标准接口 |
| `styleneutralize` | `cs_regression(y,x,0)` 只提供单风格相关基础 | 我们现有回归是带截距单解释变量；对方支持 1–16 风格，样本下限不同 |
| `jointneutralize` | 无 | 缺少行业与多个风格联合中性化标准接口 |
| `abs` | `abs` | 元素定义相同 |
| `sign` | `sign` | 元素定义相同 |
| `log` | `log` | 对方 x≤0 为 NaN；我们直接 np.log，x=0 产生 -Inf |
| `sqrt` | 无 | 可开发；现有 signedpower(x,0.5) 对负数保留负号，不是等价替代 |
| `clip` | 无 | 可开发；当前无标准注册接口 |
| `signedpower` | `signedpower` / `signed_power` | 符号幂定义相同；需要分别核对参数面板的对齐 |
| `where` | 已登记但不支持 | 比较语法不能解析；用数值条件绕过解析后执行仍报不支持 |
| `min` | 当前同名是滚动最小值 | 严重名称冲突，对方为逐元素最小值 |
| `minimum` | 无 | 缺少逐元素最小值标准入口 |
| `max` | 当前同名是滚动最大值 | 严重名称冲突，对方为逐元素最大值 |
| `maximum` | 无 | 缺少逐元素最大值标准入口 |
| `lt` | 无 | 缺少比较算子；当前比较 AST 也不支持 |

我们还拥有这份手册未列出的已注册能力：`cs_regression` 的残差/拟合值/斜率输出、`signed_log1p`、两类峰度、四类极值子样本/嵌套窗口偏度，以及 `rolling_max_subwindow_sum`、`rolling_topk_sum`。手册未列出不等于对方其他产品完全没有这些能力。

## 5. 已执行的语义探针

用单只股票四日 `close=[1,2,3,4]`、`open=[2,4,6,8]` 通过本地 `parse_formula` 和 optimized `evaluate_formula_frame` 执行。对方一栏仅按手册定义计算。

| 表达式/问题 | Factor Forge 实测 | QuantZone 手册预期 |
| --- | --- | --- |
| `ts_mean(close,4)` | `[NaN, NaN, NaN, 2.5]` | `[NaN, 1.5, 2.0, 2.5]` |
| `stddev(close,4)` 最后一天 | 1.2909944487 | 1.1180339887 |
| `covariance(close,open,4)` 最后一天 | 3.3333333333 | 2.5 |
| `ts_rank(close,4)` 最后一天 | 1.0 | 0.8 |
| 最大值位置 | `argmax(close,4)=4` | `ts_argmax(close,4)=3` |
| `min(close,4)` | `[NaN, NaN, NaN, 1]`，滚动 | `[1,2,3,4]`，逐元素 |
| `delay(close)` | 参数数量错误 | 默认 n=1 |
| `delay(close,0)` | 拒绝非正窗口 | 返回原值拷贝 |
| `ts_min(close,4)` / `cs_rank(close)` / `sqrt(close)` | 不支持的名称 | 手册提供该入口 |
| `cs_zscore(close)` | 缺少第二参数 | 手册提供单参数入口 |
| `where(close>2,close,0)` | 比较语法解析失败 | 手册支持 |
| `where(close,1,0)` | 解析成功，但执行拒绝 `where` | 不能据本地注册项存在认定已支持 |

另以 `close=[-2,0,1,4]` 测得：

- `close**2` 为 `[-4,0,1,16]`，因为本地解析器把 `**` 映射成 `signedpower`。对方手册把 `**` 列为 Python 风格算术；常规幂语义下首项应为 +4，迁移时必须特别验证。
- `log(close)` 为 `[NaN,-Inf,0,log(4)]`；对方手册规定第二项也是 NaN。

这些探针只用于工程比较，没有读取市场行情、运行研究回测或改变任何算子实现。

## 6. 借鉴顺序

1. 首先集中发布自己的算子使用手册：区分内部 Python 函数、表达式白名单、可执行状态及 Qlib 桥接状态；每项写清签名、单位/网格、预热、NaN/Inf、并列值和示例。
2. 优先完善比较与条件选择、逐元素 min/max、clip，以及截面/行业去极值和中性化的标准接口。这些是可组合因子表达式的明显缺口。
3. 补充 decay_linear、ts_product、受限前向填充等通用时间序列能力，并定义其信息可用时间和数值语义。
4. 若支持 QuantZone 表达式，使用明确的方言/语义版本及适配测试；不要直接改掉当前 `min/max`、`stddev`、`ts_rank` 或 `**` 含义，否则会改变既有因子。
5. 速度需要同数据、同语义、同硬件的测量。手册的接口丰富度不能证明其执行内核比现有引擎更快。
