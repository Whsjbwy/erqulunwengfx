# 阶段5A-E执行命令与记录位置

本阶段在Windows 11 PowerShell、仓库`D:\2区论文复现\erqulunwengfx`执行。Python使用已有`.venv\Scripts\python.exe`，没有新增依赖。完整轨迹、原始规划证书、逐步失败记录留在仓库外；公开CSV可由这些记录重新派生，不改写历史结果。

## 冻结与顺序

- 历史基线：PR #5 / `8c69bb5`，PR #6 / `9dbd5ec`；两者检查时均开放、未合并。
- 本分支：`audit/auv-stage5ae-evaluation`，PR目标：`audit/auv-stage5ar-execution`。
- `4cd92ab`在新实验前提交并推送协议、地图配方和预算。
- E0→E1小样本→完整开发集→E2后，`be3623d`提交并推送全部候选和选定LOS参数；随后才生成新地图和查看独立结果。
- E3先36次门槛，再360次正式矩阵，完整复用门槛记录。不得把两者相加为396次，也不得混入旧157条诊断路径或pytest测试数。

## 实际阶段调用

```powershell
$env:PYTHONIOENCODING='utf-8'
$env:OMP_NUM_THREADS='1'
$env:OPENBLAS_NUM_THREADS='1'
$env:MKL_NUM_THREADS='1'
$python='.venv/Scripts/python.exe'
$evidence='../local_only/stage5ae'
$old='../local_only/stage5ar'
$history='../local_only/stage5a_amend1'

& $python -m gsunlight_repro.stage5ae.runner --phase e0 --history $history --old-evidence $old --local-dir $evidence --output results/stage5ae
& $python -u -m gsunlight_repro.stage5ae.runner --phase e1_pilot --history $history --old-evidence $old --local-dir $evidence --output results/stage5ae
& $python -u -m gsunlight_repro.stage5ae.runner --phase e1 --history $history --old-evidence $old --local-dir $evidence --output results/stage5ae
& $python -u -m gsunlight_repro.stage5ae.runner --phase e2 --history $history --old-evidence $old --local-dir $evidence --output results/stage5ae
& $python -m gsunlight_repro.stage5ae.runner --phase freeze --history $history --old-evidence $old --local-dir $evidence --output results/stage5ae
& $python -u -m gsunlight_repro.stage5ae.runner --phase gate --history $history --old-evidence $old --local-dir $evidence --output results/stage5ae
& $python -u -m gsunlight_repro.stage5ae.runner --phase formal --history $history --old-evidence $old --local-dir $evidence --output results/stage5ae
```

实际长运行使用`2>&1 | Tee-Object -FilePath <日志路径>`保存完整输出并返回`$LASTEXITCODE`。E1/E2与E3日志分别为`D:\2区论文复现\local_only\stage5ae_audit\e1_pilot.log`、`e1_full.log`、`e2.log`、`e3_gate.log`、`e3_formal.log`。解析与核心测试输出为`analytic_first.log`、`core_tests.log`。每关完成标记在`stage5ae/*_completed.json`，只在整关结束后写入。

原始记录使用排他创建；不要对已有完整目录重新运行会输出同名不可变记录的E0/E2。新计算机如需完整重跑，应指定新的仓库外证据目录，保留此前记录。固定墙钟预算的计算吞吐受机器和负载影响；不承诺跨机器逐坐标相同。地图生成与随机种子固定，不能按结果换种子。

水平小型参考通过`gsunlight_repro.stage5ae.verification.horizontal_reference()`独立实际运行，6个条件的完整输出保存在`stage5ae/horizontal_reference.json.gz`；绘图命令从该文件读取实际轨迹，不重复积分。水平圆弧参考不进入正式三维矩阵。

## 完成后的派生与独立审计

```powershell
& $python -m gsunlight_repro.stage5ae.analysis --local-dir $evidence --old-evidence $old --output results/stage5ae --complete
& $python -m gsunlight_repro.stage5ae.audit --local-dir $evidence --old-evidence $old --output results/stage5ae
& $python -m gsunlight_repro.stage5ae.plots --local-dir $evidence --old-evidence $old --output results/stage5ae
```

不要在formal尚未完成、正在写gzip时并发读取全部实验记录。CSV和图是可重建的派生物；规划/轨迹原始记录不被这些命令覆盖。统计bootstrap固定seed 65888、2000次，以整张地图为聚类单位。

本次发生过一次误启动重复进程，原session 86933仍运行，重复session 60293因排他保存冲突退出1。保留`e3_formal_resume1.log`与`interruption_scan.json`，不把进程列表不可见当退出证据，先轮询原终端、核对活动日志与完成标记。后续CLI已增加目录进程锁。预登记`e682aad`明确只在formal结束后额外运行一次下列单任务运维复核，不替换360条原记录：

```powershell
& $python -m gsunlight_repro.stage5ae.resource_recheck --local-dir $evidence --old-evidence $old --output results/stage5ae
```

该命令必须使用尚未创建过`stage5ae/resource_recheck`子目录的完整原证据目录；完成或失败后都不自动重复。它不是新增科研种子或参数搜索。两次搜索之外的原主矩阵不会被覆盖。

## 质量检查

```powershell
& $python -m pytest -v --junitxml=../local_only/stage5ae_audit/final_pytest.xml
& $python -m ruff check .
& $python -m ruff format --check .
& $python -m compileall -q src tests scripts
```

完整本机日志和JUnit保留在`stage5ae_audit`，公开精简退出状态及逐项测试CSV。Windows CI使用`.github/workflows/stage5ae-windows.yml`，从GitHub官方job日志核实结果；CI只跑正确性与公开结果检查，不重新执行360次科研矩阵。

Git提交仅选择新`stage5ae`模块、新测试、新配置、新文档、新工作流与`results/stage5ae`。不生成额外文件哈希清单，不提交完整轨迹、作者材料、虚拟环境或凭据，不合并任何历史PR或main。
