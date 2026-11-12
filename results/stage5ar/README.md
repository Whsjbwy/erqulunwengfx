# 5A-R诊断结果与数据边界

本目录只保存自编合成实验的精简结果，不含原作者材料、完整体素、完整重复轨迹或个人路径。旧results/stage5a未修改。实验完成状态以experiment_accounting.json及中文报告为准；缺少完成文件时不得按部分结果下结论。

- sampling_manifest.csv：270个正式任务的selected/raw_best路径清单，缺路径也保留。is_selected表示首轮18条；in_expansion表示全部157条名义机体有效的选中路径。不是按新结果挑样，选样依据列明确保留。
- historical_csv_audit.json：450个原始row与历史公开runs.csv的33670字段比较。historical_geometry_audit.json为本阶段实际重跑的完整路径/认证/时间审计摘要。
- p0_analytic_results.json：T01—T08实际数学/几何验收，数值容差在代码中预先定义。补充S形角速符号检查在test_evidence.json中记录。
- baseline_diagnostics.csv：157条冻结基准路径的逐次诊断，与旧track及历史指标逐项一致；不是新的规划试验。
- sensitivity_paired.csv：同一157路径×5条件的785行结果和基准差值，包含失败、退化、缺失值。所有速度条件均用原时长公式，simulation_limit_s及capped逐次明示。
- condition_summary.csv：每图、每模式、每条件的完整分母/恢复/丢失数；ALL行为诊断总体汇总，不是算法总体排名。success_rate_map_mean先图内平均，再地图等权。
- failure_counts.csv、failure_locations.csv：互斥主类及每次失败的区间、位置和诊断字段。physical_sweep_rejected仅是保守认证拒绝；有独立证据时另列reference_*，仍只支持假设球模型。first_task_band_*只指任务顶界；first_mission_*是包含物理检测的组合任务验证器，不应解读为单独顶界违例。
- shortcut_pairs.csv：157个同源raw_best及固定shortcut配对；raw_path_id=shortcut_source_id是必要条件，shortcut_path_id是独立派生路径ID。source_indices记录原始顶点索引。不是把历史raw_best和无关incumbent的selected直接比较。
- path_geometry_associations.csv：每图的几何特征关联、6个地图均值的描述关联；常量/缺失导致的相关系数为空，不填0，不提供显著性或因果结论。
- failure_waterfall.csv/png：历史270任务逐层分账。point模式90条执行前拒绝没有算作实际跟踪；margin的15个方法/种子包络负例不进已知可达分母（每方法5个）。
- failure_locations.png、figure_manifest.csv：每图固定首轮样本中历史最早失败任务；包含失败，不按改善效果选图。×是首次被拒绝步末位置，红球为名义包络；精确事件只定位到0.1秒区间。绘图稀疏化不影响完整地图数值认证。
- sensitivity_by_map.png、shortcut_paired.png：全部条件及真正同源配对的可视化，不隐藏负结果。
- trace_audit.json：从完整逐步记录重建误差、饱和、时间和停止顺序，并用独立RK4复核首/中/末步的实际证据。
- local_checks.json、pytest_results.csv、windows_ci.json：本机及GitHub Windows执行证据摘要。完整原始日志留在本地；CI只运行自编代码/合成测试，不声称重跑全部历史科研矩阵。

全部路径坐标从本地原始result.json按job_id/path_id读取，未从CSV推测折线。新轨迹每0.1秒本地保存一次，raw/shortcut若与同任务已有条件坐标一致，只存轨迹引用；结果行数、实际积分次数、引用次数分开计数。无可比较误差或长度时为空，不能当0。

总账actual_integrated_replays指新增诊断循环的积分次数；不包含用于一致性核验的原版track调用或P0测试，不应解读为Python运动学函数调用总次数。CSV导出ID修复前后的实际对比见export_repair.json；修复前CSV留在本地，不改写原始轨迹或5A记录。

最小间隙是3米截断并扣曲线弦界的保守下界；失败末步指标沿用5A顺序，包含被拒绝的候选末状态，不代表该状态已被安全接受。没有实体海试、标定水动力、洋流或新规划算法。6张地图是主要聚类单元，规划seed是图内重复；这些图已用于归因，不再称未见地图。
