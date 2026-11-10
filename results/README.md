# 精简结果说明

- `stage1_summary.csv`：作者计算逻辑的无窗口基线，20个seed，每seed原始/后处理各1行，共40行。
- `diagnostic_cons1.csv`、`diagnostic_cons3.csv`、`diagnostic_cons5.csv`：独立安全诊断，各40行；原版结果不被覆盖。
- `aggregate_summary.csv`：8行分组统计。长度只对已产生的路径取均值；基线路径有碰撞，因此其平均长度不代表合法路径质量。
- `vtk_crosscheck.csv`：基线40条路径的独立VTK密集查询，采样间距最多0.02地图单位；仅作辅证。
- `native_runs.csv`：两次未修改原件的原生运行，保留窗口阶段超时及被结束的真实退出码。
- `environment.json`：日期、硬件、软件版本、输入文件名/大小及计时口径，不含私人目录或凭据。

`reported_success`是作者已产生完整候选路径；`status=ok`表示入口正常返回且存在路径；`strict_valid`同时要求连续碰撞检查和起终点匹配。`no_path`、`crash`、`timeout`分别记账，不能都解释成碰撞。无路径长度留空。每seed退出码0代表原入口正常返回，批量worker为持久子进程，并非每行新建独立进程。

`collision_segment_count`每个碰撞/越界线段最多计1次。首次线段索引从0开始，体素索引顺序为x,y,z；路径可能从目标指向起点，不能假定报告的首段靠近起点。严格首碰撞点为代表性证据点；VTK表另给障碍内部采样点和距体素面的距离。

`algorithm_seconds`为原入口计时，结束于后处理前；显示准备已被适配并复用地图。`wall_seconds`是worker请求时间，含日志与后处理，不含首次worker启动或父验证；独立检查另记`validation_seconds`。这些时间不用于和论文硬件上的结果直接比较。

原始坐标、逐seed完整日志、作者材料和本地副本保留在仓库外。详细结论见[中文阶段报告](../docs/STAGE1_REPORT_CN.md)。
