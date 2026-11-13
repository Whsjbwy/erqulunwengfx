# 阶段5A-F实际执行命令与证据位置

Windows 11 PowerShell；工作仓库`D:\2区论文复现\erqulunwengfx`，Python3.11.15使用已有`.venv`。新分支`audit/auv-stage5af-terminal`从PR #7准确head `c6f911c`创建；新PR目标5A-E，不合并。研究者已确认实施方案，未修改settings或历史成果。

## 冻结与输入

`83bd0b3`在新增解析/实验前提交并推送协议与新地图配方；`cb50315`记录独立终端引导/共享执行适配器及解析安全验收；`7d71591`在生成/查看F_*地图前提交全部612开发条件、独立审计和固定参数。只有2米前视/2米终端窗口这一组设置，没有扫参或按恢复率改阈值。

Gate0只读检查日志在`D:\2区论文复现\local_only\stage5af_audit`。469基线测试、184201字段与11张派生表5857行一致性、旧全轨迹安全复核均保留。完整旧路径取自`stage5ae/planning`，306个获解任务的raw/shortcut一对一使用，不执行旧图新搜索。

## 分关执行

```powershell
$env:PYTHONIOENCODING='utf-8'
$env:OMP_NUM_THREADS='1'
$env:OPENBLAS_NUM_THREADS='1'
$env:MKL_NUM_THREADS='1'
$python='.venv/Scripts/python.exe'
$local='../local_only/stage5af'
$old='../local_only/stage5ae'
$ar='../local_only/stage5ar'

& $python -m gsunlight_repro.stage5af.runner --phase gate1 --local-dir $local --old-evidence $old --ar-evidence $ar --output results/stage5af
& $python -u -m gsunlight_repro.stage5af.runner --phase pilot --local-dir $local --old-evidence $old --ar-evidence $ar --output results/stage5af
& $python -u -m gsunlight_repro.stage5af.runner --phase development --local-dir $local --old-evidence $old --ar-evidence $ar --output results/stage5af
& $python -m gsunlight_repro.stage5af.audit --phase development --local-dir $local --old-evidence $old --ar-evidence $ar --output results/stage5af
& $python -m gsunlight_repro.stage5af.analysis --local-dir $local --old-evidence $old --output results/stage5af
& $python -m gsunlight_repro.stage5af.runner --phase freeze --local-dir $local --old-evidence $old --ar-evidence $ar --output results/stage5af
# 提交并推送开发结果与参数冻结后，才执行下两条。
& $python -u -m gsunlight_repro.stage5af.runner --phase gate --local-dir $local --old-evidence $old --ar-evidence $ar --output results/stage5af
& $python -u -m gsunlight_repro.stage5af.runner --phase formal --local-dir $local --old-evidence $old --ar-evidence $ar --output results/stage5af
```

长运行实际通过`2>&1 | Tee-Object -FilePath <日志路径>`保存，返回`$LASTEXITCODE`。主日志为`gate1.log`、`pilot.log`（首次序列化失败）、`pilot_resume1.log`、`development.log`、`development_audit.log`、`development_analysis.log`、`independent_gate.log`、`formal.log`。阶段完成仅在全部操作完成后写`*_completed.json`。

首次pilot计算后保存遇到NumPy布尔序列化错误，失败日志和部分gzip原样留在`stage5af/serialization_failure`；显式Python bool修复及真实轨迹序列化测试后，仅重启未完成门槛，已有清单不变，完整12条件复用到612。该额外未归档执行尝试1次不能当独立样本，也没有覆盖旧记录。

所有主运行在读取大数据前取得目录OS文件锁，单核普通优先级。判断运行状态须轮询原终端和完成标记，不能因进程列表不可见重复启动。审计、分析与绘图也持同一锁，避免并发读到部分写入或争用实验CPU。每次规划的搜索、认证和既有共同处理都在10秒预算内；研究用同源shortcut另记处理成本。

## 完整矩阵结束后的派生与核查

```powershell
& $python -m gsunlight_repro.stage5af.analysis --local-dir $local --old-evidence $old --output results/stage5af --complete
& $python -m gsunlight_repro.stage5af.audit --phase independent --local-dir $local --old-evidence $old --ar-evidence $ar --output results/stage5af
& $python -m gsunlight_repro.stage5af.diagnostics --local-dir $local --old-evidence $old --ar-evidence $ar --output results/stage5af
& $python -m gsunlight_repro.stage5af.plots --local-dir $local --old-evidence $old --ar-evidence $ar --output results/stage5af
& $python -m pytest -v --junitxml=../local_only/stage5af_audit/final_pytest.xml
& $python -m ruff check .
& $python -m ruff format --check .
& $python -m compileall -q src tests scripts
```

完整轨迹仅存`stage5af/replays`：精确相等的旧前缀引用原轨迹，保存改变后的后缀；未相等的数值不舍入冒充复用。旧LOS和原控制的开发记录直接引用旧档案。失败轨迹含被拒绝候选步的末状态，不等于获准执行到该位置。统计和图只读原记录；缺失路径不填0长度。

`diagnostics`在冻结后只添加读档分析，记录实际切换姿态/目标方位和首次失效所在阶段，不执行模拟、不改控制参数，不把静态方位误差当作运动学不可达证明。

每个原始记录排他创建；如需新机器完整复跑，使用新的证据目录及新的结果输出目录，不能覆盖本轮成果。公开仓库不包含完整本地数值轨迹；精确重放306条旧路径需本地5A-E原记录。按旧协议重新生成时，墙钟预算及机器吞吐可能产生不同坐标，不能声称跨机逐值相同。Windows CI只运行软件/公开数据检查，不重跑216个科研任务。
