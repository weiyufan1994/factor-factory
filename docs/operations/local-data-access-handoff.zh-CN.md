# Bernard / Humphrey 数据访问层交接说明

## 目标

这份说明只解决一个问题：

> Bernard（Mac）和 Humphrey（EC2）以后应该怎么读取日频数据，才能和 FactorFactory 的 Step3 / Step4 保持同一口径。

当前结论是：

- 不要再在各自脚本里直接到处 `pd.read_csv(...)` 猜路径。
- 统一通过 `factor_factory.data_access` 访问本地日频数据。
- qlib 相关需求也先走这层，再转成 qlib-friendly frame。

## 当前设计

我们现在把数据访问拆成 3 层：

1. 原始存储层
- `~/.qlib/raw_tushare/行情数据/daily.csv`
- `~/.qlib/raw_tushare/行情数据/daily_basic_incremental/trade_date=YYYYMMDD/*.csv`
- `~/.qlib/raw_tushare/基础数据/trade_cal.csv`

2. 统一访问层
- `get_daily(...)`
- `get_daily_basic(...)`
- `get_trade_calendar(...)`
- `summarize_local_tushare_paths()`

3. qlib 轻适配层
- `to_qlib_signal_frame(...)`
- `daily_to_qlib_features(...)`
- `daily_basic_to_qlib_features(...)`

额外地，Step4 公共输入逻辑也已经抽出：

- `load_factor_values(...)`
- `load_daily_snapshot(...)`
- `normalize_trade_date_series(...)`
- `build_forward_return_frame(...)`

## 为什么这样分层

原因很简单：

- Bernard、Humphrey、Codex 运行环境不同。
- 本地路径不同，但访问契约应该相同。
- Step4 / Step5 不能因为 qlib 接入而被强制重写。

所以当前策略是：

- 访问层返回 normalized research DataFrame
- qlib 需求再额外转换成 qlib-friendly frame
- 不直接把整套研究层强绑到 qlib provider/store

## Bernard / Humphrey 以后应该怎么写

### Bernard（Mac）

优先写法：

```python
from factor_factory.data_access import get_daily, get_trade_calendar

daily = get_daily(
    start='20260401',
    end='20260415',
    columns=['ts_code', 'trade_date', 'open', 'high', 'low', 'close', 'vol', 'amount'],
)

calendar = get_trade_calendar(
    start='20260401',
    end='20260415',
    open_only=True,
    columns=['cal_date'],
)
```

如果 Bernard 要做 qlib 风格回测输入：

```python
from factor_factory.data_access import get_daily, daily_to_qlib_features

daily = get_daily(start='20260401', end='20260415', columns=['ts_code', 'trade_date', 'close'])
qlib_daily = daily_to_qlib_features(daily, value_columns=['close'], rename_fields={'close': '$close'})
```

### Humphrey（EC2）

EC2 上同样用这些 import，只改环境变量或本地缓存根目录，不改调用方式。

推荐：

```bash
export FACTORFORGE_LOCAL_DATA_ROOT=/data/raw_tushare
```

如果必须显式指定单个文件：

```bash
export FACTORFORGE_DAILY_CSV=/data/raw_tushare/行情数据/daily.csv
export FACTORFORGE_DAILY_BASIC_DIR=/data/raw_tushare/行情数据/daily_basic_incremental
export FACTORFORGE_TRADE_CAL_CSV=/data/raw_tushare/基础数据/trade_cal.csv
```

## 明确禁止的旧写法

以下写法以后不推荐继续扩散：

1. 在业务脚本里硬编码 `~/.qlib/raw_tushare/...`
2. 每个脚本自己写 `ts_code -> SZ000001` 之类 instrument 转换
3. 每个 backend 自己单独算 `future_return_1d`
4. 每个 agent 各自约定不同的列名和日期格式

这些逻辑现在都应该收口到共享层。

## Step3 / Step4 当前已经怎么接了

### Step3

Step3 已经开始通过共享访问层来发现本地 `daily.csv` 和 `daily_basic_incremental`，不再各写一套路径猜测逻辑。

### Step4

Step4 的两个核心 backend 现在都已经收口：

- `self_quant_adapter.py`
- `qlib_backtest_adapter.py`

它们共享：

- `load_factor_values(...)`
- `load_daily_snapshot(...)`
- `normalize_trade_date_series(...)`
- `build_forward_return_frame(...)`

同时 `qlib_backtest_adapter.py` 共享：

- `to_qlib_signal_frame(...)`
- `daily_to_qlib_features(...)`

## 现在还没做的事

这套设计还没有做两件事：

1. 还没有把 `daily_basic_incremental` 大规模同步到本地 Mac 缓存
2. 还没有做 qlib provider/store 的正式落盘转换

所以当前阶段的正确理解是：

- 已经有统一访问层
- 已经有 qlib-friendly frame 适配层
- 还没有正式 qlib bundle builder

## 推荐协作约定

从现在开始，Bernard 和 Humphrey 如果要新增数据读取代码，建议遵守：

1. 先查 `factor_factory.data_access` 里有没有现成函数
2. 没有再补到共享层，不要直接在业务脚本里临时写死
3. 如果是 qlib 相关，优先补 `to_qlib_*` 这类轻适配函数
4. 如果以后真要落 qlib provider/store，再单独建 `bundle` / `store` 模块，不污染当前访问层

## 一句话版

一句话讲给 Bernard 和 Humphrey：

> 以后先用 `factor_factory.data_access` 拿日频数据；要喂 qlib，就再走 `to_qlib_*`；不要在业务脚本里自己猜路径、自己转 instrument、自己算 forward return。
