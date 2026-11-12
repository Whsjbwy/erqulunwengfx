# 阶段5A-R实际命令与复跑说明

所有命令在仓库根PowerShell执行，Python为`.venv/Scripts/python.exe`，实际版本3.11.15。本阶段没有新增第三方依赖，使用pyproject.toml已有的固定版本：NumPy2.4.6、Matplotlib3.11.2、pytest9.2.0、Ruff0.17.4，其他是Python标准库。CPU串行、BLAS线程1、无GPU训练。完整运行输出保留在仓库外`../local_only/stage5ar_audit`，不将个人路径和完整日志上传GitHub。

## 已执行的历史核对与准备

完整阅读用户提供的5A-R任务书附件；工作总目录下未找到同名MD，未据此跳过附件内容。核对PR #5仍开放、未合并、head为8c69bb5，与本地5A完全一致。阅读5A全部核心模块、配置、报告、测试和七个提交的变更；历史工作树起始干净。

```powershell
git status --short --branch
git log --stat aac2921..8c69bb5
.venv/Scripts/python.exe -m pytest -v
.venv/Scripts/python.exe -m ruff check .
.venv/Scripts/python.exe -m ruff format --check .
.venv/Scripts/python.exe -m compileall -q src tests scripts
git switch -c audit/auv-stage5ar-execution pivot/auv-rrt-stage5a
.venv/Scripts/python.exe -m gsunlight_repro.stage5a.audit `
  --local-dir ../local_only/stage5a_amend1 --output ../local_only/stage5ar_audit
```

基线416项通过11.17秒；Ruff、123文件格式、编译均退出0。历史审计450任务/13185路径条目/13633历史引用/1305截点通过，不重放历史搜索、不修改旧输出目录。另在freeze阶段逐一比较全部450原始row与旧公开runs.csv的33670个字段，无差异。

## 分关执行命令

先实际运行P0测试，再解析验收；通过后freeze清单并提交30d39d5、推送，才运行pilot。首轮18路径通过后，P1扩展157，随后P2，最后P3。以下命令必须按顺序执行，程序会核验前置门槛：

```powershell
$env:PYTHONIOENCODING = 'utf-8'
$env:OMP_NUM_THREADS = '1'
$env:OPENBLAS_NUM_THREADS = '1'
$env:MKL_NUM_THREADS = '1'

.venv/Scripts/python.exe -m pytest tests/test_stage5ar_p0.py -v
.venv/Scripts/python.exe -m gsunlight_repro.stage5ar.runner --phase p0 `
  --history ../local_only/stage5a_amend1 --local-dir ../local_only/stage5ar `
  --output results/stage5ar
.venv/Scripts/python.exe -m gsunlight_repro.stage5ar.runner --phase freeze `
  --history ../local_only/stage5a_amend1 --local-dir ../local_only/stage5ar `
  --output results/stage5ar

# 清单提交之后运行以下阶段；保持相同目录，不能覆盖历史或已冻结配置。
.venv/Scripts/python.exe -m gsunlight_repro.stage5ar.runner --phase pilot `
  --history ../local_only/stage5a_amend1 --local-dir ../local_only/stage5ar `
  --output results/stage5ar
.venv/Scripts/python.exe -m gsunlight_repro.stage5ar.runner --phase p1 `
  --history ../local_only/stage5a_amend1 --local-dir ../local_only/stage5ar `
  --output results/stage5ar
.venv/Scripts/python.exe -m gsunlight_repro.stage5ar.runner --phase p2 `
  --history ../local_only/stage5a_amend1 --local-dir ../local_only/stage5ar `
  --output results/stage5ar
.venv/Scripts/python.exe -m gsunlight_repro.stage5ar.runner --phase p3 `
  --history ../local_only/stage5a_amend1 --local-dir ../local_only/stage5ar `
  --output results/stage5ar
```

全部新逐步轨迹以JSON.gz单份存储，若raw/shortcut与同任务已验证坐标及条件完全相同，仅保存轨迹引用。执行条件仍各自保留结果行；引用不是新增积分试验。缓存严格核对身份和配置，不静默覆盖、不自动重跑错误。墙钟守护或运行错误会停止阶段并留下记录。

## 表格、图及最终核查

```powershell
.venv/Scripts/python.exe -m gsunlight_repro.stage5ar.analysis `
  --local-dir ../local_only/stage5ar --output results/stage5ar
.venv/Scripts/python.exe -m gsunlight_repro.stage5ar.audit `
  --local-dir ../local_only/stage5ar --output results/stage5ar
.venv/Scripts/python.exe -m gsunlight_repro.stage5ar.plots `
  --history ../local_only/stage5a_amend1 --local-dir ../local_only/stage5ar `
  --output results/stage5ar
.venv/Scripts/python.exe -m pytest -v
.venv/Scripts/python.exe -m ruff check .
.venv/Scripts/python.exe -m ruff format --check .
.venv/Scripts/python.exe -m compileall -q src tests scripts
git diff --name-status pivot/auv-rrt-stage5a
```

独立复跑需要使用全新本地目录及全新输出目录，不能把新结果覆盖现有stage5ar。完整历史坐标保留在研究者本地；公开CSV不能逆推出完整折线。没有这些历史文件时可运行全部合成测试/CI，但不能声称独立重放了这157条历史路径。

## 实际遇到的问题

1. 首次在工作总目录运行Git，提示不是仓库；实际仓库在其下erqulunwengfx，改为正确工作目录后核验，未创建替代仓库。
2. 查找不存在的本地配置目录时rg提示路径不存在；随后只检查实际存在的设置，未修改settings.json、未触发deny操作。
3. 开发Ruff先后提示行长及循环闭包变量绑定风险；通过格式化、拆分字符串和提取单族选择函数修复；保留失败后续命令记录，不将这些提示说成运动学bug。
4. 初次少量测试输出的中文路径显示乱码；设置PYTHONIOENCODING=utf-8后保存正式日志，数值和退出状态未改变。
5. Git提示LF将转换为CRLF属于换行提示，提交正常完成，不是实验失败。
6. 最终测试发现CSV展开时局部path_id覆盖全局来源ID；先提交b563a8c最小失败测试，保留修复前CSV/日志，再修复导出并重建结果表。共有非ID数值字段不变，未重跑轨迹；修复后450项全量通过。
7. 证据整理脚本最初假定静默compileall也有日志文件，实际Tee-Object在无输出时未创建文件；改为依据真实退出0及无输出记录，未补造编译输出。

最终本机和Windows CI的实际结果另见STAGE5AR_TEST_RESULTS_CN.md，不以预期代替执行证据。
