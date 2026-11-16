# 6D-S真实命令与执行证据

本机仓库`D:\2区论文复现\erqulunwengfx`，Python为原`.venv\Scripts\python.exe`。以下为已实际执行命令。最终CI与artifact准确HEAD证明见[PR #14](https://github.com/Whsjbwy/erqulunwengfx/pull/14)。

## 预审、登记与构建

先完整读取Downloads中的研究者任务书及本地规范，核对PR #13准确HEAD和Windows CI。只读基线pytest为534通过（12.63秒），保留在Git外`local_only/stage6ds_audit`。研究者确认超过3文件方案后，新建独立分支，并在编码/搜索前提交继承快照及54条manifest。

现有依赖目录`..\local_only\stage6b_native`复用官方OMPL2.0.2、Clang23.1.5、CMake3.31.8、Ninja1.13.2、Boost1.89、Eigen3.4及JSON3.12。未下载新的本机工具或安装系统组件。核对盘符未占用后临时映射工作区用于构建，结束再核对准确对象撤销。

```powershell
.venv\Scripts\python.exe scripts/stage6ds_build.py --repository-root Z:\erqulunwengfx --dependency-root Z:\local_only\stage6b_native --local-root Z:\local_only\stage6ds_native
```

第一次configure退出1：CMake导入目标作用域错误，日志`build-00-configure.log`保留。修正新增父CMake的依赖声明后configure/build/ctest均退出0；补齐输入守卫和身份元数据后再次构建通过。完整7条编号命令含1失败、6成功，见`results/stage6ds/build_evidence.json`，原日志留在新构建目录。CTest实际5/5，不把旧故障检测通过当成旧接口PASS。

## P1实际入口验收和搜索前工程检查

```powershell
.venv\Scripts\python.exe -m gsunlight_repro.stage6ds.acceptance --executable ..\local_only\stage6ds_native\build\auv6ds_runner.exe --original-probe ..\local_only\stage6ds_native\build\frozen6dr\auv6dr_original_probe.exe --dependency-root ..\local_only\stage6b_native --build-root ..\local_only\stage6ds_native --legacy-root ..\local_only\stage6b_runs --grid-reference ..\local_only\stage6d_runs\grids --grid-reference ..\local_only\stage6dr_runs\grids --local-root ..\local_only\stage6ds_acceptance
.venv\Scripts\python.exe scripts/stage6ds_quality.py --dependency-root ..\local_only\stage6b_native --build-root ..\local_only\stage6ds_native --acceptance-root results/stage6ds/acceptance --output results/stage6ds/prepilot-quality
```

实际验收69+13+6图及3个planner构造身份检查通过，随机solve为0；搜索前539项pytest（13.12秒）、compileall/Ruff/格式/clang-format通过。本机完整输入、输出及计时在`stage6ds_acceptance`，公开3398区间CSV及摘要在`results/stage6ds/acceptance`。非法源状态标明未传播，不伪造测量。

## 原pilot与完整54

```powershell
.venv\Scripts\python.exe -m gsunlight_repro.stage6ds.planning --executable ..\local_only\stage6ds_native\build\auv6ds_runner.exe --dependency-root ..\local_only\stage6b_native --acceptance-root results/stage6ds/acceptance --quality-root results/stage6ds/prepilot-quality --local-root ..\local_only\stage6ds_runs --grid-reference ..\local_only\stage6d_runs\grids --grid-reference ..\local_only\stage6dr_runs\grids --grid-reference ..\local_only\stage6ds_acceptance\grids --pilot-only
```

实际退出0，三次审核合格后提交pilot账本。随后使用**完全相同命令去掉`--pilot-only`**，读取并核对原三份请求/输出，实际只新增其余51次。两个阶段实际退出0。`pilot_accounting.json`和`accounting.json`分别保留；后续批次wall不含已完成pilot的搜索时间，逐次性能时钟以原始文件为准。

每任务`search/<job_id>/`保存唯一input/output、stdout/stderr、native_clock、certificate_clock、必要execution_clock、condition_summary和独立记录`independent_record.json.gz`。任何部分目录拒绝重试；硬冲突停止并写BLOCKED。正常近似、最终证书逾期均保留，不补跑。全54目录单份存在。

## 只读终审、统计与最后质量检查

```powershell
.venv\Scripts\python.exe -m gsunlight_repro.stage6ds.audit --local-root ..\local_only\stage6ds_runs
.venv\Scripts\python.exe -m gsunlight_repro.stage6ds.analysis --local-root ..\local_only\stage6ds_runs
.venv\Scripts\python.exe scripts/stage6ds_quality.py --dependency-root ..\local_only\stage6b_native --build-root ..\local_only\stage6ds_native --acceptance-root results/stage6ds/acceptance --output results/stage6ds/final-local-quality
.venv\Scripts\python.exe -m gsunlight_repro.stage6ds.public_evidence --quality-root results/stage6ds/final-local-quality
```

实际均退出0。终审不执行native进程，不改变原性能时钟；统计和可用incumbent披露仅读取原54结果，没有新搜索/控制重放。统计图已逐张视觉检查。补充统计单元测试后最终545项pytest通过（13.38秒），0失败/错误/跳过，其余检查退出0，旧6D-R plan守卫实际退出1。

质量目录仅接受新路径，复核请另用新目录，禁止覆盖原记录。本机head-evidence如实标为工作树检查，准确最终PR HEAD由独立Windows CI检出再验证。CI从官方固定源码构建、执行5CTest、实际入口确定性验收与全量Python检查，仅核对公开的本机54账本，不重跑性能实验。

最终CI名称Stage 6D-S Windows actual planner contract，artifact为`stage6ds-windows-actual-planner-evidence`。最终HEAD、run/job、artifact及实际下载解析证明登记在PR正文，本机原ZIP/完整job日志保留Git外`local_only/stage6ds_quality`。完成后停止，不合并、不进入H1。
