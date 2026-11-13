# 阶段5A-E精简证据

以[中文协议](../../docs/STAGE5AE_PROTOCOL_CN.md)、[中文报告](../../docs/STAGE5AE_REPORT_CN.md)、[实际命令](../../docs/STAGE5AE_COMMANDS_CN.md)、[测试记录](../../docs/STAGE5AE_TEST_RESULTS_CN.md)为解释入口。

这些CSV记录实际实验，不能把软件测试条数当科研实验数。旧157条路径只作开发/诊断；新12图×5种子×3规划器×2包络共360个规划任务。36次资源门槛被正式矩阵复用，未重复计数。几何可达认证仅适用于球包络，不证明姿态约束运动可达或实际AUV可行。

| 文件 | 含义 |
| --- | --- |
| `e0_analytic.json`、`e0_audit.json` | 正负解析例、独立积分、450历史结果字段复核、固定12条原基准复现 |
| `historical_failures.csv` | 5A-R全部910个失败条件的首次连续区间、进度、目标、姿态、局部间隙诊断 |
| `historical_projection_jumps.csv` | 旧轨迹177个最近点映射跳变标记，仅作描述，不自动认定代码缺陷 |
| `development_pilot_manifest.csv` | 先验固定12条路径，不按新控制结果选择 |
| `development_runs.csv` | 157条开发路径的1099个条件记录，含引用旧轨迹和完全相同输入的复用 |
| `development_map_summary.csv`、`development_paired.csv` | 旧6图逐图成功、恢复与退化；不作独立验证 |
| `processing_reference.csv` | 全157条raw路径的水平fillet适用/拒绝；非水平不支持亦完整保留 |
| `horizontal_reference.csv` | 固定水平场景6个真实执行条件；`input_*`为各自输入指标，`curve_reference_*`仅为共享圆弧元数据 |
| `independent_map_audit.json` | 新配方、尺度、起终点、体素比例、body/margin几何可达证书 |
| `resource_gate.json` | 36次门槛实测成本、内存、超时量及技术通过条件 |
| `operational_deviation.json`、`resource_recheck.json`、`resource_recheck_runs.csv` | 误启动重复worker的完整偏离和受影响单任务的预登记复核；不替换主360任务 |
| `planning_runs.csv` | 360次规划任务、10秒预算、首次认证时间、原始长度、计数、内存；无路径长度为空 |
| `execution_runs.csv` | 每任务raw/shortcut×旧/LOS共1440个登记条件，包含未执行占位；`was_run`区分实际运行与无路径 |
| `map_summary.csv` | 每图/方法/包络/处理/控制的三层分母、成功数、耗时、到达误差、间隙和饱和 |
| `cluster_summary.csv` | 以整张地图为单位的探索性95% bootstrap区间，未定义比率为空 |
| `independent_paired.csv`、`paired_cluster_summary.csv` | 控制与处理分别配对，保留恢复、退化、共同失败和地图聚类差异区间 |
| `failure_counts.csv` | 含成功、安全拒绝、无路径和包络负例的分类全账，不把未执行算跟踪失败 |
| `failure_curve_reference.csv` | 首次安全拒绝区间的独立点到盒距离与Lipschitz下界；球模型交叠、可认证安全和未决接触带分开 |
| `terminal_diagnostics.csv`、`terminal_boundary_check.json` | 全87个误差失败条件的末端进度诊断、冻结LOS有限终点适配的事后解析边界核查；不用于改写独立实验 |
| `experiment_accounting.json`、`independent_audit.json` | 完成状态、记录/轨迹复用分账、全矩阵和原始轨迹复核 |
| `figure_manifest.csv` | 三类图固定第一张新图、seed0、body的36个展示条件，可追溯到原记录 |
| `local_checks.json`、`pytest_results.csv`、`windows_ci.json` | 本机实际退出状态、逐项软件测试与GitHub官方Windows日志证据 |
| `check_history.json`、`execution_evidence.json`、`figure_qa.json` | 编码测试失败与修复、原正式进程退出0及重复进程退出1、逐图显示检查 |

图表：`development_controls.png`、`horizontal_reference.png`、`independent_rates.png`、`ordinary_tracks.png`、`narrow_tracks.png`、`nearbed_tracks.png`。图中点云和地形只为显示稀疏化，所有几何认证使用完整地图；曲线认证使用解析积分和扩大的弦界，不使用图上稀疏点替代。

完整原始规划/逐步轨迹仅在`D:\2区论文复现\local_only\stage5ae`单份保存；旧轨迹在`stage5ar`原位引用。没有额外文件hash清单；未包含作者PDF/外来源码/原地图/凭据/环境。科研结论只限于预注册静态仿真模型。
