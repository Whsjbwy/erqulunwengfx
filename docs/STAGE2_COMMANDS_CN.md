# 第二阶段实际命令与运行记录

日期2026-11-10；以下从仓库根目录执行，PowerShell。环境Python3.11.15，作者目录在仓库外；完整stdout、stderr、路径及配置快照留在`../local_only`。未执行额外文件哈希。

## 分支、安装与回归

```powershell
git switch -c repro/gsunlight-stage2 repro/gsunlight-stage1
$env:UV_CACHE_DIR = 'D:\2区论文复现\local_only\uv_cache'
uv pip install --python .venv\Scripts\python.exe -e . --no-deps --offline
.venv\Scripts\python.exe -m gsunlight_repro.experiment_runner `
  --source-dir ..\LIU3Dsunlight-main --map-path ..\LIU3Dsunlight-main\map.vti `
  --seeds 0 --timeout 30 --mode author_original `
  --output ..\local_only\stage2_author_regression0.csv `
  --local-dir ..\local_only\stage2_author_regression0
```

原图seed0与阶段一的全部路径坐标、参数、节点数和原计数一致。可编辑安装更新Windows入口时首次受沙箱拒绝，获准后同命令离线成功；未下载额外训练框架。

## 单次预检与正式试验

最早另做S0的`author_original astar rrt_connect`三方法seed0预检，输出`../local_only/stage2_preflight_S0.csv`，不混入主数据。随后按以下顺序执行：

```powershell
.venv\Scripts\python.exe -m gsunlight_repro.benchmark `
  --scenes S0 --seeds 0 --run-id stage2_single_S0 `
  --source-dir ..\LIU3Dsunlight-main --local-dir ..\local_only\stage2_single_S0 `
  --output ..\local_only\stage2_single_S0.csv

.venv\Scripts\python.exe -m gsunlight_repro.benchmark `
  --scenes S1 --seeds 0 --run-id stage2_single_S1 `
  --source-dir ..\LIU3Dsunlight-main --local-dir ..\local_only\stage2_single_S1 `
  --output ..\local_only\stage2_single_S1.csv

.venv\Scripts\python.exe -m gsunlight_repro.benchmark `
  --scenes S1 --seeds 0 1 2 3 4 --run-id stage2_pilot_S1_5seeds `
  --source-dir ..\LIU3Dsunlight-main --local-dir ..\local_only\stage2_pilot_S1_5seeds `
  --output results\stage2\pilot_S1.csv

.venv\Scripts\python.exe -m gsunlight_repro.benchmark `
  --scenes S0 S2 S3 S4 --seeds 0 1 2 3 4 --run-id stage2_remaining_4maps `
  --source-dir ..\LIU3Dsunlight-main --local-dir ..\local_only\stage2_remaining_4maps `
  --output results\stage2\remaining_4maps.csv
```

未显式给方法时均为五方法；采用`configs/stage2_maps.json`和`configs/stage2_experiment.json`。实际门槛为S0/S1单次→S1五seed→其余四图五seed。两个正式part共125条，保留原样，预检不计入分母。搜索代码与参数在正式试验期间冻结；两条终止原因的分类修正只涉及诊断标签，不改变搜索计算。

## 合并、统计和绘图

```powershell
.venv\Scripts\python.exe scripts\combine_stage2_results.py `
  --csv results\stage2\pilot_S1.csv results\stage2\remaining_4maps.csv `
  --paths ..\local_only\stage2_pilot_S1_5seeds\paths.jsonl ..\local_only\stage2_remaining_4maps\paths.jsonl `
  --output results\stage2\runs.csv `
  --combined-paths ..\local_only\stage2_combined\paths.jsonl `
  --nodes-output results\stage2\node_counts.csv --expected-trials 125
.venv\Scripts\python.exe -m gsunlight_repro.summarize `
  --input results\stage2\runs.csv --output results\stage2\summary.csv `
  --failures-output results\stage2\failure_mechanisms.csv
.venv\Scripts\python.exe -m gsunlight_repro.plotting `
  --paths-file ..\local_only\stage2_combined\paths.jsonl `
  --output-dir results\stage2\figures --seed 0
```

合并前校验键唯一、CSV/JSONL配对及125条完整性，不修改原始part。再次运行时必须给新输出路径，工具拒绝覆盖。图片固定seed0，不择优挑图；仅绘图减采样障碍，实际碰撞使用完整地图。

额外调用已公开的`dense_vtk_check`，在内存用同配置构造VTK ImageData，对70条原始路径及10条作者原生后处理路径做间距最多0.02的独立查询；611950次查询，15条路径存在障碍内部命中，结果为`results/stage2/vtk_crosscheck.csv`。该调用由本地Python命令逐条读取合并JSONL完成，不以采样代替严格检查。

## 验收与GitHub

```powershell
.venv\Scripts\python.exe -m compileall -q src tests scripts
.venv\Scripts\python.exe -m pytest -q
.venv\Scripts\python.exe -m pytest -v --tb=short --color=no
.venv\Scripts\python.exe -m ruff check .
.venv\Scripts\python.exe -m ruff format --check .
git diff --check
git push -u origin repro/gsunlight-stage2
```

本地最终232项测试通过。首轮代码提交已触发真实WindowsCI且通过；后续最终提交以实际CI链接为准。首次push网络解析受沙箱限制，获准后成功。原始日志保留本地，连接器不支持job日志端点时通过官方gh只读取得日志。

PR通过GitHub连接器创建，head=`repro/gsunlight-stage2`、base=`repro/gsunlight-stage1`；实际链接和最终状态见阶段报告。不合并main，不创建第三阶段任务。
