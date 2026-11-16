# 6D-S近邻复核与创新性边界

本轮实际核验日期为2026-11-16，仅定向复查关键近邻，不是系统性查新。6A—6D文献矩阵保持原件。本轮没有复现DIRT/RDG，也没有把未取得全文或代码解释为方法不存在。

| 方法 | 本轮读取的一级来源 | 对H1判断的作用与限制 |
| --- | --- | --- |
| 官方SST / Control RRT | 本地锁定OMPL2.0.2源码、原接口和新实际构建；许可证沿用冻结BSD-3-Clause核验 | 真正运行原算法；SST固定半径不是SST*。本轮没有为本AUV模型重证理论假设。 |
| DIRT | [作者原文III-A—III-C](https://people.cs.rutgers.edu/~kb572/pubs/iros_dirt.pdf)，题名为Efficient and Asymptotically Optimal Kinodynamic Motion Planning via Dominance-Informed Regions；DOI 10.1109/IROS.2018.8593672沿用6D机构核验 | DIR引导和Blossom多候选扩展已有先例，宽泛的“引导扩展”不能作为原创贡献。具体时长条件化是否等价尚未证明。 |
| DIRT默认代码 | GitHub连接器实际读取作者[planner_functions.cpp第1—155行](https://github.com/PRX-Kinodynamic/ML4KP/blob/main/src/prx/planning/planner_functions/planner_functions.cpp)及[MIT LICENSE](https://github.com/PRX-Kinodynamic/ML4KP/blob/main/LICENSE) | 默认采样计划使用均匀整数时长，current未用于该默认时长；默认轨迹检查遍历状态。可替换框架仍可能容纳等价机制，默认实现不是完整排除证明。代码未复制入仓库。 |
| RDG | [官方提交记录](https://arxiv.org/abs/2609.22733)、[正文引言与III-B](https://arxiv.org/html/2609.22733v1)，题名Rapidly-Iterating Grid-Based Near-Optimal Kinodynamic Motion Planning；DOI 10.48550/arXiv.2609.22733 | 网格选点/修订及全支撑传播框架已公开；不能将“改变传播分布”单独算原创。本轮未定位作者代码及代码许可，未复现。 |
| Feng2024 | [出版商入口](https://www.sciencedirect.com/science/article/pii/S0952197624007413)本轮实际返回403；DOI 10.1016/j.engappai.2024.108583及题名沿用6D核验 | 未读全文，本轮不能排除具体机制重叠，作者代码及许可未核实。 |

RDG官方提交为2026-09-19，正文页头April2023；日期差异继续披露，不能将投稿记录当成期刊接受。没有直接照搬其其他系统的性能数字为AUV证据。VK-RRT*和约束前置AUV工作仍按6D已有读取范围引用，本轮没有假称重新读取其全文。

H1原候选是净距—姿态时间下界联合约束持续步数，并以全支撑混合和冲突回退保留原采样。它尚未实现或完成理论证明。SST的采样目标参与选点，不自动意味着随机控制会转向该目标；姿态所需时间只是必要下界，不能直接认定联合时长分布有效。

本轮PIVOT依据是**注册开发任务上的成熟基线已达到反对广泛瓶颈的门槛**，并非已证明与DIRT/RDG数学等价。全文和代码缺口继续使“创新性已证实”的表述不成立；无需借助不实的新颖性判断来解释PIVOT。未来参考契约问题同样需要独立查新和重新立项，本轮不声称它已经原创。
