# 阶段6B近邻文献与作者代码补查

审查日期：2026-11-14。已完整阅读6A文献矩阵、差异审查和H1假设；本次只补充来源证据，不修改6A历史文件，不运行DIRT/RDG，不开发H1。

本次补上一个明确缺口：**已经找到并核验作者团队的运动约束DIRT实现及MIT许可**。Feng2024正文、RDG作者实现与许可仍未取得。该变化提高了强对照审查的可操作性，不能据此认定H1新颖或有效。逐项访问状态见[补查CSV](../results/stage6b/literature_followup.csv)。

## Feng2024：正文仍缺，不能排除机制重叠

原始题名为 *Smooth path planning under maximum curvature constraints for autonomous underwater vehicles based on rapidly-exploring random tree star with B-spline curves*，作者Haobo Feng、Qiao Hu、Zhenyi Zhao、Xinglong Feng，DOI为[10.1016/j.engappai.2024.108583](https://doi.org/10.1016/j.engappai.2024.108583)。题名/作者/DOI沿用6A已核验元数据，本次没有重新运行注册机构查询。

实际访问[出版商正文入口](https://www.sciencedirect.com/science/article/pii/S0952197624007413)和[摘要入口](https://www.sciencedirect.com/science/article/abs/pii/S0952197624007413)，均返回403。出版商搜索索引可读摘要/部分引言，能确认曲率硬约束、B样条及orientation node pair等主题；这不等于获得完整方法。定向检索未定位合法作者全文或作者代码，状态继续记为`abstract_only`，代码及许可为`not_verified`。

因此不能断言其扩展、候选生成或曲率机制与H1完全不同。后续需通过合法作者稿、机构订阅或研究者提供的合法资料补读；本阶段没有绕过付费访问、联系作者或复制受限材料。

## DIRT：作者团队代码与OMPL候选必须区分

[2018原论文作者PDF](https://people.cs.rutgers.edu/~kb572/pubs/iros_dirt.pdf)可读，DOI为[10.1109/IROS.2018.8593672](https://doi.org/10.1109/IROS.2018.8593672)。本次检查方法和Blossom部分：DIR用于选点；首次扩展生成多个候选并按启发式排序，后续保留随机扩展。它已经研究了传播候选的启发式分配，不能将这类思想本身称为新贡献。

[PRACSYS官方项目页](https://pracsys.github.io/projects/)列出Aravind Sivaramakrishnan、Edgar Granados和Kostas Bekris的ML4KP项目，并链接[PRX-Kinodynamic/ML4KP](https://github.com/PRX-Kinodynamic/ML4KP)。实际GitHub分支查询得到`main`提交`064015a7545e1713cbcad3e79807b5cec0849f54`。以下结论来自该次来源读取，提交标识只用于依赖版本定位，不是文件哈希校验清单。

| 实际读取的来源 | 核实内容与适用边界 |
| --- | --- |
| [LICENSE](https://github.com/PRX-Kinodynamic/ML4KP/blob/064015a7545e1713cbcad3e79807b5cec0849f54/LICENSE) | MIT许可，版权为2021 PRACSYS Lab；若将来复用，须保留许可要求的声明。没有复制源码进本仓库 |
| [dirt.cpp](https://github.com/PRX-Kinodynamic/ML4KP/blob/064015a7545e1713cbcad3e79807b5cec0849f54/src/prx/planning/planners/dirt.cpp) 1—460行 | DIR选点、首次Blossom候选、启发式排序及随机后续扩展；属于作者团队的控制规划实现，不是第三方简化复写 |
| [planner_functions.cpp](https://github.com/PRX-Kinodynamic/ML4KP/blob/064015a7545e1713cbcad3e79807b5cec0849f54/src/prx/planning/planner_functions/planner_functions.cpp) | 默认计划采样使用给定上下限内的均匀整数控制步数；默认轨迹有效性遍历离散状态。没有本项目的连续球扫掠证书 |
| [rrt.hpp](https://github.com/PRX-Kinodynamic/ML4KP/blob/064015a7545e1713cbcad3e79807b5cec0849f54/src/prx/planning/planners/rrt.hpp) 1—180行 | 默认采样计划不使用传入姿态；默认目标检查采用二维距离。框架允许替换这些函数，不能原样套用该默认设置作为本项目三维目标认证 |
| [dirt.hpp](https://github.com/PRX-Kinodynamic/ML4KP/blob/064015a7545e1713cbcad3e79807b5cec0849f54/src/prx/planning/planners/dirt.hpp)及[示例](https://github.com/PRX-Kinodynamic/ML4KP/blob/064015a7545e1713cbcad3e79807b5cec0849f54/examples/basic/dirt_basic.cpp) | 存在可替换扩展、启发式和障碍距离接口；这说明框架可扩展，不能把默认采样中未见H1关系当成整个相关领域不存在该机制的证明 |

另实际核对[OMPL PR #1340](https://github.com/ompl/ompl/pull/1340)：状态为`open`、`merged=false`，提交为`661054add1a43e62531f5bf9f698558416631395`。变更仅有geometric DIRT头文件、实现和测试等4文件；[头文件](https://github.com/aravindsiv/ompl/blob/661054add1a43e62531f5bf9f698558416631395/src/ompl/geometric/planners/dirt/DIRT.h)为BSD许可，并注明基于ML4KP。维护者讨论也明确区分几何版本与尚待加入的control版本。不能将此PR写为OMPL正式版本已经提供control DIRT。

ML4KP存在作者control DIRT，不等于其已经匹配当前五状态、三维位置目标及连续外接球认证。本阶段主任务仍是OMPL官方control SST/RRT；没有增加ML4KP运行、学习模块或第三个算法实验。

## RDG与H1：仍只能作差异待证的候选

[RDG官方arXiv记录](https://arxiv.org/abs/2609.22733)及[正文III节](https://arxiv.org/html/2609.22733v1)实际可读。III-B描述随机控制与有界随机传播时长，核心另外包括网格选点和代表更新。当前定向题名检索、原文链接检查及作者院系页面核查未定位作者代码与代码许可；应写`not_located`/`not_verified`，不能写成代码不存在。arXiv文章许可也不能替代未找到代码的许可证。

已读DIRT/ML4KP默认采样和RDG方法中，尚未核实到H1所称“局部认证净距与姿态需求联合条件化传播时长”的同等默认机制。但随机时长、启发式传播、多候选扩展和可替换采样接口均已有研究；Feng正文仍缺。**本次补查不构成H1新颖性证明，也没有性能比较证据。**

6B科研判断应结合真正原生SST/RRT的模型与安全验收。即使基线正确运行，仍须将上述文献缺口与H1数学差异交由研究者审核，不能自动转入原创实现。
