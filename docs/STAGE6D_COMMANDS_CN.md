# 阶段6D实际执行命令

以下命令已在Windows原生实际执行，当前目录为仓库根目录。依赖复用单份`../local_only/stage6b_native`，没有系统安装或全局PATH改动。`Z:`仅作为同一工作目录的临时ASCII别名，用前确认未占用，交付前核验并撤销；不移动文件。

```powershell
git switch -c research/auv-h1-admission-stage6d e39d88a8287d4ff98ce03a8afa1d59d3a7cc2c6d
subst Z: D:\2区论文复现
.\.venv\Scripts\python.exe Z:\erqulunwengfx\scripts\stage6c_build.py --repository-root Z:\erqulunwengfx --dependency-root Z:\local_only\stage6b_native --local-root Z:\local_only\stage6d_native --jobs 2
.\.venv\Scripts\python.exe scripts/stage6d_checks.py --phase gate --local-root ../local_only/stage6d_quality --dependency-root ../local_only/stage6b_native --build-root ../local_only/stage6d_native
.\.venv\Scripts\python.exe -m gsunlight_repro.stage6d.audit --source-root ../local_only/stage6b_runs --previous-root ../local_only/stage6c_runs --dependency-root ../local_only/stage6b_native --build-root ../local_only/stage6d_native --executable ../local_only/stage6d_native/build/auv6c_runner.exe
.\.venv\Scripts\python.exe -m gsunlight_repro.stage6d.contract --source-root ../local_only/stage6b_runs --previous-root ../local_only/stage6c_runs --local-root ../local_only/stage6d_runs
.\.venv\Scripts\python.exe -m gsunlight_repro.stage6d.witnesses --executable ../local_only/stage6d_native/build/auv6c_runner.exe --dependency-root ../local_only/stage6b_native --local-root ../local_only/stage6d_runs
```

D0第一次调用13例后写汇总失败，命令只读恢复后成功；两轮console分别保存`d0.log`、`d0_retry.log`。`witnesses`在第5图返回码1，完整console在`witnesses.log`，**没有执行planning模块**。

仅针对失败输入进行诊断：

```powershell
.\.venv\Scripts\python.exe scripts/stage6d_probe_build.py --repository-root Z:\erqulunwengfx --dependency-root Z:\local_only\stage6b_native --local-root Z:\local_only\stage6d_probe
.\.venv\Scripts\python.exe -m gsunlight_repro.stage6d.diagnostics --probe ../local_only/stage6d_probe/build/auv6d_probe.exe --dependency-root ../local_only/stage6b_native --local-root ../local_only/stage6d_diagnostic --source-input ../local_only/stage6d_runs/witnesses/terrain_1/input.json
.\.venv\Scripts\python.exe -m gsunlight_repro.stage6d.analysis --source-root ../local_only/stage6b_runs --previous-root ../local_only/stage6c_runs --local-root ../local_only/stage6d_runs
.\.venv\Scripts\python.exe -m gsunlight_repro.stage6d.plots --source-root ../local_only/stage6b_runs --previous-root ../local_only/stage6c_runs --local-root ../local_only/stage6d_runs --diagnostic-root ../local_only/stage6d_diagnostic
.\.venv\Scripts\python.exe scripts/stage6d_checks.py --phase final --local-root ../local_only/stage6d_quality --dependency-root ../local_only/stage6b_native --build-root ../local_only/stage6d_native --probe-root ../local_only/stage6d_probe
```

诊断原始完整Python轨迹首次使用了Python生成的控制边界节点作一致性检查；随后以保存的原生probe输出只读复核，直接使用冻结给定控制积分工具，移除易误解的“native”字段。原始轨迹文件未覆盖，来源澄清在`stage6d_diagnostic/python_witness_scope.json`，没有重复调用native probe。

绘图只使用已有数值，地图图从过淡表面改为明确的占用切片并重画该图，三张最终PNG经`view_image`实际目视验收。未重画科研轨迹数据。

final命令中529项pytest及静态检查成功，但CTest启动受相对DLL PATH影响而失败，原日志全部保留。仅修复质量脚本环境路径后，以Python subprocess和绝对PATH实际重跑脚本编译/静态及两组CTest；每条真实argv、退出码、完整输出见`post_path_fix_checks.json`和`local_only/stage6d_quality/native_recheck`，没有重复pytest或研究实验。

所有构建configure/build/CTest的真实argv、退出码、耗时与日志名分别在`d0_audit.json`和`probe_build_evidence.json`。早期Ruff/pytest错误及路径保护见测试记录。最终云端实际命令由`.github/workflows/stage6d-windows.yml`与Actions job日志保存。
