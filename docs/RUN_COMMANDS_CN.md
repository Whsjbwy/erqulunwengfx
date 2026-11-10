# 第一阶段实际运行命令

日期：2026-11-10。以下是安装、复现、诊断与验收的实际命令记录；PowerShell中将同一组整数写成`0..19`与逐个列出0至19等价。工作根目录为`D:\2区论文复现`，仓库目录为其下`erqulunwengfx`。命令中解释器和工具均使用明确路径；没有要求修改系统PATH。原生探针、行跟踪器、报告生成器及本机凭据桥接器留在`local_only`，不属于公开作者材料。

## 准备与安装

在工作根目录执行：

```powershell
git clone https://github.com/Whsjbwy/erqulunwengfx.git erqulunwengfx
Set-Location erqulunwengfx
git status --short --branch
git remote -v
git branch -a
git switch -c repro/gsunlight-stage1
Set-Location ..
Expand-Archive -LiteralPath .\LIU3Dsunlight-main.zip -DestinationPath .

$env:UV_CACHE_DIR = 'D:\2区论文复现\local_only\uv_cache'
$env:UV_PYTHON_INSTALL_DIR = 'D:\2区论文复现\local_only\python'
uv python install 3.11
Set-Location erqulunwengfx
uv venv --python 'D:\2区论文复现\local_only\python\cpython-3.11.15-windows-x86_64-none\python.exe' .venv
uv pip install --python .venv\Scripts\python.exe -e '.[dev]'
```

首次clone因`getaddrinfo() thread failed to start`失败；Python及依赖下载因网络访问权限10013失败，获准后以相同命令完成。`uv python list --only-installed`的缓存访问和CIM硬件查询在沙箱中被拒绝，在获准的正常用户环境完成。未以其他算法或合成地图替代真实原版运行。

## 未修改原件的直接运行与定位

下列命令由仓库外探针启动，并保存stdout、stderr、墙钟及进程退出状态。在作者目录执行的实际子命令为：

```powershell
..\erqulunwengfx\.venv\Scripts\python.exe -u main_sunlight_3Dgrid.py --noanimate
```

探针在45秒后结束未退出进程，原生输出已生成路径。探针本身调用方式（从工作根目录）为：

```powershell
& .\erqulunwengfx\.venv\Scripts\python.exe .\local_only\native_probe.py `
  --source-dir .\LIU3Dsunlight-main --output-dir .\local_only\native --timeout 45
```

之后在作者目录以`render_trace.py`固定random和numpy的seed=0，通过runpy执行同一原件，记录源码33/34/173/174行；父探针30秒后结束进程：

```powershell
..\erqulunwengfx\.venv\Scripts\python.exe -u ..\local_only\render_trace.py .\main_sunlight_3Dgrid.py
```

日志确认到达174行`p.show()`；两个原生进程被探针结束的退出码均为1，须结合timeout标志解释。

## 基线逐级运行

以下从仓库目录执行；各目录分别保存日志和路径，避免覆盖。原运行在命令行逐个列出了种子，这里使用PowerShell等价数组缩写。

```powershell
.\.venv\Scripts\python.exe -m gsunlight_repro.experiment_runner `
  --source-dir ..\LIU3Dsunlight-main --map-path ..\LIU3Dsunlight-main\map.vti `
  --seeds 0 --timeout 120 --output results\pilot_seed0.csv `
  --local-dir ..\local_only\pilot_seed0

.\.venv\Scripts\python.exe -m gsunlight_repro.experiment_runner `
  --source-dir ..\LIU3Dsunlight-main --map-path ..\LIU3Dsunlight-main\map.vti `
  --seeds (0..4) --timeout 120 --output results\pilot_seeds0_4.csv `
  --local-dir ..\local_only\pilot_seeds0_4

.\.venv\Scripts\python.exe -m gsunlight_repro.experiment_runner `
  --source-dir ..\LIU3Dsunlight-main --map-path ..\LIU3Dsunlight-main\map.vti `
  --seeds (0..19) --timeout 120 --output results\stage1_summary.csv `
  --local-dir ..\local_only\baseline20

.\.venv\Scripts\python.exe -m gsunlight_repro.crosscheck `
  --map-path ..\LIU3Dsunlight-main\map.vti `
  --paths-file ..\local_only\pilot_seed0\paths.jsonl `
  --output ..\local_only\pilot_seed0\vtk_crosscheck.csv --max-spacing 0.02

.\.venv\Scripts\python.exe -m gsunlight_repro.crosscheck `
  --map-path ..\LIU3Dsunlight-main\map.vti `
  --paths-file ..\local_only\baseline20\paths.jsonl `
  --output results\vtk_crosscheck.csv --max-spacing 0.02
```

预检CSV后来移动到对应的仓库外记录目录，公开仓库只保留正式20次结果。最终包装异常证据补强后，执行了以下重放并逐字段比较路径和参数，全部一致；不比较计时，不进行额外哈希：

```powershell
.\.venv\Scripts\python.exe -m gsunlight_repro.experiment_runner `
  --source-dir ..\LIU3Dsunlight-main --map-path ..\LIU3Dsunlight-main\map.vti `
  --seeds 0 --timeout 120 --output ..\local_only\replay0\summary.csv `
  --local-dir ..\local_only\replay0
```

## 安全诊断

最初的隔离自编hook保存在`..\local_only\safety_adapter.py`，完成seed0和0—4预检；公开实现后来整理为`diagnostics.py`及`scripts/safety_adapter.py`，增加了在原地修改情况下仍能回退的保护，通过19项测试，再用于正式三组20次实验。真实作者后处理本就复制输入，保护没有改变其正常计算行为。

```powershell
.\.venv\Scripts\python.exe -m gsunlight_repro.experiment_runner `
  --source-dir ..\LIU3Dsunlight-main --map-path ..\LIU3Dsunlight-main\map.vti `
  --seeds 0 --timeout 120 --mode safety_diagnostic `
  --adapter-path ..\local_only\safety_adapter.py `
  --output results\diagnostic_pilot0.csv --local-dir ..\local_only\diagnostic_pilot0

.\.venv\Scripts\python.exe -m gsunlight_repro.experiment_runner `
  --source-dir ..\LIU3Dsunlight-main --map-path ..\LIU3Dsunlight-main\map.vti `
  --seeds (0..4) --timeout 120 --mode safety_diagnostic `
  --adapter-path ..\local_only\safety_adapter.py `
  --output results\diagnostic_pilot0_4.csv --local-dir ..\local_only\diagnostic_pilot0_4

.\.venv\Scripts\python.exe scripts\prepare_diagnostic_source.py `
  --source-dir ..\LIU3Dsunlight-main --output-dir ..\local_only\diagnostic_cons3 --capacity 3
.\.venv\Scripts\python.exe scripts\prepare_diagnostic_source.py `
  --source-dir ..\LIU3Dsunlight-main --output-dir ..\local_only\diagnostic_cons5 --capacity 5

.\.venv\Scripts\python.exe -m gsunlight_repro.experiment_runner `
  --source-dir ..\LIU3Dsunlight-main --map-path ..\LIU3Dsunlight-main\map.vti `
  --seeds (0..19) --timeout 120 --mode safety_cons1 `
  --adapter-path scripts\safety_adapter.py `
  --output results\diagnostic_cons1.csv --local-dir ..\local_only\diagnostic_cons1_20
```

容量3和5分别先运行以下预检，再运行正式20次；循环写法是对实际两组相同命令的等价展示：

```powershell
foreach ($capacity in 3,5) {
  .\.venv\Scripts\python.exe -m gsunlight_repro.experiment_runner `
    --source-dir "..\local_only\diagnostic_cons$capacity" `
    --map-path ..\LIU3Dsunlight-main\map.vti --seeds (0..4) --timeout 120 `
    --mode "safety_cons$capacity" --adapter-path scripts\safety_adapter.py `
    --output "..\local_only\diagnostic_cons${capacity}_pilot\summary.csv" `
    --local-dir "..\local_only\diagnostic_cons${capacity}_pilot"

  .\.venv\Scripts\python.exe -m gsunlight_repro.experiment_runner `
    --source-dir "..\local_only\diagnostic_cons$capacity" `
    --map-path ..\LIU3Dsunlight-main\map.vti --seeds (0..19) --timeout 120 `
    --mode "safety_cons$capacity" --adapter-path scripts\safety_adapter.py `
    --output "results\diagnostic_cons$capacity.csv" `
    --local-dir "..\local_only\diagnostic_cons${capacity}_20"
}
```

## 最终检查与汇总

```powershell
.\.venv\Scripts\python.exe -m compileall -q src tests scripts
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m pytest -v --tb=short --color=no
.\.venv\Scripts\python.exe -m ruff check .
.\.venv\Scripts\python.exe -m ruff format --check .
git diff --check
.\.venv\Scripts\python.exe ..\local_only\build_report.py .
```

实际结果：85项测试通过，编译与Ruff通过，18个Python文件格式规范。合成测试生成的VTI仅在pytest临时目录中使用，不是替换作者地图的实验数据。汇总读取已有CSV和本地JSONL，不重新生成路径、不手填成功率。

## GitHub交付命令

GitHub CLI为官方免安装版2.103.3；安全使用Git凭据管理器的已有账号Whsjbwy，令牌仅经进程环境传给官方CLI，不记录、不存储到本仓库。提交前审查暂存文件；最后实际交付状态见阶段报告G节。

```powershell
git add .gitignore AGENTS.md README.md pyproject.toml src tests scripts docs results
git diff --cached --check
git diff --cached --name-only
git commit -m "repro: verify G-Sunlight stage-one paths and document safety diagnostics"
git push -u origin repro/gsunlight-stage1
gh pr create --repo Whsjbwy/erqulunwengfx --base main --head repro/gsunlight-stage1 `
  --title "G-Sunlight 阶段1：原版复现、严格碰撞核验与安全诊断" `
  --body-file ..\local_only\pr_body.md
```

本机未将gh加入PATH，实际调用使用`local_only/github_cli/bin/gh.exe`完整路径及外置凭据桥接器；上面的`gh`为同一官方程序的简写。未执行force push或合并。
