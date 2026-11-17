# 7B-0标准LTV-LQR数学与模型验收

实现位置：`src/gsunlight_repro/stage7b0/lqr.py`；冻结传播仍直接调用 `stage5a/tracking.py:integrate`，不替换植物，不优化速度。

## 精确传播及解析导数

定义 `C(a,b)=h*sinc(bh/2)*cos(a+bh/2)`、`S(a,b)=h*sinc(bh/2)*sin(a+bh/2)`，这里sinc(x)=sin(x)/x。对常值角速率(r,q)，位移为

\[
\Delta x=\frac v2[C(\psi+\theta,r+q)+C(\psi-\theta,r-q)],
\]
\[
\Delta y=\frac v2[S(\psi+\theta,r+q)+S(\psi-\theta,r-q)],\quad
\Delta z=vS(\theta,q).
\]

角度更新为wrap(ψ+rh)、θ+qh。`C_a=-S`、`S_a=C`，令x=bh/2，

\[
C_b=\frac{h^2}{2}[sinc'(x)\cos(a+x)-sinc(x)\sin(a+x)],
\]
\[
S_b=\frac{h^2}{2}[sinc'(x)\sin(a+x)+sinc(x)\cos(a+x)].
\]

其中 `sinc'(x)=(x cos x−sin x)/x²`；接近0时用其Taylor式 `−x/3+x³/30−x⁵/840+x⁷/45360` 避免相消。状态位置块A为单位阵，姿态偏导由上式求和/差构成；B的姿态块为diag(h,h)。这是冻结精确流的局部切空间导数，不是Euler近似，也不是对clip的导数。

±π处用wrap后的输出差检验局部导数，不把表示切缝当作植物不连续。pitch边界测试数学流的局部扩展；真正执行则另外检查受约束状态/输入，不能因有限差分访问边界两侧就将越界状态认证为合法。

## 标准反向Riccati

\[
P_N=Q_f,\quad K_k=(R+B_k^TP_{k+1}B_k)^{-1}B_k^TP_{k+1}A_k,
\]
\[
P_k=Q+A_k^TP_{k+1}A_k-A_k^TP_{k+1}B_kK_k.
\]

代码使用`numpy.linalg.solve`，检查Q/Qf半正定、R正定及矩阵维数/有限性，反向递推后对P作对称化以消除舍入非对称。状态误差为位置、wrap的yaw、pitch，指令是u_ref−K e，然后按冻结角速率及下一步pitch数值包络投影。包络仍是原20°+1e-12rad，只在二进制舍入恰使投影越界时向零移动一个浮点邻值；不扩大任何物理或数值阈值。

名义状态/输入由保存密集原生数组读取，控制时长严格为原0.1s网格。不含精确目标桥段，不产生参考结束后的延拓。Q/R使用预登记尺度而非实验搜索。该公式是成熟有限时域LQR，参考[官方算法定义](https://drake.mit.edu/pydrake/pydrake.systems.controllers.html)，没有声明复现其软件、构建或Windows部署。

## 保证范围

直线、零角速率线性化的可控矩阵秩为4，纵向误差不可控，测试也验证对应增益列为0。因此有限时域LQR存在不等于任意初差可渐近稳定；角饱和也使无约束最优性/稳定性结论不直接适用。安全必须以实际执行轨迹的连续扫掠认证判定，不来自Riccati或原生证书。

本轮19项验收中有独立标量解析代价最小值、冻结流中央差分、非零姿态误差修正和负例，避免只用实现复制品验证实现。六次科研执行反馈误差恰为0，故没有测到反馈相对纯前馈的性能收益；不能把6/6解释为鲁棒控制结果。
