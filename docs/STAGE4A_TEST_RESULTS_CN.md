# 第四阶段4A测试与Windows记录

## 基线及实现检查

阶段三基线d3a8e96在本轮重跑：265 passed in 6.78s，compileall、Ruff及格式检查通过。原测试与源码未修改。

第一版4A实现本地308 passed in 7.02s。加入统计和精确接触边界回归后，本地全量为320 passed in 7.07s，编译和Ruff静态检查通过；命令文档Python示例引号经格式化后，Ruff格式检查88文件通过。该计数对应当前开发检查，最终交付检查另记，不以预期数量代替实测。

新增测试覆盖：13张新图的严格见证、不可达证书、固定列表和再生成；统一截止、首次确认时刻、过期路径不倒填、shortcut中断回退；原贪心后处理顺序等价；缓存只绑定不可变单图、精确坐标、容量界限、异常恢复、面/棱/角接触与非单位spacing随机障碍；Anytime函数恢复和全部保留路径严格验证；402个唯一任务与预检复用、冻结配置不能覆盖；固定工作量路径/展开顺序；地图分层bootstrap可重复、无共同有效路径长度缺失、低覆盖不能通过幸存者触发Go；公开派生分析不能改原始配置。

错误处理不静默忽略：非法候选、后处理非法、map见证非法和worker错误都明确停止。新的超时测试使用可控时钟隔离边界，不把实际程序超时当无解证据。前三阶段闭体素oracle测试继续全量保留。

## 已实际完成的工程检查

S1/D1各模式先对比完整原始路径、终止状态、参数、逻辑计数和展开序列，全部相同。随后每图每模式5次完整重复，共30条计时，结果见fixed_work_timing.csv。精确缓存的物理查询计数有意减少，不以物理查询完全相等作为逻辑等价的前提。未使用cProfile计时作速度排名。

单种子预检12次、三种子预检36次均完成。最终预注册402次独立运行全部完成，无非法接受路径、worker错误或资源守护。预检与开发集重合的24条只计一次；240次新留出运行、30次封闭负例均保留完整失败记录。

额外审计402份单份原始记录：1886条归档路径条目、1307条不同图/折线组合、2442条历史引用和2010个截点全部通过，非法路径、端点不符、迟到认证和截点倒填均为0。实际结果见[certificate_audit.json](../results/stage4a/certificate_audit.json)。10张最终PNG均实际打开检查，失败方法没有用见证路径替代。

## Windows GitHub Actions

独立workflow为.github/workflows/stage4a-windows.yml；GitHub-hosted Windows与本机Windows11分别记录，CI只执行自编合成测试，不能称CI重跑了全部科研矩阵。

分析实现提交1a1d145的[实际Windows运行42964895115](https://github.com/Whsjbwy/erqulunwengfx/actions/runs/42964895115)成功：320 passed in 13.84s；编译、Ruff和87文件格式检查全部成功。官方日志job130339704570已实际读取。早期f54a66d/3fea66f的Windows检查亦已成功，不将不同提交的测试数量混用。

## 开发时的修正

Ruff发现了文档字符串、图标题行长和命令文档代码围栏中的引号格式，均修正后复查。没有通过修改地图、选择种子或改写实验结果修复检查。额外最终审计时间在正式搜索前补为独立字段；规划预算及核心数学行为未改变。Git在受限环境内偶发DNS线程错误，授权网络环境重试后推送成功，不涉及算法结果。

新增结果测试第一次在Windows默认GBK编码下读取UTF-8中文JSON失败（1 failed、2 passed）；错误表示文本解码不匹配，已为4A新测试显式指定UTF-8，单项3 passed后再运行全量。未修改旧测试、地图或任何原始运行结果。

## 最终本地交付检查

2026-11-11在本机Windows 11、原Python 3.11环境实际执行：

| 命令 | 实际结果 |
| --- | --- |
| `python -m compileall -q src tests scripts` | 退出码0 |
| `python -m pytest -v` | 327 passed in 6.90s，退出码0 |
| `python -m ruff check .` | All checks passed，退出码0 |
| `python -m ruff format --check .` | 92 files already formatted，退出码0 |

命令使用仓库`.venv/Scripts/python.exe`。逐项327条记录见[pytest_results.csv](../results/stage4a/pytest_results.csv)，检查时刻、命令及实际进程耗时见[local_checks.json](../results/stage4a/local_checks.json)。pytest自身耗时6.90秒与整个子进程7.37秒口径不同。

正式搜索核心相对3fea66f无改动，前三阶段已有源码、配置和CSV无改动。

## 交付代码的实际Windows CI

代码与结果交付提交300eba4，两个实际Windows检查均已完成，官方job日志均已读取：

| 事件 | 运行/job | 实际结果 |
| --- | --- | --- |
| 分支push | [42985355697](https://github.com/Whsjbwy/erqulunwengfx/actions/runs/42985355697) / 130405119895 | 327 passed in 12.84s |
| PR #4 | [42985433804](https://github.com/Whsjbwy/erqulunwengfx/actions/runs/42985433804) / 130405365371 | 327 passed in 14.23s |

两次compileall、Ruff静态检查及92文件格式检查均成功；分支job镜像为windows-2025-vs2026。精简官方日志见[windows_ci.json](../results/stage4a/windows_ci.json)。这些是GitHub-hosted Windows合成测试，不冒充本机实验重跑。

随后仅补报告链接和本次CI证据。独立审核入口为[PR #4](https://github.com/Whsjbwy/erqulunwengfx/pull/4)，目标repro/gsunlight-stage3；最后元数据提交的检查状态在PR中核实，不把早期320项结果当327项证据。
