# 阶段8A真实文献矩阵

日期2026-11-20。检索范围为复杂流场、AUV运动约束、有限感知、安全可达/不变集与鲁棒跟踪；不是系统综述或“穷尽2026所有文献”的声明。五项7B-0近邻全部复核，另补五项原始方法。完整作者、正式题名、模型/控制、流信息、导数界、安全证书、实验、代码许可和Windows运行状态见`results/stage8a/tables/literature.csv`及其来源JSON。

| ID | 正式题名、年份、DOI | 本轮方法证据 | 代码与复现 |
|---|---|---|---|
| L1 | [A Hierarchical Trajectory Planning Framework for Autonomous Underwater Vehicles via Spatial–Temporal Alternating Optimization](https://www.mdpi.com/2218-6581/15/1/18)，Robotics2026；10.3390/robotics15010018 | 本轮仅摘要；7B-0 §2/3/5全文记录保留。完整已知流场假设来自此前记录，本轮未重获全文 | 官方精确实现/许可未定位；未运行 |
| L2 | [Safe and Optimal Motion Planning for Autonomous Underwater Vehicles: A Robust Model Predictive Control Framework Integrating Fast Marching Time Objectives and Adaptive Control Barrier Functions](https://www.mdpi.com/2504-446x/9/4/273)，Drones2025；10.3390/drones9040273 | HTML §3.2/4.1；二维、当前无洋流，MPC/CBF | 未定位/未运行；本项目未实现MPC |
| L3 | [Instantaneous planning, control and safety for navigation in unknown underwater spaces](https://www.sciencedirect.com/science/article/pii/S0029801826024613)，Ocean Engineering2026；10.1016/j.oceaneng.2026.126627 | [作者v1](https://arxiv.org/html/2604.05310v1) §I-C/II与不变区域；三维局部障碍感知、速度可控 | 未定位精确代码许可；ROS/Gazebo原生Windows未验证 |
| L4 | [FaSTrack: a Modular Framework for Real-Time Motion Planning and Guaranteed Safe Tracking](https://arxiv.org/html/2102.07039v2)，IEEE TAC2021；10.1109/TAC.2021.3059838 | 相对系统/HJ误差界/安全反馈；有界扰动集合 | [相关仓库](https://github.com/HJReachability/fastrack) BSD-3-Clause已核实；非2021全部实验精确复现；未构建 |
| L5 | [A meta-heuristic assisted path planning method for unmanned underwater vehicles and experimental validation](https://www.sciencedirect.com/science/article/pii/S0029801825023959)，Ocean Engineering2025；10.1016/j.oceaneng.2025.122712 | 仅官方检索摘要/元数据；正文403。时变流、B样条、安全/速度可行；其余未知 | 未定位/未运行；关键全文阻断 |
| L6 | [Safe Returning FaSTrack With Robust Control Lyapunov-Value Functions](https://doi.org/10.1109/LCSYS.2024.3410636)，IEEE CSL2024；10.1109/LCSYS.2024.3410636 | [作者v1](https://arxiv.org/html/2404.02472v1) §II–III；紧集合扰动下返回跟踪界 | 本篇扩展代码/许可未定位，不能借通用仓库替代 |
| L7 | [Parameterized Fast and Safe Tracking (FaSTrack) using DeepReach](https://proceedings.mlr.press/v242/jeong24a.html)，L4DC/PMLR242:1006–1017，2024 | 正式PDF方法及感知范围假设；参数化值函数近似与规划速度界 | 精确代码/许可未定位；未训练或运行 |
| L8 | [Model Error Propagation via Learned Contraction Metrics for Safe Feedback Motion Planning of Unknown Systems](https://doi.org/10.1109/CDC45484.2021.9683354)，CDC2021；10.1109/CDC45484.2021.9683354 | [扩展v2](https://arxiv.org/html/2104.08695v2) §III/IV/V；局部误差界、CCM管、可信域与采样规划 | 未定位精确代码；论文CC-BY不是软件许可；未训练/运行 |
| L9 | [Planning under uncertainty for safe robot exploration using Gaussian process prediction](https://link.springer.com/article/10.1007/s10514-024-10172-6)，Autonomous Robots2024；10.1007/s10514-024-10172-6 | 正式全文定义11/12、§6；GP-EstMDP安全可达/返回概率 | 精确实现/许可未定位；GPy依赖不是论文代码 |
| L10 | [Safety-Certificated Line-of-Sight Guidance of Unmanned Surface Vehicles for Straight-Line Following in a Constrained Water Region Subject to Ocean Currents](https://html.rhhz.net/jmsa/html/20230316.htm)，JMSA2023；10.1007/s11804-023-00351-9 | 正式全文§3假设、ESO/LOS与CBF/QP；二维USV、扰动及导数有界 | 官方代码/许可未定位；未运行控制器 |

L6、L8正式DOI由Crossref实际返回的题名、刊物和年份核对。L7的正式PMLR页面未列DOI，`10.48550/arXiv.2404.07431`属于预印本，不能写成正式会议DOI。L3作者预印本的Tejal Bedmutha与期刊元数据Tejal Jain不同，保留版本差异，不臆断身份变更原因。

## 三项最近邻的逐项差异审查

| 最近邻 | 已覆盖 | 仍需核实的具体区别 | 对本项目的限制 |
|---|---|---|---|
| L8，§IV-A/C/D | 训练点附近的Lipschitz误差界、误差传播管、可信状态/控制域、管与障碍相交时拒绝 | 有限流场测量下可验证局部时变界；固定正水速和特定yaw/pitch限制下持续安全判据 | 需要增量稳定性和概率验证；不能将其当作任意受限AUV均适用的现成证书 |
| L3，模型/不变集 | 三维、局部点云、重叠安全区域及反馈规划 | 流场值/梯度/时间不确定性与固定速度限制的联合机制 | 障碍感知与流场感知不同；可控surge与低层速度实现假设不能省略 |
| L7，参数化方法 | 环境余量相关的速度/误差管调整，减少保守性的成熟思路 | 同流信息、同物理限幅下是否仍有独立于参数化管的机制 | 学习近似和感知范围前提要保留；不能为了通过改变物理转向限幅 |

“未覆盖”不能由全文中未检索到关键词推断。上表中的待核实区别只是问题清单，没有证明原创，也没有证明全部论文等价。关键L5全文缺失，因此当前不能完成排除等价性的准入论证。

## 检索与访问限制

检索使用真实题名/DOI、出版页面、作者arXiv/PMLR方法正文及GitHub仓库搜索。`access_log.json`记录返回内容和失败；HTTP403/Access Denied是访问限制，不是论文不存在，也没有尝试绕过访问限制。GitHub精确检索为空只能说明本次未定位。

除相关FaSTrack仓库外，均未核实精确官方代码及软件许可；所有外部方法本轮均未构建、训练或运行。Windows/资源可行性只作依赖审查，不宣称已完成复现。没有将外部论文PDF或外部源码提交到仓库。
