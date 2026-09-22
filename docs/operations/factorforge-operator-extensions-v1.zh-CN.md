# 通用算子补充 v1 与原生内核加速方向

日期：2026-09-20。基于用户提供的 QuantZone 手册借鉴功能，自行实现 Factor Forge 长表语义；不依赖 QuantZone SDK，也不声称兼容其全部方言。

## Step3 三种路线

- `operator`：表达式 → Formula-IR → 算子 → 生成实现与样本检查。
- `direct_code`：针对数学对象编写自定义代码。
- `hybrid`：`compute_operator_subgraph()` 产生算子结果，`apply_custom_block()` 做自定义计算，`compute_factor()` 组合输出。

路线按照数学对象、数据结构与计算需要选择。已有算子不足时可以选纯代码或混合实现；进入正式执行后不能因失败而悄悄改换已冻结路线。算子是复用工具，因子定义不受算子清单限制。

## 本次接入的 17 项能力

新增 16 个名称，并实现原有占位 `where`。当前注册表从 35 项增至 51 项，51 项均声明 pandas 支持，Qlib 支持条目仍为 18 项。新算子在 Qlib 桥接中明确返回 unsupported，不作静默近似。此统计不替代全库逐算子验收。

输入为统一 `ts_code`、`trade_date` 长表。时序窗口按每只证券已有的行数计算；完整日历和 PIT 合法的行业字段由调用方提供。固定参数必须显式填写，避免不同来源默认值混用。

| 名称与签名 | 本地语义 |
| --- | --- |
| `minimum(a,b)`、`maximum(a,b)` | 逐元素最值；NaN 传播。已有 `min/max` 继续代表滚动最值 |
| `sqrt_nonnegative(x)` | 非负值开平方；负数为 NaN。与保留符号的平方根区分 |
| `clip(x,lo,hi)` | 有限常量上下界，允许 lo=hi；NaN 保留 |
| `lt(a,b)` | 小于比较输出 0/1；任一 NaN 时为 0 |
| `where(cond,a,b)` | cond 非零且非 NaN 时选 a，否则 b；使用共享输入网格，两分支都求值 |
| `cs_demean(x)` | 每日有限值截面去均值；非有限输入为 NaN |
| `cs_winsor_quantile(x,lo,hi)` | 从有限值估计线性插值分位边界；0≤lo<hi≤1；Inf 在有边界时裁剪，NaN 保留 |
| `cs_winsor_mad(x,k)` | median±k×未缩放 MAD，k>0；尺度为零时保留原值 |
| `cs_winsor_std(x,k)` | finite mean±k×总体标准差，k>0；不足两只或尺度为零时保留原值 |
| `cs_fillmean(x)` | 当日有限值均值只填 NaN；不改 Inf；没有捐赠样本时保持 NaN |
| `cs_rank_group(x,g)` | 同日、同有限数值分组内 average 百分位；x 的 Inf 参与，缺失组不排名 |
| `ind_demean(x,g)` | 同日分组内有限值去均值；组内不足两只为 NaN；没有额外全市场 8 只门槛 |
| `ind_fillmean(x,g)` | 同日同行业有限值均值填 NaN；缺失组不填，已有非缺失值保留 |
| `ts_decay_linear(x,n)` | 旧到新权重 1..n，完整 n 行预热；有限值有效权重至少一半，按有效权重归一 |
| `ts_product(x,n)` | 完整 n 行且全部有限才连乘；零保留；数值溢出为 NaN |
| `ts_ffill(x,n)` | 仅用本证券过去 n 行以内的有限值填 NaN；不改 Inf；n=0 保持原值 |

这些定义是明确选择的 Factor Forge 语义。其中 `ts_product` 的完整有效窗口要求比外部手册严格，`ind_demean` 的样本门槛也不同。已有 `stddev`、`ts_rank`、`argmin/argmax`、`**` 等定义保持不变。

表达式示例：

```text
cs_demean(cs_winsor_quantile(close / delay(close, 1) - 1, 0.01, 0.99))
where(lt(close, delay(close, 1)), minimum(close, open), ts_decay_linear(close, 5))
ind_demean(cs_winsor_mad(close, 3), industry_code)
ts_product(1 + returns, 20)
```

目前比较使用 `lt(a,b)`，没有同时扩展 `<`、`and/or` 的表达式语法。行业码在此接口中须为数值。前向填充是可选计算动作，不代表允许替代研究所要求的缺失证据或填补未获准的数据。

代码在 `factor_factory/formula/extension_registry.py` 与 `extension_operators.py`。统一注册表、reference/optimized 求值器、生成代码、样本回看和截面采样识别已接通；每项有语义版本与哈希。Step3 的生成与校验共享新增算子的单位定义，校验器读取注册表中的窗口定义。补充前的 35 项盘点保留在 2026-09-20 对照报告中。

## 验证

`tests/test_formula_extension_operators.py` 使用手工可核对的预期值检查 NaN/Inf、并列/单成员分组、日期和证券隔离、预热、无未来数据依赖、边界参数、输入不变性、生成代码与明确的 Qlib unsupported 状态。另检查实际 Step3 混合代码生成器可把新算子结果交给自定义代码，以及实际校验器拒绝错误或缺失的窗口、错误输出单位。对接时修正了生成器与校验器对收益字段的单位标签不一致；具体收益换算仍由已有字段来源合同定义。

新增算子、既有公式语义、源方言、代码生成以及 direct_code/hybrid 相关的 5 个测试文件共 153 项通过；Step3 样本与派生字段合同的既有回归另有 42 项通过，合计 195 项。它们是工程验收，不是因子经济有效性或正式研究执行证据。

## Rust / C++ 加速方向

Python 保留研究编排与 Step3 编写接口。可以把已证明的热点放到 Rust（PyO3/maturin）或 C++（pybind11/现有 Arrow 接口），通过整块连续数组、Arrow RecordBatch 或按证券/日期分区调用；避免逐行跨语言调用。

适合优先评估的部分是分钟数据的滚动状态、rank/corr/cov、事件生命周期递推、分组聚合与账户状态循环。读取、解压、过滤、排序和重复扫描要单独计时；Arrow 的 C++、Polars 的 Rust 与 NumPy/pandas 的编译内核已经能承担一部分原生计算。分钟可复用状态应由既有 Data API/datamart 层准备，Step4 消费它们。

语言选择以模块为单位：新增需要安全并行和状态管理的独立内核可优先考虑 Rust；成熟 C++ 库或紧邻 Arrow 的计算可用 C++。不把两套工具链作为每个算子的必选依赖。开发原生扩展时须保留参考实现、明确 dtype/NaN/并列值/窗口语义，验证块边界状态、结果索引及下游 rank 的一致性，并记录后端版本、线程数和峰值内存。

本机检查：Apple clang++ 21 可用；当前 PATH 中未找到 rustc/cargo，当前 Python 未找到 maturin/pybind11。Polars 与 PyArrow 可导入。本轮没有安装工具链或新增原生二进制依赖。

## 本轮合成内核基准

运行：

```bash
python3 scripts/benchmark_factorforge_extension_operators.py \
  --output docs/operations/factorforge-extension-kernel-benchmark-20260920.json
```

配置为 200 只证券×1,200 行=240,000 行、窗口 60、3 次重复；行量相当于每只证券 5 个交易日×240 分钟，但输入只是有限合成数值，预先有序。比较的是 pandas grouped rolling.apply 参考计算与本次 NumPy 批量实现。

| 内核 | pandas 参考中位耗时 | NumPy 中位耗时 | 比值 |
| --- | ---: | ---: | ---: |
| `ts_decay_linear` | 0.169609 秒 | 0.007265 秒 | 23.35 倍 |
| `ts_product` | 0.198901 秒 | 0.008725 秒 | 22.80 倍 |

本次两项最大绝对差均为 0，NaN 掩码相同。完整 JSON 记录版本、样本和源码哈希。结果不包含读盘、网络、排序、峰值内存、完整因子或回测耗时，不是 Rust/C++ 对比，也不能外推为整个分钟回测提速倍数。它说明先使用合适的批量编译内核即可显著减少 Python 回调；下一次原生语言实验应选择这之后仍占主要耗时的模块。
