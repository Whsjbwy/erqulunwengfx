# 阶段二结果

- `pilot_S1.csv`与`remaining_4maps.csv`为两批原始记录，共125条，保留原样。
- `runs.csv`按场景、方法、种子合并排序；`summary.csv`为25组汇总，`failure_mechanisms.csv`区分终止原因与共存的观察事件。
- `node_counts.csv`补充永久节点、容量淘汰和计数单位。不同方法的sampled_nodes含义不同，不能统一排名。
- `vtk_crosscheck.csv`为80条有坐标路径的独立VTK辅证，不能替代严格检测。
- `figures/`固定规划seed0绘制五张图，不用见证替代失败路径。
- `environment.json`仅公开必要环境与配置引用，无私人路径和令牌。

strict_valid为空表示没有路径证据，False才表示实际无效路径；strict=True也可能伴随timeout。正常预算内完成另看budget_valid_success。长度均值只取严格有效路径，包括预算截止时保留的候选，不自动等于正常预算成功的长度均值。S4负例单列，不能混入可达场景成功率解释。

原始路径JSONL和完整日志保留在仓库外。详见[第二阶段报告](../../docs/STAGE2_REPORT_CN.md)。
