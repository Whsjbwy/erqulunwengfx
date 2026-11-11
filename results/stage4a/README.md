# 第四阶段4A数据口径

协议在搜索前提交为70422ec，见[预注册协议](../../docs/STAGE4A_PROTOCOL_CN.md)。固定矩阵402次独立试验，阶段预检与主矩阵相同任务只运行一次；另外30次固定工作量计时单列，不混入主成功率。

- `runs.csv`：每个实际已完成任务一行，包含地图、端点、方法、参数、种子、总耗时、首次获解、最短有效长度、计数器、内存和负载。
- `angle_controls.csv`：四组固定角度的全部记录，另列完整锥理论射线数与不同方向数。真实逻辑射线次数与物理oracle次数保留，不以理论数代替实测。
- `anytime_curves.csv`：0.1/1/5/10/30秒之前完成严格认证的最佳路径。未获解时长度缺失、valid=False，不能填0。
- `incumbent_history.csv`：真实原始路径和shortcut改善事件；path_id引用仓库外的单份坐标记录。
- `map_level_summary.csv`：每图、方法和截点的覆盖率、条件长度、已获解任务首次时间。首次时间统计为最终获解子集，不是对未获解任务填30秒。
- `paired_comparisons.csv`：相同图/seed/截点的配对；共同有效时才定义相对长度收益，其余仍保留失败配对行。
- `statistical_summary.csv`：完整留出矩阵才生成相应对照的地图分层/图内配对bootstrap，95%区间及共同覆盖。8张图不是40张独立地图。
- `failure_audit.csv`：所有任务的停止与候选机制，包括有incumbent的时间截止和负例无误报。容量淘汰不是已证明丢失可行路线的数量。
- `timing_breakdown.csv`：搜索与管理、外部验证、shortcut互斥耗时；ray_and_collision_busy_s是包含在其中的忙碌子区间，不能再相加。
- `map_features.csv`：新地图的种子、尺寸、端点、占用率、见证长度和设计开口宽度。普通障碍/地形不伪称已求出全空间最窄通道。
- `engineering_equivalence.json`、`fixed_work_timing.csv`：非约束固定工作量等价性及各模式五次完整计时，缓存模式不替换主矩阵。
- `experiment_accounting.json`、`decision.json`：完整性及预注册Go/Pivot门槛。未完成必须保持Incomplete；不是把当前部分结果伪报成最终结论。

G-Sunlight四组使用冻结安全参考，外层允许预定随机流重启；RRT首解只运行一次，RRT重启用完同一30秒总预算。所有候选采用相同完整校验和可中断shortcut，不另给免费后处理时间。其结果身份是stage4a-budgeted-static-v1，不冒充原论文单次控制器。后处理未完成时可保留此前已确认的有效原始路径，best_kind明确区分。

本阶段strict_valid表示预算内曾接受严格有效解；False且没有坐标表示未获解，不等于返回了碰撞路径。非法候选由invalid_candidates另列，出现时立即停止批量。normal/backend停止状态与预算内曾有效分开。

actual_total_s包含所有规划内操作及测量管理，deadline_overshoot_s保留不可中断查询的实际超出；截止后确认的解不补记到截点。post_run_audit_s和post_run_diagnostics_s是额外事后核验/转折/间隙指标，不参与选解。进程峰值内存是在规划调用结束时读取的生存期峰值，包含导入/地图，尚不包含后续VTK间隙指标构建，不是纯搜索增量。

oracle_query_calls计完整折线验证或整射线遍历API次数，oracle_queried_segments另列累计请求线段数；逻辑射线、接受树节点、永久图节点不能混作统一采样节点。geometry busy计时不在每个体素插入时钟；固定工作量开销对照另列。

clearance_lower_bound为占用体素外接球与0.5单位采样间隔导出的Lipschitz保守下界，另取地图边界余量；不是精确最小距离。下界0不表示碰撞，正值也不构成实体AUV动力学认证。转折阈值1°，忽略零长度边。安全结论仍仅限闭体素中的零半径静态折线。

图选择D1/T4/T5/T7的seed0，事前固定；失败不以见证替换，障碍抽样只用于显示。主Go/Pivot只看冻结A4与RRT重启的留出结果，不从A1—A4中事后挑最佳方法。全部完整路径和日志仅在仓库外local_only/stage4a；公开文件均为自编合成实验结果。
