# 阶段6B精简结果

所有数字来自真实运行或对既有原始记录的只读重算。13例真实SI接口验收后，固定36次官方控制规划全部完成；原生严格可行21次，实际合格LOS执行21次，其中严格成功11次。15条approximate保留失败，4条晚证书另作截止标记。

| 证据 | 内容 |
| --- | --- |
| `interface_cases.csv`、`interface_acceptance.json` | 13例逐次原生/冻结Python/独立RK4对照 |
| `middle_collision.json` | 两端自由而区间中点球相交的实际反例 |
| `search_manifest.json`、`planning_runs.csv` | 固定36任务、标签与原生种子、完整逐次状态/时间/失败 |
| `experiment_accounting.json` | 36实际任务，2 pilot原位复用，不额外计次 |
| `rates.csv` | 各算法、场景及见证类型的K/M/E/S和三个不同分母 |
| `failure_counts.csv`、`paired_outcomes.csv` | 完整失败与同条件配对结果，不作优劣显著性宣称 |
| `trace_audit.json`、`terminal_diagnostics.csv` | 全部原始目录/控制/保存LOS轨迹审计及10条失效区间 |
| `trajectory_metrics.csv` | 全36原生长度/限幅、21条LOS积分长度与安全前缀；未执行值留空 |
| `literature_followup.csv` | Feng、DIRT、RDG真实访问与代码/许可差异 |
| `native_los_matrix.png`、`trajectory_comparison.png` | 全36结果与预定四场景轨迹投影 |
| `figure_manifest.csv`、`figure_qa.json` | 图中所有任务ID、选择规则和实际视觉QA |
| `local_checks.json`、`final_source_checks.json`、`pytest_results.csv` | 实际本机完整检查、最终源码复核和497项逐测试记录 |
| `build_evidence.json`、`windows_ci.json` | 21条实际构建命令（含6失败）及真正云端源码构建/13例验收 |
| `delivery_review.json` | 相对冻结6A的变更范围、历史只读与公开体积核查 |

完整构建源码/缓存/失败日志在工作目录的`local_only/stage6b_native`，13例与36任务完整输入/输出/控制及轨迹在`local_only/stage6b_runs`，质量原日志/JUnit在`local_only/stage6b_quality`；均不提交Git。每个任务只保留单个记录目录，原生与LOS是不同轨迹对象，未重复复制完整数据。没有额外文件哈希清单或作者材料公开。

`trace_audit.json`只重建和认证已保存控制/状态，不重新执行规划器或LOS；其审计区间数不是新增实验次数。拒绝区间的端点不等同于碰撞瞬时位置。参考桥段是单独认证的几何参考扩展，不属于原生控制序列。

主入口：[中文科研报告](../../docs/STAGE6B_REPORT_CN.md)、[实际命令](../../docs/STAGE6B_COMMANDS_CN.md)、[测试记录](../../docs/STAGE6B_TEST_RESULTS_CN.md)、[PR #10](https://github.com/Whsjbwy/erqulunwengfx/pull/10)。最终科学建议为**Need More Evidence**，完成后停止等待审核。
