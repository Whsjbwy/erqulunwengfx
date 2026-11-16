# 阶段6C真实执行命令与证据位置

以下均对应实际调用；省略前缀为仓库根目录的已有`.venv/Scripts/python.exe`。命令文本不代替执行证据。所有搜索已经完成，**不要在现有目录重跑**。重放/原生调用使用排他目录，pilot完整记录只复用一次。

## 审计、解析验收和C1

```powershell
.\.venv\Scripts\python.exe -m gsunlight_repro.stage6c.audit --source-root ..\local_only\stage6b_runs --build-root ..\local_only\stage6b_native
.\.venv\Scripts\python.exe -m pytest tests/test_stage6c_reference.py -q
.\.venv\Scripts\python.exe -m gsunlight_repro.stage6c.contract --source-root ..\local_only\stage6b_runs --local-root ..\local_only\stage6c_runs
```

预登记提交`5037f5c`先于上述实验；C1代码/解析证据提交`d51c346`、完整独立执行计时澄清`603c900`先于21次新重放。C0不搜索、不模拟新轨迹。C1基线直接读取6B保存记录。

## 原生构建与13例验收

复用6B现有官方依赖、工具和JSON头文件，只构建6C新目标；不重复保存依赖。中文路径下使用指向同一目录的临时ASCII别名，须先确认Z未被其他任务占用：

```powershell
subst.exe Z: 'D:\2区论文复现'
.\.venv\Scripts\python.exe scripts/stage6c_build.py --repository-root Z:\erqulunwengfx --dependency-root Z:\local_only\stage6b_native --local-root Z:\local_only\stage6c_native --jobs 2
.\.venv\Scripts\python.exe -m gsunlight_repro.stage6c.acceptance --source-root ..\local_only\stage6b_runs --executable ..\local_only\stage6c_native\build\auv6c_runner.exe --dependency-root ..\local_only\stage6b_native --local-root ..\local_only\stage6c_runs
```

首次沙箱映射被拒绝，尚未进入编译；获准构建权限后配置成功。首次编译因PSAPI头文件顺序失败；修复后重新配置/编译/CTest成功。编号构建命令共5条、1失败，另有前置映射失败。命令/耗时见[build_evidence.json](../results/stage6c/build_evidence.json)，完整5份日志位于`local_only/stage6c_native`。13例最大状态差0，实际930接受区间、936次传播调用。

## 固定72次校准

提交`da7048d`先于4次pilot；提交`52c9eca`保留检查器故障、明确失败计时和修复后，才扩展其余68次。

```powershell
.\.venv\Scripts\python.exe -m gsunlight_repro.stage6c.calibration --source-root ..\local_only\stage6b_runs --dependency-root ..\local_only\stage6b_native --build-root ..\local_only\stage6c_native --executable ..\local_only\stage6c_native\build\auv6c_runner.exe --local-root ..\local_only\stage6c_runs --pilot-only
.\.venv\Scripts\python.exe -m gsunlight_repro.stage6c.recovery --local-root ..\local_only\stage6c_runs
.\.venv\Scripts\python.exe -m gsunlight_repro.stage6c.calibration --source-root ..\local_only\stage6b_runs --dependency-root ..\local_only\stage6b_native --build-root ..\local_only\stage6c_native --executable ..\local_only\stage6c_native\build\auv6c_runner.exe --local-root ..\local_only\stage6c_runs
```

恢复入口只执行过一次，只读复核已返回控制，把原预算时钟保留为空、M/S为失败，没有重新搜索。三条完整pilot记录原位复用，第四条故障记录也留在72分母中。`pilot_console.log`、`calibration_console.log`和`stopped-*.json`保留全部异常和实际输出。

## 只读终审、绘图和完整检查

```powershell
.\.venv\Scripts\python.exe -m gsunlight_repro.stage6c.analysis --source-root ..\local_only\stage6b_runs --local-root ..\local_only\stage6c_runs
.\.venv\Scripts\python.exe -m gsunlight_repro.stage6c.plots --source-root ..\local_only\stage6b_runs --local-root ..\local_only\stage6c_runs
.\.venv\Scripts\python.exe -m compileall -q src tests scripts
.\.venv\Scripts\python.exe -m pytest -q --junitxml=..\local_only\stage6c_quality\pytest.xml
.\.venv\Scripts\python.exe -m ruff check .
.\.venv\Scripts\python.exe -m ruff format --check .
```

终审执行过两遍：第二遍增加冻结内环与严格时钟门槛核对，不产生新规划/闭环实验。绘图后实际查看全部3图；C1图例遮挡修正后只重绘该图并重新检查，QA为passed。再次运行绘图会重置视觉QA，不能沿用旧状态。

CTest实际命令由构建脚本执行：`ctest.exe --test-dir Z:/local_only/stage6c_native/build --output-on-failure`，2/2通过。最终又直接运行两个原生测试程序；clang-format对3个新C++文件执行`--dry-run --Werror`，样式为LLVM、4空格、100列。实际完整argv/退出码/输出见[local_checks.json](../results/stage6c/local_checks.json)，原日志与JUnit在`local_only/stage6c_quality`。

所有构建结束后，仅撤销本任务创建、且确认指向原工作目录的Z别名：`subst.exe Z: /D`。该操作不删除目录或历史文件；撤销结果见交付审核记录。未来增量构建需要重新建立同样别名，普通exe运行使用实际D盘路径与子进程DLL环境。

Windows最终HEAD工作流额外生成`stage6c-windows-evidence` artifact，其中含实际检出HEAD、JUnit、两套确定性接口摘要与原生构建/CTest证据。CI不运行72次随机搜索；正式结果来自本机原始目录。
