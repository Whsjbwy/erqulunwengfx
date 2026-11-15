# 阶段6B实际构建与验收命令

以下是本次调用的精简等价形式；逐次完整argv、退出码和耗时保存在仓库外`local_only/stage6b_native/build_status.json`。本文不执行命令，也不以命令文本代替执行证据。B0/B1已实际通过，搜索完成情况及最终项目检查、CI结论须查看最终总账与主报告。

## 路径和原生构建

在仓库根目录使用已有Python 3.11环境。`Z:`必须事先确认没有被其他工作占用；本次只将原工作目录建立临时盘符别名，不复制依赖或修改系统PATH。

```powershell
Set-Location 'D:\2区论文复现\erqulunwengfx'
subst Z: 'D:\2区论文复现'
.\.venv\Scripts\python.exe scripts\stage6b_build.py --local-root Z:\local_only\stage6b_native --repository-root Z:\erqulunwengfx --jobs 2
```

构建脚本锁定官方源码包与版本，设置局部工具PATH，保留失败日志；首次下载成功解压后删除下载归档，实际源树只保存一份。完整依赖构建参数及失败修复见[构建记录](STAGE6B_BUILD_CN.md)。上面命令表示修正后的完整构建入口，不能声称00—20所有历史尝试均使用其最终参数。

脚本支持分阶段入口：

```powershell
.\.venv\Scripts\python.exe scripts\stage6b_build.py --local-root Z:\local_only\stage6b_native --repository-root Z:\erqulunwengfx --jobs 2 --dependencies-only
.\.venv\Scripts\python.exe scripts\stage6b_build.py --local-root Z:\local_only\stage6b_native --repository-root Z:\erqulunwengfx --jobs 2 --adapter-only
```

这两个入口用于依赖和适配器分阶段执行；是否发生过某次调用，以`build_status.json`中记录的底层命令为准。脚本遇到非零退出码即报错保留记录，不能忽略错误后直接开始搜索。

最终适配器CTest对应实际编号20，底层调用为：

```powershell
& 'Z:\local_only\stage6b_native\packages\cmake-3.31.8-windows-x86_64\bin\ctest.exe' --test-dir 'Z:\local_only\stage6b_native\build\adapter' --output-on-failure
```

实际1/1测试通过，总时间0.13秒；该测试内部含6组模型/几何检查。不是上游OMPL全部测试，也不是Python全套pytest的替代。

## 13例原生接口验收

```powershell
.\.venv\Scripts\python.exe -m gsunlight_repro.stage6b.runner accept --executable '..\local_only\stage6b_native\build\adapter\auv6b_runner.exe' --build-root '..\local_only\stage6b_native' --local-root '..\local_only\stage6b_runs'
```

runner先核对官方构建和CTest真实成功记录，再调用原生接口。完整请求、结果和进程输出位于`local_only/stage6b_runs/acceptance/<scenario_id>`；公开13例CSV及汇总位于`results/stage6b`。实际13/13符合预期、936次适配propagator调用、930接受区间；没有把这些给定控制称为规划搜索结果。

当前运行目录已经包含本次真实证据。不要为了重现展示而对已有目录直接重复验收；原生调用使用排他目录防止覆盖。重新实验应另行明确新目录与新记录，不能删除原记录后重跑。

## 预登记搜索入口

只有B0/B1均通过后才可执行。先做两个直线任务，再原位复用这两个任务，串行运行预登记36个任务的其余部分：

```powershell
.\.venv\Scripts\python.exe -m gsunlight_repro.stage6b.runner search --executable '..\local_only\stage6b_native\build\adapter\auv6b_runner.exe' --build-root '..\local_only\stage6b_native' --local-root '..\local_only\stage6b_runs' --pilot-only
.\.venv\Scripts\python.exe -m gsunlight_repro.stage6b.runner search --executable '..\local_only\stage6b_native\build\adapter\auv6b_runner.exe' --build-root '..\local_only\stage6b_native' --local-root '..\local_only\stage6b_runs'
```

两条搜索入口不能并发运行，目录锁负责阻止同一记录树多worker。pilot属于36任务，不额外再计2次；标签种子0/1预先映射原生1/2。每任务新原生进程，模型和采样支持一致，规划总预算10秒含桥接与独立证书，搜索最多8秒。完整参数见[冻结配置](../configs/stage6b_protocol.json)。

冻结LOS由同一runner为严格合格exact参考执行，使用显式共同初态；原生控制可行与LOS严格成功分开统计。approximate、no_solution、deadline和接口失败全部保留，不通过另挑种子或改阈值补成功。本文不在搜索进行中填写最终成功数。

## 证据路径与临时映射清理

| 路径 | 内容 |
| --- | --- |
| `local_only/stage6b_native/build_status.json` | 00—20底层命令、真实退出码及耗时 |
| `local_only/stage6b_native/build-*.log` | 21份逐次构建原始输出，包含6次失败 |
| `local_only/stage6b_native/cmake_diagnostic_trace.log` | 额外一次诊断调用，不与编号21条混为一谈 |
| `local_only/stage6b_native/packages`、`prefix`、`build` | 私有工具/官方依赖源码、安装静态库及自编适配器产物 |
| `local_only/stage6b_runs/acceptance` | 13例完整原生输入/输出与进程日志 |
| `local_only/stage6b_runs` | 搜索与独立轨迹的本地排他记录树；保留全部失败 |
| `results/stage6b/interface_cases.csv` | 公开逐例接口证据 |
| `results/stage6b/planning_runs.csv` | 公开逐次搜索与跟踪记录；完整性以最终总账为准 |

构建/增量构建全部结束后撤销本任务创建的盘符映射：

```powershell
subst Z: /D
```

该清理只移除临时别名，不删除D盘原目录、依赖、轨迹或日志。不要在本次构建仍使用`Z:`时提前清理，也不要借此修改其他盘符。完整日志/数值证据不公开进Git；最终仅提交自编代码、精简CSV、必要图与中文报告，不生成额外文件hash清单。
