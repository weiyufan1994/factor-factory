---
report_id: "ALPHA009_ALPHA007_CHOPPY_SKEW_20260422"
factor_id: "Alpha009Extended"
decision: "iterate"
run_status: "success"
final_status: "partial"
tags:
  - "regime"
  - "choppy"
  - "skewness"
  - "kurtosis"
  - "mean-reversion"
  - "segmented-regime"
  - "fold-delta"
  - "inv_chop"
  - "oos_validated"
---

# Alpha009/Alpha7 Choppy + Skew/Kurt Regime Fusion

## 最终判定：iterate（暂缓 promote_official）

**入库状态**：进入 factor_library_all，标注为 iterate
**理由**：
- OOS Spearman rho=0.915, p=0.0002（稳健显著）
- IC_IR 衰减 7.2%（可接受）
- 但目前 OOS 仅 165天，建议等 200+ 天数据后再升 official

## OOS 验证（最终结论）

**数据**：raw data, IS=2010-01-04→2025-07-10（3768天），OOS=2025-07-11→2026-03-19（**165天**）

| 策略 | IS→OOS IC_IR 衰减 | OOS G10 | OOS Spearman rho | OOS p值 |
|---|---|---|---|---|
| folded | 0.60→0.56（7.8%）| +0.109% | 0.261 | **0.47 ❌** |
| alpha7_skew | 0.56→0.54（3.1%）| +0.153% | 0.891 | **0.0005 ✅** |
| **inv_5d_a25** | 0.56→0.52（7.2%）| +0.147% | **0.915** | **0.0002 ✅** |

**关键发现**：
- folded 在 OOS 上 Spearman rho 不显著（p=0.47），quantile 单调性消失
- inv_5d_a25 在 OOS 上 rho=0.915，且是最低 p 值（0.0002）
- **choppy 增强的核心价值是保证 quantile 分层稳健性，而非提升 IC**

## 问题背景

- **Alpha009**：用 5d ts_min/ts_max 二分法判断 choppy，在 choppy 时做均值回归（-delta），趋势时不交易
- **Alpha7**：用 20d return 的 60d 滚动 skewness/kurtosis 作为 regime 权重，加在 folded delta 信号上

两者本质都是 regime 判断，但切入角度不同：
- Alpha009：离散二分类（choppy/trend）
- Alpha7：连续权重（|skew|, kurt）

能否把两者融合？

---

## 两轮测试结论

### 第一轮：V1 — 线性叠加（效果有限）

```
signal = folded_zs × (1 + choppy_w×choppy_zs + vol_w×vol_zs + skew_w×|skew|_zs + kurt_w×kurt_zs)
```

**发现**：
- choppy 作为线性权重，加和不加差异不大（choppy_w 在 0.25~1.0 之间结果几乎一样）
- skew/kurt 单独用效果好（IC=0.057, rho=1.000），加 vol 反而变差
- choppy 和 skew/kurt 在线性框架下存在**信息冗余**：sigmoid 软切换比分段线性更有效

### 第二轮：V2 — 软分段切换（核心创新）

**发现硬门（Gating）失败**：choppy gate 把趋势行情直接归零，丢失信息，效果差。

**软分段成功**：

```python
from scipy.special import expit

# 核心创新：用 sigmoid 把 choppy 二分类变成 [0,1] 连续过渡
sigmoid_choppy = expit(choppy_zs)   # 0~1 平滑，choppy高→1，trend→0

# 最优公式（seg_choppy_skew）：
signal = folded_zs × sigmoid_choppy × (1 + 0.25×|skew20|_zs)

# 或分段版本（seg_b25_g50）：
# choppy=1（震荡）: signal = folded_zs × (1 + 0.25×|skew|)
# choppy=0（趋势）: signal = folded_zs × (1 - 0.50)  → 信号衰减但不归零
```

**效果对比**：

| 策略 | IC | IC_IR | LS_IR | G10 | rho |
|---|---|---|---|---|---|
| folded（baseline）| 0.069 | 0.717 | 0.455 | +0.013% | 0.758 |
| s_chop+skew（V1）| 0.057 | 0.679 | 0.465 | +0.027% | 1.000 |
| seg_choppy_skew（V2）| 0.056 | 0.676 | 0.464 | +0.023% | 1.000 |
| seg_b25_g50（V2）| 0.057 | 0.676 | 0.462 | +0.024% | 1.000 |

**关键结论**：
1. 加了 regime 判断后，IC 略有下降，但 **G10 多头端翻倍**，Spearman rho 从 0.758 → **1.000**（完美单调）
2. skew 和 kurt 效果几乎等价，说明在 60d 窗口上两者高相关
3. vol 加入后变差，不应加入
4. **分段切换（seg）优于线性叠加（V1）**：choppy 低时保留部分信号（软衰减）而非归零

---

## Regime 判断矩阵（最终理解）

```
              |skew|/kurt 高（肥尾）    |skew|/kurt 低（薄尾）
choppy=1（震荡）   强均值回归信号          中等均值回归信号
choppy=0（趋势）   信号大幅衰减            信号完全衰减（folded baseline）
```

**经济解释**：
- choppy 市场本来就该均值回归
- 高 |skew| = 尾部极端事件频发 = 投资者行为偏差更强 = 均值回归机会更大
- 两者叠加 → 最强的均值回归环境

---

## 对 Alpha7 的意义

Alpha7 原来的 regime 框架是：
```
signal = folded_zs × (1 + α×|skew|_zs)   # 线性叠加
```

现在可以升级为：
```
signal = folded_zs × sigmoid(choppy_zs) × (1 + α×|skew|_zs)   # 加 choppy 软门
```

即：**把 choppy 作为第四个 regime 变量，用 sigmoid 软切换**，让信号在趋势市场中平滑衰减而不是硬切断。

---

## Alpha7 Choppy Regime 测试结果（补充）

基于 V1/V2 的发现，移植到 Alpha7（folded delta + skew/kurt）上测试。

### Alpha7 测试结论

| 策略 | IC | IC_IR | LS_IR | G10 | rho |
|---|---|---|---|---|---|
| **alpha7_sig_inv_chop** | **0.057** | **0.680** | **0.467** | **+0.027%** | **1.000** |
| alpha7_seg_b25_g50 | 0.057 | 0.676 | 0.462 | +0.024% | 1.000 |
| alpha7_sig_chop_a25 | 0.057 | 0.676 | 0.461 | +0.024% | 1.000 |
| alpha7_skew（基准）| 0.057 | 0.677 | 0.459 | +0.023% | 0.988 |
| alpha7_folded | 0.069 | 0.717 | 0.455 | +0.013% | 0.758 |

### ⚠️ 关键意外发现：inv_chop（反向 choppy）效果最好

```python
# inv_chop 公式（趋势放大，choppy 压制）
signal = folded_zs * (1 - sigmoid(choppy_zs)) * (1 + 0.5 * abs_skew_zs)
```

- `1 - sigmoid(choppy)` → choppy 高时 → 抑制；choppy 低（趋势）时 → 放大
- 这意味着：**在趋势市场中放大 fold delta 信号，在 choppy 市场中压制**
- 与原始假设（choppy 时做均值回归）**相反**

### 经济解释（待验证）

两种可能：
1. **拥挤效应**：choppy 市场里大家都做均值回归，信号被套利了；趋势市场里 fold 信号仍有价值
2. **方向持续性**：在有趋势的股票里，delta 方向更持续；在无趋势的股票里，delta 随机性更大

### Alpha7 最终推荐公式

稳健版（符合金融假设）：
```python
signal = folded_zs * sigmoid(choppy_zs) * (1 + 0.25 * abs_skew_zs)
# G10=+0.024%, rho=1.000
```

激进版（追求 G10）：
```python
signal = folded_zs * (1 - sigmoid(choppy_zs)) * (1 + 0.5 * abs_skew_zs)
# G10=+0.027%, rho=1.000，但需更多样本外验证
```

---

## 完整实验记录

| 脚本 | 说明 |
|---|---|
| `scripts/alpha009_regime_extended.py` | V1：线性叠加 choppy+vol+skew+kurt |
| `scripts/alpha009_regime_v2.py` | V2：硬门/软分段/sigmoid切换 |
| `scripts/alpha007_choppy_regime.py` | Alpha7 移植：choppy sigmoid + skew/kurt |
| `evaluations/ALPHA009_REGIME_EXTENDED_20260422/` | V1 结果 |
| `evaluations/ALPHA009_REGIME_V2_20260422/` | V2 结果 |
| `evaluations/ALPHA007_CHOPPY_REGIME_20260422/` | Alpha7 choppy 结果 |

---

## 窗口对比发现（第二轮测试：5d vs 10d vs 20d）

### 核心结论

| 窗口 | chop only IC | inv G10 | norm G10 | 关键发现 |
|---|---|---|---|---|
| **5d** | 0.066 | **+0.028%** | +0.024% | inv>>norm，5d chop有真实信号 |
| **10d** | 0.069 | +0.024% | +0.024% | chop无信息量，inv≈norm |
| **20d** | 0.069 | +0.024% | +0.024% | chop无信息量，inv≈norm |

**关键发现**：
1. **10d/20d choponly ≈ no_chop**（IC几乎相同）→ choppy检测在10d以上基本是噪声
2. **5d时inv显著优于norm**（G10 +0.028% vs +0.024%）→ choppy信号真实时，inv作为噪声抑制器更有效
3. **α越小G10越高**（a25 > a50 > a75 > a100）→ skew权重不宜过大

### 机制解释：inv_chop为何有效

inv_chop 本质上是一个**噪声抑制器**：
- choppy 检测有噪声（假阳性：实际是趋势却被判定为choppy）
- norm_chop：在假阳性choppy期错误放大信号
- inv_chop：在假阳性choppy期抑制信号，减少损失

10d/20d 时 chop 检测基本是噪声，inv 和 norm 效果相同。
5d 时 chop 检测有真实信号，inv 的噪声抑制效应让它明显胜出。

### 最优推荐更新

**全场最优**：`inv_5d_a25`
```python
sigmoid_choppy = sigmoid(choppy_5d_zs)  # 5d窗口
signal = folded_zs * (1 - sigmoid_choppy) * (1 + 0.25 * abs_skew_zs)
# IC=0.058, G10=+0.028%, rho=1.000
```

---

## 最优推荐公式

```python
# inv_5d_a25（全场最优，已通过165天OOS验证）
sigmoid_choppy = sigmoid(choppy_5d_zs)  # 5d窗口
signal = folded_zs * (1 - sigmoid_choppy) * (1 + 0.25 * abs_skew_zs)
# IC=0.058 (IS), OOS rho=0.915, p=0.0002
```

## 完整实验记录

| 脚本 | 说明 |
|---|---|
| `scripts/alpha009_regime_extended.py` | V1：线性叠加 choppy+vol+skew+kurt |
| `scripts/alpha009_regime_v2.py` | V2：硬门/软分段/sigmoid切换 |
| `scripts/alpha007_choppy_regime.py` | Alpha7 移植：choppy sigmoid + skew/kurt |
| `scripts/alpha007_choppy_window_test.py` | 窗口测试：5d/10d/20d |
| `scripts/alpha007_oos_raw.py` | OOS测试：raw data，165天 |
| `evaluations/ALPHA009_REGIME_EXTENDED_20260422/` | V1 结果 |
| `evaluations/ALPHA009_REGIME_V2_20260422/` | V2 结果 |
| `evaluations/ALPHA007_CHOPPY_REGIME_20260422/` | Alpha7 choppy 结果 |
| `evaluations/ALPHA007_CHOPPY_WINDOW_20260422/` | 窗口测试结果 |
| `evaluations/ALPHA007_CHOPPY_OOS_RAW_20260422/` | OOS测试结果 |

---

## 下一步

1. 等数据到今天后再做一次 200+ 天 OOS 验证
2. 测试更细的α值（如0.1、0.15、0.2）看G10是否还能提升
3. 把 inv 和 norm 做成双向信号（invert一方的信号作为空头）
4. 验证噪声抑制假说
