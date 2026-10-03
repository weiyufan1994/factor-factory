# Factor Forge 与 Qlib 的离线数据互通

共享实现位于 `factor_factory/data_access/qlib.py`。本次提供标准因子表、日线特征及 provider 文件格式的转换和手算验收；没有安装、导入或运行 Microsoft Qlib，没有市场回测。格式通过不证明 Qlib 原生账户与自有账户等价。`portfolio_api.backtest(backend="qlib")` 仍不支持原生账户执行。

## 三种不同的对象

| 对象 | 键或字段 | 用途 |
| --- | --- | --- |
| prediction signal | `datetime/instrument` MultiIndex 与 `factor_value` | 研究输出 F，用于选股或排序 |
| features | 同一 MultiIndex 与 `$open/$high/$low/$close/$volume/$amount/$ret/$factor` | 提供声明口径的行情特征；`$factor` 是价格缩放，绝非研究因子 F |
| instruments | `instrument/start_time/end_time` | 明确给定的可用区间；不是信号表，也不能从有报价推断上市、成分资格或可成交性 |

共享 formatter 接受长表 `ts_code/trade_date`，也接受标准 `datetime/instrument` MultiIndex。日期支持 YYYYMMDD 字符串/整数、YYYY-MM-DD 和无时区的午夜 datetime；歧义格式、浮点日期、非法日期、日内时间、时区、空键和重复键直接报错，不静默丢行。数值必须为实数或 NaN，拒绝布尔、数值字符串和 infinity。输入不修改。

`legacy_qlib/qlib` 将 `000001.SZ`、`600000.SH`、`920599.BJ` 转成 `SZ000001`、`SH600000`、`BJ920599`；`ts_code/tushare/provider` 可逆转回点后缀格式。不凭六位代码猜市场。其他资产显式选择 `raw`。

## 因子互通：日期与缺值保持原意

```python
from factor_factory.data_access.qlib import to_qlib_signal_frame

# F 为现有标准因子 DataFrame。保留 NaN 时可以往返核验。
signal = to_qlib_signal_frame(F, dropna_value_columns=False)
restored = to_qlib_signal_frame(
    signal, instrument_style="ts_code", dropna_value_columns=False,
)
```

默认 `dropna_value_columns=True` 保留历史接口的“省略 NaN 信号”行为；需要无损往返时明确传 False。零信号总是保留。转换不移动日期、不延迟信号、不推断交易日历。当前 Amihud F 已用次交易日 entry 作键，不能在格式转换时再加一次滞后；未来 Qlib strategy/executor 实际何时读取该信号必须另验。

## 行情转换：先声明单位和价格口径

```python
from factor_factory.data_access.qlib import daily_to_qlib_features

features = daily_to_qlib_features(
    bars,
    volume_unit="lot100",        # 源 vol 为 100 股/手
    amount_unit="cny_thousand",   # 源 amount 为千元
    return_unit="percent",       # 源 pct_chg=5 表示 5%
    price_basis="adjusted",       # 输入 OHLC 已经复权，不再乘一次
    adjustment_factor_col="price_scale",
)
```

上述名字 `price_scale` 是调用者提供的正数列，定义为同一来源和快照的 `adjusted_price/raw_price`，且须覆盖所声明 OHLC 口径；示例不是说当前 Data API 已交付该列。转换器不推导真实复权因子，也不认证调用者的来源声明。

| 输入声明 | 输出 |
| --- | --- |
| vol: lot100 / share | ×100 / ×1 得物理股数；若价格已复权，再除以正的 price scale 得与复权价一致的数量单位 |
| amount: cny_thousand / cny | ×1000 / ×1，单位 CNY，不随价格复权缩放 |
| pct_chg: percent / decimal | ×0.01 / ×1，直接使用已声明收益率，不从 close 重算 |
| price_basis=raw | 输入价格原样，`$factor=1`，成交量为物理股数 |
| price_basis=adjusted | 输入价格原样，`$factor=adjusted/raw`，必须给正数 scale |
| 未声明 price_basis | 不制造 scale；provider 中 factor 为 NaN，metadata 标记 unspecified |

手算：复权 close=7.5，scale=0.5，对应 raw close=15；2 手=200 股=400 个复权价数量单位，amount=3 千元变 3000 元，pct_chg=5 变 0.05。零成交保留零，缺失保持 NaN。日线 formatter 默认单位 `source` 只改字段名，metadata 的单位为 unspecified；provider 的 `return_unit` 默认 percent 延续原 pct_chg 接口。源 `change` 可能是绝对价差，不能在缺少 pct_chg 时冒充收益率。

**当前数据边界（2026-10-03）：** 数据组对固定 catalog `68acacb11799c2fd325f57773682c3d0e4cb2f13ade69dbda29ba54f386df7b2` 复核后，真实全 OHLC 复权 scale 的交付合同仍为 Unknown。当前 Amihud 六角色交付也不能当作完整 OHLCV。观察到的 `close_adj/execution_close_raw` 只是同快照的 close 比率，不构成独立企业行动因子或完整 OHLC 基准证据。不得用 `fillna(1)`、跨快照拼字段或更改研究账户填补这个缺口。当前适配不新建数据任务。

## 写入独立的本地 provider

每次选择**不存在的新输出目录**。已有目录、文件或符号链接会报错，原内容保留；没有默认覆盖开关。失败后不要把残留的部分输出当完整 provider，改用新目录重试。

显式日历 CSV/Parquet 仅含 `trade_date`；instruments CSV/Parquet 含 `instrument/start_time/end_time`。区间端点须是日历内交易日，可给同一 instrument 多段不重叠区间；每条 bar 须落在声明区间内。声明区间可以包含无任何 bar 的 instrument，此时 features 保持 NaN。输入日历必须排序、唯一。禁止用首末报价日期证明上市/退市，禁止缺值补零或前值填充推断停牌/可成交。

```bash
python3 scripts/publish_qlib_daily_provider.py \
  --input /path/to/approved_bars.parquet \
  --provider-dir /path/to/new_provider_trial \
  --calendar-file /path/to/approved_sessions.csv \
  --instrument-intervals-file /path/to/approved_intervals.csv \
  --instrument-style legacy_qlib \
  --volume-unit lot100 --amount-unit cny_thousand --return-unit percent \
  --price-basis adjusted --adjustment-factor-column price_scale
```

只在相应输入合同已成立时使用这些声明。未提供显式 calendar/instruments 的旧调用仍能生成诊断文件，但 metadata 分别标记 `observed_bar_union_not_exchange_calendar` 和 `observed_bar_extent_not_listing_or_membership`，不能用于宣称原生回测就绪。旧 `build_source_snapshot` 是单独的 source_daily 导出辅助，会重写它自己的导出目录；本指南 publisher 路径不调用它，勿将它用于现有研究目录。

输出包括 `calendars/day.txt`、`instruments/all.txt`、`features/<instrument>/<field>.day.bin`、`provider_metadata.json` 与 publisher 的 `publish_report.json`。二进制为 little-endian float32，首值为日历起点，后续值对应区间内日历，缺失交易日仍占一格 NaN。构建前拒绝重复 bar、目录碰撞、错误区间和 float32 溢出。按 instrument 分组一次，避免为每只股票反复扫描全表。

`native_data_contract_declared=true` 仅表示调用者声明完整，不能替代数据 QA/PIT/哈希、全 OHLC scale 交付或引擎验证。`native_execution_equivalence` 始终为 `not_verified`。raw format smoke 只检查磁盘格式。已有 `--qlib-smoke` 另需完整声明和真实 Microsoft Qlib，不能把缺包 SKIPPED 当成功。本次不执行此选项、Data API 拉取、S3 同步或环境切换。

## 未来比较原生账户之前需要对齐什么

| 项目 | 当前自有研究账户 | 既有 Qlib native 路径及需要确认的差异 |
| --- | --- | --- |
| 选股与持仓 | 冻结的月度形成池、90% 分位含并列、等权 | 现有 TopkDropoutStrategy(topk=50, n_drop=5) 不同；不能直接比较 NAV |
| 时点和日历 | formation t、next-session entry、next-month entry exit | 原脚本从稀疏 signal dates 构造范围且截到倒数第二个 signal；需对齐完整交易日历和 executor 信号滞后 |
| 本金、数量、公司行动 | 初始资金 1、可分割的复权价数量单位 | 原脚本 1 亿本金；lot、最小费、股数和复权行为依赖实际引擎配置，不能只缩放本金就认定等价 |
| 费用与下单顺序 | .003/.006 两档各自 fee-aware 数量；先卖后买、共同比例买入 | 必须逐项显式给同费用、最低费、交易单位、成交价和顺序；不能依赖未核验默认值 |
| 执行限制和缺失 | raw V17 状态/方向限价；买入阻断到期、超额卖出重试；仅确认停牌且已有持仓时允许同快照估值延续 | 旧脚本 limit_threshold=.095、deal_price=close，不能替代所有规则；不能把缺行当停牌或可成交 |
| gross shadow | 同数量，仅将费用返还现金 | 不等于另跑零费账户重新优化买入数量 |

先逐键比较 pool、signal、formation/entry/exit、买卖方向和执行决策，再核对价格、数量、费用、现金、持仓和 NAV。只有同输入、同规则实际成立，才约定和报告数值容差；表达不了同一账户就明确不可比，不反改研究定义。这里不预先给“原生等价”结论或捏造账户误差阈值。

## 离线验收

`tests/test_qlib_interop.py` 使用两条手算 bar、四个交易日和一个无 bar 的 instrument，禁止 native Qlib import 和网络：覆盖标准长表/MultiIndex 往返、SH/SZ/BJ、零和 NaN、entry 日期不移动、单位、scale、区间和日历缺口、重复键、已有目录拒绝覆盖及 publisher CLI。浮点信号往返应保持实际输入精度；float32 文件单独测量序列化误差，示例相对误差不超过 float32 epsilon，不把此结果推广为回测容差。

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -c pytest-offline.ini -p no:cacheprovider \
  tests/test_qlib_interop.py tests/test_research_api.py tests/test_step4_qlib_resource_guard.py
```
