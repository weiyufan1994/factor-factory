# Data SDK 与算子 API：人工调用说明

核对基线：R32 的独立 Data SDK；本次工程继续复用它，不另建数据服务。
本文件里的联网查询是调用示例，本次接口验收只使用离线合成数据。

## 1. 数据读取只有一个入口

```python
from factorforge_data_api import DataApiClient, DataQuery

client = DataApiClient.from_catalog("/absolute/path/data_catalog.json")
print(client.list_datasets())              # 本地目录查询，不取行情
print(client.describe_dataset("clean_daily_bar"))

request = DataQuery(
    dataset="clean_daily_bar",
    start_date="20160104", end_date="20160108",
    universe=["000001.SZ", "600000.SH"],
    fields=["open", "close", "pct_chg", "amount"],
    frequency="daily",
)
result = client.fetch(request)             # 此行才读取数据
if result.status != "ready":
    raise RuntimeError((result.status, result.blocked_reason, result.proxy_rules))
daily_df = result.frame                    # pandas.DataFrame，不是 dict
print(daily_df.head(), daily_df.dtypes)
```

`proxy_ready` 表示显式代理，必须先确认研究是否接受；不是自动认可。
`blocked` 结果不可继续计算。读取存储或日期范围错误也可能直接抛异常，不能只检查 status。
导入包是 `factorforge_data_api`；不要从兼容包 `factor_factory.data_api` 导入 `DataQuery`。

### 构造与请求参数

| 项 | 类型/默认值 | 实际含义 |
|---|---|---|
| `DataApiClient.from_catalog(path)` | 本地目录 JSON 路径 | 可选 `expected_sha256` 检查版本；不需要每因子新审批 |
| `DataApiClient.from_env()` | 无参数 | 先 `FACTORFORGE_DATA_CATALOG`，再已有根目录配置；不猜最新目录 |
| `dataset` | str | `list_datasets()` 中的精确名称 |
| `start_date/end_date` | YYYYMMDD、YYYY-MM-DD、整数 YYYYMMDD 或 Timestamp | 包含两端；SDK 规范为 YYYYMMDD |
| `universe` | `"a_share_all"` 或代码 list/tuple | 不接受任意股票池名称；它是查询筛选，不等于 PIT 成员证明 |
| `fields` | 非空 list[str] | 返回物理列名；别名映射在 `result.resolved_fields`，不自动换单位 |
| `frequency` | `"daily"`；分钟用 `"1min"` | 不会因为写了频率就替你聚合/重采样 |
| `expected_trade_dates` | 可选有序唯一 tuple | 独立交易所日历的请求区间切片；同时给 `calendar_identity` |
| `minute_domain` | 可选 dict | 分钟范围/时区约定；不得用缺失分钟自动代表停牌 |
| `allow_duplicate_keys` | False | 一般保持 False；不能以 True 掩盖重复 |

`adjust`、`include_suspended`、`calendar` 在 DataQuery 中存在，但不能靠这些参数宣称
客户端已经复权、过滤停牌或取得交易所日历。本版读数使用已发布数据集的实际口径；
客户端没有据 `adjust/include_suspended` 实施这种转换。

### 返回值

`DataApiResult` 包括 `frame/query/schema/coverage/source/freshness/warnings/status/blocked_reason`，
以及 `resolved_fields/proxy_rules/delivery_contract/performance_profile`。
`to_metadata()` 返回不含 DataFrame 的元数据。schema 描述目录列，不保证本次投影读取了全部列；
以 `frame.columns` 判断实际输入。

SDK 自动保留键。日表通常为 `ts_code, trade_date`；分钟表加 `trade_time`；派生状态还可能有
`cutoff_time/bucket_id/window_id` 等声明键。不要不看数据集键就按日去重。

`coverage` 包括行数、日期/证券数、实际首尾日期、重复键、缺字段、缺日期及缺证券。
没提供日历时 `missing_dates=None` 表示未知，不是没有缺日期；提供证券列表也不证明每日全成员完整。

### 大数据读取

```python
for day_result in client.iter_days(request, memory_budget_bytes=256 * 1024**2,
                                   workers=1, prefetch_days=1):
    # 一次一日的结果；逐项检查 status。不把所有日期存入 list 再 concat。
    pass

stream = client.iter_batches(request, memory_budget_bytes=256 * 1024**2)
for batch_result in stream:
    pass
print(stream.report)  # 只有完全消费后 complete=True 才是该流的全局覆盖结论
```

`iter_days` 适合完整截面；`iter_batches` 一批可能只是部分截面，不能直接批内 rank 当全市场 rank。
滚动计算的历史重叠/状态由因子实现管理。内存额度不包括 Python/Arrow 的全部运行开销。

## 2. 常用数据集、单位和责任

| 数据集 | 键/用途 | 需要牢记的语义 |
|---|---|---|
| `clean_daily_bar` v2 | 股票×日，价格/量/事件/基本控制 | 价格为同一发布快照的前复权价；不得把它与 raw 限价比较 |
| `daily_event_state_v1` v2 | 股票×日，保留事件行 | `daily_basic_close` 是未复权元价；其他价格列与 clean 同快照 |
| `daily_basic` raw_v1 | 股票×日，市值、估值、换手 | `close` 是原始未复权价，`circ_mv/total_mv` 为万元 |
| `minute_bar` raw_v1 | 股票×日×分钟 | 原始分钟条；不等于逐笔成交，不把日频单位推给分钟字段 |
| `standard_full_market_universe` | 股票×日，`in_universe` | 从成员表选择，不把返回行情股票集合当成员表 |
| `microcap_universe` | 股票×日及股票池信息 | 读后明确选择 `universe_id`；该名字不是 DataQuery 的 universe 参数 |
| `mszq_daily_execution_constraint_v2` | 股票×日，SH/SZ 的 IS 方向性约束 | 边界 20160104–20250711；`pretrade_*_blocked=False` 不是无需限价检查 |
| `fundamental_*_pit_v1` | 以各表声明键和时间字段为准 | 报告期不能替代历史可得时间；基本面因子必须明确 PIT observation map |

日频 clean/event 的换算：`return_decimal=pct_chg/100`；`amount_cny=amount*1000`；
`market_cap_cny=circ_mv*10000`。SDK 别名不会执行这些换算。
`open/high/low/close/pre_close` 的复权口径不得当作实际股份账户的成交价或分红再投资总回报。
日频与分钟字段各查各自数据字典；未有明确单位的分钟字段本手册不代填。

日历复用既有 `trade_cal` 交付，作为独立命名输入 `exchange_calendar`。
R32 的 35 个 SDK catalog 条目中没有名为 `trade_cal` 的数据集或 `get_exchange_calendar()` 方法；
不能把一个不存在的 SDK 方法写成可用接口，也不能用个股有行情的日期冒充交易所日历。
既有 Amihud 的日历交付是 SSE 来源，不自动宣称独立 SZSE/BJ 日历覆盖。

数据组负责发布数据质量/版本及字段定义；研究者只选择字段、做明确换算和正确 join；
回测模块负责执行价格、买卖方向约束、成本和记账。每研究一个因子不重做数据生产验收。

便利函数实际存在：`get_daily_bars(...)`、`get_daily_basic(...)`、`get_minute_bars(...)`、
`get_mszq_daily_execution_constraints(...)`。函数存在不证明对应目录有该数据集；比如
`get_daily_minute_features` 在本版 SDK 中存在，但 R32 目录没有它所需的 `daily_minute_features` 条目。

## 3. 算子可选，标准输出必须一致

```python
from factor_factory.formula import parse_formula, to_qlib_expression
from factor_factory.formula.evaluator import evaluate_formula_frame

ir = parse_formula("mean(close - open, 2)", list(daily_df.columns), raise_on_error=True)
values = evaluate_formula_frame(ir, daily_df)  # ts_code/trade_date/factor_value
print(to_qlib_expression(ir))                 # supported 或 unsupported，不是执行结果
```

`parse_formula()` 返回 dict，不是 Formula 对象。
`evaluate_formula_ir()` 返回 Series；`evaluate_formula_frame()` 返回三列 DataFrame。
`evaluate_formula_frame(..., return_profile=True)` 返回 `(frame, profile)`。
普通路径为 pandas/NumPy optimized；`engine="reference"` 是对照路径。

| 算子/类别 | 语义和边界 |
|---|---|
| `+ - * / abs log sign signedpower` | 逐元素；除零/非法对数不可自动替换为 0，出口检查拒绝 Inf |
| `mean/sum/stddev(x,n)` | 每股票尾随 n 条观测，含当行，min_periods=n；stddev 的 ddof=1 |
| `delay(x,n)` / `delta(x,n)` | 每股票按已排序观测行 lag/diff n；不自动补交易所缺日 |
| `rank(x)` | 同日截面百分比 rank，ties 用 average；不是分位数组别 |
| `ts_rank(x,n)` | 最后一项在尾随 n 项中的百分比平均秩 |
| `correlation/covariance(x,y,n)` | 每股票尾随配对窗口，要求完整窗口；常量相关系数不可计算 |
| `min/max(x,n)` | 时间窗口极值；逐元素极值用 `minimum/maximum` |
| `argmin/argmax(x,n)` | 窗口中首次极值位置，最老为 1、最新为 n |
| `scale(x)` | 同日 x / sum(abs(x))；分母为 0 返回 NaN |
| `cs_regression(y,x,out_type)` | 每日 y~1+x；0 残差、1 拟合值、2 斜率，不是 Fama–MacBeth |
| `where/lt/clip` 等扩展 | 查真实注册项参数与边界，不拼不存在的算子 |

完整目录可以直接在本地检查，不需要 LLM：

```python
from factor_factory.formula.registry import SUPPORTED_OPERATORS, operator_meta
for name, meta in sorted(SUPPORTED_OPERATORS.items()):
    print(name, meta["arity"], meta["category"], meta["supports_pandas"], meta["supports_qlib"])
print(operator_meta("mean"))
```

R32 实际合并注册表有 51 项；应看合并后的表，不能只看 registry 文件顶部的初始字典。
`where` 被扩展表实现，pandas 可用而 Qlib 表达式不支持。Qlib codegen supported 只是可翻译，
不证明已经安装 Microsoft Qlib、provider 可用或外部引擎数值相同。

算子中的 `returns` 若解析到 `pct_chg`，求值层会除以 100；直接写 `pct_chg` 不会。
这与 SDK 别名规则不同，手写代码应把换算写出来，避免两次除以 100。
时间窗口按观测行而非交易所日数，这一限制必须在数学机制需要连续交易日时显式处理。
引用同一实现的 reference parity 不能替代手算独立 oracle。

## 4. 源码与数据字典

- SDK：`factorforge_data_api/query.py`、`client.py`、`contracts.py`、`validation.py`、`streaming.py`。
- 算子：`factor_factory/formula/parser.py`、`evaluator.py`、`registry.py`、`extension_registry.py`、`operators.py`、`qlib_codegen.py`。
- 已有字段字典：`/Users/humphrey/projects/factor-factory-data-api/docs/data-api-data-dictionary.zh-CN.md`，日频单位在第 15 行起；SDK 调用以当前代码为准。
- 本次 class/API 与可直接运行示例见 `docs/research-interface.zh-CN.md`；未实现功能不得靠改文档宣称完成。
