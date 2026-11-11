# 阶段三实际运行与复查命令

以下 PowerShell 命令在仓库根目录执行。使用现有 Python 3.11 虚拟环境；无 GPU 训练。原作者资料位于仓库外，本阶段扫描不重新导入作者代码。完整试验目录也必须位于仓库外。

## 冻结基线

```powershell
git status --short
git switch repro/gsunlight-stage2
git switch -c repro/gsunlight-stage3
.venv\Scripts\python.exe -m compileall -q src tests scripts
.venv\Scripts\python.exe -m pytest -q
.venv\Scripts\python.exe -m ruff check .
.venv\Scripts\python.exe -m ruff format --check .
```

阶段二基线实际为 `40008f8`，232 项测试通过。预注册协议与首版观察器提交为 `6a461ad`，在参数扫描前推送；后续补充了 S1 候选产生和父边确认事件，发生在任何 S1 新试验开始前。没有更改阶段二控制器。

## 串行执行

```powershell
.venv\Scripts\python.exe -m gsunlight_repro.stage3.experiment `
  --phase s3 --local-dir ..\local_only\stage3 --output results\stage3

foreach ($phase in @('capacity','size','astar','profile','stop','baselines','sampling','holdout')) {
  .venv\Scripts\python.exe -m gsunlight_repro.stage3.experiment `
    --phase $phase --local-dir ..\local_only\stage3 --output results\stage3
  if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
}

.venv\Scripts\python.exe -m gsunlight_repro.stage3.analysis `
  --local-dir ..\local_only\stage3 --output results\stage3
```

每项搜索由新子进程执行，先加载地图，再启动搜索计时。每项保存独立 `job.json`、`result.json`、控制台输出；S1 seed0 另存有上限的事件 JSONL。已有完整且规格一致的阶段三试验直接引用，不重复计算；发现不完整记录会明确停止，不能静默覆盖。要独立复测，换用新的 `--local-dir` 和 `--output` 目录。

`s3/capacity/size` 中完全相同的参照试验使用同一 `job_id`。阶段表是实验设计视图，不能相加当独立样本数；`unique_runs.csv` 是去重视图。`sampling` 和 `stop` 按事前触发条件运行；未触发时不生成虚构试验行。留出选择仅使用 A/B 开发集，不读取留出结果。

`--phase profile` 固定 S3、seed0、`n_max=10`，依次运行未观察、观察、cProfile 三种测量模式。它们只用于固定工作量一致性和性能归因，不能混进正式速度排名。

## 最终代码检查

```powershell
.venv\Scripts\python.exe -m compileall -q src tests scripts
.venv\Scripts\python.exe -m pytest -v
.venv\Scripts\python.exe -m ruff check .
.venv\Scripts\python.exe -m ruff format --check .
git diff --name-only repro/gsunlight-stage2
git status --short
```

公开提交仅包含自编模块、测试、合成配置、精简表格、图和报告。完整日志、路径、作者资料和虚拟环境不提交。未进行额外文件哈希校验；Git 自身的提交标识仅用于版本追溯。

## 已执行的GitHub交付

```powershell
git add AGENTS.md README.md docs/STAGE3_COMMANDS_CN.md docs/STAGE3_REPORT_CN.md `
  docs/STAGE3_TEST_RESULTS_CN.md src/gsunlight_repro/stage3 `
  tests/test_stage3_observation.py tests/test_stage3_protocol.py `
  tests/test_stage3_results.py results/stage3
git commit -m "feat: complete stage-three failure diagnostics with 112 reproducible trials"
git push -u origin repro/gsunlight-stage3
```

交付代码为 `371412d`。已通过已连接GitHub工具创建[PR #3](https://github.com/Whsjbwy/erqulunwengfx/pull/3)，head=`repro/gsunlight-stage3`、base=`repro/gsunlight-stage2`。后续只补交付链接和已验证的CI记录。没有合并、强制推送或重写历史。
