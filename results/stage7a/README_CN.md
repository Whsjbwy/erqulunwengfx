# 7A精简证据

- `execution_index.csv`：47条已保存名义执行的只读审计索引。
- `failure_audit.csv`：上述索引中原LOS严格失败的15条，保留原终止标签并新增首次严格事件。
- `event_audit.csv`：每项首次事件区间、候选坐标及原零起始索引；时间不是精确碰撞瞬间。
- `identical_failure_records.csv`：直接逐字段/逐数组相等比较，不使用文件hash。两对完整LOS轨迹相同，15条记录有13条不同轨迹，仍保留全部任务分母。
- `audit_summary.json`、`source_availability.json`：实际提取计数及原始记录完整性。
- `literature_sources.json`、`literature_matrix.csv`：13项真实文献和公开代码/许可的实际核验范围；未知明确标记。
- `decision.json`：PIVOT，不进入原创7B。
- `figures/`：仅由保存数组绘制的两张图，不产生新轨迹或安全证书。
- `local-quality/`：实际本地Python检查，CI对应产物另从PR Checks取证。

`not_recorded`是原字段缺失，`not_observed`是已知字段中无该事件。`first_*_candidate_time_s`是事件对应区间末端时间；引导/终端条件在该区间开始处计算。`first_failure_before_guide_bridge`依据虚拟参考进度，不能称为实际车辆在桥段前后。

`native_gap_on_first_failure_active_segment_m`仅对应虚拟活跃原生段；LOS派生必需净距是保存的body/mission下界减0.25m。距离查询存在3m截断，远离障碍时只能解释为保守下界。全局最近折线距离、虚拟参考距离与共同时间域偏差分别给出，不互换。

源轨迹仍只在 `D:\2区论文复现\local_only\stage6ds_runs\search\<job_id>\` 保留一份；未复制进Git。公开摘要不能据以重建未保存字段。继承原生积分/连续认证的科学证据来自6D-S，7A新增检查是来源对应及只读统计。
