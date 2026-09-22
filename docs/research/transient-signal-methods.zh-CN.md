# 短暂信号的观测模型参考：小波、卡尔曼、因果卷积与变分/TV

这是一份方法参考，不是因子结果。若经济假设认为观测路径混有短暂冲击、较持久的潜在状态和多尺度运动，首要问题是：哪一个观测模型保留了该对象、且在决策时点可合法计算？四种工具不能互换，也不识别注意力、过度反应或收益来源。

| 方法 | 观测映射与保留/丢失 | 在线时点与反证 |
| --- | --- | --- |
| 小波（wavelet） | 在预先声明的历史窗计算 \(W_x(a,b)=\langle x,\psi_{a,b}\rangle\) 或尺度局部能量。保留局部时频/尺度变化；压缩为能量会丢失相位、符号或跨尺度依赖。 | 中心化小波本身不必然泄漏：其完整 support 若都在合法历史窗内即可；support 越过决策时点 \(t\) 才是泄漏，且必须披露边界 padding。比较不同合法 support；尺度改变后若结论消失，不得把该尺度当机制事实。 |
| 卡尔曼（Kalman） | 指定 \(x_t=F_tx_{t-1}+w_t\)、\(y_t=H_tx_t+v_t\)，递推 \(x_{t\mid t}\)。保留显式状态—观测—噪声假设；会遗漏模型外非线性、厚尾或断点。 | 只能使用当期可得观测。时变增益递推仍可对输入线性，但不能等同单一固定卷积核；仅在 \(F,H,K\) 常数且初始状态项已规定时，输入响应可写为固定因果核，通常是 IIR 而非有限 FIR。检查创新残差是否仍有结构。 |
| 因果卷积（causal convolution） | \(z_t=\sum_{k=0}^K h_k y_{t-k}\)，可用 dilation 扩大历史感受野。保留有限历史因果映射；未显式携带的窗外信息会丢失。 | padding、归一化和训练切分不得见未来。波峰经过滤波仍不是 attention/overreaction 的证据；缩短/延长感受野并比较投影损失。 |
| 变分/TV | \(\arg\min_u \frac12\lVert y-u\rVert_2^2+\lambda TV(u)\)，一维 \(TV(u)=\sum_t|u_t-u_{t-1}|\)。保留分段平滑与边缘；可压平渐变、移动变点。 | 在线特征的优化输入窗右端必须 \(\le t\)，只取 endpoint \(u_t\)；之后窗口得到的历史 \(u\) 修订不得回写为当时可交易特征。\(\lambda\) 也不能用未来调优。改变 \(\lambda\)、检查重构残差与变点时刻；若只在未预注册参数下出现，拒绝机制结论。 |

性能变差时，先定位缺失数据、available-time 对齐、投影/重构损失、归一化和参数稳定性；这些测量失败尚不能否定经济假设，更不能倒推出新的机制。

原始方法来源（定义与约束，不支持金融实证结论）：[Mallat 1989](https://www.di.ens.fr/~mallat/papiers/MallatTheory89.pdf)、[Kalman 1960](https://doi.org/10.1115/1.3662552)、[WaveNet](https://arxiv.org/abs/1609.03499)、[Rudin–Osher–Fatemi 1992](https://doi.org/10.1016/0167-2789(92)90242-F)。可访问的大学存档副本：[Kalman PDF](https://people.duke.edu/~hpgavin/SystemID/References/Kalman-JBE-1960.pdf)、[ROF PDF](https://math.ucla.edu/~lvese/285j.1.09f/ROF.pdf)。
