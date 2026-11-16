# 阶段6D证据索引

**科研判断BLOCKED。** D1完成42次新重放，A/B/C/D严格LOS分别11/11/14/14（各分母21）。D2给定控制验收发现模型/SI俯仰边界冲突，54条登记搜索实际0，不能填0/54失败率；没有H1模块或性能比较。

| 文件 | 真实口径 |
| --- | --- |
| `d0_audit.json`、`d0_historical_runs.csv` | 全108份历史返回控制重认证、准确6C HEAD CI和新构建 |
| `d0_interface/*`、`d1_acceptance.json` | 原生13例实际调用及14项实验前测试 |
| `d1_results.csv` | 全84个A/B/C/D条件；A/D历史保存，B/C42次新测 |
| `d1_pairs.csv`、`d1_geometry_equivalence.csv` | 全21配对、恢复与退化、父子边/弧长等价 |
| `d1_trace_audit.csv`、`analysis_summary.json` | 全64822区间只读引导/内环/安全/时钟审核 |
| `d1_outcome_counts.csv`、`failure_locations.csv` | 全条件结局与34个LOS失败及1个接口异常的候选区间位置 |
| `d2_witnesses.csv` | 4张图已实际通过SI与独立控制认证的原始逐图结果 |
| `d2_witness_status.csv`、`d2_accounting.json` | 全6图：4通过、1原生异常、1按门槛未运行 |
| `model_mapping_failure.json` | 同一失败输入的原生probe和Python模型诊断；不是规划成功 |
| `d2_registered_not_run.csv` | 全54预登记任务，逐条not_run；实测指标留空 |
| `literature_matrix.csv` | 标题/DOI/原文范围/作者代码许可及未核实差异 |
| `gate_checks.json`、`gate_pytest_cases.csv` | 实验前14项实际验收 |
| `final_checks.json`、`final_pytest_cases.csv` | 529项实际通过；final中CTest启动失败也保留 |
| `post_path_fix_checks.json` | 路径修复后受影响原生/脚本检查通过，pytest未重跑 |
| `delivery_static_checks.json` | 最终派生表/交付脚本的编译与全量静态检查 |
| `probe_build_evidence.json` | 独立故障诊断构建与“检测已知缺口”的CTest |
| `development_failures.json` | 开发错误、D0汇总写入故障和真实日志边界 |
| 3张PNG、`figure_manifest.csv`、`figure_qa.json` | 全21同源轨迹、六图验收状态、俯仰边界诊断；真实视觉QA |

D1的`minimum_clearance`按冻结mission机体球定义，额外0.25m要求的净距下界另见`d1_trace_audit.csv`。所有净距查询注明3m截断；候选位置不等于精确首次接触位置。历史种子标签0/1不等于D2登记的原生种子1/2/3。

完整原始数据和失败单份留在仓库外`local_only/stage6d_runs`、`stage6d_diagnostic`，构建/依赖分别`stage6d_native`、`stage6d_probe`与复用的`stage6b_native`，日志在`stage6d_quality`。没有上传二进制/外部源码/原始轨迹包或额外文件hash清单。CI artifact保存最终HEAD的真实检查以及BLOCKED门槛，本地另留完整job日志；不再次提交CI结果改变被验HEAD。

入口：[中文报告](../../docs/STAGE6D_REPORT_CN.md) · [预登记](../../docs/STAGE6D_PROTOCOL_CN.md) · [明确决策](../../docs/STAGE6D_DECISION_CN.md) · [近邻与机制](../../docs/STAGE6D_LITERATURE_CN.md) · [测试记录](../../docs/STAGE6D_TEST_RESULTS_CN.md) · [真实命令](../../docs/STAGE6D_COMMANDS_CN.md)。

完成6D后停止。唯一下一步是另行提交审核模型边界一致性修复与确定性验收，不能自动恢复搜索或进入H1。
