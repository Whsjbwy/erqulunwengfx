# 6D-R实际命令、目录及复核

本机仓库为`D:\2区论文复现\erqulunwengfx`，以下命令从仓库运行。Python为原`.venv\Scripts\python.exe`，不安装系统工具。历史依赖在`..\local_only\stage6b_native`，复用OMPL 2.0.2、Clang 23.1.5、CMake 3.31.8、Ninja 1.13.2、Boost 1.89、Eigen 3.4及nlohmann/json 3.12。官方源码/许可证及编译来源沿用6B记录，未修改官方源码。

## 已实际执行

只在核对Z盘符未占用后建立指向工作区的临时进程盘符。构建命令实际以ASCII别名执行，结束后核对映射对象再撤销；没有持久PATH或settings修改。原始第一次配置失败也保留在新build_status中。

```powershell
.venv\Scripts\python.exe scripts/stage6dr_build.py --repository-root Z:\erqulunwengfx --dependency-root Z:\local_only\stage6b_native --local-root Z:\local_only\stage6dr_native
```

第一次configure退出3221226505；修正新增脚本的子进程PATH后第二次configure、build、ctest均退出0。实际CMake、编译、CTest完整参数保存在`results/stage6dr/build_evidence.json`；本机原日志为`..\local_only\stage6dr_native\build-00-configure.log`至`build-03-ctest.log`。

```powershell
.venv\Scripts\python.exe -m gsunlight_repro.stage6dr.acceptance --executable ..\local_only\stage6dr_native\build\auv6dr_runner.exe --original-probe ..\local_only\stage6dr_native\build\auv6dr_original_probe.exe --dependency-root ..\local_only\stage6b_native --build-root ..\local_only\stage6dr_native --legacy-root ..\local_only\stage6b_runs --old-map-root ..\local_only\stage6d_runs --local-root ..\local_only\stage6dr_runs
```

实际退出0；完整案例输入/输出及桥接计时分组存为`stage6dr_runs/{boundary,legacy13,maps6}/<case>/`，逐例Python审核另存同目录`independent_audit.json`。复用网格直接引用旧只读缓存；terrain_2此前未原生验收，其缺失缓存仅写入新目录。对任何部分写入/失败进程拒绝静默重跑；已完整保存且输入一致的进程可只读复核。

```powershell
.venv\Scripts\python.exe scripts/stage6dr_quality.py --dependency-root ..\local_only\stage6b_native --build-root ..\local_only\stage6dr_native --acceptance-root results/stage6dr --output results/stage6dr/local-quality
```

实际退出0。完整pytest 534通过（12.70秒），compileall、Ruff、格式及clang-format退出0。该脚本只允许新的质量目录，复核时使用另一新目录，保留原记录。它还实际验证plan请求被入口拒绝。脚本不执行任何随机搜索。

## 单条故障最小复现

本轮已保存精确输入；运行时应让DLL路径包含现有LLVM目录（只影响该PowerShell进程）。下列两个入口接收同一保存输入，新入口成功不依赖更换模型或控制：

```powershell
$env:PATH = (Resolve-Path ..\local_only\stage6b_native\packages\llvm-mingw-20261104-ucrt-x86_64\bin).Path + ';' + $env:PATH
& ..\local_only\stage6dr_native\build\auv6dr_original_probe.exe ..\local_only\stage6dr_runs\f0_original\input.json ..\local_only\stage6dr_audit\recheck-old.json
& ..\local_only\stage6dr_native\build\auv6dr_runner.exe ..\local_only\stage6dr_runs\boundary\original_interval_89\input.json ..\local_only\stage6dr_audit\recheck-new.json
```

旧probe正常退出0表示**成功测得不一致**，JSON应为索引89、expected1/actual0；不能把退出0误读成旧模型接口PASS。新单区间入口JSON应为真实accepted1及agreement=true，`source_interval_index=89`在公开CSV中另存。上面复核命令使用新的输出文件名，须在不存在这些文件时执行，避免覆盖自己的复核证据。原始已测量输入/输出仍留在原文件夹。

新克隆没有本机缓存时，先运行工作流中的官方依赖构建及`stage6b.runner accept`生成冻结13例，再运行上面的6DR验收（不传`--old-map-root`，原生旧四图配对仅本机可用）。模块从未改的6D地图配方重建几何并生成同一单条输入。全流程都是确定性控制，不含规划。

## 最终HEAD云端证明

独立工作流：[stage6dr-windows.yml](../.github/workflows/stage6dr-windows.yml)。检出`${{ github.event.pull_request.head.sha || github.sha }}`并与实际`git rev-parse HEAD`比较。最终运行、job、artifact及实际下载核验结论登记在PR正文；本机ZIP、完整job日志及解析证明位于Git外`..\local_only\stage6dr_quality`，不再提交改变最终HEAD。

artifact名称为`stage6dr-windows-model-interface-evidence`，包含CI逐次结果、JUnit、命令/退出码、CTest日志、plan拒绝证据和`head-evidence.json`。关键字段分别为`engineering_checks_passed`、`original_adapter_mismatch_still_detected`、`new_model_interface_passed`，并要求`new_planning_searches=0`和`h1_authorized=false`。
