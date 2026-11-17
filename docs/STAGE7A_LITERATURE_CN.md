# 7A文献与官方代码核验

查阅时间：2026-11-16—2026-11-17。共13项，11项为2023—2026年、2项为基础文献。10项取得可读全文并重点阅读方法；L01/L02/L04实际范围单独注明。未取得全文或未定位代码不等于不存在。

## 检索与证据边界

使用题名/DOI检索，优先出版社、作者主页、机构仓储和arXiv；代码通过作者相关GitHub仓库核查README、源文件和LICENSE。论文DOI与arXiv DOI分开。只读核验，不下载外部依赖、不执行外部算法，不构成系统综述的穷尽性声明。

正式文献矩阵：[CSV](../results/stage7a/literature_matrix.csv)，机器可读完整记录：[JSON](../results/stage7a/literature_sources.json)。

## L01 · An Adaptive Line-of-sight (ALOS) Guidance Law for Path Following of Aircraft and Marine Craft

年份/出处：2023；IEEE Transactions on Control Systems Technology 31(6), 2887–2894。DOI：[10.1109/TCST.2023.3259819](https://doi.org/10.1109/TCST.2023.3259819)。

实际阅读：[来源](https://www.fossen.biz/publications/)；未取得全文；作者出版目录核实题名和DOI，另读作者MSS相关ALOS代码；不冒充逐式复现。

方法与限制：作者ALOS代码属于自适应侧滑补偿引导；原论文证明的完整假设未逐项核实。

代码：https://github.com/cybergalactic/MSS。许可：MIT，已读根LICENSE；不保证当前版本等同论文版本。

Windows/模型适配：MATLAB实现，未执行；MSS许可不等于MATLAB运行时许可。具体差异：本项目无侧滑扰动，仅恒速Euler角速率输入；ALOS名称或自适应项不是T1原创依据。

## L02 · A uniform semiglobal exponential stable adaptive line-of-sight (ALOS) guidance law for 3-D path following

年份/出处：2024；Automatica 163, 111556。DOI：[10.1016/j.automatica.2024.111556](https://www.sciencedirect.com/science/article/pii/S0005109824000487)。

实际阅读：[来源](https://github.com/cybergalactic/MSS/blob/master/GNC/ALOS3D.m)；出版元数据/摘要核实；机构旧PDF转到NVA脚本页面，未取得论文全文；已读ALOS3D.m与LOSobserver.m。

方法与限制：作者代码输出期望heading/pitch，并明确建议用角度/角速度观测器处理航点切换；接受圆半径须小于最小航点间距。

代码：https://github.com/cybergalactic/MSS/blob/master/GNC/ALOS3D.m。许可：MIT，已核实MSS LICENSE。

Windows/模型适配：MATLAB；NED向下z需映射为本项目向上z；0.1m密集点不能盲用米级接受圆；本阶段未移植。具体差异：角速率前馈/平滑已成熟；代码本身未提供本项目折线、限幅内环和连续障碍认证的整体证明。

## L03 · A spherical amplitude–phase formulation for 3-D adaptive line-of-sight (ALOS) guidance with USGES stability guarantees

年份/出处：2026；Automatica 192, 113149（作者出版目录）；全文读作者预印本v2。DOI：[10.1016/j.automatica.2026.113149](https://doi.org/10.1016/j.automatica.2026.113149)。

实际阅读：[来源](https://arxiv.org/html/2505.08344v2)；已读预印本方法§4假设1–2及定理1；v1为2025，v2为2026-02-26；出版社DOI跳转访问失败。

方法与限制：球坐标幅相重新定义三维耦合；假设heading/pitch完美跟踪、真实crab角缓变，不能借USGES越过实际限幅内环。

代码：未定位与此2026版本一一对应的作者代码；MSS为相关实现。许可：论文对应代码许可未核实。

Windows/模型适配：代数引导量轻量；完整证明前提未满足，未执行或安装。具体差异：当前恒速无侧滑模型与有受限内环场景不同；不是障碍安全管证明。预印本另有DOI 10.48550/arXiv.2505.08344。

## L04 · A Virtual Reference Point Kinematic Guidance Law for 3-D Path-Following of Autonomous Underwater Vehicles

年份/出处：2024；IEEE Access 12, 109822–109831。DOI：[10.1109/ACCESS.2024.3440659](https://doi.org/10.1109/ACCESS.2024.3440659)。

实际阅读：[来源](https://ub-ir.bolton.ac.uk/esploro/outputs/journalArticle/A-Virtual-Reference-Point-Kinematic-Guidance/9921073608841)；作者目录与机构索引核实；索引可读§III/IV方法片段；带过期签名PDF链接未作为已取得全文。

方法与限制：虚拟参考点/路径粒子及两级反馈线性化用于Remus100；索引片段要求正则路径、虚拟粒子切向运动。

代码：未定位论文对应官方仓库。许可：代码许可未核实。

Windows/模型适配：未核实可运行版本；需要动态内环与VRP坐标映射，不直接等于当前五状态。具体差异：虚拟参考点、路径进度及运动学引导已被研究；未读全文部分不能声称已排除等价方法。

## L05 · A Model-Based Kinematic Guidance Method for Control of Underactuated Autonomous Underwater Vehicles

年份/出处：2024；Control Engineering Practice 152, 106068。DOI：[10.1016/j.conengprac.2024.106068](https://doi.org/10.1016/j.conengprac.2024.106068)。

实际阅读：[来源](https://www.fossen.biz/publications/2024%20Degorre%20et%20al%20CEP.pdf)；取得17页作者全文；重点§2模型、§3.1式12–15、§4 Handy矩阵和§5比较设计。

方法与限制：外层位置姿态PI加期望速度前馈，内层反馈线性化；Handy矩阵通过运动学耦合补偿缺少sway驱动；前馈要求至少C2参考。

代码：未定位论文对应官方仓库。许可：代码许可未核实。

Windows/模型适配：可讨论公式，但水动力参数/执行器拓扑不同；未复现，不作为本项目原生模型即插即用控制器。具体差异：姿态/速度前馈和引导控制协调是已有内容；折线本身不满足其光滑条件。

## L06 · Intelligent-PID with PD Feedforward Trajectory Tracking Control of an Autonomous Underwater Vehicle

年份/出处：2023；Machines 11(2), 300。DOI：[10.3390/machines11020300](https://www.mdpi.com/2075-1702/11/2/300)。

实际阅读：[来源](https://www.mdpi.com/2075-1702/11/2/300)；已读HTML§2、§3控制和§4.1–4.2模拟设计；Data Availability为Not applicable。

方法与限制：LIVA六自由度模型，i-PID与PD前馈混合；作者结果指出角向额外前馈并非总改善；模拟含噪声和参数不确定性。

代码：文章未提供可核实官方仓库；检索未定位。许可：代码许可未核实；论文开放不等于软件许可。

Windows/模型适配：公式可实现但原植物为推力/力矩动力学；本阶段未运行；不能替换五状态后混比分数。具体差异：前馈属于成熟研究；不能把六自由度论文的鲁棒性移植成我方实证。

## L07 · Governor-parameterized barrier function for safe output tracking with locally sensed constraints

年份/出处：2023；Automatica 152, 110996。DOI：[10.1016/j.automatica.2023.110996](https://www.sciencedirect.com/science/article/pii/S0005109823001498)。

实际阅读：[来源](https://existentialrobotics.org/ref/Li_GCBF_Automatica23.pdf)；取得8页作者全文；已读§2–4式1–10及安全调节问题。

方法与限制：以局部障碍距离和输出调节Lyapunov能量构造PBF；§3要求固定参考点存在稳定平衡，§2为LTI，扩展到反馈可线性化系统。

代码：未定位该论文可核实官方实现。许可：代码许可未核实。

Windows/模型适配：低维代数思想可CPU研究，但恒速1m/s无法在固定点平衡，不能直接套用原定理。具体差异：安全间隙与跟踪能量共同调节参考已有明确最近邻；T2须证明新机制而非改名。

## L08 · Fast Iterative Region Inflation for Computing Large 2-D/3-D Convex Regions of Obstacle-Free Space

年份/出处：2025（预印本2024）；IEEE Transactions on Robotics，出版社DOI检索核实；读arXiv v3。DOI：[10.1109/TRO.2025.3562482](https://doi.org/10.1109/TRO.2025.3562482)。

实际阅读：[来源](https://arxiv.org/html/2403.02977v3)；已读HTML§III算法与§IV半空间计算；DOI搜索命中官方解析记录，直接打开失败；预印本DOI 10.48550/arXiv.2403.02977。

方法与限制：交替限制性膨胀和最大体积内接椭球，凸无障碍区可包含指定种子；几何走廊不自动给出闭环误差界。

代码：https://github.com/ZJU-FAST-Lab/GCOPTER/blob/main/gcopter/include/gcopter/firi.hpp。许可：MIT，已读头部和根LICENSE；文件明确声明是旧版，不冒充论文最新版。

Windows/模型适配：头文件核心依赖Eigen/局部优化；整仓ROS部署未验证，未构建。具体差异：安全走廊是成熟几何模块；当前原生连续认证与跟踪可达管是另外两项要求。

## L09 · Safe Returning FaSTrack with Robust Control Lyapunov-Value Functions

年份/出处：2024；arXiv预印本2404.02472v1；未核实另有正式出版DOI。DOI：[10.48550/arXiv.2404.02472](https://arxiv.org/abs/2404.02472)。

实际阅读：[来源](https://arxiv.org/html/2404.02472v1)；已读HTML§II-B/II-C、式5–9与返回误差管条件。

方法与限制：相对动力学、预设扰动界、HJ误差界和R-CLVF允许从误差管外返回；较大扰动界会扩大障碍膨胀并减少可通行性。

代码：未定位该返回扩展的官方实现；不以通用FaSTrack仓库冒充。许可：对应代码许可未核实。

Windows/模型适配：离线可达性计算资源需另验；未计算本项目五状态相对系统可达集。具体差异：失败恢复与安全误差管已有工作；T2不能只提出回到安全走廊。

## L10 · Parameterized Fast and Safe Tracking (FaSTrack) using DeepReach

年份/出处：2024；arXiv预印本2404.07431v1；未核实另有正式出版DOI。DOI：[10.48550/arXiv.2404.07431](https://arxiv.org/abs/2404.07431)。

实际阅读：[来源](https://arxiv.org/html/2404.07431v1)；已读HTML§2相对动力学/式3–5、§2.2参数化可达性与神经近似。

方法与限制：对规划器控制集合参数化HJ值函数，用DeepReach估计；以控制能力/速度换误差管大小。

代码：未定位该文一一对应官方仓库；不能以框架代码等同论文复现。许可：对应代码许可未核实。

Windows/模型适配：神经训练与离线高维可达性不属本阶段实施范围，未运行。具体差异：规划跟踪能力协同不是空白；本项目禁止增加新网络，故仅文献对照。

## L11 · Path Following Model Predictive Control of a Coupled Autonomous Underwater Vehicle

年份/出处：2024；IFAC-PapersOnLine 58(20), 183–188。DOI：[10.1016/j.ifacol.2024.10.052](https://strathprints.strath.ac.uk/91602/)。

实际阅读：[来源](https://strathprints.strath.ac.uk/91602/1/Jimoh-Yue-IFAC-PapersOnLine-2024-Path-following-model-predictive-control.pdf)；取得6页机构全文；已读§2模型、§3 LOS与minimax控制设计、§4模拟和未来碰撞避免限制。

方法与限制：耦合三维位置姿态引导，速度增量为优化变量，对有界扰动做minimax MPC；文末将实时避障列为后续研究。

代码：机构记录未提供可核实官方代码；未定位。许可：软件许可未核实；论文CC BY-NC-ND不自动授予代码许可。

Windows/模型适配：求解器与耦合动态模型需另验；本阶段与7B草案均不实现MPC。具体差异：三维规划执行协调与扰动跟踪已有研究；原论文不等同我方连续障碍安全基线。

## L12 · Funnel Libraries for Real-Time Robust Feedback Motion Planning

年份/出处：2017（基础文献）；International Journal of Robotics Research 36(8), 947–982。DOI：[10.1177/0278364917712421](https://collaborate.princeton.edu/en/publications/funnel-libraries-for-real-time-robust-feedback-motion-planning/)。

实际阅读：[来源](https://arxiv.org/html/1601.04037v3)；机构记录核实DOI；作者12.6MB PDF被工具大小限制，改读HTML§4式7–14、§7/8实验与限幅处理说明。

方法与限制：名义状态/输入轨迹加反馈，围绕轨迹计算前向可达漏斗；用Lyapunov/SOS条件和碰撞排除组合轨迹。

代码：https://github.com/RobotLocomotion/drake。许可：当前Drake BSD-3-Clause已核实；论文原示例的历史版本/依赖未还原。

Windows/模型适配：当前Drake官方支持表无Windows，未安装；SOS离线求解不能当作现有连续oracle的同义替代。具体差异：保留时间/状态/控制和误差管已是基础做法；论文实验并不普遍包含所有饱和与不确定性。

## L13 · FaSTrack: a Modular Framework for Real-Time Motion Planning and Guaranteed Safe Tracking

年份/出处：2021（基础文献）；IEEE Transactions on Automatic Control 66(12), 5861–5876。DOI：[10.1109/TAC.2021.3059838](https://minerva-access.unimelb.edu.au/items/1e0f211b-981b-5e30-b892-62657d440cfd)。

实际阅读：[来源](https://arxiv.org/html/2102.07039v2)；作者机构记录核实DOI；读HTML§III–V相对系统、值函数、误差界不变性；预印本DOI 10.48550/arXiv.2102.07039。

方法与限制：区分低维规划器与受扰跟踪器，离线HJ最坏情形误差界，在线用该界膨胀障碍并选择安全控制。

代码：https://github.com/HJReachability/fastrack。许可：BSD-3-Clause已核实；README引用2017原工作/2018扩展，不声称精确等同2021全部实验。

Windows/模型适配：README为ROS/catkin、MATIO/Eigen/FLANN等依赖，原生Windows未验证；不安装或切换系统。具体差异：低维规划加安全跟踪的主问题已成熟；我们的实现/模型差异本身不足证明T2原创。

## 强对照的选择与科研判断

成熟时间参数化基线选名义状态/输入前馈加有限时域LTV-LQR，数学定义与接口已由[Drake官方控制器文档](https://drake.mit.edu/pydrake/pydrake.systems.controllers.html)核实。当前[BSD许可](https://github.com/RobotLocomotion/drake/blob/master/LICENSE.TXT)已读，[平台表](https://drake.mit.edu/installation.html)无官方Windows支持。建议未来以本项目NumPy实现标准离散Riccati并重新验收，不声称已在本机复现Drake。

MSS ALOS3D.m明确提示配合[LOSobserver](https://github.com/cybergalactic/MSS/blob/master/GNC/LOSobserver.m)产生平滑期望角度/角速度。其当前文件含2026-11-03修订，不可冒充2024论文原始代码；角速度输出也不等于完整障碍安全证明。NED符号、航点接受半径和当前密集折线需单独审查。

T1的时间/姿态/前馈保留与成熟跟踪高度重合；T2与PBF、FaSTrack、Funnel Libraries、FIRI等明确重合。现有材料不足支持新原创机制，故PIVOT。没有以代码未检索到、论文访问受限或Windows移植困难作为新颖性证据；没有声称这些方法在47条历史轨迹上已经实测成功。

## 访问受限与额外线索

曲率/B-spline候选题名及DOI `10.1016/j.engappai.2024.108583` 来自前阶段线索；本轮出版社PII页面403，未重新获得足够的一手全文证据，因此不计入13项已核验主矩阵，不据其摘要推断定理或实现。VRP机构索引只读到方法片段；过期签名URL不写入长期证据链接。FIRI已读作者预印本与作者旧版实现，直接出版社DOI打开失败，如需逐式比对最终出版版还需补取。
