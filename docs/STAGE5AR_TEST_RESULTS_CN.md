# 阶段5A-R测试与执行证据

科研实验、软件正确性和实体车辆适用性分开验收。所有下列本机结果来自2026-11-12实际命令，完整UTF-8输出、JUnit及失败记录保留在仓库外stage5ar_audit；公开只保存精简JSON和逐项CSV。

## 历史基线

- 416 passed in11.17s，Ruff通过，123文件格式通过，compileall退出0。
- 完整5A审计：450任务、13185路径条目、13633历史引用、1305截点，非法路径/迟到认证/标记不一致均0。
- 450原始row对公开runs.csv的33670字段无差异。
- 历史PR #5 head=8c69bb5，与本地一致，检查时仍open/unmerged；旧源码/配置/结果保持冻结。

## P0与独立复核

T01—T08预期在测试和p0.py中定义，8例全部实际通过。覆盖对齐与偏航直线、水平圆弧、三维常角速、S形、上下浮潜、面棱角/边界、额外余量和几何尖角。独立RK4参考最大差8.832×10⁻¹³米，验收容差10⁻¹⁰米；曲线弦界包含中间轨迹。S形正负角速均为±0.1745329252rad/s。

首轮18路径与冻结原track/历史记录一致后，按预注册整体扩展；157条selected基准全部一致。P2共785个条件，P3为157组/314个条件；有85份同坐标条件轨迹引用复用，不重复计独立规划任务。

最终完整逐步审计1099记录、361456记录步（含引用），重建最大/RMS误差、饱和、时间、连接、停止顺序及输入/姿态限制；独立RK4检查3297个首/中/末步，最大差9.973×10⁻¹⁴米，容差10⁻¹⁰米。83个基准物理拒绝区间均有独立球模型交叠样本；2个任务带拒绝区间物理部分有正下界，任务顶界有球模型交叠，未混称物理碰撞。

## 发现并修复的新增导出问题

实际全量检查曾为448 passed / 1 failed（9.43秒）：shortcut_pairs的全局raw/shortcut路径ID被展开的数值path_id覆盖。修复前CSV及JUnit/日志保留；b563a8c先提交最小失败测试，实际1 failed in0.24s。

修复后将局部索引放入raw_registry_path_id、shortcut_registry_path_id，保留全局ID。最小测试1 passed in0.13s，公开结果3 passed in0.13s；157个派生ID唯一。修复前后共有非ID字段逐项相等，成功15/32不变，未重跑或改写轨迹。此错误是5A-R输出元数据错误，不是旧5A跟踪失败原因。[修复证据](../results/stage5ar/export_repair.json)保留前后统计。

## 最终本机交付检查

| 实际命令 | 实际结果 |
| --- | --- |
| `python -m pytest -v --junitxml=...` | 450 passed in9.07s，退出0 |
| `python -m ruff check .` | All checks passed，退出0 |
| `python -m ruff format --check .` | 143 files already formatted，退出0 |
| `python -m compileall -q src tests scripts` | 无标准输出，退出0 |

Python3.11.15；依赖实际为NumPy2.4.6、Matplotlib3.11.2、pytest9.2.0、Ruff0.17.4。未添加依赖。450个逐项状态/耗时在[pytest_results.csv](../results/stage5ar/pytest_results.csv)，各命令时间/退出码在[local_checks.json](../results/stage5ar/local_checks.json)。测试项数450与历史科研任务数450含义不同，不能混计。

新增测试覆盖解析场景、初始航向不修改目标、固定取样/最早最晚规则、清单重复与覆盖保护、缺失条件/几何量、配对退化保留、地图等权分母、同源索引/全局ID、轨迹引用循环、逐步指标损坏拒绝及旧结果输出保护。测试不要求任何方法达到预设科研成功率。

5张图已逐张打开；总览加深显示障碍、扩展右边留白、局部间隙放大后再次打开核对。figure_qa.json记录尺寸和显示改动；没有改地图或执行数据。

## GitHub Windows CI

新增stage5ar-windows.yml在本分支push及以pivot/auv-rrt-stage5a为目标的PR上运行Windows测试、Ruff、格式和编译。只用自编代码/合成数据，不下载作者材料，也不宣称CI重跑了全部科研矩阵。

代码/结果提交87a87c6的[PR Windows运行43151114687](https://github.com/Whsjbwy/erqulunwengfx/actions/runs/43151114687)已实际成功，job130960212608。已读取完整官方日志：450 passed in16.15s，compileall与Ruff成功，145 files already formatted。镜像windows-2025-vs2026，Python3.11.9；与本机Windows11/Python3.11.15分别记录，不混记补丁版本、耗时或收集文件数。

精简官方证据在[windows_ci.json](../results/stage5ar/windows_ci.json)，完整日志留本地。审核入口为[PR #6](https://github.com/Whsjbwy/erqulunwengfx/pull/6)，base为pivot/auv-rrt-stage5a，保持开放、未合并。其后仅补文档和CI证据的最终提交状态在PR实时检查中另核验。
