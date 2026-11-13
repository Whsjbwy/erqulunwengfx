# 阶段6A成熟强基线与Windows可行性审查

首选同模型成熟对照为**OMPL control::SST**，并加入**control::RRT**作可行解搜索对照。选择依据是能直接使用当前五状态前向传播、无需伪造两点最优连接、公开BSD许可与可审查实现。它们是优先复现的成熟对照，不是已证实的本任务最强算法。2026 RDG及其比较的DIRT必须纳入后续强度挑战；目前不能声称SST代表整个领域上限。

## 方法、实现与许可

| 候选 | 原文/官方实现 | 与当前模型的关系 | 6A实际状态 |
| --- | --- | --- | --- |
| control SST | [Li等2016](https://doi.org/10.1177/0278364915614386)；[OMPL 2.0.2源码](https://github.com/ompl/ompl/blob/2.0.2/src/ompl/control/planners/sst/src/SST.cpp) | 可用相同ODE前向控制传播；BestNear、witness和稀疏化不需解析连接 | 阅读原文4节与源码；未安装/编译/运行原生规划器 |
| control RRT | [LaValle/Kuffner2001](https://doi.org/10.1177/02783640122067453)；[官方源码](https://github.com/ompl/ompl/blob/2.0.2/src/ompl/control/planners/rrt/src/RRT.cpp) | 采样控制并传播；保持算法原意，作为快速可行性对照 | 实际审查控制采样/传播与近似解返回逻辑；未新运行 |
| RDG / DIRT | [RDG2026预印本](https://arxiv.org/html/2609.22733v1)及其相关工作 | 一般前向传播框架；可挑战SST的近邻开销和扩展策略 | RDG方法已读；官方可用代码与许可证未定位，不伪称复现 |
| Vana / Vana-Owen 3D Dubins | [Moll2024](https://doi.org/10.1109/OCEANS55160.2024.10754581)；[VanaOwen头文件](https://github.com/ompl/ompl/blob/2.0.2/src/ompl/base/spaces/VanaOwenStateSpace.h) | 约束空间曲率与俯仰；不是独立10/5°/s率限制的直接等价连接 | 可作为曲率参照；尚不能认定同模型可行强基线 |
| Generalized Dubins | [Kumar等预印本](https://arxiv.org/html/2509.24143v2)；[作者仓库](https://github.com/DeepakPrakashKumar/3D-Motion-Planning-for-Generalized-Dubins-with-Pitch-Yaw-constraints) | Bishop完整姿态、两体轴率；不是固定滚转的五状态Euler模型 | README和Apache-2.0已核验；模型映射/全局俯仰边界未证，不直接采用 |
| GCOPTER / FIRI | [GCOPTER作者仓库](https://github.com/ZJU-FAST-Lab/GCOPTER)；[FIRI原文](https://doi.org/10.1109/TRO.2025.3562482) | 多旋翼平坦系统优化或纯几何走廊，需额外模型推导 | MIT许可已核；firi.hpp注明old version，未把它当成2025完整实现 |

OMPL的[BSD-3-Clause许可证](https://github.com/ompl/ompl/blob/2.0.2/LICENSE)已实际读取。未复制外部源码进入本仓库。将来若使用其代码需保留规定声明，作者论文图与文章许可不能代替代码许可。

固定半径OMPL SST不可写为SST*。原文SST为渐近近优，SST*通过半径收缩追求渐近最优；鲁棒净距和半径关系等假设是前提，不构成10秒有限样本保证。RRT-Connect、RRT*、Informed RRT*保留为冻结几何基线，不因名字带RRT而自动获得运动可行性。

## 源码发现的关键安全缺口

实际检查[SpaceInformation::propagateWhileValid](https://github.com/ompl/ompl/blob/2.0.2/src/ompl/control/src/SpaceInformation.cpp)130—230行：传播后逐步调用`isValid`检查端点，默认没有本项目的曲线扫掠球连续证书。因此“OMPL返回有效路径”不能直接等同于当前严格安全通过。不能仅设置几何`MotionValidator`就假定控制传播自动使用它。

将来适配需统一：

1. 状态空间为有界`R³ × SO(2) × [-20°,20°]`，控制为两个有界Euler角速度，正向速度恒1 m/s，不使用SE(3)四元数或反向传播偷换模型。
2. 每个传播内部0.1秒子区间复用同一解析积分和完整球/边界/任务高度/弦偏差认证；超界或不能认证时显式返回无效，不静默裁剪俯仰后继续。适配层必须先用解析正例及拒绝例验证。
3. 初态所有方法相同，目标为同一0.75 m位置球，终端姿态自由，不能要求基线比候选更精确的终态。`APPROXIMATE_SOLUTION`必须单列失败或近似，不能算精确成功。
4. 每个返回轨迹独立重放其控制，核验状态、全区间安全和目标到达。所有算法使用同一安全oracle和相同额外0.25 m余量，不将默认端点检测与新机制的连续检测比较。
5. 再通过同一冻结`los_terminal_v1`执行参考。开环原生控制轨迹与闭环参考跟踪分别报告；不能让候选免费执行原生控制，却让几何基线承担跟踪误差。

这些是**未来适配要求**，6A没有编写OMPL适配器或自行实现“简化SST”冒充成熟对照。

## Windows与资源实证

审查日期2026-11-13。官方[下载页](https://ompl.kavrakilab.org/download.html)与[发布说明](https://ompl.kavrakilab.org/releaseNotes)列2.0.2；实际请求`https://pypi.org/pypi/ompl/2.0.2/json`返回404。PyPI真实包元数据最新2.0.1，所有已列版本未见`win_amd64/win32/win_arm64`轮子；Linux/macOS轮子不能作为Windows安装证据。官方[安装说明](https://ompl.kavrakilab.org/core/installation.html)推荐Windows vcpkg，且不包含Python绑定；[Python接口](https://ompl.kavrakilab.org/python.html)存在回调/线程开销约束。

本机`importlib.util.find_spec('ompl')`未找到包，`Get-Command cmake,cl`未找到命令。没有新装工具链、WSL或改变旧依赖。Windows C++实现有正式支持路径，**尚未实际构建成功**。可考虑小型C++可执行文件与现有Python记录格式交换，或在独立环境编译绑定；两者都需先补齐构建、完整安全认证和计时验收，不能将平台可能性写成本机通过。

Ryzen 5 9600X/32 GB适合串行小规模CPU规划，RTX 5060不参与当前ODE与几何认证；无需为了本阶段下载GPU框架。未来编译内存/运行耗时没有实测，不能给出虚构性能值。正式324个候选任务按10秒仅规划上限约54分钟，另有执行/认证/构建成本，不是6A实际用时。原生接口开销可能压过采样改进，须报告全管线时间、传播数和碰撞调用数，避免语言差异冒充机制优势。

## 小型验收与结论

[12例协议](../configs/stage6a_feasibility_protocol.json)先提交后实际运行：六条给定控制正例、六个明确拒绝输入/场景；全部通过预期，930个接受区间，27个独立RK4核对，最大误差`1.2079e-13 m`。这证明给定控制与现有认证的一致性，不证明SST/RRT已找到这些轨迹。无规划搜索、无随机种子筛选、无大规模基线实验。

强基线方法与授权可接受；**同模型原生运行和连续认证适配仍未验收**。因此当前阶段判定为`Need-Baseline-Evidence`。完成这些证据前，不批准原创规划器原型或论文性能实验。
