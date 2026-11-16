# 6D最近邻复核与H1可证伪机制

本轮实际联网核查日期2026-11-16，继承6A—6C证据并注明新增读取范围，不宣称系统综述。矩阵见[逐项CSV](../results/stage6d/literature_matrix.csv)。未联系作者、绕过付费访问或上传论文/外部源码；论文许可与代码许可分开。

## 已核验的差异与访问边界

DIRT（Littlefield、Bekris，2018）的完整题名见矩阵，[机构记录](https://scholarship.libraries.rutgers.edu/esploro/outputs/conferenceProceeding/Efficient-and-Asymptotically-Optimal-Kinodynamic-Motion/991031665068804646)核对DOI `10.1109/IROS.2018.8593672`。本轮实际读取[作者原文](https://people.cs.rutgers.edu/~kb572/pubs/iros_dirt.pdf)III-A—III-C：DIR选点、按启发式排序的Blossom、初次多候选及后续随机扩展；候选可由随机或人工设计控制构成。它已覆盖“有指导的多控制扩展”这一宽概念，不能把H1改名后据为创新。

[作者项目页](https://pracsys.github.io/projects/)链接[ML4KP](https://github.com/PRX-Kinodynamic/ML4KP)。实际重读当前main的MIT LICENSE、`dirt.cpp`相关扩展代码及`planner_functions.cpp`默认采样/检查：默认时长均匀整数缩放，传入current未用于该默认时长；轨迹检查遍历离散状态。框架可替换扩展函数，默认实现未见H1不等于整个框架排除了等价机制。未复现DIRT，不将其默认二维距离/离散认证冒充本项目三维连续基线。当前文件URL读取不声称等同6B历史提交的每个字节。[默认源码](https://github.com/PRX-Kinodynamic/ML4KP/blob/main/src/prx/planning/planner_functions/planner_functions.cpp)

RDG题名为*Rapidly-Iterating Grid-Based Near-Optimal Kinodynamic Motion Planning*，[官方提交记录](https://arxiv.org/abs/2609.22733)为2026-09-19，DOI `10.48550/arXiv.2609.22733`；正文页头April2023与提交日期不同，两者均披露。重读[原文III-B及引言](https://arxiv.org/html/2609.22733v1)：有界随机时长、随机控制及允许全支撑传播器的框架。作者代码和代码许可证本轮仍未定位；不是“代码不存在”，也不把预印本当期刊接受。

Feng2024的[出版商入口](https://www.sciencedirect.com/science/article/pii/S0952197624007413)再次403。题名/DOI `10.1016/j.engappai.2024.108583`沿用已核验记录；本轮只见出版商搜索索引的摘要与方法片段，未读完整方法。可确认其曲率受限B样条和姿态节点对主题，不能排除未读细节中的机制重叠，作者代码许可未核验。

[VK-RRT*原文4.2](https://www.mdpi.com/2077-1312/14/10/919)已研究障碍邻近与局部洋流耦合的自适应空间步长，DOI `10.3390/jmse14100919`；[约束前置AUV工作](https://www.mdpi.com/2079-9292/15/15/3435)DOI `10.3390/electronics15153435`在树扩展/选父/重连中处理转角与俯仰。它们限制宽泛的“净距＋姿态＋步长”创新主张，与本项目恒正速Euler控制时长是否数学等价尚未证明。代码许可本轮未完成核验，不虚填可复现。

官方SST/RRT的本轮核心证据来自本地锁定2.0.2源码和实际构建：SST使用均匀控制及1—50整数时长，RRT保留其有效前缀语义；BSD-3-Clause实际读取。SST论文DOI `10.1177/0278364915614386`与RRT论文DOI `10.1177/02783640122067453`沿用6A已核验记录。本轮没有把固定半径SST称为SST*，没有改官方算法核。[官方SST源码](https://github.com/ompl/ompl/blob/2.0.2/src/ompl/control/planners/sst/src/SST.cpp)

## 仅供未来审查的明确机制，未实现

输入为当前状态q、同一采样目标姿态所需变化`Δψ=wrap(ψ_target−ψ)`和`Δθ=θ_target−θ`、速度v、两个角速率上限，以及**同一完整球/顶界/边界下的认证净距下界c**。c的3m截断必须披露。定义：

```text
N0 = {1,...,50}, dt = 0.1s
tau_att = max(abs(Delta_psi)/r_max, abs(Delta_theta)/q_max)
tau_ball = max(0,c)/v
N_joint = {n in N0: n*dt >= tau_att and n*dt < tau_ball}
```

`tau_att`只是改变姿态的必要时间下界，不保证给定随机控制能达到该姿态，更不保证到达位置目标。`tau_ball`利用位移不超过弧长`v*t`给出当前自由球内的保守位置时间尺度，不表示整条通道的可达性。姿态界限、所有0.1s曲线安全和目标仍必须由冻结oracle认证。

若`N_joint`非空，可研究`epsilon*Uniform(N0)+(1−epsilon)*Uniform(N_joint)`；为空则回退`Uniform(N0)`，**不得硬删除状态或宣布无解**。epsilon必须大于0并在未来另行预登记；两个控制仍同分布采样。此定义处理净距短于转姿态时间时的冲突，避免用两项分数简单加权就宣称原创。它仍可能是已知启发式的一种具体化，不具备已证明的新颖性或原SST理论保证。

当前官方SST直接在solve内抽取整数时长，并没有已实现的状态条件时长回调。将来若原型获准，必须明确最小接口改动并保持树选点/剪枝等一致；不能在传播器里偷偷改传入duration，否则PathControl时长与状态会失配。**本阶段没有实现这个接口或任何H1模块。**

## 可证伪检验和未来消融

未来仅在模型契约先通过后，才可另行批准同核SST、仅净距、仅姿态、联合机制四条件；控制分布、原始采样支持、状态度量、goal bias、连续安全及总预算相同。主要比较严格M/K，LOS与成本/开销分别报告，失败和退化不得删；使用真实障碍开发图与另行冻结的独立测试图。

若联合不优于两项单因素、冲突回退使其等同均匀基线、收益只来自额外传播/碰撞调用或更宽时钟、成熟SST已消除难例、或查得数学等价先验，拒绝H1的当前贡献解释。现阶段未运行这些消融，也没有性能证据支持联合机制必要性。

创新差异结论为**未证实**，不是已证明或已否定。模型映射门槛失败已足以使6D选择BLOCKED；上述文献和机制表述不构成GO理由。
