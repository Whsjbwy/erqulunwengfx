# 阶段三结果字段与复查

实验先固定[协议](../../docs/STAGE3_EXPERIMENT_PROTOCOL_CN.md)，再运行。结论、限制与是否继续主线见[中文报告](../../docs/STAGE3_REPORT_CN.md)，运行方法见[命令](../../docs/STAGE3_COMMANDS_CN.md)。

- `s3.csv`：Paper/Safety 在 S3 上各五次，内部首次严格有效路径和改善历史。
- `capacity.csv`、`size.csv`：顺序执行的两个单因素实验。容量实验固定宽度5；宽度实验固定容量1。
- `sampling.csv`：仅当 A/B 的 S1 全部未找到有效路径时执行的独立单因素诊断。
- `astar.csv`：确定性 A* 节点预算及必要的单独时间预算测试，每个配置只计一次。
- `stop.csv`：单独版本 `stage3-stop-first-v1`，不冒充论文控制器的完整搜索时间。
- `baselines.csv`：同地图同预定种子的 RRT-Connect 新对照。
- `holdout_selection.json`、`holdout.csv`：先用开发集冻结一个单因素设置，再在 H1/H2 评估。
- `unique_runs.csv`：真实已完成试验的去重表，含完整算法参数、版本、内存、计数器和指标。
- `summary.csv`：按阶段、地图、方法、参数、时间、节点预算和测量模式分组；复用参照仍对应原 `job_id`。
- `incumbent_history.csv`：实际记录的首次与后续严格长度改善，不以最终路径倒填历史。
- `failure_counts.csv`：终止原因计数，包含有有效 incumbent 的预算截止，不能全部称为无路径失败。
- `candidate_spatial_counts.csv`：S1 seed0 被淘汰、展开和终止时仍保留节点的20单位空间分箱，仅为事件分布。
- `candidate_event_summary.csv`：同一事件流的时间范围、坐标范围和不同容量网格单元数，便于核查搜索实际覆盖区域。
- `profiling.csv`：cProfile 的函数自身时间分组，避免嵌套累计时间重复相加。
- `profiling_equivalence.json`：三种固定工作量模式的实际路径、计数器和状态一致性。
- `sampling_path_geometry.csv`：45°诊断返回路径的实际边出发角，属于事后解释，不是可达性证明。
- `experiment_accounting.json`：112次搜索、130条设计视图等总账，不作为异构设置混合成功率。
- PNG：事前固定 seed0 路径、单因素有效率和 S3 改善历史。失败图不使用见证路径代替实际规划结果。

`valid_solution_found_by_30s` 表示预算内曾经独立确认过有效完整路径；`normal_completion_by_30s` 表示状态正常且30秒内结束。两者不能互换。`unique_runs.csv` 另派生 `budget_valid_success`，沿用阶段二正常结束、报告成功、严格有效且搜索时间不超预算的定义。缺失首次时间保留空值，未观察的首次指标不伪填零；汇总另列 `valid_by_budget_known_runs`。

G-Sunlight 首次时间在内部完整路径形成并独立验证后记录；A*/RRT 时间在其首次返回路径并独立验证后记录。主计时包含观察开销。进程峰值内存含导入和地图加载，不是纯搜索增量；节点、射线和树顶点定义因方法而异。

每个汇总组的 `runs` 按 `job_id` 去重，`design_view_rows` 另保留设计视图行数。采样步长与半锥角两组共用的参照不能计作六次独立实验。

所有严格有效仅指零半径静态折线，不能用于声称实体 AUV 已安全。S0/S4 没有作为阶段三新实验重跑；阶段二记录保持原样。原始每次试验的完整证据只保存在仓库外 `local_only/stage3`，公开表可由分析模块重新导出，不复制大型数据。

路径图展示原始折线，长度公平比较使用表中的共同shortcut结果。障碍体素经过显示抽样，碰撞判断始终使用完整占用图；图像不能替代连续安全验证。
