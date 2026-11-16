# 6C最近邻方法与代码许可复核

本轮实际联网审查日期为2026-11-15；完整继承6A/6B矩阵，新增访问状态见[literature_matrix.csv](../results/stage6c/literature_matrix.csv)。没有联系作者、绕过付费访问或上传论文/外部源码。

## Feng2024

题名为 *Smooth path planning under maximum curvature constraints for autonomous underwater vehicles based on rapidly-exploring random tree star with B-spline curves*，DOI[10.1016/j.engappai.2024.108583](https://doi.org/10.1016/j.engappai.2024.108583)。出版商完整入口本轮仍返回403；搜索索引仅提供摘要/引言片段。可确认BSRRT*、曲率约束、B样条与姿态节点对主题，但完整方法和合法作者代码仍未取得，不能排除细节重叠。[出版商](https://www.sciencedirect.com/science/article/pii/S0952197624007413)

## 作者control DIRT

[作者项目页](https://pracsys.github.io/projects/)仍链接[ML4KP](https://github.com/PRX-Kinodynamic/ML4KP)。实际重读MIT LICENSE、dirt.cpp的DIR/blossom相关代码和planner_functions.cpp。默认时长抽样使用均匀整数与simulation_step缩放，默认采样未使用传入姿态；有效性检查遍历离散轨迹状态。它不能直接替代本项目连续球扫掠适配。[默认函数源码](https://github.com/PRX-Kinodynamic/ML4KP/blob/main/src/prx/planning/planner_functions/planner_functions.cpp)

本轮读取main URL，分支连接器未返回提交ID；6B已验证的`064015a7545e1713cbcad3e79807b5cec0849f54`继续作为历史定位，不宣称当前main与之逐字节相同。可替换采样接口说明框架允许其他机制，不能由默认函数未见H1推断整个领域不存在等价方法。

[OMPL PR #1340](https://github.com/ompl/ompl/pull/1340)重新查询仍open且未合并，HEAD仍`661054add1a43e62531f5bf9f698558416631395`、4文件，与6B所读geometric DIRT版本一致；不能写成正式发布的control DIRT。本阶段未编译或实验DIRT。

## RDG与准入边界

*Rapidly-Iterating Grid-Based Near-Optimal Kinodynamic Motion Planning*（Moncton、Frew），arXiv2609.22733v1正文仍可读。本轮复读III-B：用随机控制和有界随机时长传播，另由网格选点/代表更新管理树；框架允许满足相应支撑条件的传播器。[原文](https://arxiv.org/html/2609.22733v1)

定向题名、作者和代码检索，以及原文链接核对，仍未定位可核验的作者代码与许可证。状态是not_located/not_verified，不是“代码不存在”。未核验期刊DOI，也不把论文许可当作代码许可。

目前没有证据证明H1的净距—姿态联合条件时长具有已确认的新颖性；也没有找到足以据此断言数学等价的完整先验。两种不确定性都保留。结合参考表示依赖和开发地图覆盖，当前选择Need More Evidence，不建议原型准入。
