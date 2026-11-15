# 阶段6C证据索引

结论为**Need More Evidence**。C1固定21条原生路径，LOS由11/21变14/21；C2固定72次实际搜索，47原生exact、25approximate，严格M46、参考Gref/E46、严格S34。1条缺原始时钟的真实pilot保留失败，不重搜。

| 文件 | 实际口径 |
| --- | --- |
| `pr10_verification.json`、`c0_audit.json`、`c0_jobs.csv` | PR10准确HEAD/最终CI与36原始任务独立审核 |
| `c1_acceptance_checks.json` | 配对前13项解析/安全测试 |
| `c1_paired.csv`、`c1_transition_counts.csv` | 全21同源配对及11/0/3/7四格 |
| `c1_terminal_events.csv`、`c1_analysis.json` | 两版本切换/投影/首次失效区间及只读复核 |
| `c2_interface_cases.csv`、`c2_interface_acceptance.json` | 新原生适配器13例实际验收 |
| `c2_manifest.json`、`c2_accounting.json` | 72预登记任务、4 pilot原位复用、1仪器失败 |
| `planning_runs.csv`、`rates.csv` | 全72逐次结果及各条件完整K/M/Gref/E/S |
| `c2_pilot_recovery.json` | 真实时钟缺失、M/S保守失败、零重搜证明范围 |
| `native_cost_events.csv`、`anytime_summary.csv` | 原生证书事件、整数弧长改善、浮点平台；不是Python证书时间 |
| `c2_paired_conditions.csv` | 选点半径与终止方式各18同条件配对 |
| `failure_counts.csv`、`c2_execution_metrics.csv` | 完整结局（含成功）及执行饱和/安全前缀/失效时间 |
| `c2_raw_audit.csv`、`final_trace_audit.json` | 全控制、首次解、保存LOS、冻结引导/内环和时钟复核 |
| `literature_matrix.csv` | 真实文献/代码/许可访问与未核验项 |
| `build_preflight.json`、`build_evidence.json` | 前置映射失败及5条构建命令（1次编译失败） |
| `local_checks.json`、`pytest_results.csv` | 真实513项检查、全部实际命令/退出码 |
| 3张PNG、`figure_manifest.csv`、`figure_qa.json` | 全21轨迹、全72结果、全18 AnyTime组；实际视觉QA |
| `resource_summary.json`、`delivery_review.json` | 资源体积与相对冻结6B的范围审核 |

M是预算内原生运动可行；Gref是对实际生成参考的完整几何认证，**不是另一个几何规划器成功率**；E为合格且实际执行的LOS；S为严格到达/安全/时钟成功。没有参考或未执行的数值留空，不能填0冒充测量。`model_feasible_before_deadline`意为施加截止筛选前的模型判据，不能证明证书按时；缺时钟行的该值来自事后复核，主要M仍为False。

C1源job的seed0/1是6B标签，C2的seed1/2/3是原生种子，不能混用。LOS积分弧长包含最终候选步，另列首个余量拒绝前认证前缀；候选端点不是精确碰撞瞬时。

完整日志、13例接口与C1/C2原始记录分别位于工作目录的`local_only/stage6c_native`、`local_only/stage6c_runs`、`local_only/stage6c_quality`；地图复用`local_only/stage6b_runs/grids`，官方依赖复用`local_only/stage6b_native`。历史数据未复制或覆盖，Git不含大型轨迹、依赖源码或额外文件hash清单。

最终HEAD云端证明在本阶段PR的`stage6c-windows-evidence` artifact及本地质量目录；不通过再次提交结果文件改变被核验HEAD。

入口：[中文报告](../../docs/STAGE6C_REPORT_CN.md)、[预登记协议](../../docs/STAGE6C_PROTOCOL_CN.md)、[pilot补充说明](../../docs/STAGE6C_PILOT_AMENDMENT_CN.md)、[真实命令](../../docs/STAGE6C_COMMANDS_CN.md)、[测试记录](../../docs/STAGE6C_TEST_RESULTS_CN.md)。完成6C后停止，等待审核。
