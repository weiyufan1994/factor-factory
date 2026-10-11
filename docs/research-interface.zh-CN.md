# 人工可复现的因子研究接口

接口始于 `factorforge-it-hybrid-integration-20261002`，R36 保持四个公开 SDK 文件不变。以所选 checkout 的实现为准；
源码修改不会自动升级 `current` release。本文例子完全离线。

## 1. 职责只有五段

```text
DataApiClient → 命名 DataFrame → Factor 实例 → 标准 factor values
                                                 ↓
                    明确的标签 / 市场输入 → 分析或账户模块 → 标准 metrics + 明细
```

因子类不负责数据下载、收益标签、成交约束或回测。研究者不需要自己编写 evaluator，
也不需要为 operator/direct/hybrid 分别做一套回测接口。

| 模块 | 可直接调用的入口 | 职责 |
|---|---|---|
| 数据 | `factorforge_data_api.DataApiClient`、`DataQuery` | 返回数据及实际字段/版本/覆盖；[SDK 与算子手册](research-api-data-and-operators.zh-CN.md) |
| 因子 | `BaseFactor`、`PriceVolumeFactor`、`FundamentalFactor`、`FormulaFactor` | 实例参数、命名输入、计算、统一输出 |
| 因子表检查 | `normalize_factor_frame`、`factor_coverage` | 类型/键/有限值/缺行检查，不判断 alpha 好坏 |
| 标签 | `build_forward_returns` | 按独立日历和明确 entry/horizon 对齐价格，不跳过缺行情日 |
| preliminary | `evaluate_factor` | IC、事件收益、Fama–MacBeth；不模拟账户 |
| 账户 | `factor_factory.portfolio_api.backtest` | 公共 self-account 模型或明确的外部 backend；见账户节 |
| 人工展示 | `write_factor_review` | 实际代码、输入、head/tail/date slice、metrics 的离线 HTML，不重新计算指标 |

## 2. 手写因子：一个实例，一个出口

### 显式辅助输入与工作区 Python 模块

因子仍只声明 `input_columns` 并实现 `compute(inputs)`。在现有 prepared daily
输入声明中，使用下列可选字段为任意辅助角色绑定文件；名字不限定为成员表：

```json
{
  "additional_input_paths": {"formation_membership": "source/members_full.parquet"},
  "step3b_additional_input_paths": {"formation_membership": "source/members_sample.parquet"}
}
```

这两个字段与 `daily_df_parquet`、`step3b_daily_df_parquet` 等一起放在同一份
prepared inputs / `local_input_paths` 中。辅助表相对路径与 Python helper 都从 runtime
manifest 的 `factor_workspace` 或显式 `FACTORFORGE_FACTOR_WORKSPACE` 解析；两者同时
提供时必须一致，并与当前运行根一致。没有显式研究工作区的旧布局使用运行根的父目录。
辅助表也接受明确绝对路径。既有 daily/calendar 路径的解析规则保持不变。
Step3A 保留绑定；Step3B 和其 validator 读取明确的样本文件；Step4
读取完整文件。两组角色必须一致。主表、分钟表、独立日历继续使用既有专用字段，
不得在辅助 map 中重名。文件支持 Parquet/CSV，不自动下载、合并、推断成员或填零。
样本受既有行数预算约束；含 `trade_date` 的辅助表必须在相应声明窗口内。

普通工作区模块可直接导入，例如：

```python
from implementation.local_math import calculate  # workspace/implementation/local_math.py
```

框架在实际 generated module 装载和调用期间承载 workspace，不依赖开发 shell 的
`PYTHONPATH`；允许函数内普通 lazy import。结束或异常后恢复 `sys.path` 和同名模块缓存，
不同研究的 `implementation` 不互相替代。无需研究者写 loader 或 wrapper。
该机制服务单进程中的单次因子调用，不是代码安全沙箱。通过静态普通 import 引用的本地
Python 包和显式辅助文件内容进入已有计算缓存身份，变更后重新计算；未声明的动态加载
不在该约定内。已有无辅助输入、无本地 helper 的路径保留原来的缓存行为。

此绑定支持普通 DataFrame 执行路径。分钟流式和 partitioned controller 有自己的输入
契约，本补丁不自动扩展它们；在这些路径声明辅助 map 会明确报不支持，不能静默丢弃。
这也不等于 Step3A 已能从 Data API 自动生产任意角色的数据，或已证明该角色的 PIT 含义。

完整实现：[factor_definitions.py](../examples/manual_interface_replay/factor_definitions.py)。
该文件包含量价、hybrid、基本面类和注释；量价例子并非新 alpha，只检查计算能力。

```python
from factor_factory.factors import PriceVolumeFactor

class MyFactor(PriceVolumeFactor):
    name = "my_factor"
    input_columns = {"daily_df": ("ts_code", "trade_date", "open", "close")}

    def compute(self, inputs):
        df = inputs["daily_df"]
        # 同日盘后才能形成的价格差，单位元；不能用于当日开盘交易。
        return df[["ts_code", "trade_date"]].copy().assign(
            factor_value=df["close"] - df["open"]
        )

FACTOR = MyFactor()
factor_values = FACTOR({"daily_df": daily_df})
```

若有窗口等参数，在 `__init__` 检查后 `super().__init__(window=window)`，
通过 `self.parameters["window"]` 使用。参数字典按实例保存、顶层只读；若参数含嵌套可变对象，
作者仍需明确复制/固定，不能把这个接口当作深度不可变或安全沙箱。
`compute(inputs)` 返回计算结果；外部调用 `run(inputs)` 或 `instance(inputs)` 才是检查过的公共出口。
框架执行模块导出的 `FACTOR`，旧 `compute_factor` 函数仅兼容，异常不会触发换签名重试。
新 operator codegen 也导出实例，旧函数只是一次通用长表转换。

`FundamentalFactor` 出口相同，输入角色可以叫 `fundamentals`；必须先解决 PIT 可得时间、
TTM/单季定义和单位，不以报告期当交易日。父类不凭空完成这些经济语义。

### 标准因子表

```text
                       factor_value
datetime   instrument
2020-01-03 000001.SZ              2.0
           000002.SZ              4.0
           600000.SH              6.0
```

- `pandas.DataFrame`，MultiIndex 精确命名且顺序为 `datetime, instrument`。
- 日频 `datetime` 为无时区的午夜 session date；此版不是盘中时间戳因子接口。
- `instrument` 是非空证券标识，保留原值，不偷偷将 `000001.SZ` 改成 `SZ000001`。
  外部 Qlib provider 如采用另一标识，映射属于它的统一适配器。
- 唯一值列 `factor_value` 为 float64；按索引排序，键唯一；NaN 可表达 warmup/无定义。
- 公共入口也接受精确三列 `ts_code/trade_date/factor_value`，一次转换。
  已有阶段长表如附带诊断列可在兼容存储保留，但分析器必须显式选因子列。
- 一个实例输出一个标量因子。多个因子是多个实例/表；不能让最后一个数值列自动成为 signal。

Parquet 保留该 MultiIndex；CSV 重载需要显式恢复索引，不能假设普通 CSV 自带它：

```python
import pandas as pd
factor_values = pd.read_csv("factor_values.csv", parse_dates=["datetime"],
                            dtype={"instrument": str}).set_index(["datetime", "instrument"])
```

## 3. Preliminary analysis 的实际调用

```python
from factor_factory.research_api import build_forward_returns, evaluate_factor

# prices 只有 keys + close；prices/calendar 与形成信号所用输入分开。
# 盘后 t 形成，t+1 close 入、t+2 close 出：
labels = build_forward_returns(prices, calendar=exchange_dates,
                               entry_offset=1, horizon=1)

ic = evaluate_factor(factor_values, labels, analysis="ic", expected_index=membership_index)
events = evaluate_factor(event_factor_values, labels, analysis="event_study")
fmb = evaluate_factor(factor_values, labels, analysis="fama_macbeth",
                      controls=controls, newey_west_lags=5)
```

`forward_returns` 是同索引的单列 `forward_return`，单位小数：1%=0.01。
`controls` 是同索引的数值控制列；无控制时省略。参数和输入本身必须合法，错误直接抛出，
不能解释为研究结果为 0。

`build_forward_returns` 的定义为
`close[t+entry_offset+horizon] / close[t+entry_offset] - 1`。
两个端点按给定交易所日历精确寻找，缺任一价格则 NaN，不移到该股票下一个有行情日。
它不保证可成交，不处理复权，不把多个重叠持有期标签连乘为账户 NAV。
也可交外部标签，但结果会如实注明其 timing 是调用方提供、未由该函数证明。

### 稳定的 metrics 形状

```json
{"value": 0.5, "unit": "correlation", "n": 4, "reason": null}
```

公共结果的 `metrics` 是上述对象的命名字典，版本为 `api_version=factorforge_research_api_v1`，另外有 `analysis/status/evaluation_scope/`
`account_simulation/periods/coverage/warnings`。只要统计定义没变，同名指标单位不变。
不可计算时 `value=null` 且 `reason` 有值；JSON 不允许 NaN 或 Infinity。

| analysis | 稳定名称 | 定义 |
|---|---|---|
| IC | `rank_ic_mean/std/ir`、`pearson_ic_mean/std/ir` | 每日横截面相关，跨有效日期等权；std ddof=1；IR=mean/std，不年化 |
| event_study | `event_return_mean/std/ir` | 所有非缺失事件的标签收益，按事件等权；是描述统计，不是 Sharpe |
| event_study | `date_mean_return_mean/std/ir` | 先每日事件等权，再跨日期等权；不推断重叠事件独立 |
| Fama–MacBeth | `lambda_mean/standard_error/tstat/pvalue_normal` | 每期带截距 OLS 的因子系数，再跨期等权；控制变量不自动标准化 |

事件研究不以 factor 值的大小/正负选择或加权事件；调用方须交明确选择的事件表。
当前是指定持有期的事件收益统计，不是已实现任意 [-k,+k] 事件窗、基准异常收益 CAR 或聚类推断。

FMB 推断用 Bartlett Newey–West，协方差分母 T；p 值为双侧渐近正态近似，
不是小样本 Student t。输出包含请求/effective lags。秩不足或样本不足的截面单独报告；
无效期间不被压缩后冒充连续 HAC 系数序列。它不自动证明经济机制或风险溢价。
理论恒定系数若只在浮点精度内波动，t/SE 返回 null 与
`zero_variation_at_float_precision`，不把舍入误差解释为显著性；判断基于系数相对尺度。

### 普通 IS 的双边 partial Rank IC

```python
partial = evaluate_factor(
    factor_values, labels, analysis="partial_rank_ic", controls=controls,
    expected_index=membership_index, min_observations=100,
)
```

每期先取信号、收益和全部声明控制列的完整样本 H，再计算 U=midrank(signal)、
V=midrank(return)，Z=[截距, 原控制变量]，结果为 Corr(M_Z U, M_Z V)。
并列取平均秩；控制变量不排名，残差不再排名。控制列居中和按列归一化仅用于数值
稳定，保持 [1,C] 的列空间；不删除控制列，不用 ridge 或秩亏伪逆改写问题。
这不同于仅对信号残差化后的 Rank IC，也不同于 rank(signal) 对原始 return 的偏相关。

`min_observations` 只用于此分析，默认 100；不足、设计矩阵秩亏、任一残差方差为零
均保留该期并返回 null 与 reason。数值秩和零残差判定的相对容差为
float64 epsilon × max(完整样本数, 设计列数)，方法元数据记录具体约定。
`expected_index` 可保留整期没有信号的日期，因而不能通过缺行压缩评估日历。

结果含 `partial_rank_ic_mean/std/ir`，以及 H 上的 `same_support_rank_ic_*` 和
`same_support_pearson_ic_*`；逐期记录输入数、完整样本数、剔除数和设计秩。
均值/标准差/IR 为有效期间的描述统计，不年化；此入口不计算 HAC 或显著性，
`newey_west_lags` 仍仅用于 FMB。后续时序推断必须保留缺月位置，不能删掉无效月份
后称为连续序列。该分析无账户、OOS 释放或正式证明写入，与正式 verifier 保持独立。

形成频率、标签 horizon、账户调仓频率是三件事，配置要分别说明。预先声明的 warmup
不进入估计窗口，但保留在全因子表中；不得看完结果再裁掉不好的月份。

## 4. 因子表到底检查什么

| 层 | 检查内容 | 不能证明什么 |
|---|---|---|
| 结构 | DataFrame、精确列/索引名、日期可解析且非空、证券非空、键唯一 | 经济含义与历史可得性 |
| 数值 | 实数 dtype，拒绝字符串/bool/complex/Inf；保留 NaN 与真实0 | 值虽有限，不代表公式正确 |
| 覆盖 | observed 与独立 expected keys 分开；缺行/NaN/意外行分别计数 | 没给分母时不能称完整全市场 |
| 时间 | 独立日历端点，不跨缺行情日；前缀/未来扰动等实现测试 | DataFrame 本身不能证明任意 Python 无未来信息 |
| 数学实现 | 独立手算、特定边界、不同实现路线同值 | 两个调用共用一个错误函数仍会 parity PASS |
| 分析器 | 手算 IC/FMB，常量和样本不足返回不可计算，费用/现金逐笔核对 | 不能只凭最终收益相近证明路径正确 |

`completeness_verified` 只表示 expected keys 无缺失/多余；还必须看有效值比例。
例如预期36行却只返回30行，observed ratio 可以是100%，expected ratio只能是83.33%。
常量、零很多、IC差不自动判“代码错误”；先解释模型定义，再区分数据/实现/经济假设。

## 5. 无需 AI 的独立重跑

这台 Mac 可直接使用已有依赖环境，不安装、不联网：

```bash
FF_INTERFACE_CHECKOUT=/Users/humphrey/projects/factorforge-it-hybrid-integration-20261002
FF_BASE_RUNTIME=/Users/humphrey/projects/factorforge-local-runtime/releases/20261002-hybrid-integration-r32
PYTHONDONTWRITEBYTECODE=1 \
PYTHONPATH="$FF_INTERFACE_CHECKOUT:$FF_BASE_RUNTIME/factorforge-data-api" \
"$FF_BASE_RUNTIME/.venv/bin/python" \
"$FF_INTERFACE_CHECKOUT/examples/manual_interface_replay/run_demo.py" \
--output-dir /tmp/factorforge-manual-replay
```

可移植的依赖是 Python、pandas、NumPy、SciPy、PyArrow、独立 Data SDK 和本仓源码。
不需要 Codex、LLM、Host 身份、网络数据或研究工作区。

独立输入/期望在 `examples/manual_interface_replay/`：

- `daily.csv`：5日×3股票的合成输入；手写 `expected_factor_values.csv`，不由被测实现生成。
- 1月3日因子：`(1+3)/2=2`、`(3+5)/2=4`、`(5+7)/2=6`。
- 标签另列在 `forward_returns.csv`；预先指定分析窗口1月3日至8日。
- IC 路径 `1,-1,1,1`，均值0.5，样本标准差1，未年化 IR=0.5。
- FMB 系数 `.005,-.005,.005,.005`，均值 `.0025`；L=0 时
  `SE=sqrt(sum((lambda-.0025)^2)/16)=.002165063509`，t≈1.154700538。
- 12个事件的收益均值2%；每日均值恒定，其 IR 不可计算，应返回 null/zero_variance。

输出 `human_review.html` 展示带行号注释代码和样本，`factor_values.parquet/csv`
是完整标准表，`metrics.json` 是实际计算的三类结果。不能以这些合成数字声称实盘效果。

## 6. 账户模型与发布状态

原有月历账户使用 `portfolio_api.backtest_calendar_month`，接收已经按下一交易日
标记的因子输出、完整形成日 PIT 成分和明确价格/执行约束，沿用已验收的账户内核。
共享 Step4 adapter 直接消费本次因子输出并生成日账本、月度标签诊断及标准 metrics。
输入、时间关系、费用和审后维护版本接入方式见 [月历账户接口](calendar-month-account.md)。
这项维护扩展不属于既有 R35p4；固定 R35p4 的研究应显式记录所用维护包和范围。

```python
from factor_factory.portfolio_api import backtest

result = backtest(
    factor_values, calendar=exchange_dates, prices=prices, constraints=constraints,
    formation_dates=rebalance_dates, entry_offset=1, holding_period=1,
    top_k=1, initial_cash=1010.0, one_way_cost=0.01,
    annualization=252, backend="self_account",
)
```

`prices` 为同索引的 `execution_price, mark_price`（同货币/价格基准，正数或明确 NaN）；
`constraints` 为同索引的 `can_buy, can_sell, is_suspended`（真正 bool，不能传字符串或 Unknown）。
它们分别来自数据服务、统一状态处理和已经选择的执行价格规则；不能直接把 raw 涨跌停价
与前复权价比较，不能把 `pretrade_*_blocked=False` 直接当作最终 `can_buy=True`。
本入口不重新下载或清洗这些输入。

支持模型为 fractional-share long-only：形成日按因子降序选 top_k，边界同值全部保留；
entry_offset 至少1个交易日；持有期从入场日计。先卖后买，卖不出逐交易日再检查，
买不进留现金且不补买/不将失败份额分给别的股票。每批按当时现金等额预算，含买入费用。
月末形成等日程直接通过 `formation_dates` 给出；本版 `holding_period` 是固定交易日数，
不冒充已经实现任意“下个月月末退出”策略。

已持仓且明确停牌、缺估值时沿用 last mark，并标明该日估值来源；不明缺价抛错。
没有真实手数、冲击容量、滑点、公司行为、退市结算、借券或分红再投资，不能称100%实盘。
给复权价只能解释为同基准虚拟单位账户，不可与原始股份账户混用。

结果中 `daily` 有 cash、market_value、equity（金额）、nav（initial_cash归一）、daily_return；
`positions` 有股数/估值来源；`trades` 有成交/未成交、方向、金额、费用和现金流。
metrics 包括 `final_equity/final_nav/final_cash/total_return/annualized_return/`
`annualized_volatility/sharpe/max_drawdown/fees_paid/gross_traded_amount`。
年化基于返回的完整 calendar session 数，包含现金空仓日；volatility 用 ddof=1；
Sharpe 无风险利率为0；max_drawdown 是含初始现金基准的负数回撤。
这些定义是账户路径指标，不是用重叠标签连乘的“伪净值”。

运行 [run_account_demo.py](../examples/manual_interface_replay/run_account_demo.py)，
使用上节相同解释器、同一个 `--output-dir` 即可。预先手算路径：

| 日期 | 事件 | 现金 | 股数 | 估值 | equity |
|---|---|---:|---:|---:|---:|
| 2020-01-02 | 形成信号 | 1010 | 0 | — | 1010 |
| 2020-01-03 | 10元买100单位，买费10 | 0 | 100 | 10 | 1000 |
| 2020-01-06 | 到期但停牌，未成交 | 0 | 100 | last mark 10 | 1000 |
| 2020-01-07 | 12元卖出，卖费12 | 1188 | 0 | — | 1188 |

总费22，净收益 `1188/1010-1 = 17.623762%`。这只是四日合成 oracle，不能外推年化业绩。
另一个变体在1月3日禁止买入，四日现金都应为1010且没有任何成交。

Microsoft Qlib 在已核对的 R32 venv 中不可用；未把错误同名包或导入失败叫成功。
`backend="qlib"` 明确返回 unsupported，当前不偷偷降级到自研或分组均值。
当前研究 release 与原研究 pin 不因本手册改变。先完成源代码与离线验证，再明确说明
部署/发布情况，不能把“新文件可运行”说成“所有历史调用链已升级”。

## 结果文件、目录与交接

沿用现有 `FactorForgeContext` 和 workspace manifest；以下是位置说明，
不要求旧 workspace 补建 `source/implementation` 等目录，也不迁移历史文件：

```text
<明确的研究 workspace>/
  source/、implementation/       已声明的来源、实现及辅助代码（位置以 manifest 为准）
  step3_runtime/                 run_step3/run_step3b 的运行副本及 meta
  runs/<report_id>/              因子值、运行元数据和检查点
    step3a_local_inputs/         准备后的日表；其他辅助输入按 manifest 显式引用
  evaluations/<report_id>/<backend>/
    evaluation_payload.json     指标、状态、身份和明确的文件引用
    account/、diagnostics/       本 backend 生成的具体结果文件
  reports/                      面向研究员的报告
```

输入和实现仍通过现有 manifest/resolver 定位，因子输出仍用
`context.factor_values_path()`、`context.run_metadata_path()`。
backend 用 `factor_factory.result_artifacts.prepare_result_paths(context, report_id,
backend, files=..., directories=...)` 分配输出路径并创建父目录；它不移动或覆盖文件。
相对文件名以该 backend 输出目录为基准，绝对路径必须仍在该目录内。

写完具体文件后，以 `build_result_artifacts()` 构造引用，用 `write_result_payload()`
校验并原子写入 payload。`artifacts` 是“角色 → 具体文件路径”，可选文件不可用时显式填
`null`；`artifact_directories` 只记录目录位置。月度结果须逐项列出文件，不自动遍历目录，
不能用一个目录代替文件清单。Step4 保存、原生校验、Step5 和续接记录使用同一规则。
通用读写函数的相对路径都相对于显式绝对 `base_dir`，不使用当前工作目录猜测。

可运行 [run_result_artifact_demo.py](../examples/manual_interface_replay/run_result_artifact_demo.py)：

```bash
python examples/manual_interface_replay/run_result_artifact_demo.py --output-dir '/tmp/结果文件 示例 workspace'
```

示例要求新的绝对目录，产生两个合成文件和 `evaluation_payload.json`。
它只展示文件接口，不证明回测、指标完备性或研究结论。已有文件型 payload 保持兼容；
目录误写进 `artifacts` 会明确报错。历史失败的受限引用修复见
[本地代码评审续接](../skills/factor-forge-ultimate/references/local-code-review.md)，
保留原 payload 字节和失败记录，不改数值、不重算，修复后仍须原生校验。

发布归档不依赖 `.git` 或启动目录识别版本。打包时，在刚解出的 `git archive`
源码根目录调用 `write_source_archive_version(root, commit, source_files)`；三个参数分别是
绝对源码根、归档的精确 commit 和该归档明确的文件成员列表。它只创建一次
`factorforge_source_version.json`。`current_source_commit(root)` 校验清单内文件后返回包版本；
源码 checkout 则只读自己的 Git 根，未标记的归档保持 `unknown`，不借用父目录版本。
这只是构建来源信息，不改变 Host 准入、数据口径或研究结论。
