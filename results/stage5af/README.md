# 阶段5A-F精简科研证据

入口：[中文报告](../../docs/STAGE5AF_REPORT_CN.md)、[预注册协议](../../docs/STAGE5AF_PROTOCOL_CN.md)、[实际命令](../../docs/STAGE5AF_COMMANDS_CN.md)、[测试记录](../../docs/STAGE5AF_TEST_RESULTS_CN.md)。完整参数在`configs/stage5af_protocol.json`、`stage5af_maps.json`及开发后冻结的`stage5af_selected.json`。

| 文件 | 口径 |
| --- | --- |
| `gate1_analytic.json` | 7个指令正反例、13个实际模型/安全例；不是新地图科研样本 |
| `pilot_manifest.json` | 按既有ID固定选择6个任务×raw/shortcut=12条件，复用到全612 |
| `development_runs.csv` | 360旧任务×6登记条件=2160；306获解任务共1836实际条件，其中1224历史引用、612新修正 |
| `development_map_summary.csv` | 旧E_*仅开发回归，按图/方法/包络/处理/控制的完整三层分母 |
| `development_paired.csv` | 同路径旧LOS/原控制→修正及三控制各自raw→shortcut，保留恢复/退化和误差改善却安全拒绝 |
| `terminal54_paired.csv` | 旧54个末端相关误差条件逐ID的新结果，不能包装成54条独立规划路径 |
| `terminal_mechanisms.csv` | 所有真实修正条件的切换状态、实际速度与目标夹角、目标俯仰与姿态误差；区分首次失效在切换前/后，只读分析不重跑 |
| `development_audit.json`、`development_failure_reference.csv` | 612新条件全区间/独立积分审计及首次安全拒绝的点到盒/Lipschitz参考 |
| `development_plan_metadata_audit.json` | 新增预算、半径、无路径首证、首证时间/端点断言对360旧规划的补充只读验收 |
| `independent_map_audit.json` | 12新图、名义球直连受阻、几何见证与包络负例；不是姿态受限可达证明 |
| `resource_gate.json` | 18任务技术/资源门槛，完整复用到正式216，不累计成234 |
| `planning_runs.csv` | 正式216次10秒规划任务、预算/首次证书/全局rawID/原索引/计数/内存，无路径长度为空 |
| `execution_runs.csv` | 216任务×raw/shortcut×3控制=1296登记条件；`was_run`区分真实执行与无路径 |
| `map_summary.csv`、`cluster_summary.csv` | 逐图条件数/成功数/耗时/误差/间隙/饱和与整图聚类探索性95%区间 |
| `independent_paired.csv`、`paired_cluster_summary.csv` | 分离终点修正、原控制参考与路径处理，恢复和退化完整配对 |
| `*_failure_counts.csv`、`independent_failure_reference.csv` | 含无路径/包络负例的分类账，首次安全拒绝独立诊断，不等同实体碰撞 |
| `independent_audit.json`、`experiment_accounting.json` | 正式完整矩阵、轨迹/前缀/终点目标/曲线安全/独立RK4与分账 |
| `figure_manifest.csv` | 固定旧O1/O3各前3个终端失败ID，新每类首图seed0/body所有三方法，两处理/三控制；不按恢复挑图 |
| `local_checks.json`、`pytest_results.csv`、`windows_ci.json` | 实际本机退出码、逐项软件测试和官方Windows CI日志证据，测试数不是科研实验数 |
| `figure_qa.json`、`delivery_audit.json` | 六图实际目视检查、历史跟踪文件不变与发布范围审查；不含文件hash |

图表共6张：旧开发逐图成功`development_controls.png`、旧终端邻域对比`development_terminal.png`、新三分母及区间`independent_rates.png`、新普通/窄通道/近底固定轨迹`ordinary_tracks.png`、`narrow_tracks.png`、`nearbed_tracks.png`。点云和地形显示稀疏化不替代完整几何认证。

完整记录保存在仓库外`D:\2区论文复现\local_only\stage5af`，旧轨迹原位引用，没有复制作者材料、凭据或环境，没有额外SHA256/MD5/文件hash清单。数学方向修正不保证固定正速度/转向限制下任意终点状态都收敛；安全拒绝和失败全部保留，不用成功率数字定义基线合格。
