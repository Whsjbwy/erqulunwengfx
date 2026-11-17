# 7B-0真实命令与质量证据

## 冻结与验收

基线7A为`24cc32d`。控制模块、运行入口、19项测试和协议在首次执行之前提交`a11a9b7`，参数不作事后修改。

```powershell
.venv/Scripts/python.exe scripts/stage7b0_acceptance.py
```

实际B1通过19项，0.482910秒（含pytest启动）；逐项结果在`results/stage7b0/admission/cases.csv`，真实stdout/JUnit/命令/源码HEAD/权重在该目录。首轮失败JUnit `admission-first.xml`保留3项测试失败，原因是测试整数数组截断扰动；`development_errors.json`说明修复，解析公式和容差不变。修复后的16项、后续补齐18项、最终19项均有分开的真实记录。

## 唯一六次执行

```powershell
.venv/Scripts/python.exe -m gsunlight_repro.stage7b0.runner --raw-root ../local_only/stage6ds_runs --local-root ../local_only/stage7b0_runs --admission results/stage7b0/admission --execute-six
```

本命令真实完成一次，登记/执行6/6，严格成功6/6；不重跑，不筛选。新目录`invocation.json`保存实际argv、源码HEAD和协议；每任务`execution.json.gz`是唯一完整新轨迹，`result.json`是独立证书及真实墙钟。`execution_ledger.json`逐次从not_run/started到completed，缺失或异常会保留并停止后续执行，没有例外吞掉或覆盖重试。

6次执行后另做6次同一新输入的独立数值/安全认证，属于每次执行的认证成本，不是新增规划、另一个控制条件或再次选择性能样本。全部3113区间另用RK4检查。继承原生/LOS不重放；本轮没有新原生规划、LOS或受扰执行。

```powershell
.venv/Scripts/python.exe -m gsunlight_repro.stage7b0.analysis --raw-root ../local_only/stage6ds_runs --local-root ../local_only/stage7b0_runs
.venv/Scripts/python.exe -m gsunlight_repro.stage7b0.plots --raw-root ../local_only/stage6ds_runs --local-root ../local_only/stage7b0_runs
```

这两条只读取已有记录，生成六行CSV、18行基线、失败表、科研决定和两张图，不进行积分或新执行。图已目视检查。

## 两页方向报告

PDF采用已配置的Codex附带Python/reportlab/pypdf和系统SimHei字体，不改变项目依赖或安装系统工具。先执行PDF技能要求的operation marker，再调用`scripts/stage7b0_direction_pdf.py`（显式传入source、font、output）。pypdf与pdfinfo确认恰好2页A4、71811字节；Poppler渲染两页PNG并目视检查，无裁剪/乱码/重叠。中间渲染只在`local_only/stage7b0_quality/tmp/pdfs/`，不重复提交PDF截图。

## 最终工程检查和CI

完整工程命令为`scripts/stage7b0_quality.py --output results/stage7b0/local-quality`，实际运行compileall、全量pytest、Ruff check、Ruff format --check和公开六行证据检查。真实退出码、耗时、日志及JUnit在新结果目录。合成单元测试正常运行模型积分；不把这些测试计为新增科研轨迹执行。

本地实际检查通过：571项pytest，12.64秒，失败/错误/跳过均0；compileall、Ruff、格式及公开证据检查退出码全部0。该次源码HEAD为`05bdb27`，日志和结果入库后的最终提交由Windows CI重新执行并核对实际HEAD。

新增Windows工作流取PR真实HEAD，运行相同检查，不依赖本地私有轨迹、不再执行六条任务。源码提交身份、计数和日志由CI产物核对；最终HEAD、运行/任务/产物ID及链接写入PR描述，并在工作区`local_only/stage7b0_quality/final_ci_verification.json`保存取证。避免为把自身HEAD写回仓库而递归提交，或把前一提交的CI作为最终证据。

本轮无C++改动，无新OMPL构建和CTest。历史CTest只为继承证据，不写成本轮执行。相对7A的差异应全部为新增路径，无依赖源码、大原生轨迹、额外文件hash清单；PR目标7A，不合并main。完成后停止。
