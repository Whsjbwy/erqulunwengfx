# 第四阶段4A实际命令

所有命令在仓库根目录PowerShell执行。使用原有Python3.11虚拟环境，无GPU训练。作者资料和前三阶段结果不参与4A新矩阵。

## 基线与预注册

```powershell
git status --short
git switch -c repro/gsunlight-stage4a
.venv\Scripts\python.exe -m pytest -q
.venv\Scripts\python.exe -m ruff check .
.venv\Scripts\python.exe -m ruff format --check .
.venv\Scripts\python.exe -m compileall -q src tests scripts
git add configs/stage4a_protocol.json configs/stage4a_maps.json docs/STAGE4A_PROTOCOL_CN.md
git commit -m "docs: preregister stage-4A matrix, independent maps and Go-Pivot criteria"
git push -u origin repro/gsunlight-stage4a
```

基线为阶段三d3a8e96，265项测试通过。预注册提交70422ec在所有4A正式搜索前推送；核心实现f54a66d通过308项测试；3fea66f补记工程等价性、计时和事后审计时间字段后开始正式预检。此后只新增分析、图表、测试和文档，不根据结果调整搜索核心。

## 工程对照

```powershell
$env:OMP_NUM_THREADS='1'
$env:OPENBLAS_NUM_THREADS='1'
$env:MKL_NUM_THREADS='1'
$env:VTK_SMP_MAX_THREADS='1'
.venv\Scripts\python.exe -m gsunlight_repro.stage4a.runner `
  --phase engineering --local-dir ..\local_only\stage4a --output results\stage4a
```

S1、D1固定n_max3、seed0、非约束120秒截止。先进行各模式的展开序列和路径等价性检查，再每种模式重复5次，按确定性轮换顺序运行，共30次计时。缓存每次重新建立，不挑最快值。工程命令拒绝覆盖已有证据；要独立复测请使用新的本地目录及输出目录。

## 单种子预检与固定矩阵

首先实际执行以下Python片段，对S1/D1/D2四组各运行seed0，共12次，检查预算、内存和安全后再扩展：

```python
from pathlib import Path
from gsunlight_repro.stage4a.runner import Runner

runner = Runner(Path("../local_only/stage4a"), Path("results/stage4a"))
for scene in runner.protocol["pilot_maps"]:
    for method in runner.protocol["angles"]:
        runner.run(scene, method, 0)
```

```powershell
.venv\Scripts\python.exe -m gsunlight_repro.stage4a.runner `
  --phase pilot --local-dir ..\local_only\stage4a --output results\stage4a

foreach ($phase in @('development','holdout','negative')) {
  .venv\Scripts\python.exe -m gsunlight_repro.stage4a.runner `
    --phase $phase --local-dir ..\local_only\stage4a --output results\stage4a
  if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
}

.venv\Scripts\python.exe -m gsunlight_repro.stage4a.analysis `
  --local-dir ..\local_only\stage4a --output results\stage4a
```

每阶段先所有方法seed0，再按1—4执行；pilot只到2。相同预检任务自动复用，不重算、不增加独立样本。每个新trial启动全新子进程，固定单个可用逻辑CPU、普通优先级，线程环境1。无有效路径也保留完整失败记录，不会改种子。使用`--no-figures`可以仅重新派生表格，不影响原始证据。

全局30秒包含搜索、外部完整路径确认和共同shortcut；地图加载、进程启动及事后指标不占规划预算，各自记录。若遇程序错误、非法候选或外部守护，controller停止并留下error.json，不覆盖成成功。固定configuration.json发生变更也会拒绝复用。既往结果目录不是新增实验的缓存来源。

## 检查与交付

```powershell
.venv\Scripts\python.exe -m compileall -q src tests scripts
.venv\Scripts\python.exe -m pytest -v
.venv\Scripts\python.exe -m ruff check .
.venv\Scripts\python.exe -m ruff format --check .
git diff --name-only --diff-filter=M repro/gsunlight-stage3
git status --short
```

公开提交只含自编代码、合成配置、测试、精简表格、图及报告。原始每次试验只保存一份本地证据，改善路径按path_id引用，不重复保存逐射线轨迹；无额外文件hash/校验清单。Git push只针对stage4a，PR目标stage3，不合并。实际试验是否已完成须看experiment_accounting.json，不能以命令列表代替完成证据。
