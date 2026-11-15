# 阶段6B实际测试与证据

本机完整检查已真实执行：**497项pytest通过，13.68秒**；Python编译、Ruff、219文件格式检查、6组原生模型测试和C++ clang-format检查均退出0。完整命令和精简输出见[local_checks.json](../results/stage6b/local_checks.json)，逐测试记录见[pytest_results.csv](../results/stage6b/pytest_results.csv)。原始日志/JUnit位于仓库外`local_only/stage6b_quality`。

轨迹指标代码补齐后又对最终源码执行完整pytest，**497项通过、12.06秒**，编译、Ruff和格式检查也退出0；见[最终源码检查](../results/stage6b/final_source_checks.json)。这是代码检查复核，未增加规划或LOS实验。

## 实际检查范围

```powershell
.\.venv\Scripts\python.exe -m compileall -q src tests scripts
.\.venv\Scripts\python.exe -m pytest -q --junitxml=..\local_only\stage6b_quality\pytest.xml
.\.venv\Scripts\python.exe -m ruff check .
.\.venv\Scripts\python.exe -m ruff format --check .
```

原生构建后的CTest已实际1/1通过（内部6组），最终本机又直接运行同一`auv6b_model_tests.exe`确认6组通过。该重复是确定性测试复核，不是新增规划实验。clang-format使用同一工具链对4个自编C++文件作`--dry-run --Werror`检查；没有格式化外部源码。

新增Python测试覆盖C-order与地图复用、原初向不被goal-facing替换、中段端点漏碰反例、节点损坏拒绝、approximate不升级、参考桥段安全、共同初态与冻结LOS调用。原生6组覆盖解析运动、严格限幅、闭盒面/棱/角接触、短区间穿障、任务顶界与非法输入。没有把Release下被移除的`assert`当测试。

首轮静态检查发现过新代码长行和格式问题，已修复后通过；这些输出未全部单独保存成完整日志，不能声称日志文件存在。原生依赖的6次失败则有完整实际构建日志与退出码，不作隐藏。[构建记录](STAGE6B_BUILD_CN.md)

## 数值审计

13例真实OMPL接口验收先于搜索，通过后才运行36任务。后续只读审计重新检查了27661个原生区间和16259个已保存LOS区间，没有再次启动搜索或LOS模拟。分别108/63个独立RK4抽查最大误差约`8.5265e-14/8.6460e-14 m`；完整逐步状态、安全、终止和余量失败分类与原始结果相符。[trace_audit.json](../results/stage6b/trace_audit.json)

## Windows CI

`.github/workflows/stage6b-windows.yml`已在Windows云端从锁定官方源码构建同一OMPL与适配器，运行CTest和13例真实接口验收，并通过完整Python/Ruff检查。[实际成功运行43693078784](https://github.com/Whsjbwy/erqulunwengfx/actions/runs/43693078784)对应提交`21fe832`：497项pytest通过（26.64秒），217文件格式检查通过，原生依赖/适配器构建和CTest退出0；13例验收再次得到930接受区间、936次真实传播调用及同样的RK4误差。精简证据见[windows_ci.json](../results/stage6b/windows_ci.json)，完整云端日志已保留在本地质量目录。

**CI没有额外规划搜索，也不把云端确定性验收混入本机36次计账。** 此次CI在最终只读分析/图表源码提交前完成，因此217文件与本机219文件的口径不同；最终HEAD还需实际检查，结果在PR中更新，不能用这次较早的成功替代最终HEAD状态。

云端`windows-latest`与本机Windows 11不是同一硬件环境。CI能验证构建及确定性接口，不代替本机搜索时间/成功率证据。最终源码或文档提交的CI状态需在PR中核对实际HEAD，不用历史6A的检查替代6B。
