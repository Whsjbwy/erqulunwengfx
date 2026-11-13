# 阶段6A精简证据

本目录全部为6A新产物。历史数据未修改。没有新的随机规划批次，未运行OMPL原生基线，未来324任务草案未执行。

| 文件 | 内容与来源 |
| --- | --- |
| `literature_matrix.csv` | 22项真实题名/作者/DOI/方法访问深度/代码许可/模型差异；15项为2023—2026年 |
| `literature_verification.json` | 实际注册请求状态、日期与URL；保留首次失败再成功的记录 |
| `baseline_source_audit.json` / `historical_pr_review.json` | 成熟基线源码/许可/平台观察与PR #5—#8真实元数据 |
| `historical_review.json` | `stage6a.review`只读重算5A-F分母与末端失效阶段 |
| `historical_success_rates.csv` | 历史六个固定流程的G/K、S/E、S/K；body/margin混合仅作诊断 |
| `feasibility_cases.csv` | 实际12例逐次输入预期/结果/拒绝候选/最后接受位置/独立积分误差 |
| `feasibility_acceptance.json` | 12例验收总账；无规划搜索，6正例6拒绝例 |
| `feasibility_witnesses.png` | 唯一私有数值记录生成的六条正例投影，以及解析率约束兼容性图；非规划性能图 |
| `local_checks.json` / `pytest_results.csv` | 本机完整检查退出码、实际测试结果，完整日志保留仓库外 |
| `windows_ci.json` | 6A官方Windows CI实际工作流/作业/步骤和日志摘录 |
| `delivery_review.json` | 相对冻结基点的文件范围、历史修改数与交付检查 |

代码提交的Windows CI已实际489项通过，详见`windows_ci.json`。本目录均可由[PR #9](https://github.com/Whsjbwy/erqulunwengfx/pull/9)进入审核。

唯一完整数值记录位于本地工作目录的`local_only/stage6a_feasibility/acceptance.json.gz`，不进Git；图表复用这一记录，没有重存轨迹。公开CSV中的拒绝候选位置不是成功接受状态；输入超限时可没有积分轨迹。

注册元数据实际检索记录保留在`local_only/stage6a_audit`。不上传作者原文/源码、完整日志、环境、文件哈希清单。原始完整记录不可被精简摘要代替；下次审核可在本机检查。

科研结论与证据缺口见[主报告](../../docs/STAGE6A_RESEARCH_DESIGN_CN.md)、[下一步决策](../../docs/STAGE6A_NEXT_DECISION_CN.md)与[质量记录](../../docs/STAGE6A_VALIDATION_CN.md)。
