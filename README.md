# G-Sunlight 科研复现

阶段4A：[中文决策报告](docs/STAGE4A_REPORT_CN.md)、[预注册协议](docs/STAGE4A_PROTOCOL_CN.md)、[实际命令](docs/STAGE4A_COMMANDS_CN.md)、[测试记录](docs/STAGE4A_TEST_RESULTS_CN.md)、[CSV与图表](results/stage4a/README.md)。402次预注册独立运行完成，建议Pivot：新留出集A4有效29/40，RRT重启40/40，共同有效任务上A4长度平均更长约1.12%。新地图和总预算Anytime实验在独立stage4a模块运行，前三阶段保持冻结；结论限于已测试静态零半径折线，不进入4B。

阶段三诊断入口：[中文报告](docs/STAGE3_REPORT_CN.md)、[预注册协议](docs/STAGE3_EXPERIMENT_PROTOCOL_CN.md)、[运行命令](docs/STAGE3_COMMANDS_CN.md)、[独立新结果](results/stage3/README.md)。重点区分首次有效路径、正常完成和预算不足；阶段一/二代码与结果冻结。

阶段三审核：[PR #3](https://github.com/Whsjbwy/erqulunwengfx/pull/3)，目标为阶段二分支，暂不合并。

本仓库提供独立编写的运行包装、体素碰撞验证器、测试和实验记录，用于核查 G-Sunlight 作者提供的三维示例。阶段一运行原版并做隔离诊断；阶段二独立重建论文结构、建立安全参考并开展固定多地图对比。不加入洋流、MPC、Attention、训练或其他科研创新模块。

阶段一（2026-11-10）本机结果：作者计算流程20/20产生路径，原始及后处理严格有效率均0/20；VTK独立查询确认内部穿透。隔离安全诊断容量1/3/5分别为0/20、6/20、5/20。阶段一85项测试通过。详见[中文实验报告](docs/STAGE1_REPORT_CN.md)、[完整测试结果](docs/TEST_RESULTS_CN.md)及[实际命令](docs/RUN_COMMANDS_CN.md)。这些历史结果不并入阶段二性能排名，也不等同于复现论文全部主图表。

论文、作者 ZIP、作者源码和 `map.vti` 均保存在仓库外，不随本项目发布。原仓库公开可见不等于获得再分发许可；所检查材料未附明确的 `LICENSE`。请从[作者原仓库](https://github.com/breaker123344/LIU3Dsunlight)自行取得材料，并遵守其适用授权。

## Windows 安装

需要 Python 3.11。以下 PowerShell 命令在本仓库目录执行；虚拟环境仅保留在本机。

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e '.[dev]'
```

依赖由 `pyproject.toml` 声明：NumPy、PyVista、VTK、OpenCV、Pillow；开发依赖为 pytest 和 Ruff。无需 GPU、CUDA、WSL 或 Docker。

## 作者材料与实验

建议将作者 ZIP 解压为与本仓库并列的 `LIU3Dsunlight-main` 目录。运行工具通过 `--source-dir` 指定该本地目录，通过 `--map-path` 指定原始 `map.vti`；不得把作者文件复制进本仓库。参数使用命令行路径，不依赖个人用户名或固定盘符。

原版首次运行应在作者源码目录执行：

```powershell
Set-Location ..\LIU3Dsunlight-main
..\erqulunwengfx\.venv\Scripts\python.exe main_sunlight_3Dgrid.py --noanimate
```

原入口没有随机种子参数，且 `--noanimate` 仍保留最终窗口。固定种子、超时控制、路径提取和无窗口适配由独立包装记录；它们与原版直接执行分别标识。遇到碰撞或异常后才进行明确标注的本地安全诊断，不覆盖作者原件、不改地图。

批量实验按 seed 0、0—4、条件允许时0—19逐级推进，串行执行。作者声称产生路径与独立严格有效路径分别统计；原始路径与后处理路径也分别验证。严格检查针对零半径折线，障碍体素的面、棱、角接触均判为碰撞。它不证明带实体半径和动力学约束的 AUV 可执行。

回到本仓库后执行以下命令。首次可将 `$seeds` 改成 `@(0)`，小规模检查用 `0..4`。

```powershell
$seeds = 0..19
.\.venv\Scripts\python.exe -m gsunlight_repro.experiment_runner `
  --source-dir ..\LIU3Dsunlight-main --map-path ..\LIU3Dsunlight-main\map.vti `
  --seeds $seeds --timeout 120 --output results\stage1_summary.csv `
  --local-dir ..\local_only\baseline20

.\.venv\Scripts\python.exe -m gsunlight_repro.crosscheck `
  --map-path ..\LIU3Dsunlight-main\map.vti `
  --paths-file ..\local_only\baseline20\paths.jsonl `
  --output results\vtk_crosscheck.csv --max-spacing 0.02
```

父验证进程和持久规划子进程各读取地图一次，逐 seed 重用；每轮重新导入作者工具模块并同时重置两个随机源。原版 `Plotter` 和五个纯显示函数被明确跳过，计算代码不变。CSV 每个 seed 有原始/后处理两行；`status=ok` 仅表示作者程序正常产生路径，`strict_valid` 才是独立碰撞与端点检查。密集 VTK 查询只是辅证。每次重跑请使用新的本地记录目录，避免与旧的 `paths.jsonl` 混合。

## 隔离安全诊断

此步骤在完成原版验证后运行。容量1可直接引用原始源码；容量3、5通过自编脚本建立仓库外的小型源码副本，只改容量，不复制地图。以下以容量3为例，输出目录必须不存在。

```powershell
.\.venv\Scripts\python.exe scripts\prepare_diagnostic_source.py `
  --source-dir ..\LIU3Dsunlight-main `
  --output-dir ..\local_only\diagnostic_cons3 --capacity 3

.\.venv\Scripts\python.exe -m gsunlight_repro.experiment_runner `
  --source-dir ..\local_only\diagnostic_cons3 --map-path ..\LIU3Dsunlight-main\map.vti `
  --seeds (0..19) --timeout 120 --mode safety_cons3 `
  --adapter-path scripts\safety_adapter.py --output results\diagnostic_cons3.csv `
  --local-dir ..\local_only\diagnostic_cons3_20
```

独立 hooks 过滤不安全父连边、严格检查目标连接、支持当前太阳直连目标，并对后处理完整复检和回退。为适应原入口，直连用零增量重复候选表示，证据保留重复点。多项措施同时改变，容量对比属于安全诊断，不能作单因素因果消融，也不是作者论文结果。

论文与源码核对见 [论文和源码审计](docs/PAPER_CODE_AUDIT_CN.md)。实际运行命令、退出码、环境、实验范围和未完成项以最终 `docs/STAGE1_REPORT_CN.md` 为准；任何未执行的实验都不能视为通过。

## 阶段二：独立重建与多地图对比

五个方法分别为 Author-Original、Paper-Reimplementation、Safety-Reference、A*和RRT-Connect。阶段二安全参考是独立自编实现，与上述阶段一作者代码hooks诊断身份分开。方法版本、参数和运行顺序见[版本与运行指南](docs/STAGE2_VERSION_GUIDE_CN.md)，论文对应关系见[三版本差异表](docs/STAGE2_PAPER_CODE_DIFF_CN.md)及[重建假设](docs/STAGE2_ASSUMPTIONS_CN.md)。

在本仓库中先执行单场景、单seed预检；两处输出必须使用新名称，本地路径证据保存在仓库外：

```powershell
.\.venv\Scripts\python.exe -m gsunlight_repro.benchmark `
  --source-dir ..\LIU3Dsunlight-main `
  --map-config configs/stage2_maps.json `
  --experiment-config configs/stage2_experiment.json `
  --scenes S0 --seeds 0 --run-id stage2-s0-example `
  --local-dir ..\local_only\stage2_s0_example `
  --output results/stage2/s0_example.csv
```

S0—S4是五套提前冻结的确定性场景配方，`map_seed`只是配方标识，没有随机生成障碍；五个规划seed不代表五张随机地图。地图沿用作者坐标范围及原始端点，S3是自编合成海床，不是论文海床重建。先完成各场景单次预检，确认记录与资源控制可信后，再按指南扩展至0—4共五个规划seed，不能按成功率改地图或挑选结果。

主要比较原始路径；共同严格shortcut作为次要结果，作者原生后处理单列。`reported_success`、`strict_valid`和预算内成功分别统计，未知用空值；各方法 `sampled_nodes`单位不同，不能直接排名。实际完成范围、命令、测试及结论见[阶段二报告](docs/STAGE2_REPORT_CN.md)、[阶段二完整测试结果](docs/STAGE2_TEST_RESULTS_CN.md)和[阶段二汇总](results/stage2/summary.csv)，不在此预填未完成实验数字。

## 代码检查

```powershell
.\.venv\Scripts\python.exe -m compileall -q src tests scripts
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m ruff check .
.\.venv\Scripts\python.exe -m ruff format --check .
```

请勿提交虚拟环境、缓存、原始材料、逐点大日志或私密信息，也不生成额外文件哈希或校验清单。工作只推送独立分支并创建 Pull Request，每一阶段完成后等待研究者审核，不自行合并 `main`。

## 研究引用

Deng, Y., Zhao, J., Yan, J., Liu, F., and Zhao, D. (2026). *Novel Sunlight Algorithm for AUV Fast Global Path Planning With Grid-Constrained Sampling*. Journal of Field Robotics. [DOI: 10.1002/rob.70356](https://doi.org/10.1002/rob.70356)。

作者代码来源：[breaker123344/LIU3Dsunlight](https://github.com/breaker123344/LIU3Dsunlight)。本仓库是独立核查工具，单张示例地图的运行不能等同于复现论文全部主图、表格或实体实验。
