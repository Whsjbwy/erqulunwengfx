# 5A数据字段与证据边界

当前状态请看experiment_accounting.json；complete=false表示尚未完成矩阵，不得据部分结果宣称最终结论。

- runs.csv：每个完成的独立任务一行。phase区分135功能、45开发和270留出；dataset_revision明确地图修正版。半径、预算、步长、地图/端点、规划报告、严格几何、名义机体复核与执行结果分别保留。
- executions.csv：每条被实际评估的唯一raw-best/selected路径一行，不含完整轨迹。原始和选中路径相同只评估/存储一次。eligible=false为名义机体几何拒绝，不能当成控制器已运行后失败；无路径时主表执行为缺失。
- map_summary.csv：每图×方法×规划半径；有解长度只对有效任务统计，并列有效数和执行分母。封闭/孔径不足是指定包络模型负例，不并入已知可达的算法覆盖率。
- paired_comparisons.csv、paired_map_summary.csv：相同图/seed配对，保留失败；共同几何有效才定义长度收益，先图内平均再比较地图。6图不是90张独立地图，不声称显著性。
- anytime_curves.csv、incumbent_history.csv：真实认证时间与1/5/10/30秒视图。功能3秒只有1秒截点；后续路径不能倒填较早截点，跟踪耗时不计作规划改善。
- failure_log.csv、failure_counts.csv：逐次/分类失败和停止原因，包括规划预算、包络不可达、名义尺寸拒绝、物理扫掠/任务带认证拒绝、误差、执行超时或安全余量不足。扫掠认证失败不自动等于已证明实际穿透。
- path_features.csv：选中和原始路径的段俯仰、尖角及固定初始朝向差。尖角不赋有限曲率，相关性不证明某一特征唯一导致失败。
- map_features.csv：14张新图、单位米、spacing、端点、占用率、h范围、设计孔径及逐尺度证书；完整体素只在内存生成，不发布大地图副本。
- map_amendment_regression.json：O1/O2重复地图修正的几何回归计数和185条完整任务复用记录，不是文件hash或文件校验清单。原185份记录及1份中止尝试保留在旧本地目录。
- windows_ci.json：实际GitHub Windows运行与精简官方日志，CI不重跑科研矩阵。

strict_geometry_valid表示当前规划半径下预算内已有认证路径；nominal_body_valid则始终使用约1.0198米球包络，即使规划模式为point。execution_success使用同一个有限尺寸无洋流模型；margin模式还要求全程.25米额外余量。physical_execution_success只取消额外余量要求，仍要求任务带、输入/姿态限制和位置到达。

min_physical_clearance_lower_bound_m与min_mission_clearance_lower_bound_m是3米截断、扣除曲线弦偏差的保守间隙下界。positive只适用于给定球包络与静态模型，不能称真实6DOF认证。rate_limit_violations=0常由限幅保证，须结合饱和次数及跟踪失败解释。

实际规划总时间包含搜索、独立确认及共同shortcut，三项互斥计时相加；post_run_audit_s、地图生成/见证及tracking_wall_s在规划之后或之前单列。RSS为进程生存期峰值，含导入/地图，不能称纯算法增量。原子计算超出记录deadline_overshoot_s，迟到认证不接受。

固定图为H5_O1/B1/N1/N2、seed0、body规划模式，保留失败；显示体素和轨迹稀疏化仅用于绘图。真实模型每.1秒作曲线扫掠认证，不靠图上点采样判安全。原始与选中路径可能来自不同incumbent，二者执行差异不是纯shortcut因果消融。
