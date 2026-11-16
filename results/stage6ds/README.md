# 6D-S公开证据索引

完整中文说明：[科研报告](../../docs/STAGE6DS_REPORT_CN.md)、[协议与差异](../../docs/STAGE6DS_PROTOCOL_CN.md)、[真实命令](../../docs/STAGE6DS_COMMANDS_CN.md)、[近邻边界](../../docs/STAGE6DS_LITERATURE_CN.md)。[PR #14](https://github.com/Whsjbwy/erqulunwengfx/pull/14)保存准确最终HEAD的Windows CI与artifact下载核验链接，PR开放未合并。

- `inherited_protocol.json`、`search_manifest.json`：编码/搜索前提交的原6D d2快照与完整54条件。原地图配方直接引用，未改。
- `native_entry_diff.patch`、`build_evidence.json`：实际规划函数的最小版本化差异和全部7条构建命令，含1次失败。
- `config_audit.json`、`actual_input_audit.csv`：实际54份请求逐项核对原配置、地图字节、初态/目标、种子、预算与实际planner身份，不使用文件hash。
- `acceptance/`：新实际搜索二进制的69边界、原13例、六图2440区间、3个实际planner身份检查、旧故障复现及3398区间判定。
- `prepilot-quality/`：搜索前539项pytest和实际检查日志。`pilot_review.json`、`pilot_accounting.json`为固定3次pilot审核，真实结果原样复用。
- `planning_runs.csv`：完整54条逐次主账本，全部completed；模型、身份、seed、最终证书、LOS、真实时钟、RSS、查询数及失败均保留。M字段是冻结6D最终回传认证链路口径。
- `deadline_available_incumbents.csv`：另列全部54任务在10秒内已经独立认证的保存first/final候选及最佳可用成本。两条最终认证逾期任务已有及时首次证书，因此M_final=47、M_available=49；不修改主标记，不追加LOS。该补充范围不是对所有未保存中间incumbent做独立重认证。
- `rates.csv`、`map_rates.csv`：完整K/M_final/Gref/E/S、补充M_available、成本样本数及逐图分子分母；剔除任一图的范围是敏感性，不是置信区间。
- `failure_counts.csv`、`failure_positions.csv`：保留7个最终链路失败及15个LOS失败；候选端点不是碰撞瞬时位置，搜索终点不是碰撞点。
- `native_cost_events.csv`、`paired_sst_costs.csv`：全部原生incumbent事件及18组SST配对，失败成本为空，原生时钟不冒充Python独立证书。
- `all54_outcomes.png`、`time_cost_coverage.png`、`all_anytime_costs.png`：完整结果、时间/质量/覆盖及全部Anytime曲线，late final cert明确标记。
- `final_audit_cases.csv`、`final_trace_audit.json`：54任务全部控制及LOS只读终审，24,313+6,832个原生/首次区间、21,283个LOS区间，无安全成功假阳性。
- `final-local-quality/`：最终545项pytest、5CTest日志、compileall/Ruff/格式、旧6D-R plan守卫及公开账本核验。本机工作树证明不代替最终准确HEAD CI。
- `statistics.json`、`accounting.json`、`decision.json`：完整统计、54账本及唯一科研判断PIVOT。H1未实现。

完整原始实验单份位于Git外`D:\2区论文复现\local_only\stage6ds_runs`，前置验收在`stage6ds_acceptance`，构建日志在`stage6ds_native`。依赖和旧网格直接复用，不上传外部源码/二进制或大型轨迹，不生成额外文件哈希清单。历史6D BLOCKED、54条not_run及阶段1—6D-R全部原件保留。
